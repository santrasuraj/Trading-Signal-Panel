"""Unit tests for the maths and data-integrity logic that every result depends on."""
import numpy as np
import pandas as pd
import pytest

from scanner import corporate, store
from scanner.costs import CostModel
from scanner.engine import EventStrategy, RankStrategy, rebalance_days, simulate
from scanner.nse import DayFile, _OtherDay, _parse_stocks
from scanner.panel import Factors, panel_from_wide


# ------------------------------------------------------------------ costs
def test_costs_round_trip_includes_stt_stamp_and_slippage():
    c = CostModel()
    # 1 lakh: brokerage capped at Rs20 each side, STT 0.1% x2, stamp 0.015%, slippage 0.1% x2, DP Rs15.34
    rt = c.round_trip_pct(100_000)
    assert 0.45 < rt < 0.50
    assert c.buy_cost(100_000) == pytest.approx(20 + 2.97 + 0.1 + (20 + 2.97 + 0.1) * 0.18 + 100 + 15, rel=1e-3)


def test_costs_override_from_config():
    c = CostModel.from_config({"brokerage_max": 0, "brokerage_pct": 0, "unknown_key": 5})
    assert c.brokerage_max == 0 and c.buy_cost(100_000) < CostModel().buy_cost(100_000)


# ------------------------------------------------------------------ corporate actions
@pytest.mark.parametrize("purposes,expected", [
    (["BONUS 1:1"], 0.5),
    (["BONUS 4:1"], 0.2),
    (["FV SPLT FRM RS 2 TO RE 1"], 0.5),
    (["FACE VALUE SPLIT (SUB-DIVISION) - FROM RS 10/- PER SHARE TO RE 1/- PER SHARE"], 0.1),
    (["BONUS 1:1", "FV SPLT FRM RS 2 TO RE 1"], 0.25),
    (["CONSOLIDATION FROM RS 1 TO RS 10"], 10.0),
    (["DEMERGER"], None),
    (["ANNUAL GENERAL MEETING"], None),
])
def test_purpose_factor(purposes, expected):
    got = corporate.purpose_factor(purposes)
    assert (got is None and expected is None) or got == pytest.approx(expected)


def _nse_day(sym, open_, close, prev):
    stocks = pd.DataFrame({"open": [open_], "high": [max(open_, close)], "low": [min(open_, close)],
                           "close": [close], "volume": [1e6], "prev_close": [prev], "deliv_pct": [50.0]},
                          index=pd.Index([sym], name="symbol"))
    return DayFile(None, "ok", stocks, None)


def _series_frames(closes, dates):
    c = pd.DataFrame({"X": closes}, index=pd.DatetimeIndex(dates, name="date"), dtype=float)
    return {"close": c.copy(), "open": c.copy(), "high": c * 1.01, "low": c * 0.99,
            "volume": c * 0 + 1e6, "deliv_pct": c * np.nan}


def test_event_factor_split_in_raw_data_is_adjusted(monkeypatch):
    # Our data is raw: 1000 -> 505 on a 1:1 bonus day (official move +1% after adjustment).
    monkeypatch.setattr(corporate, "symbol_on", lambda s, d: s)
    monkeypatch.setattr(corporate, "actions_on", lambda s, d, prior: ["BONUS 1:1"])
    dates = pd.bdate_range("2025-01-01", periods=3)
    fr = _series_frames([990, 1000, 505], dates)
    adj = store._event_factor(fr, "X", dates[2], _nse_day("X", 500, 505, 1000), [dates[1].date()])
    assert adj and adj["factor"] == pytest.approx(0.5)
    store._apply_corporate_action(fr, "X", dates[2], adj["factor"])
    assert fr["close"]["X"].tolist() == pytest.approx([495, 500, 505])


