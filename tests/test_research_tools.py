"""Options backtester (scanner/options_backtest.py), company numbers (scanner/fundamentals.py) and the economic calendar
(scanner/econ.py). Synthetic data only: no NSE call."""
from datetime import date

import numpy as np
import pandas as pd
import pytest

from scanner import econ, fundamentals as fu, options_backtest as ob


def _hist(spot_path, expiry="2026-03-30", start="2026-03-02"):
    """Daily option rows for one expiry: strikes every 100 around 10,000, prices = intrinsic + a time value that
    shrinks to zero at expiry."""
    days = pd.bdate_range(start, expiry)
    exp = pd.Timestamp(expiry)
    rows = []
    for d, s in zip(days, spot_path):
        tv = 150.0 * max((exp - d).days, 0) / 30
        for k in range(9000, 11001, 100):
            for typ in ("CE", "PE"):
                intr = max(s - k, 0) if typ == "CE" else max(k - s, 0)
                px = intr + tv * np.exp(-abs(k - s) / 400)
                rows.append({"date": d, "symbol": "NIFTY", "expiry": exp, "strike": float(k), "type": typ,
                             "close": round(px, 2), "settle": px, "oi": 1000.0, "volume": 10.0, "underlying": float(s), "lot": 65.0})
    return pd.DataFrame(rows)


def test_iron_condor_keeps_the_credit_when_the_index_stays_put():
    h = _hist([10_000.0] * 21)
    r = ob.backtest(h, {"strategy": "iron_condor", "cycle": "monthly", "entry_dte": 30, "short_pct": 2, "wing_pct": 4,
                        "slippage_pct": 0})
    t = r["trades"][0]
    assert t["why"] == "expiry" and [l["strike"] for l in t["legs"]] == [9600, 9800, 10200, 10400]
    assert t["gross"] == pytest.approx(t["credit"]) and t["pnl"] == pytest.approx(t["credit"] - t["charges"])
    assert 0 < t["charges"] < 200


def test_stop_closes_a_short_strangle_on_a_big_move():
    path = [10_000.0] * 5 + [10_000.0 + 150 * i for i in range(1, 17)]
    r = ob.backtest(_hist(path), {"strategy": "short_strangle", "cycle": "monthly", "entry_dte": 30, "short_pct": 2,
                                  "stop_pct": 100, "slippage_pct": 0})
    t = r["trades"][0]
    assert t["why"] == "stop" and t["exit"] < "2026-03-30" and t["pnl"] < 0
    assert r["stats"]["exits"]["stop"] == 1


def test_bad_wings_are_refused():
    with pytest.raises(ValueError):
        ob.legs_for({"strategy": "iron_condor", "short_pct": 3, "wing_pct": 2})


XBRL = """<xbrli:xbrl>
<xbrli:context id="OneD"><xbrli:entity/><xbrli:period><xbrli:startDate>2026-07-01</xbrli:startDate><xbrli:endDate>2026-09-30</xbrli:endDate></xbrli:period></xbrli:context>
<xbrli:context id="Seg"><xbrli:entity><xbrli:segment><xbrldi:explicitMember>x</xbrldi:explicitMember></xbrli:segment></xbrli:entity><xbrli:period><xbrli:startDate>2026-07-01</xbrli:startDate><xbrli:endDate>2026-09-30</xbrli:endDate></xbrli:period></xbrli:context>
<xbrli:context id="Half"><xbrli:entity/><xbrli:period><xbrli:startDate>2026-04-01</xbrli:startDate><xbrli:endDate>2026-09-30</xbrli:endDate></xbrli:period></xbrli:context>
<in-capmkt:RevenueFromOperations contextRef="Seg" unitRef="INR">5</in-capmkt:RevenueFromOperations>
<in-capmkt:RevenueFromOperations contextRef="Half" unitRef="INR">2000</in-capmkt:RevenueFromOperations>
<in-capmkt:RevenueFromOperations contextRef="OneD" unitRef="INR">1000</in-capmkt:RevenueFromOperations>
<in-capmkt:ProfitLossForPeriod contextRef="OneD" unitRef="INR">150</in-capmkt:ProfitLossForPeriod>
<in-capmkt:BasicEarningsLossPerShareFromContinuingOperations contextRef="OneD" unitRef="INRPerShare">2.5</in-capmkt:BasicEarningsLossPerShareFromContinuingOperations>
</xbrli:xbrl>"""


