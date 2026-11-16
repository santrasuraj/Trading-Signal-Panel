"""Your own scans (scanner/scans.py), strategy robustness (web/api/services/robustness.py), chart drawings
(scanner/watch.py) and the extra chart indicators (web/api/services/chart_data.py)."""
import numpy as np
import pandas as pd
import pytest

from scanner import scans, watch
from scanner.panel import panel_from_wide


def _frames(n=320, syms=("AAA", "BBB", "CCC")):
    idx = pd.bdate_range("2024-01-01", periods=n)
    rng = np.random.default_rng(1)
    close = pd.DataFrame({s: 100 * np.exp(np.cumsum(rng.normal(0.0005 * (i + 1), 0.01, n))) for i, s in enumerate(syms)}, index=idx)
    close["CCC"] = np.r_[np.full(n - 1, 100.0), 120.0]                    # CCC jumps on the last day only
    fr = {"close": close, "open": close.shift(1).fillna(close), "high": close * 1.01, "low": close * 0.99,
          "volume": pd.DataFrame(1000.0, index=idx, columns=list(syms))}
    fr["volume"].iloc[-1, 2] = 5000.0
    return fr


def test_validate_rejects_bad_scans():
    for bad in ({"rules": []}, {"rules": [{"left": "nope", "op": ">", "right": {"value": 1}}]},
                {"rules": [{"left": "close", "op": "~", "right": {"value": 1}}]},
                {"rules": [{"left": "close", "op": ">", "right": {"field": "sma50", "mult": -1}}]},
                {"rules": [{"left": "close", "op": ">", "right": {}}]}, {"match": "most", "rules": [{"left": "close", "op": ">", "right": {"value": 1}}]}):
        with pytest.raises(ValueError):
            scans.validate(bad)
    s = scans.validate({"rules": [{"left": "close", "op": ">", "right": {"field": "sma50"}}]})
    assert s["rules"][0]["right"] == {"field": "sma50", "mult": 1.0} and s["match"] == "all"
    assert scans.describe_rule(s["rules"][0]) == "Close > SMA 50"


def test_rules_all_any_and_crosses():
    fr = _frames()
    ctx = scans.Ctx(panel_from_wide(fr))
    jump = {"left": "change_pct", "op": ">=", "right": {"value": 15}}
    volx = {"left": "vol_ratio", "op": ">", "right": {"value": 3}}
    m = scans.evaluate(scans.validate({"match": "all", "rules": [jump, volx]}), ctx)
    assert m.iloc[-1].to_dict() == {"AAA": False, "BBB": False, "CCC": True} and not m.iloc[:-1]["CCC"].any()
    cross = scans.evaluate(scans.validate({"rules": [{"left": "close", "op": "crosses_above", "right": {"value": 110}}]}), ctx)
    assert cross["CCC"].sum() == 1 and bool(cross["CCC"].iloc[-1])
    anym = scans.evaluate(scans.validate({"match": "any", "rules": [jump, {"left": "close", "op": "<", "right": {"value": 0}}]}), ctx)
    assert bool(anym["CCC"].iloc[-1]) and anym["AAA"].sum() == 0


def test_run_today_lists_matches_and_new_ones():
    fr = _frames()
    r = scans.run_today({"name": "Jump", "rules": [{"left": "change_pct", "op": ">=", "right": {"value": 15}}]}, fr, ["AAA", "BBB", "CCC"],
                        {"CCC": {"company": "Ccc Ltd"}})
    assert r["count"] == 1 and r["rows"][0]["symbol"] == "CCC" and r["rows"][0]["new_today"] and r["rows"][0]["company"] == "Ccc Ltd"
    assert r["rows"][0]["values"]["change_pct"] == 20.0 and r["universe_size"] == 3