def test_event_factor_already_adjusted_data_is_left_alone(monkeypatch):
    # Source already adjusted the bonus: our series is smooth, NSE shows the raw halving.
    monkeypatch.setattr(corporate, "symbol_on", lambda s, d: s)
    monkeypatch.setattr(corporate, "actions_on", lambda s, d, prior: ["BONUS 1:1"])
    dates = pd.bdate_range("2025-01-01", periods=3)
    fr = _series_frames([495, 500, 505], dates)
    assert store._event_factor(fr, "X", dates[2], _nse_day("X", 500, 505, 1000), []) is None


def test_event_factor_genuine_crash_is_kept(monkeypatch):
    monkeypatch.setattr(corporate, "symbol_on", lambda s, d: s)
    monkeypatch.setattr(corporate, "actions_on", lambda s, d, prior: [])
    dates = pd.bdate_range("2025-01-01", periods=3)
    fr = _series_frames([1900, 1886, 1207], dates)   # e.g. POLICYBZR -36%: real, no corporate action
    assert store._event_factor(fr, "X", dates[2], _nse_day("X", 1697, 1207, 1886), []) is None


def test_event_factor_demerger_uses_special_session_price(monkeypatch):
    monkeypatch.setattr(corporate, "symbol_on", lambda s, d: s)
    monkeypatch.setattr(corporate, "actions_on", lambda s, d, prior: ["DEMERGER"])
    dates = pd.bdate_range("2026-04-28", periods=3)
    fr = _series_frames([739.3, 773.6, 271.55], dates)   # VEDL 2026-04-30
    adj = store._event_factor(fr, "X", dates[2], _nse_day("X", 289.5, 271.55, 773.6), [])
    assert adj["factor"] == pytest.approx(289.5 / 773.6, rel=1e-4)


def test_merge_overwrites_only_given_values():
    idx = pd.DatetimeIndex(pd.bdate_range("2025-01-01", periods=2), name="date")
    frames = {f: pd.DataFrame({"A": [1.0, 2.0], "B": [3.0, 4.0]}, index=idx) for f in store.FIELDS}
    new_idx = pd.DatetimeIndex([idx[1], idx[1] + pd.Timedelta(days=1)], name="date")
    store._merge(frames, {"close": pd.DataFrame({"A": [20.0, 30.0], "C": [np.nan, 5.0]}, index=new_idx)})
    c = frames["close"]
    assert c.loc[idx[1], "A"] == 20 and c.loc[idx[1], "B"] == 4 and c.loc[new_idx[1], "C"] == 5
    assert c.loc[idx[0], "A"] == 1 and np.isnan(c.loc[new_idx[1], "B"])


def test_nse_holiday_file_detected():
    csv = ("SYMBOL, SERIES, DATE1, PREV_CLOSE, OPEN_PRICE, HIGH_PRICE, LOW_PRICE, LAST_PRICE, CLOSE_PRICE, "
           "AVG_PRICE, TTL_TRD_QNTY, TURNOVER_LACS, NO_OF_TRADES, DELIV_QTY, DELIV_PER\n"
           "RELIANCE, EQ, 19-Oct-2026, 1211.2, 1212, 1228.2, 1201, 1202, 1202, 1212.3, 100, 1, 1, 50, 50.0\n")
    from datetime import date
    with pytest.raises(_OtherDay):
        _parse_stocks(csv, date(2026, 10, 20))
    df = _parse_stocks(csv, date(2026, 10, 19))
    assert df.loc["RELIANCE", "close"] == 1202 and df.loc["RELIANCE", "deliv_pct"] == 50.0


# ------------------------------------------------------------------ factors
def test_rsi_flat_is_neutral_and_rising_is_100(frames_factory):
    fr = frames_factory({"FLAT": [100.0] * 40, "UP": list(np.arange(100, 140, dtype=float))})
    f = Factors(panel_from_wide(fr))
    assert f.rsi14["FLAT"].iloc[-1] == 50 and f.rsi14["UP"].iloc[-1] == 100


