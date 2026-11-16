"""Live signal engine (scanner/intraday/live_engine.py, web/api/services/livesig_svc.py): building the earlier sessions
once and then only today from the carried state gives exactly the Days of one full pass, and the engine's signals are
exactly the 5-minute task's on the same bars. Synthetic sessions; nothing is fetched."""
from datetime import datetime

import numpy as np
import pandas as pd
import pytest

from scanner.intraday.engine import SLOTS
from scanner.settings import IST

SYMS = [f"S{i:02d}" for i in range(12)]
DAYS = pd.bdate_range("2026-10-01", "2026-11-13")          # 32 sessions, the last one is "today"
TODAY = DAYS[-1]
NOW = datetime(2026, 11, 13, 13, 0, tzinfo=IST)


def _world():
    rng = np.random.default_rng(3)
    rows, daily = [], {k: {} for k in ("open", "high", "low", "close", "volume")}
    for s in SYMS:
        px = 100.0 + 10 * SYMS.index(s)
        for d in DAYS:
            drift = rng.normal(0, 0.003)
            path = px * np.exp(np.cumsum(rng.normal(drift, 0.004, SLOTS)))
            o = np.r_[px * (1 + rng.normal(0, 0.006)), path[:-1]]
            h = np.maximum(o, path) * (1 + rng.uniform(0, 0.002, SLOTS))
            lo = np.minimum(o, path) * (1 - rng.uniform(0, 0.002, SLOTS))
            v = rng.uniform(2e4, 2e5, SLOTS)
            ts = d + pd.Timedelta(hours=9, minutes=15) + pd.to_timedelta(np.arange(SLOTS) * 5, unit="m")
            keep = slice(None) if d != TODAY else slice(0, 45)        # today: bars until 13:00
            rows.append(pd.DataFrame({"ts": ts[keep], "symbol": s, "open": o[keep], "high": h[keep], "low": lo[keep],
                                      "close": path[keep], "volume": v[keep], "flags": 0, "source": "fyers"}))
            if d != TODAY:                                             # the daily store ends yesterday
                for k, x in (("open", o[0]), ("high", h.max()), ("low", lo.min()), ("close", path[-1]),
                             ("volume", v.sum())):
                    daily[k].setdefault(s, {})[d] = x
            px = path[-1]
    frames = {k: pd.DataFrame(v).sort_index() for k, v in daily.items()}
    bars = pd.concat(rows, ignore_index=True)
    info = {"fno": set(SYMS[:8]), "etfs": set(), "min_turnover_cr": 0.0}
    return frames, bars, info


def test_earlier_days_once_then_today_from_the_carry_equals_one_full_pass():
    from scanner.intraday.run import build_days
    frames, bars, info = _world()
    full = build_days(bars, frames, info, set(SYMS[:4]), {})
    cache, carry = {}, {}
    build_days(bars[bars["ts"] < TODAY], frames, info, set(SYMS[:4]), {}, daily_cache=cache, carry=carry)
    for _ in range(2):                                   # every new bar starts again from the same carried state
        c2 = {k: (list(a), list(b), x) for k, (a, b, x) in carry.items()}
        inc = build_days(bars[bars["ts"] >= TODAY], frames, info, set(SYMS[:4]), {}, daily_cache=cache, carry=c2)
        for s in SYMS:
            a = [d for d in full[s] if d.date == TODAY]
            b = inc.get(s, [])
            assert len(a) == len(b) == 1
            for f in ("o", "h", "l", "c", "v"):
                assert np.array_equal(getattr(a[0], f), getattr(b[0], f), equal_nan=True)
            assert (a[0].prev_close, a[0].atr_d, a[0].ctx) == (b[0].prev_close, b[0].atr_d, b[0].ctx)