def test_backtest_measures_onset_events_against_the_average_member(monkeypatch):
    idx = pd.bdate_range("2023-01-02", periods=600)
    syms = [f"S{i}" for i in range(6)]
    close = pd.DataFrame(100.0, index=idx, columns=syms)
    close["S0"] = 100 * np.exp(np.arange(600) * 0.002)                    # S0 rises steadily: above its 20-day SMA
    fr = {"close": close, "open": close.shift(1).fillna(close), "high": close, "low": close,
          "volume": pd.DataFrame(1000.0, index=idx, columns=syms)}
    uni = pd.DataFrame(True, index=idx, columns=syms)
    ctx = scans.Ctx(panel_from_wide(fr, universe=uni))
    monkeypatch.setattr(scans, "_pit_ctx", lambda: (None, ctx))
    b = scans.backtest({"rules": [{"left": "close", "op": ">", "right": {"field": "sma20"}}]})
    assert b["events"] == 1                                               # onset only: once, not every day it holds
    flat = scans.backtest({"rules": [{"left": "close", "op": "<", "right": {"value": 0}}]})
    assert flat["events"] == 0 and flat["verdict"] == "too_few"


def test_saved_scans_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(watch, "DATA_DIR", tmp_path)
    watch._cache.clear()
    s = scans.save(scans.PRESETS[0])
    assert [x["id"] for x in scans.saved()] == [s["id"]]
    scans.save({**scans.PRESETS[1], "name": "Renamed"}, s["id"])
    assert scans.saved()[0]["name"] == "Renamed"
    scans.delete(s["id"])
    assert scans.saved() == []


def test_drawings_round_trip_and_validation(tmp_path, monkeypatch):
    monkeypatch.setattr(watch, "DATA_DIR", tmp_path)
    watch._cache.clear()
    out = watch.save_drawings("reliance", [{"kind": "hline", "price": 1300}, {"kind": "fib", "a": {"t": "2026-01-02", "v": 1200},
                                                                            "b": {"t": "2026-03-02", "v": 1400}}])
    assert [d["kind"] for d in watch.drawings("RELIANCE")] == ["hline", "fib"] and out[0]["id"]
    for bad in ([{"kind": "circle"}], [{"kind": "hline", "price": -1}], [{"kind": "trend", "a": {"t": "x", "v": 1}, "b": {"t": "2026-01-01", "v": 1}}]):
        with pytest.raises((ValueError, TypeError)):
            watch.save_drawings("RELIANCE", bad)
    watch.save_drawings("RELIANCE", [])
    assert watch.drawings("RELIANCE") == []


def test_monte_carlo_and_deflated_sharpe():
    from web.api.services import robustness as rb
    rng = np.random.default_rng(3)
    good = rng.normal(0.0012, 0.01, 1500)                                 # ~35%/yr, Sharpe ~1.9
    mc = rb.monte_carlo(good, bench_cagr=0.10, paths=2000)
    assert mc["cagr_pct"]["p5"] < mc["cagr_pct"]["p50"] < mc["cagr_pct"]["p95"] and mc["prob_loss_pct"] < 5
    assert mc["max_dd_pct"]["p5"] <= mc["max_dd_pct"]["p50"] <= 0
    lucky = rb.deflated_sharpe(good, [0.02, 0.05, 0.08, -0.01, 0.12])
    noise = rb.deflated_sharpe(rng.normal(0.0, 0.01, 1500), [0.02, 0.05, 0.08, -0.01, 0.12])
    assert lucky["deflated_pct"] > 95 and noise["deflated_pct"] < 50 and lucky["trials"] == 5


def test_extra_chart_indicators_are_in_range():
    from web.api.services import chart_data
    n = 400
    rng = np.random.default_rng(5)
    c = pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.01, n))), index=pd.bdate_range("2025-01-01", periods=n))
    df = pd.DataFrame({"open": c, "high": c * 1.01, "low": c * 0.99, "close": c, "volume": 1000.0})
    out = chart_data.with_indicators(df)
    for k, lo, hi in (("stoch_k", 0, 100), ("mfi14", 0, 100), ("willr14", -100, 0), ("adx14", 0, 100)):
        v = out[k].dropna()
        assert len(v) and v.min() >= lo - 1e-9 and v.max() <= hi + 1e-9, k
    st = out["supertrend"].dropna()
    assert len(st) > n - 20 and (out["dc_upper"].dropna() >= out["dc_lower"].dropna()).all()