def test_52w_high_prev_excludes_today(frames_factory):
    path = list(np.linspace(100, 150, 300))
    f = Factors(panel_from_wide(frames_factory({"A": path})))
    assert f.high_52w_prev["A"].iloc[-1] < f.p.high["A"].iloc[-1]          # yesterday's high is lower
    assert f.high_52w["A"].iloc[-1] == pytest.approx(f.p.high["A"].iloc[-1])


def test_momentum_score_ranks_stronger_stock_higher(frames_factory):
    rng = np.random.default_rng(0)
    noise = rng.normal(0, 0.01, (400, 3))
    paths = {k: 100 * np.exp(np.cumsum(drift + noise[:, i])) for i, (k, drift)
             in enumerate([("STRONG", 0.003), ("FLAT", 0.0), ("WEAK", -0.003)])}
    f = Factors(panel_from_wide(frames_factory(paths)))
    last = f.momentum.iloc[-1]
    assert last["STRONG"] > last["FLAT"] > last["WEAK"] > 0


def test_factors_have_no_lookahead(frames_factory):
    """Changing the future must not change any factor value in the past."""
    rng = np.random.default_rng(1)
    base = 100 * np.exp(np.cumsum(rng.normal(0, 0.02, 320)))
    alt = base.copy()
    alt[300:] *= 3   # wild future
    fa = Factors(panel_from_wide(frames_factory({"A": base, "B": base[::-1].copy()})))
    fb = Factors(panel_from_wide(frames_factory({"A": alt, "B": base[::-1].copy()})))
    for name in ("sma50", "rsi14", "rsi2", "atr14", "high_52w_prev", "vol_ratio", "rs_rating", "momentum", "macd"):
        a, b = getattr(fa, name).iloc[:300], getattr(fb, name).iloc[:300]
        pd.testing.assert_frame_equal(a, b, check_exact=False, rtol=1e-9)


# ------------------------------------------------------------------ engine
def _flat_market(frames_factory, n=300, price=100.0):
    fr = frames_factory({"A": [price] * n, "B": [price] * n})
    p = panel_from_wide(fr)
    p.index_close = pd.Series(1000.0, index=p.dates)
    return p


def test_engine_fills_next_open_and_hits_stop(frames_factory):
    n = 300
    closes = [100.0] * n
    opens = [100.0] * n
    opens[262], closes[262] = 101.0, 101.0          # filled here (day after the signal)
    for i in range(263, n):
        closes[i] = 80.0                             # collapse -> stop must trigger
        opens[i] = 80.0
    fr = frames_factory({"A": closes}, opens={"A": opens})
    p = panel_from_wide(fr)
    p.index_close = pd.Series(1000.0, index=p.dates)
    f = Factors(p)
    sig = pd.DataFrame(False, index=p.dates, columns=["A"])
    sig.iloc[261] = True                             # signal at close of day 261
    strat = EventStrategy("t", "t", "", entries=lambda _: sig, stop_pct=8, max_positions=1, use_regime=False)
    costs = CostModel(slippage_pct=0.1, illiquid_below_cr=0)     # treat the test stock as liquid
    trad = pd.DataFrame(True, index=p.dates, columns=["A"])
    res = simulate(strat, f, costs, tradable=trad, capital=100_000, warmup=252)
    t = res.trades[0]
    assert t.entry_date == p.dates[262] and t.entry_price == pytest.approx(101 * 1.001)
    assert t.reason == "stop-loss" and t.exit_date == p.dates[263]
    assert t.exit_price == pytest.approx(80 * 0.999)             # gapped below the stop: filled at the open
    assert t.pnl < 0 and t.ret_pct < -20
    # The same stock as an illiquid one (~Rs 10 crore/day < 25) pays the higher slippage.
    t2 = simulate(strat, f, CostModel(slippage_pct=0.1, slippage_illiquid_pct=0.3), tradable=trad,
                  capital=100_000, warmup=252).trades[0]
    assert t2.entry_price == pytest.approx(101 * 1.003)


