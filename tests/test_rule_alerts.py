"""Trendline, RSI, moving-average, scan-hit and pattern alerts (scanner/watch.py, scanner/rule_alerts.py), the new
drawing kinds, and scans on today's live prices (scanner/scans.py run_live). Synthetic data in a temporary folder."""
from datetime import date

import numpy as np
import pandas as pd
import pytest

from scanner import rule_alerts, scans, watch


@pytest.fixture
def wdir(tmp_path, monkeypatch):
    monkeypatch.setattr(watch, "DATA_DIR", tmp_path)
    return tmp_path


def test_trendline_alert_follows_the_line(wdir, monkeypatch):
    monkeypatch.setattr(watch, "ist_now", lambda: pd.Timestamp("2026-11-11 10:00"))
    a = watch.add_alert("TCS", "line_above", a={"t": "2026-10-01", "v": 100}, b={"t": "2026-11-01", "v": 131})
    assert a["value"] == pytest.approx(141.0)                     # 41 days at Rs 1 a day
    assert watch.evaluate({"TCS": {"price": 140, "source": "live"}}) == []
    fired = watch.evaluate({"TCS": {"price": 141.5, "source": "live"}})
    assert fired and "trendline" in watch.message(fired[0])
    with pytest.raises(ValueError):
        watch.add_alert("TCS", "line_above", a={"t": "2026-10-01", "v": 100}, b={"t": "2026-10-01", "v": 120})


def test_rsi_and_average_alerts_use_the_live_price(wdir):
    idx = pd.bdate_range("2026-01-01", periods=250)
    close = pd.DataFrame({"UP": np.linspace(100, 200, 250), "DN": np.linspace(200, 100, 250)}, index=idx)
    watch.add_alert("UP", "rsi_above", 70)
    watch.add_alert("DN", "rsi_below", 30)
    watch.add_alert("DN", "sma_above", 50)
    day = date(2026, 12, 21)
    fired = rule_alerts.check_live(close, {"UP": {"price": 205, "source": "live"}, "DN": {"price": 95, "source": "live"}}, day)
    assert sorted(a["kind"] for a in fired) == ["rsi_above", "rsi_below"]
    assert all(a["detail"].startswith("RSI") for a in fired)
    assert rule_alerts.check_live(close, {"DN": {"price": 150, "source": "live"}}, day)[0]["kind"] == "sma_above"
    with pytest.raises(ValueError):
        watch.add_alert("UP", "sma_above", 33)
    assert rule_alerts.check_live(close, {"UP": {"price": 300, "source": "close"}}, day) == []   # a stored close never fires


def test_scan_alert_fires_on_a_new_stock_only(wdir):
    a = watch.add_alert("ignored", "scan_hit", ref="abc", note="Breakouts", seen=["TCS"])
    assert a["symbol"] == watch.ALL and a["seen"] == ["TCS"]
    assert rule_alerts.check_scans({"abc": ["TCS"]}) == []
    fired = rule_alerts.check_scans({"abc": ["TCS", "INFY"]})
    assert fired[0]["detail"] == "new: INFY" and "Breakouts" in watch.message(fired[0])
    assert watch.ALL not in watch.feed_symbols()


def test_pattern_alert_needs_a_pattern_with_a_tested_edge(wdir, monkeypatch):
    from scanner import levels
    idx = pd.bdate_range("2026-01-01", periods=30)
    f = {k: pd.DataFrame({"TCS": np.full(30, 100.0)}, index=idx) for k in ("open", "high", "low", "close")}
    watch.add_alert("TCS", "pattern")
    monkeypatch.setattr(levels, "patterns", lambda df, last=1: [{"key": "bullish_engulfing", "bars_ago": 0}])
    no_edge = {"patterns": {"bullish_engulfing": {"name": "Bullish engulfing", "verdict": "no_edge"}}}
    assert rule_alerts.check_patterns(f, no_edge) == []
    edge = {"patterns": {"bullish_engulfing": {"name": "Bullish engulfing", "verdict": "edge"}}}
    fired = rule_alerts.check_patterns(f, edge)
    assert fired and "Bullish engulfing" in fired[0]["detail"]


def test_new_drawing_kinds_are_validated(wdir):
    out = watch.save_drawings("TCS", [
        {"kind": "rect", "a": {"t": "2026-01-02", "v": 100}, "b": {"t": "2026-02-02", "v": 110}},
        {"kind": "text", "a": {"t": "2026-01-02", "v": 100}, "note": "results day"},
        {"kind": "avwap", "a": {"t": "2026-01-02", "v": 100}},
    ])
    assert [d["kind"] for d in out] == ["rect", "text", "avwap"]
    with pytest.raises(ValueError):
        watch.save_drawings("TCS", [{"kind": "text", "a": {"t": "2026-01-02", "v": 100}, "note": " "}])


