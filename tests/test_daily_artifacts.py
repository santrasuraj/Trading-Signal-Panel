"""scanner/daily.py additions for the platform: B4 lifecycle, B5 rules, B9 write order (latest.json last)."""
from __future__ import annotations

import json
from datetime import datetime
from types import SimpleNamespace

import pandas as pd

from scanner import daily
from scanner.settings import IST
from scanner.strategies import REJECTED_REASONS, build_strategies, strategy_lifecycle


def test_lifecycle_rules():
    assert strategy_lifecycle({}, "momentum") == ("active", None)
    assert strategy_lifecycle({}, "rsi2_pullback")[0] == "rejected"
    assert strategy_lifecycle({"strategies": {"momentum": {"enabled": False}}}, "momentum") == ("disabled", None)
    cfg = {"strategies": {"momentum": {"enabled": False, "rejected_reason": "too slow"}}}
    assert strategy_lifecycle(cfg, "momentum") == ("rejected", "too slow")
    assert strategy_lifecycle({"strategies": {"near_high": {"enabled": True}}}, "near_high") == ("active", None)
    keys_all = {s.key for s in build_strategies({}, include_disabled=True)}
    keys_on = {s.key for s in build_strategies({})}
    assert set(REJECTED_REASONS) <= keys_all and not (set(REJECTED_REASONS) & keys_on)


def test_rules_cover_every_simulation_setting():
    cfg = {"strategies": {"earnings_gap": {"stop_pct": 6, "max_hold": 30}}}
    by_key = {s.key: s for s in build_strategies(cfg, include_disabled=True)}
    r = daily._rules(by_key["earnings_gap"], cfg["strategies"]["earnings_gap"])
    assert r["kind"] == "event" and r["stop_pct"] == 6 and r["max_hold"] == 30 and r["params"] == {"stop_pct": 6, "max_hold": 30}
    assert r["rebalance"] is None and r["top_n"] is None
    m = daily._rules(by_key["momentum"], None)
    assert m["kind"] == "rank" and m["rebalance"] == "monthly" and m["top_n"] == 15 and m["keep_rank"] == 30
    assert m["use_regime"] is True and m["regime_action"] == "hold" and m["sizing"] == "equal" and m["params"] == {}
    for k in ("stop_pct", "target_pct", "trail_pct", "sizing", "risk_pct"):   # keys the paper journal reads
        assert k in r and k in m


def test_save_writes_artifacts_first_and_latest_last(tmp_path, monkeypatch):
    for name, f in (("RESULTS_DIR", ""), ("LATEST_FILE", "latest.json"), ("CURVES_FILE", "curves.parquet"),
                    ("TRADES_FILE", "trades.parquet"), ("SCREENER_FILE", "screener.parquet")):
        monkeypatch.setattr(daily, name, tmp_path / f if f else tmp_path)
    order = []
    real = daily._write_atomic

    def spy(path, write):
        order.append(path.name)
        real(path, write)
    monkeypatch.setattr(daily, "_write_atomic", spy)
    idx = pd.bdate_range("2026-01-01", periods=5, name="date")
    p = SimpleNamespace(index_close=pd.Series([100, 101, 102, 103, 104.0], index=idx))
    ew = pd.Series([1, 1.01, 1.02, 1.03, 1.04], index=idx)
    result = {"version": 2, "generated_at": "2026-01-07T19:00:00+05:30", "strategies": []}
    trades = pd.DataFrame([{"strategy": "x", "symbol": "A", "ret_pct": 1.0}])
    screener = pd.DataFrame([{"symbol": "A", "price": 10.0}])
    daily._save(result, {"x": pd.Series([1, 1.1, 1.2, 1.3, 1.4], index=idx)}, p, ew, None,
                datetime(2026, 1, 7, 19, 0, tzinfo=IST), trades=trades, screener=screener)
    assert order[-1] == "latest.json" and order[0] == "curves.parquet"
    assert order.index("trades.parquet") < order.index("latest.json") > order.index("screener.parquet")
    assert not list(tmp_path.glob("*.tmp"))
    assert pd.read_parquet(tmp_path / "trades.parquet")["scan_id"].tolist() == ["2026-01-07T19:00:00+05:30"]
    assert json.loads((tmp_path / "latest.json").read_text(encoding="utf-8"))["generated_at"] == result["generated_at"]
    assert (tmp_path / "scan_20260107_1900.json").exists()