def test_rank_strategy_holds_top_n_and_respects_regime(frames_factory):
    p = _flat_market(frames_factory)
    f = Factors(p)
    score = pd.DataFrame({"A": 2.0, "B": 1.0}, index=p.dates)
    strat = RankStrategy("r", "r", "", score=lambda _: score, top_n=1, keep_rank=1, use_regime=False)
    res = simulate(strat, f, CostModel(), tradable=pd.DataFrame(True, index=p.dates, columns=["A", "B"]))
    assert [o["symbol"] for o in res.open_positions] == ["A"]
    p.index_close = pd.Series(np.linspace(2000, 1000, len(p.dates)), index=p.dates)   # falling Nifty
    f2 = Factors(p)
    strat2 = RankStrategy("r", "r", "", score=lambda _: score, top_n=1, use_regime=True)
    res2 = simulate(strat2, f2, CostModel(), tradable=pd.DataFrame(True, index=p.dates, columns=["A", "B"]))
    assert not res2.trades and not res2.open_positions                 # no buys below the 200-DMA


def test_rebalance_days_are_month_ends():
    d = pd.bdate_range("2025-01-01", "2025-03-31")
    r = rebalance_days(d, "monthly")
    assert [x.date().isoformat() for x in d[r]] == ["2025-01-31", "2025-02-28"]   # last row never rebalances


def test_scan_lock_blocks_second_scan():
    from scanner.lock import ScanBusy, scan_lock
    with scan_lock("test"):
        with pytest.raises(ScanBusy):
            with scan_lock("test2"):
                pass
    with scan_lock("again"):   # released afterwards
        pass


# ------------------------------------------------------------------ tax
def _result_with(trades, equity):
    from scanner.engine import SimResult
    return SimResult("x", equity, equity * 0 + 1, trades, [], [], 0)


def test_after_tax_short_term_gain_taxed_next_april():
    from scanner.costs import TaxModel
    from scanner.engine import Trade, after_tax_equity
    idx = pd.bdate_range("2024-01-01", "2025-06-30")
    eq = pd.Series(np.linspace(100_000, 150_000, len(idx)), index=idx)
    t = Trade("A", pd.Timestamp("2024-05-01"), 100, pd.Timestamp("2024-09-01"), 120, 1000, 20_000, 20, 85, "x")
    out = after_tax_equity(_result_with([t], eq), TaxModel())
    assert out.loc[:"2025-03-31"].equals(eq.loc[:"2025-03-31"])           # nothing paid during FY24-25
    pay = out.index[out.index >= "2025-04-01"][0]
    assert out.loc[pay] == pytest.approx(eq.loc[pay] - 20_000 * 0.208)     # 20.8% of the gain, next April


def test_after_tax_losses_offset_and_ltcg_exemption():
    from scanner.costs import TaxModel
    from scanner.engine import Trade, after_tax_equity
    idx = pd.bdate_range("2023-01-02", "2025-06-30")
    eq = pd.Series(1_000_000.0, index=idx)
    trades = [
        Trade("A", pd.Timestamp("2023-05-01"), 1, pd.Timestamp("2023-08-01"), 1, 1, -30_000, -3, 60, "x"),  # ST loss
        Trade("B", pd.Timestamp("2023-05-01"), 1, pd.Timestamp("2023-09-01"), 1, 1, 50_000, 5, 80, "x"),   # ST gain
        Trade("C", pd.Timestamp("2022-01-01"), 1, pd.Timestamp("2023-10-01"), 1, 1, 100_000, 10, 400, "x"),  # LT gain
    ]
    out = after_tax_equity(_result_with(trades, eq), TaxModel())
    # ST net 20k -> 4,160 tax; LT 100k is under the 1.25L exemption -> 0
    assert out.iloc[-1] == pytest.approx(1_000_000 - 20_000 * 0.208)


