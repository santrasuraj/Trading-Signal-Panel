"""Paper-trading journal: fills, charges, stops, model sync, idempotency and determinism."""
import numpy as np
import pandas as pd
import pytest

from scanner import paper
from scanner.alerts import paper_line
from scanner.costs import CostModel

COSTS = CostModel(slippage_pct=0.1, slippage_illiquid_pct=0.1)   # same slippage whatever the liquidity
SLIP = 0.001
N = 30


def make_store(n=N, opens=None, lows=None, closes=None, n500=None):
    """Store-like wide frames: stocks A and B flat at 100 unless overridden, plus both indices."""
    idx = pd.bdate_range("2026-01-01", periods=n, name="date")
    close = pd.DataFrame({"A": 100.0, "B": 100.0, "NIFTY50": 1000.0, "NIFTY500": 100.0}, index=idx)
    for (sym, i), v in (closes or {}).items():
        close.iloc[i, close.columns.get_loc(sym)] = v
    if n500 is not None:
        close["NIFTY500"] = n500
    open_ = close.copy()
    for (sym, i), v in (opens or {}).items():
        open_.iloc[i, open_.columns.get_loc(sym)] = v
    high, low = np.maximum(open_, close), np.minimum(open_, close)
    for (sym, i), v in (lows or {}).items():
        low.iloc[i, low.columns.get_loc(sym)] = v
    return {"open": open_, "high": high, "low": low, "close": close,
            "volume": pd.DataFrame(1e6, index=idx, columns=close.columns)}


def scan(day, actions=(), positions=(), key="mom", kind="rank", max_positions=2, rules=None, live=False,
         capital=100_000.0):
    """The parts of a run_daily() result the journal reads."""
    return {
        "data_date": str(pd.Timestamp(day).date()), "generated_at": f"{pd.Timestamp(day).date()}T19:00:00+05:30",
        "live": live, "capital": capital, "min_position": 0,
        "strategies": [{
            "key": key, "name": key.title(), "kind": kind, "max_positions": max_positions, "rules": rules or {},
            "metrics": {"full": {"cagr_pct": 20.0, "cagr_range": [15.0, 25.0], "vol_pct": 20.0, "te_n500_pct": 10.0,
                                 "n500_benchmark": {"cagr_pct": 12.0}, "benchmark": {"cagr_pct": 11.0}}},
            "actions": [{"action": a, "symbol": s, "reason": r, "qty": 1, "price": 100.0, "stop": None}
                        for a, s, r in actions],
            "positions": [{"symbol": s, "entry_date": str(pd.Timestamp(e).date()), "entry_price": 100.0,
                           "last_price": 100.0, "stop": stop} for s, e, stop in positions],
        }],
    }


@pytest.fixture
def jpath(tmp_path):
    return tmp_path / "journal.sqlite"


def report(fr, jpath, key="mom"):
    return paper.build_report(fr, COSTS, jpath)[key]


def test_etf_stray_open_print_is_cleaned_like_the_backtest(jpath):
    """An ETF's odd-lot pre-open print (85 between closes of 100) is not a real fill price: the paper replay
    fills where the backtest does (clean_etf_prints) and never changes the shared store frames."""
    fr = make_store(opens={("A", 21): 85.0})
    d = fr["close"].index
    paper.record_scan(scan(d[20], actions=[("BUY", "A", "enters top ranks")]), jpath)
    assert paper.build_report(fr, COSTS, jpath)["mom"]["open"][0]["entry_price"] == pytest.approx(85 * (1 + SLIP))
    rep = paper.build_report(fr, COSTS, jpath, etfs={"A"})["mom"]
    assert rep["open"][0]["entry_price"] == pytest.approx(98 * (1 + SLIP))     # clamped to 2% below the closes
    assert fr["open"].iloc[21, 0] == 85.0                                      # the caller's frames untouched