def test_ranking_uses_the_simulation_universe(frames_factory):
    """The ranking shown for a rank strategy never lists what its backtest cannot buy (ETFs in a stock
    strategy, stocks in an ETF strategy, untradable or ineligible names)."""
    from scanner.engine import RankStrategy
    from scanner.panel import Factors, panel_from_wide
    p = panel_from_wide(frames_factory({"A": [100.0] * 30, "B": [100.0] * 30, "NIFTYBEES": [100.0] * 30}))
    f = Factors(p, etfs={"NIFTYBEES"})
    score = pd.DataFrame({"NIFTYBEES": 3.0, "A": 2.0, "B": 1.0}, index=p.dates)
    trad = pd.DataFrame(True, index=p.dates, columns=["A", "B", "NIFTYBEES"])
    trad.iloc[-1, trad.columns.get_loc("B")] = False
    stocks = RankStrategy("s", "s", "", score=lambda _: score)
    etfs = RankStrategy("e", "e", "", score=lambda _: score, universe="etfs")
    only_b = RankStrategy("b", "b", "", score=lambda _: score, eligible=lambda _: score < 1.5)
    assert list(daily._rank_candidates(stocks, f, trad).index) == ["A"]
    assert list(daily._rank_candidates(etfs, f, trad).index) == ["NIFTYBEES"]
    assert daily._rank_candidates(only_b, f, trad).empty


def test_clean_metrics_rounds_lists_like_numbers():
    m = daily._clean_metrics({"full": {"cagr_pct": 41.91543139, "cagr_range": [41.91543139, 47.4499, float("nan")],
                                       "name": "x"}})
    assert m["full"]["cagr_pct"] == 41.915 and m["full"]["cagr_range"] == [41.915, 47.45, None]
    assert m["full"]["cagr_range"][0] <= m["full"]["cagr_pct"] and m["full"]["name"] == "x"


def test_yearly_returns_run_from_the_previous_year_end():
    idx = pd.to_datetime(["2021-06-01", "2021-12-31", "2022-01-03", "2022-12-30"])
    eq = pd.Series([100.0, 110.0, 99.0, 121.0], index=idx)
    y = daily._calendar_yearly(eq).round(4).to_dict()
    assert y == {2021: 10.0, 2022: 10.0}        # 2022 = 121 / 110 - 1, not 121 / 99 - 1


def test_etf_stray_open_prints_are_cleaned_and_stocks_are_not():
    from scanner.panel import panel_from_wide
    idx = pd.to_datetime(["2021-12-30", "2021-12-31", "2022-01-03"])
    frame = lambda e, s: pd.DataFrame({"JUNIORBEES": e, "STOCK": s}, index=idx)   # noqa: E731
    frames = {"open": frame([437.0, 481.0, 386.1], [100.0, 100.0, 112.0]),
              "high": frame([440.0, 484.0, 464.7], [101.0, 101.0, 113.0]),
              "low": frame([382.9, 432.0, 386.1], [99.0, 99.0, 104.0]),
              "close": frame([437.2, 443.8, 446.8], [100.0, 100.0, 105.0]),
              "volume": frame([1.0, 1.0, 1.0], [1.0, 1.0, 1.0])}
    p = panel_from_wide(frames, ["JUNIORBEES", "STOCK"], etfs={"JUNIORBEES"})
    o, lo, hi = p.open["JUNIORBEES"], p.low["JUNIORBEES"], p.high["JUNIORBEES"]
    assert abs(o.iloc[2] - 443.8 * 0.98) < 0.01 and abs(o.iloc[1] - 443.8 * 1.02) < 0.01
    assert (lo <= o).all() and (o <= hi).all() and (lo <= p.close["JUNIORBEES"]).all()
    assert p.open["STOCK"].iloc[2] == 112.0 and p.low["STOCK"].iloc[2] == 104.0     # a real stock gap stays