@pytest.fixture
def world(tmp_path, monkeypatch):
    import scanner.intraday.data as idata
    import scanner.intraday.live_engine as le
    import scanner.intraday.run as R
    from scanner import fno_intraday
    frames, bars, info = _world()
    monkeypatch.setattr(R, "SIGNALS_FILE", tmp_path / "intraday_signals.json")
    monkeypatch.setattr(R, "load_intraday", lambda: {"generated_at": "x", "strategies": [
        {"key": "orb15", "name": "ORB", "status": "working"}, {"key": "vwap_trend", "name": "VWAP", "status": "mixed"}]})
    monkeypatch.setattr(R.fyers_sync, "is_trading_day", lambda d: True)
    uni = lambda cfg, fr: (list(SYMS), info)                       # noqa: E731
    nifty = lambda name: (pd.DataFrame({"symbol": SYMS[:4]}), None)   # noqa: E731
    for mod in (R, le):
        monkeypatch.setattr(mod, "intraday_universe", uni)
        monkeypatch.setattr(mod, "get_universe", nifty)
        monkeypatch.setattr(mod, "results_history", lambda *a, **k: {})
    monkeypatch.setattr(R, "update_bars", lambda symbols, cfg=None, log=print, today_only=False: (bars, ["fyers"]))

    def load(self, interval, symbols=None, start=None, end=None, drop_flags=0):
        df = bars if symbols is None else bars[bars["symbol"].isin(symbols)]
        if start is not None:
            df = df[df["ts"] >= pd.Timestamp(start)]
        if end is not None:
            df = df[df["ts"] < pd.Timestamp(end) + pd.Timedelta(days=1)]
        return df.reset_index(drop=True)

    monkeypatch.setattr(idata.IntradayStore, "load", load)
    monkeypatch.setattr(le.live_feed, "load_live", lambda root, day=None, one_minute=False: idata.empty_bars())
    monkeypatch.setattr(le.live_feed, "feed_fresh", lambda root, now=None: False)
    monkeypatch.setattr(idata, "fetch_yahoo_intraday", lambda *a, **k: idata.empty_bars())
    monkeypatch.setattr(fno_intraday, "load", lambda: None)
    cfg = {"intraday": {"show_untested": True}, "account": {"capital": 500000}}
    return R, le, frames, cfg


def test_the_engine_gives_exactly_the_5_minute_tasks_signals(world):
    R, le, frames, cfg = world
    cold = R.run_intraday_signals(cfg, frames=frames, log=lambda m: None, now=NOW)
    eng = le.LiveEngine(log=lambda m: None, frames_fn=lambda: frames, cfg_fn=lambda: cfg)
    warm = eng.refresh(cfg, now=NOW, force=True)
    assert cold["signals"], "the synthetic sessions should trigger some strategies"
    assert warm["signals"] == cold["signals"]
    assert (warm["engine"], cold["engine"]) == ("live", "job")
    assert warm["bars_to"] == cold["bars_to"] == "2026-11-13T12:55:00"
    again = eng.refresh(cfg, now=NOW, force=True)           # the next bar: the day's caches are reused
    assert again["signals"] == cold["signals"] and eng.stats["day_builds"] == 1 and eng.stats["runs"] == 2


def test_engine_waits_for_a_fresh_live_feed_and_the_open(world, monkeypatch):
    R, le, frames, cfg = world
    eng = le.LiveEngine(log=lambda m: None, frames_fn=lambda: frames, cfg_fn=lambda: cfg)
    monkeypatch.setattr(le.live_feed, "market_open_now", lambda lead_minutes=0: True)
    assert eng.refresh(cfg, now=NOW) is None                 # FYERS live feed not fresh: the 5-minute task covers it
    monkeypatch.setattr(le.live_feed, "feed_fresh", lambda root, now=None: True)
    assert eng.refresh(cfg, now=NOW.replace(hour=9, minute=18)) is None     # before the first complete bar
    assert eng.refresh(cfg, now=NOW)["engine"] == "live"


def test_service_times_the_run_and_wakes_its_listeners(world, monkeypatch):
    R, le, frames, cfg = world
    from web.api.services import latency_svc, livesig_svc
    latency_svc.reset()
    eng = le.LiveEngine(log=lambda m: None, frames_fn=lambda: frames, cfg_fn=lambda: cfg)
    monkeypatch.setattr(livesig_svc, "_engine", eng)
    monkeypatch.setattr(eng, "refresh", lambda force=False, _r=eng.refresh: _r(cfg, now=NOW, force=True))
    woke = []
    monkeypatch.setattr(livesig_svc, "_listeners", [woke.append])
    out = livesig_svc.run_once()
    assert woke == [out] and livesig_svc.latest() == (out, eng.ready_at)
    rows = {r["name"]: r for r in latency_svc.summary()}
    assert rows["signal_compute"]["n"] == 1 and rows["bar_to_signals"]["n"] == 1
    assert livesig_svc._bar_close_epoch("2026-11-13T12:55:00") == datetime(2026, 11, 13, 13, 0, tzinfo=IST).timestamp()