def test_buy_fills_at_next_open_with_charges(jpath):
    fr = make_store(opens={("A", 21): 102.0})
    d = fr["close"].index
    paper.record_scan(scan(d[20], actions=[("BUY", "A", "enters top ranks")]), jpath)
    rep = report(fr, jpath)
    fill = 102 * (1 + SLIP)
    qty = int(50_000 // fill)                      # equity / max_positions
    value = qty * fill
    cash = 100_000 - value - COSTS.buy_cost(value)
    pos = rep["open"][0]
    assert pos["entry_date"] == d[21].date().isoformat() and pos["entry_price"] == pytest.approx(fill)
    assert pos["qty"] == qty and pos["via"] == "order"
    eq = rep["equity"]["Paper"]
    assert eq.index[0] == d[20] and eq.iloc[0] == 100_000           # curve starts on the journal day
    assert eq.iloc[1] == pytest.approx(cash + qty * 100)             # marked at the day's close
    assert rep["fees"] == pytest.approx(COSTS.buy_cost(value)) and rep["slippage"] == pytest.approx(qty * 102 * SLIP)


def test_sell_order_exits_at_next_open_after_all_charges(jpath):
    fr = make_store(opens={("A", 25): 110.0}, closes={("A", 25): 110.0})
    d = fr["close"].index
    paper.record_scan(scan(d[20], actions=[("BUY", "A", "enters top ranks")]), jpath)
    paper.record_scan(scan(d[24], actions=[("SELL", "A", "dropped from ranking")], positions=[("A", d[21], None)]),
                      jpath)
    rep = report(fr, jpath)
    t = rep["trades"][0]
    entry = 100 * (1 + SLIP)
    qty = int(50_000 // entry)
    cost = qty * entry + COSTS.buy_cost(qty * entry)
    exit_ = 110 * (1 - SLIP)
    proceeds = qty * exit_ - COSTS.sell_cost(qty * exit_)          # sell side includes the DP charge
    assert t["exit_date"] == d[25].date().isoformat() and t["exit_price"] == pytest.approx(exit_)
    assert t["reason"] == "dropped from ranking" and t["pnl"] == pytest.approx(proceeds - cost)
    assert not rep["open"] and rep["equity"]["Paper"].iloc[-1] == pytest.approx(100_000 - cost + proceeds)


@pytest.mark.parametrize("open_23,expected_raw", [(95.0, None), (85.0, 85.0)])
def test_stop_loss_intraday_and_on_a_gap(jpath, open_23, expected_raw):
    fr = make_store(opens={("A", 23): open_23}, lows={("A", 23): 84.0})
    d = fr["close"].index
    rules = {"stop_pct": 8}
    paper.record_scan(scan(d[20], actions=[("BUY", "A", "entry signal")], kind="event", rules=rules), jpath)
    rep = report(fr, jpath)
    t = rep["trades"][0]
    stop = 100 * (1 + SLIP) * 0.92
    raw = expected_raw if expected_raw is not None else stop         # gapped below the stop: filled at the open
    assert t["reason"] == "stop-loss" and t["exit_date"] == d[23].date().isoformat()
    assert t["exit_price"] == pytest.approx(raw * (1 - SLIP)) and t["pnl"] < 0


def test_stopped_out_position_is_not_bought_back_while_model_still_holds_it(jpath):
    fr = make_store(lows={("A", 23): 90.0})
    d = fr["close"].index
    rules = {"stop_pct": 8}
    paper.record_scan(scan(d[20], actions=[("BUY", "A", "entry signal")], kind="event", rules=rules), jpath)
    # The model's own stop sits lower (it bought earlier), so it still holds A after day 23.
    paper.record_scan(scan(d[24], positions=[("A", d[10], 80.0)], kind="event", rules=rules), jpath)
    rep = report(fr, jpath)
    assert [t["reason"] for t in rep["trades"]] == ["stop-loss"] and not rep["open"]


def test_follows_model_portfolio_on_first_day_and_after_missed_scans(jpath):
    fr = make_store()
    d = fr["close"].index
    paper.record_scan(scan(d[20], positions=[("B", d[5], None)]), jpath)    # no orders, model holds B
    paper.record_scan(scan(d[25], positions=[]), jpath)                     # model sold B on a day we missed
    rep = report(fr, jpath)
    t = rep["trades"][0]
    assert t["symbol"] == "B" and t["via"] == "sync"
    assert t["entry_date"] == d[21].date().isoformat() and t["exit_date"] == d[26].date().isoformat()
    assert t["reason"] == paper.NOT_IN_MODEL


def test_journal_is_idempotent_and_skips_live_scans(jpath):
    fr = make_store()
    d = fr["close"].index
    s1 = scan(d[20], actions=[("BUY", "A", "enters top ranks")], positions=[("B", d[5], None)])
    assert paper.record_scan(s1, jpath) == 1
    first = report(fr, jpath)
    assert paper.record_scan(s1, jpath) == 1                       # same day scanned again
    j = paper.load_journal(jpath)
    assert (len(j["scans"]), len(j["orders"]), len(j["positions"])) == (1, 1, 1)
    again = report(fr, jpath)
    pd.testing.assert_frame_equal(first["equity"], again["equity"])  # deterministic re-run
    assert first["open"] == again["open"]

    assert paper.record_scan(scan(d[21], actions=[("BUY", "B", "x")], live=True), jpath) == 0
    assert len(paper.load_journal(jpath)["scans"]) == 1           # provisional intraday orders never journaled

    paper.record_scan(scan(d[20], actions=[("BUY", "B", "enters top ranks")]), jpath)   # same day, new orders
    j = paper.load_journal(jpath)
    assert j["orders"]["symbol"].tolist() == ["B"] and j["positions"].empty


def test_orders_wait_for_the_next_trading_day(jpath):
    fr = make_store(n=21)
    d = fr["close"].index
    paper.record_scan(scan(d[20], actions=[("BUY", "A", "enters top ranks")]), jpath)
    rep = report(fr, jpath)
    assert rep["days"] == 0 and not rep["open"] and rep["pending"] == [
        {"action": "BUY", "symbol": "A", "reason": "enters top ranks"}]
    assert "first fills at the next open" in paper_line(rep["summary"])
    rep2 = report(make_store(n=22), jpath)                         # next day's prices arrive
    assert not rep2["pending"] and rep2["open"][0]["entry_date"] == "2026-01-30"


def test_summary_compares_with_indices_and_backtest(jpath):
    n500 = np.r_[np.full(21, 100.0), np.linspace(100, 110, N - 21)]
    fr = make_store(n500=n500)
    d = fr["close"].index
    paper.record_scan(scan(d[20]), jpath)                          # all cash: paper return 0
    sm = report(fr, jpath)["summary"]
    assert sm["return_pct"] == pytest.approx(0) and sm["n500_pct"] == pytest.approx(10)
    assert sm["nifty_pct"] == pytest.approx(0) and sm["excess_pct"] == pytest.approx(-10)
    years = 9 / 252
    exp_excess = (1.2 ** years - 1.12 ** years) * 100
    assert sm["expected_excess_pct"] == pytest.approx(exp_excess)
    assert sm["expected_pct"] == pytest.approx(10 + exp_excess)
    assert sm["noise_pct"] == pytest.approx(2 * 10 * np.sqrt(years))
    assert "Too early" in sm["verdict"]
    line = paper_line(paper.summaries(fr, COSTS, jpath)["mom"])
    assert line.startswith("📒 Paper since 29 Jan (9 days): +0.0%") and "Nifty 500 +10.0%" in line


def test_paper_report_is_plain_json_for_the_api(jpath):
    import json
    fr = make_store(opens={("A", 25): 110.0}, closes={("A", 25): 110.0})
    d = fr["close"].index
    paper.record_scan(scan(d[20], actions=[("BUY", "A", "enters top ranks")], positions=[("B", d[5], 90.0)]), jpath)
    paper.record_scan(scan(d[24], actions=[("SELL", "A", "dropped from ranking")],
                           positions=[("A", d[21], None), ("B", d[5], 90.0)]), jpath)
    out = paper.paper_report(fr, COSTS, jpath)
    assert json.loads(json.dumps(out, allow_nan=False)) == out     # no NaN, numpy or pandas types anywhere
    s = out["strategies"]["mom"]
    assert s["equity"][0] == ["2026-01-29", 100_000.0] and len(s["equity"]) == len(s["nifty500"]) == N - 20
    assert s["nifty50"][-1] == ["2026-02-11", 100_000.0]          # flat index, scaled to the capital
    assert [t["symbol"] for t in s["trades"]] == ["A"] and [o["symbol"] for o in s["open"]] == ["B"]
    assert s["open"][0]["stop"] == pytest.approx(90.0)             # model stop, as a fraction of that day's close
    assert s["summary"]["comparison"].startswith("Since 29 Jan 2026 (9 trading days)")
    assert s["summary"] == paper.summaries(fr, COSTS, jpath)["mom"]


def test_no_journal_gives_empty_report(jpath):
    assert paper.build_report(make_store(), COSTS, jpath) == {}
    assert paper.paper_report(make_store(), COSTS, jpath)["strategies"] == {}