def test_quarterly_and_semiannual_rebalance():
    d = pd.bdate_range("2025-01-01", "2025-12-31")
    q = [x.date().isoformat() for x in d[rebalance_days(d, "quarterly")]]
    h = [x.date().isoformat() for x in d[rebalance_days(d, "semiannual")]]
    assert q == ["2025-03-31", "2025-06-30", "2025-09-30"] and h == ["2025-06-30"]


def test_rebalance_offset_moves_decision_earlier():
    d = pd.bdate_range("2025-01-01", "2025-03-31")
    base = [x.date().isoformat() for x in d[rebalance_days(d, "monthly")]]
    shifted = [x.date().isoformat() for x in d[rebalance_days(d, "monthly", offset=2)]]
    assert base == ["2025-01-31", "2025-02-28"] and shifted == ["2025-01-29", "2025-02-26"]


# ------------------------------------------------------------------ console / Telegram summary
def _summary_result(**market):
    m = {"label": "Mixed", "level": "neutral", "advice": "Be selective.", "nifty": 22687.6, "nifty_change_pct": -0.5,
         "vix": 15.8, "breadth_50": 13.2}
    m.update(market)
    buys = [{"action": "BUY", "symbol": "AAA", "qty": 100, "price": 300.0, "amount": 30_000.0, "stop": 276.0},
            {"action": "BUY", "symbol": "MRF", "qty": 0, "price": 140_000.0, "amount": 0.0},
            {"action": "BUY", "symbol": "TINY", "qty": 2, "price": 5_000.0, "amount": 10_000.0}]
    return {"generated_at": "2026-10-23T22:19:02+05:30", "data_date": "2026-10-22", "live": False,
            "min_position": 15_000, "market": m, "holdings": [],
            "strategies": [{"key": "momentum", "name": "Momentum", "status": "working", "actions": buys,
                            "positions": [], "metrics": {"full": {"cagr_pct": 10.0, "start": "2019-08-19",
                                                                  "end": "2026-10-22"}, "12m": {}}}]}


def test_summary_survives_missing_index_data_and_skips_buys_the_backtest_would_skip():
    from scanner.alerts import format_daily
    text = format_daily(_summary_result(nifty=None, nifty_change_pct=None, vix=None, breadth_50=None))
    assert "Nifty - (-)" in text and "VIX -" in text and "- of stocks above 50-DMA" in text
    buy_line = next(x for x in text.splitlines() if "BUY at next open" in x)
    assert "AAA x100" in buy_line and "MRF" not in buy_line and "TINY" not in buy_line
    skipped = next(x for x in text.splitlines() if "Skipped" in x)
    assert "MRF" in skipped and "TINY" in skipped and "15,000" in skipped


def test_telegram_without_credentials_sends_nothing(monkeypatch):
    from scanner import alerts

    def no_network(*a, **k):
        raise AssertionError("must not call Telegram without credentials")
    monkeypatch.setattr(alerts, "env", lambda name, default="": "")
    monkeypatch.setattr(alerts.requests, "post", no_network)
    ok, msg = alerts.send_telegram("hello")
    assert not ok and "not configured" in msg


def test_run_scan_finishes_even_if_the_summary_fails(tmp_path, monkeypatch):
    import json
    import logging
    import sys

    import run_scan

    def broken_summary(*a, **k):
        raise KeyError("market")
    monkeypatch.setattr(run_scan, "_logger", lambda: logging.getLogger("test-run-scan"))   # not data/logs
    monkeypatch.setattr(run_scan, "load_config", lambda: {})
    monkeypatch.setattr(run_scan, "run_daily", lambda cfg, **kw: {"elapsed_s": 1.0})
    monkeypatch.setattr(run_scan, "format_daily", broken_summary)
    status = tmp_path / "status.json"
    monkeypatch.setattr(sys, "argv", ["run_scan.py", "--no-update", "--status", str(status)])
    assert run_scan.main() == 0
    assert json.loads(status.read_text(encoding="utf-8"))["state"] == "done"