def test_xbrl_reads_the_quarter_without_segments():
    v = fu.parse_xbrl(XBRL, "2026-09-30")
    assert v["revenue"] == 1000 and v["profit"] == 150 and v["eps"] == 2.5


def test_growth_ttm_and_point_in_time_frames(tmp_path, monkeypatch):
    monkeypatch.setattr(fu, "DIR", tmp_path)
    q = {}
    for i, qe in enumerate(["2025-06-30", "2025-09-30", "2025-12-31", "2026-03-31", "2026-06-30", "2026-09-30"]):
        q[qe] = {"revenue": 1000.0 * (1.1 ** (i // 4)) + i, "profit": 100.0 + 10 * i, "eps": 1.0 + 0.1 * i,
                 "filed": (pd.Timestamp(qe) + pd.Timedelta(days=20)).date().isoformat(), "xbrl": "x"}
    fu._save("AAA", {"symbol": "AAA", "basis": "consolidated", "quarters": q, "checked": "2026-11-01"})
    t = fu.table(fu.load("AAA"))
    last = t.iloc[-1]
    assert last["profit_growth"] == pytest.approx((150 / 110 - 1) * 100)
    assert last["eps_ttm"] == pytest.approx(1.2 + 1.3 + 1.4 + 1.5)
    dates = pd.bdate_range("2026-09-01", "2026-11-10")
    f = fu.frames(["AAA", "BBB"], dates)
    assert f["eps_ttm"].loc["2026-10-19", "AAA"] == pytest.approx(1.1 + 1.2 + 1.3 + 1.4)    # before the Sep quarter's filing
    assert f["eps_ttm"].loc["2026-10-20", "AAA"] == pytest.approx(5.4)                     # from its filing day
    assert f["eps_ttm"]["BBB"].isna().all()


def test_economic_calendar_rules():
    ev = econ.events(date(2026, 11, 1), date(2026, 12, 31))
    names = {(e["date"], e["name"]) for e in ev}
    assert ("2026-11-12", "India CPI inflation") in names
    assert ("2026-12-14", "India CPI inflation") in names                 # the 12th is a Saturday
    assert ("2026-12-04", "RBI policy decision") in names
    assert ("2026-11-30", "India GDP") in names
    assert ("2026-12-10", "US Fed decision (overnight)") in names


# ---- formulas, drawings, trendlines, weekly fields ------------------------------------------------------------------
def test_formula_language_is_safe_and_works_on_one_or_many_stocks():
    from scanner import formula as fm
    idx = pd.bdate_range("2026-01-01", periods=80)
    s = pd.Series(np.linspace(100, 179, 80), index=idx)
    cols = {"open": s, "high": s + 1, "low": s - 1, "close": s, "volume": s * 0 + 1000}
    v = fm.evaluate("close - sma(close, 10)", cols)
    assert v.iloc[-1] == pytest.approx(4.5) and v.iloc[:9].isna().all()
    wide = {k: pd.DataFrame({"A": x, "B": x * 2}) for k, x in cols.items()}
    w = fm.evaluate("roc(close, 1)", wide)
    assert list(w.columns) == ["A", "B"] and w["A"].iloc[-1] == pytest.approx(w["B"].iloc[-1])
    for bad in ("__import__('os')", "close.real", "sma(close, n)", "close ** close", "open[0]", "1 + 2", "'x'"):
        with pytest.raises(fm.FormulaError):
            fm.evaluate(bad, cols)


def test_saved_formulas_become_scan_fields(tmp_path, monkeypatch):
    from scanner import formula as fm, scans
    monkeypatch.setattr(fm, "DATA_DIR", tmp_path)
    out = fm.save_all([{"name": "Stretch", "expr": "close / sma(close, 20)", "pane": "own"}])
    key = f"f_{out[0]['id']}"
    assert key in scans.FIELDS and scans.FIELDS[key].group == "Your formulas"
    with pytest.raises(fm.FormulaError):
        fm.save_all([{"name": "A", "expr": "close"}, {"name": "a", "expr": "open"}])
    fm.save_all([])
    assert key not in scans.FIELDS


def test_new_drawing_kinds_are_validated(tmp_path, monkeypatch):
    from scanner import watch
    monkeypatch.setattr(watch, "DATA_DIR", tmp_path)
    p = lambda t, v: {"t": t, "v": v}  # noqa: E731
    out = watch.save_drawings("TCS", [
        {"kind": "channel", "a": p("2026-01-02", 100), "b": p("2026-02-02", 110), "c": p("2026-01-15", 120)},
        {"kind": "pitchfork", "a": p("2026-01-02", 100), "b": p("2026-02-02", 110), "c": p("2026-03-02", 95)},
        {"kind": "arrow", "a": p("2026-01-02", 100), "note": "up"},
        {"kind": "measure", "a": p("2026-01-02", 100), "b": p("2026-02-02", 110)},
        {"kind": "ray", "a": p("2026-01-02", 100), "b": p("2026-02-02", 110)}])
    assert [d["kind"] for d in out] == ["channel", "pitchfork", "arrow", "measure", "ray"] and out[0]["c"]["v"] == 120
    with pytest.raises(ValueError):
        watch.save_drawings("TCS", [{"kind": "arrow", "a": p("2026-01-02", 100), "note": "sideways"}])
    with pytest.raises(ValueError):
        watch.save_drawings("TCS", [{"kind": "channel", "a": p("2026-01-02", 100), "b": p("2026-02-02", 110)}])


def test_falling_trendline_breakout_is_found():
    from scanner import levels as lv
    n = 120
    idx = pd.bdate_range("2026-01-01", periods=n)
    base = np.linspace(200, 150, n)                                   # a falling market ...
    wave = 6 * np.sin(np.arange(n) / 5.0)                             # ... with swings
    close = base + wave
    close[-3:] = close[-4] + np.array([8, 14, 18])                    # ... that breaks out at the end
    df = pd.DataFrame({"open": close, "high": close + 1, "low": close - 1, "close": close, "volume": 1e5}, index=idx)
    pts = lv.turning_points(df)
    a = float(lv.atr(df).iloc[-1])
    found = lv._trendlines(df, pts, a)
    up = [p for p in found if p["key"] == "trendline_break_up"]
    assert up and up[0]["status"] == "confirmed" and up[0]["direction"] == "up" and up[0]["lines"]


def test_weekly_scan_fields_use_completed_weeks_only():
    from scanner import scans
    from scanner.panel import panel_from_wide
    idx = pd.bdate_range("2026-01-05", periods=60)                    # Mondays to Fridays
    close = pd.DataFrame({"A": np.arange(60, dtype=float) + 100}, index=idx)
    p = panel_from_wide({"open": close, "high": close, "low": close, "close": close, "volume": close * 0 + 1e5})
    ctx = scans.Ctx(p)
    w = ctx.get("w_ret_4")["A"]
    fridays = [d for d in idx if d.weekday() == 4]
    f5 = fridays[4]
    assert not np.isnan(w.loc[f5])
    nxt = idx[idx.get_loc(f5) + 1]                                      # the Monday after: still last Friday's value
    assert w.loc[nxt] == w.loc[f5]
    assert w.loc[fridays[3]] != w.loc[f5]


def test_chart_layouts_round_trip(tmp_path, monkeypatch):
    from web.api.paths import P
    from web.api.services import layouts_svc
    monkeypatch.setattr(P, "data", tmp_path)
    lay = {"name": "Swing", "ind": ["sma50"], "log": False, "lines": True, "ctype": "candles", "tf": "1d", "range": "1y", "levels": []}
    out = layouts_svc.write([lay, {**lay, "name": "swing "}])
    assert [x["name"] for x in out["layouts"]] == ["Swing"] and layouts_svc.read() == out
