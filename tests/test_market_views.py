"""Seasonality and the market heatmap (web/api/services/market_views.py) on synthetic data."""
import numpy as np
import pandas as pd
import pytest

from web.api.services import data, market_views as mv, quotes_svc


def test_seasonality_averages_each_month_and_marks_only_strong_ones(monkeypatch):
    idx = pd.bdate_range("2014-01-01", "2025-12-31")
    rng = np.random.default_rng(1)
    r = rng.normal(0, 0.004, len(idx)) + np.where(idx.month == 4, 0.004, 0.0)   # April is strongly up every year
    close = pd.DataFrame({"ABC": 100 * np.cumprod(1 + r), "NIFTY50": 100 * np.cumprod(1 + rng.normal(0, 0.003, len(idx)))}, index=idx)
    monkeypatch.setattr(data, "store", lambda: {"close": close})
    s = mv.seasonality("ABC")
    apr = next(m for m in s["months"] if m["name"] == "Apr")
    assert apr["n"] == 12 and apr["avg"] > 5 and apr["up_pct"] == 100 and apr["pattern"]
    assert sum(m["pattern"] for m in s["months"]) <= 3                     # the random months stay noise
    assert apr["vs_nifty"]["avg"] > 4 and len(s["years"]) == 12


def test_heatmap_groups_by_industry_and_uses_live_moves(monkeypatch):
    sc = pd.DataFrame({"symbol": ["A", "B", "C"], "company": ["a", "b", "c"], "industry": ["IT", "IT", None],
                       "price": [10.0, 20.0, 30.0], "turnover_cr": [100.0, 50.0, 10.0], "change_pct": [1.0, -2.0, 0.5],
                       "ret_1w": [1, 2, 3], "ret_1m": [1, 2, 3], "ret_3m": [1, 2, 3], "ret_12m": [1, 2, 3], "scan_id": "s"})
    monkeypatch.setattr(data, "screener", lambda: sc)
    monkeypatch.setattr(quotes_svc, "quotes", lambda syms, allow_network=True, wait=True: {
        "session": "open", "quotes": [{"symbol": "A", "price": 11.0, "change_pct": 3.0, "source": "live"}]})
    h = mv.heatmap("1d")
    it = next(g for g in h["groups"] if g["industry"] == "IT")
    assert [s["symbol"] for s in it["stocks"]] == ["A", "B"] and it["stocks"][0]["move"] == 3.0 and h["live"] == 1
    assert it["move"] == pytest.approx((3.0 * 100 - 2.0 * 50) / 150, abs=0.01)   # weighted by traded value
    assert any(g["industry"] == "Other" for g in h["groups"])
    assert mv.heatmap("1m")["live"] == 0


def _universe(n=6):
    syms = [f"S{i}" for i in range(n)]
    return pd.DataFrame({"symbol": syms, "company": syms, "industry": "IT", "price": 100.0, "turnover_cr": 10.0,
                         "change_pct": -1.0, "ret_1w": 1.0, "ret_1m": 1.0, "ret_3m": 1.0, "ret_12m": 1.0,
                         "scan_id": "2026-11-13T18:20:00+05:30"})


def test_heatmap_never_waits_for_quotes_and_says_where_each_move_came_from(monkeypatch):
    """09:15-18:00, FYERS logged out, Yahoo slow: the heatmap answers at once from the live feed's ticks, today's
    cached Yahoo quotes and the scan, labels each, gives the quotes' age, and the stale ones fill in on a later load."""
    import threading
    import time as _t
    from web.api.services import clock
    gate, calls = threading.Event(), []
    today = quotes_svc.now_ist().date().isoformat()

    def yahoo(syms):
        calls.append(list(syms))
        assert gate.wait(5)
        return {s: {"symbol": s, "price": 102.0, "prev_close": 100.0, "change_pct": 2.0, "time": today} for s in syms}

    tick = _t.time() - 2
    hub = {"updated": quotes_svc.now_ist().isoformat(), "written": _t.time(),
           "quotes": {"S0": {"symbol": "S0", "price": 105.0, "prev_close": 100.0, "change_pct": 5.0, "received": tick}}}
    monkeypatch.setattr(data, "screener", lambda: _universe())
    monkeypatch.setattr(data, "latest", lambda: {"data_date": "2026-11-13"})
    monkeypatch.setattr(clock, "market_clock", lambda now=None: {"session": "open"})
    monkeypatch.setattr(quotes_svc, "hub_info", lambda: hub)
    monkeypatch.setattr(quotes_svc, "get_fyers", lambda cfg: (None, "not logged in"))
    monkeypatch.setattr(quotes_svc, "_from_yahoo", yahoo)
    monkeypatch.setattr(quotes_svc, "_from_store", lambda syms: {})
    monkeypatch.setattr(quotes_svc, "_bg_thread", None)
    old = quotes_svc.time.monotonic() - 90                       # S1 was fetched 90 s ago: stale, still today's
    monkeypatch.setattr(quotes_svc, "_cache", {"S1": (old, "yahoo", {"symbol": "S1", "price": 99.0, "prev_close": 100.0,
                                                                      "change_pct": -1.5, "time": today, "source": "yahoo",
                                                                      "delayed": True})})
    try:
        t0 = _t.monotonic()
        h = mv.heatmap("1d")
        assert _t.monotonic() - t0 < 1.0                         # Yahoo is still fetching: not waited for
        by = {s["symbol"]: s for g in h["groups"] for s in g["stocks"]}
        assert (by["S0"]["move"], by["S0"]["source"]) == (5.0, "live")
        assert (by["S1"]["move"], by["S1"]["source"]) == (-1.5, "yahoo")
        assert (by["S2"]["move"], by["S2"]["source"]) == (-1.0, "scan") and h["scan_date"] == "2026-11-13"
        assert h["sources"] == {"live": 1, "yahoo": 1, "scan": 4} and h["refreshing"] and h["live"] == 2
        assert h["quotes_from"] < h["quotes_to"] and h["as_of"] >= h["quotes_to"]   # S1's fetch, then S0's tick
        gate.set()
        quotes_svc._bg_thread.join(5)
        assert sorted(sum(calls, [])) == ["S1", "S2", "S3", "S4", "S5"]   # the feed's symbol is never fetched
        h = mv.heatmap("1d")
        assert h["sources"] == {"live": 1, "yahoo": 5} and not h["refreshing"]
        assert {s["move"] for g in h["groups"] for s in g["stocks"] if s["source"] == "yahoo"} == {2.0}
    finally:
        gate.set()
        if quotes_svc._bg_thread is not None:
            quotes_svc._bg_thread.join(5)


def test_heatmap_outside_the_session_is_the_scan_with_no_network(monkeypatch):
    from web.api.services import clock
    monkeypatch.setattr(data, "screener", lambda: _universe(3))
    monkeypatch.setattr(data, "latest", lambda: {"data_date": "2026-11-16"})
    monkeypatch.setattr(clock, "market_clock", lambda now=None: {"session": "closed"})
    monkeypatch.setattr(quotes_svc, "_rest", lambda *a, **k: pytest.fail("no quote fetch after 18:00"))
    monkeypatch.setattr(quotes_svc, "refresh_in_background", lambda *a, **k: pytest.fail("no refresh after 18:00"))
    monkeypatch.setattr(quotes_svc, "_from_store", lambda syms: {})
    h = mv.heatmap("1d")
    assert h["sources"] == {"scan": 3} and not h["refreshing"] and h["quotes_from"] is None
    assert h["scan_date"] == "2026-11-16" and h["groups"][0]["stocks"][0]["source"] == "scan"
