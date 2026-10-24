"""The shared FYERS rate limiter must never let us breach FYERS' limits."""
import datetime
import json

import pytest

from scanner import fyers_limits as fl


@pytest.fixture
def limiter(tmp_path, monkeypatch):
    monkeypatch.setattr(fl, "STATE_FILE", tmp_path / "usage.json")
    monkeypatch.setattr(fl, "LOCK_FILE", tmp_path / "usage.lock")
    clock = {"t": 1_000_000.0}
    slept = []

    def fake_sleep(s):
        slept.append(s)
        clock["t"] += s

    monkeypatch.setattr(fl.time, "time", lambda: clock["t"])
    monkeypatch.setattr(fl.time, "sleep", fake_sleep)
    lim = fl.FyersLimiter("standard")
    lim._clock, lim._slept = clock, slept
    return lim


def _bare_provider(limiter):
    """A FyersProvider without the SDK (only what _call needs)."""
    from scanner import providers
    p = providers.FyersProvider.__new__(providers.FyersProvider)
    p.limiter, p.calls, p.errors = limiter, 0, {}
    return p


def test_per_second_and_per_minute_spacing(limiter):
    per_sec, per_min, _ = fl.LIMITS["standard"]["data"]
    for _ in range(per_min):
        limiter.acquire("data")
    # never more than per_sec calls inside any one second, never more than per_min inside 60 s
    assert sum(limiter._slept) >= (per_min / per_sec) - 1 - 1e-6
    start = limiter._clock["t"]
    limiter.acquire("data")                      # the 46th call must wait for the minute window
    assert limiter._clock["t"] - start > 0
    assert limiter.usage()["data"]["calls_today"] == per_min + 1


def test_stops_after_two_strikes(limiter):
    limiter.acquire("data")
    limiter.strike()
    limiter.acquire("data")                      # one strike: still allowed (after waiting)
    limiter.strike()
    with pytest.raises(fl.FyersRateLimited):
        limiter.acquire("data")                  # a third breach would block the account - refuse
    assert limiter.usage()["stopped"] is True


def test_strike_pauses_every_call_for_a_fresh_minute(limiter):
    limiter.acquire("data")
    limiter.strike()
    start = limiter._clock["t"]
    limiter.acquire("user")                      # the pause applies to every bucket and every process
    assert limiter._clock["t"] - start >= fl.STRIKE_PAUSE_S - 1e-6


def test_daily_budget_is_enforced(limiter, monkeypatch):
    monkeypatch.setitem(fl.LIMITS, "standard", {"data": (1000, 1000, 3), "user": (8, 180, 90000)})
    lim = fl.FyersLimiter("standard")
    for _ in range(3):
        lim.acquire("data")
    with pytest.raises(fl.FyersRateLimited):
        lim.acquire("data")
    lim.acquire("user")                          # the user bucket has its own budget


def test_usage_resets_on_a_new_day(limiter, monkeypatch):
    limiter.acquire("data")
    limiter.strike()
    monkeypatch.setattr(fl, "ist_today", lambda: datetime.date(2099, 1, 1))
    u = limiter.usage()
    assert u["strikes"] == 0 and u["data"]["calls_today"] == 0


def test_new_day_keeps_the_last_minute_window(limiter, monkeypatch):
    _, per_min, _ = fl.LIMITS["standard"]["data"]
    for _ in range(per_min):
        limiter.acquire("data")
    monkeypatch.setattr(fl, "ist_today", lambda: datetime.date(2099, 1, 1))
    start = limiter._clock["t"]
    limiter.acquire("data")                      # midnight resets the day's count, not the per-minute window
    assert limiter._clock["t"] - start > 0
    assert limiter.usage()["data"]["calls_today"] == 1


def test_clock_set_back_after_a_strike_waits_one_window_at_most(limiter):
    limiter.acquire("data")
    limiter.strike()
    limiter._clock["t"] -= 3600                  # wall clock set back an hour (manual change / time sync)
    start = limiter._clock["t"]
    limiter.acquire("user")                      # one strike window, not until the clock catches up
    assert limiter._clock["t"] - start <= fl.STRIKE_PAUSE_S + 1e-6


def test_non_finite_numbers_in_the_state_file(limiter):
    fl.STATE_FILE.write_text('{"date": "%s", "strikes": 1, "pause_until": NaN, '
                             '"buckets": {"data": {"count": 3, "recent": [NaN, Infinity]}}}'
                             % fl.ist_today().isoformat(), encoding="utf-8")
    limiter.acquire("data")                      # no ValueError from time.sleep(nan); strikes and count kept
    u = limiter.usage()
    assert u["strikes"] == 1 and u["data"]["calls_today"] == 4


def test_damaged_or_old_state_file_does_not_crash(limiter):
    fl.STATE_FILE.write_text("{not json", encoding="utf-8")
    limiter.acquire("data")
    assert limiter.usage()["data"]["calls_today"] == 1
    fl.STATE_FILE.write_text(json.dumps({"date": fl.ist_today().isoformat(), "calls": 7}), encoding="utf-8")
    limiter.acquire("data")                      # an older file layout: no KeyError
    assert limiter.usage()["data"]["calls_today"] == 1


def test_provider_stops_on_the_second_rate_limit_error(limiter):
    p = _bare_provider(limiter)
    calls = []

    def limited():
        calls.append(1)
        return {"s": "error", "code": -429, "message": "request limit reached"}

    with pytest.raises(fl.FyersRateLimited):
        p._call(limited)
    assert len(calls) == 2 and limiter.usage()["strikes"] == fl.MAX_STRIKES


def test_provider_does_not_retry_bad_input(limiter):
    p = _bare_provider(limiter)
    calls = []

    def bad_symbol():
        calls.append(1)
        return {"s": "error", "code": -300, "message": "Invalid symbol provided"}

    assert p._call(bad_symbol)["code"] == -300 and len(calls) == 1
    assert limiter.usage()["strikes"] == 0


def test_provider_network_errors_are_retried_a_bounded_number_of_times(limiter):
    p = _bare_provider(limiter)
    calls = []

    def down():
        calls.append(1)
        raise ConnectionError("network down")

    assert p._call(down)["code"] == -99 and len(calls) == 3
    assert limiter.usage()["data"]["calls_today"] == 3   # every attempt went through the shared limiter


def test_raw_fyers_model_goes_through_the_shared_limiter(limiter):
    from scanner.intraday import data as idata
    from scanner.providers import FyersAuthError

    class RawModel:                              # stands in for a bare fyersModel.FyersModel
        def __init__(self, resp):
            self.resp = resp

        def history(self, data=None):
            return self.resp

    ok = RawModel({"s": "ok", "candles": [[1_760_000_000, 1.0, 2.0, 0.5, 1.5, 100]]})
    bars = idata.fetch_fyers_intraday(ok, ["SBIN"], datetime.date(2026, 1, 5), datetime.date(2026, 1, 6))
    assert len(bars) == 1 and limiter.usage()["data"]["calls_today"] == 1
    expired = RawModel({"s": "error", "code": -16, "message": "Could not authenticate the user"})
    with pytest.raises(FyersAuthError):          # not a plain RuntimeError: callers know this one
        idata.fetch_fyers_intraday(expired, ["SBIN"], datetime.date(2026, 1, 5), datetime.date(2026, 1, 6))
