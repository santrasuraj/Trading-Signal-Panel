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