def test_scan_on_live_prices_only_counts_quoted_stocks():
    idx = pd.bdate_range("2026-01-01", periods=60)
    base = pd.DataFrame({"A": np.linspace(100, 110, 60), "B": np.linspace(100, 110, 60), "C": np.linspace(100, 110, 60)}, index=idx)
    frames = {"open": base, "high": base * 1.01, "low": base * 0.99, "close": base, "volume": base * 0 + 1e5}
    scan = {"name": "up today", "match": "all", "direction": "long",
            "rules": [{"left": "change_pct", "op": ">", "right": {"value": 3}}]}
    quotes = {"A": {"price": 120, "open": 111, "high": 121, "low": 110, "volume": 2e5, "source": "live"},
              "B": {"price": 110.1, "source": "live"}, "C": {"price": 130, "source": "close"}}
    r = scans.run_live(scan, frames, quotes, ["A", "B", "C"], day=date(2026, 3, 30))
    assert [x["symbol"] for x in r["rows"]] == ["A"] and r["quoted"] == 2 and r["live"]


def test_smart_watchlist_follows_its_scan(wdir):
    watch.save_watchlists([{"name": "Main", "symbols": ["TCS"]}, {"name": "Breakouts", "symbols": [], "scan_id": "abc"}])
    assert watch.smart_scan_ids() == ["abc"]
    assert watch.refresh_smart({"abc": ["INFY", "WIPRO"]}) == 1
    lists = {x["name"]: x for x in watch.watchlists()["lists"]}
    assert lists["Breakouts"]["symbols"] == ["INFY", "WIPRO"] and lists["Main"]["symbols"] == ["TCS"]
    assert watch.refresh_smart({"abc": ["INFY", "WIPRO"]}) == 0                      # unchanged: no rewrite


def test_new_indicators_and_bar_sizes():
    from web.api.services import chart_data, intraday_chart
    idx = pd.bdate_range("2024-01-01", periods=120)
    up = pd.DataFrame({"open": np.linspace(100, 160, 120), "close": np.linspace(101, 161, 120)}, index=idx)
    up["high"], up["low"], up["volume"] = up["close"] + 1, up["open"] - 1, 1e5
    out = chart_data.extra_indicators(up, pd.DataFrame(index=idx))
    assert (out["psar"].iloc[-20:] < up["low"].iloc[-20:]).all()                 # an uptrend: SAR under the price
    assert out["aroon_up"].iloc[-1] == 100 and out["aroon_down"].iloc[-1] < 10
    assert out["ichi_span_a"].iloc[:26].isna().all()                               # the cloud starts 26 bars later
    assert len(chart_data.monthly(up)) == 6
    ts = pd.date_range("2026-11-10 09:15", "2026-11-10 15:25", freq="5min")
    bars = pd.DataFrame({"ts": ts, "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0, "flags": 0})
    r30 = intraday_chart.resample(bars, "30m")
    assert r30["ts"].dt.strftime("%H:%M").iloc[:3].tolist() == ["09:15", "09:45", "10:15"]
    assert intraday_chart.resample(bars, "1h")["ts"].dt.strftime("%H:%M").iloc[1] == "10:15"


def test_formula_alert_uses_the_live_bar(wdir, monkeypatch, tmp_path):
    from scanner import formula
    monkeypatch.setattr(formula, "DATA_DIR", tmp_path)
    f = formula.save_all([{"name": "Stretch", "expr": "close / sma(close, 20)"}])[0]
    idx = pd.bdate_range("2026-01-01", periods=60)
    s = pd.DataFrame({"TCS": np.full(60, 100.0)}, index=idx)
    frames = {"open": s, "high": s, "low": s, "close": s, "volume": s * 0 + 1e5}
    watch.add_alert("TCS", "formula_above", 1.05, ref=f["id"])
    day = date(2026, 3, 30)
    assert rule_alerts.check_live(s, {"TCS": {"price": 101, "source": "live"}}, day, frames=frames) == []
    fired = rule_alerts.check_live(s, {"TCS": {"price": 110, "source": "live"}}, day, frames=frames)
    assert fired and "Stretch" in fired[0]["detail"] and "Stretch" in watch.message(fired[0])
    with pytest.raises(ValueError):
        watch.add_alert("TCS", "formula_below", 1, ref="nope")
    formula.save_all([])
