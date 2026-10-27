"""Signal track record (scanner/track.py) and signal strength (web/api/services/signal_quality.py)."""
import json

import numpy as np
import pandas as pd
import pytest

from scanner.costs import CostModel
from scanner.paper import NOT_IN_MODEL, _COLUMNS
from scanner.track import MIN_CLOSED, strategy_track, track_record, verdict

DATES = pd.bdate_range("2026-09-01", periods=12)
COSTS = CostModel()


def frames(opens, lows=None, highs=None, closes=None, sym="AAA"):
    o = np.array(opens, dtype=float)
    lo = np.array(lows if lows is not None else o * 0.99, dtype=float)
    hi = np.array(highs if highs is not None else o * 1.01, dtype=float)
    c = np.array(closes if closes is not None else o, dtype=float)

    def mk(v):
        return pd.DataFrame({sym: v}, index=DATES[:len(v)])
    return {"open": mk(o), "high": mk(hi), "low": mk(lo), "close": mk(c), "volume": mk(np.full(len(o), 5e6))}


def journal(days, buys=(), sells=(), held=None, rules=None, kind="event"):
    """days: journal (scan) dates; buys / sells: (date, symbol, price, stop); held: {date: [symbols in the model]}."""
    rules = {"max_positions": 10, "stop_pct": 8.0, "target_pct": None, "trail_pct": None, **(rules or {})}
    scans = [(x, "s1", "Strat", kind, f"{x}T19:15:00+05:30", 500000.0, json.dumps(rules), json.dumps({"status": "working"}))
             for x in days]
    orders = [(x, "s1", s, "BUY", i, "entry signal", 100, p, st) for i, (x, s, p, st) in enumerate(buys)]
    orders += [(x, "s1", s, "SELL", 50 + i, "exit signal", 100, p, None) for i, (x, s, p, _) in enumerate(sells)]
    pos = [(x, "s1", s, x, 100.0, 100.0, None) for x, syms in (held or {}).items() for s in syms]
    return {"scans": pd.DataFrame(scans, columns=_COLUMNS["scans"]),
            "orders": pd.DataFrame(orders, columns=_COLUMNS["orders"]),
            "positions": pd.DataFrame(pos, columns=_COLUMNS["positions"])}


def d(i):
    return DATES[i].date().isoformat()


def test_signal_fills_next_open_and_is_marked_open():
    f = frames([100, 101, 102, 103, 104])
    j = journal([d(i) for i in range(5)], buys=[(d(0), "AAA", 100.0, 92.0)], held={d(i): ["AAA"] for i in range(1, 5)})
    [r] = strategy_track("s1", j, f, COSTS)
    assert r["state"] == "open" and r["entry_date"] == d(1) and r["qty"] == 100
    # under 15 days of turnover history a stock counts as illiquid: the higher slippage, as in the backtest
    assert r["entry_price"] == pytest.approx(101 * (1 + COSTS.slippage_illiquid_pct / 100), rel=1e-4)
    assert r["last_price"] == 104.0 and r["days"] == 3
    assert r["pnl"] < (104 - r["entry_price"]) * 100                      # charges both ways are paid
    assert r["status_then"] == "working"


def test_stop_loss_exits_intraday_at_the_stop():
    f = frames([100, 101, 97, 96, 96], lows=[99, 100, 90, 95, 95])       # stop = 8% under the fill (~93)
    j = journal([d(0), d(1), d(2)], buys=[(d(0), "AAA", 100.0, None)], held={d(1): ["AAA"], d(2): ["AAA"]})
    [r] = strategy_track("s1", j, f, COSTS)
    assert r["state"] == "closed" and r["exit_reason"] == "stop-loss" and r["exit_date"] == d(2)
    stop = 101 * (1 + COSTS.slippage_illiquid_pct / 100) * 0.92
    assert r["exit_price"] == pytest.approx(stop * (1 - COSTS.slippage_illiquid_pct / 100), abs=0.01)   # rupees, 2 dp
    assert r["ret_pct"] < -8


def test_sell_signal_exits_at_the_next_open_and_a_missing_model_position_too():
    f = frames([100, 101, 102, 103, 104, 105])
    j = journal([d(0), d(1), d(2), d(3)], buys=[(d(0), "AAA", 100.0, None)], sells=[(d(2), "AAA", 102.0, None)],
                held={d(1): ["AAA"], d(2): ["AAA"]})
    [r] = strategy_track("s1", j, f, COSTS)
    assert (r["state"], r["exit_reason"], r["exit_date"]) == ("closed", "exit signal", d(3))
    j2 = journal([d(0), d(1), d(2)], buys=[(d(0), "AAA", 100.0, None)], held={d(1): ["AAA"]})   # gone on d(2)
    [r2] = strategy_track("s1", j2, f, COSTS)
    assert (r2["exit_reason"], r2["exit_date"]) == (NOT_IN_MODEL, d(3))


def test_target_and_trailing_stop_follow_the_rules():
    f = frames([100, 101, 103, 112, 104], highs=[101, 102, 104, 113, 105], lows=[99, 100, 102, 111, 103])
    j = journal([d(i) for i in range(5)], buys=[(d(0), "AAA", 100.0, None)],
                held={d(i): ["AAA"] for i in range(1, 5)}, rules={"target_pct": 10.0})
    [r] = strategy_track("s1", j, f, COSTS)
    assert r["exit_reason"] == "target" and r["exit_date"] == d(3)
    f2 = frames([100, 101, 110, 120, 104], lows=[99, 100, 109, 119, 103], closes=[100, 101, 110, 120, 104])
    j2 = journal([d(i) for i in range(5)], buys=[(d(0), "AAA", 100.0, None)],
                 held={d(i): ["AAA"] for i in range(1, 5)}, rules={"trail_pct": 10.0})
    [r2] = strategy_track("s1", j2, f2, COSTS)
    assert r2["exit_reason"] == "stop-loss" and r2["exit_date"] == d(4)      # 10% under the 120 peak = 108
    assert r2["ret_pct"] > 0


def test_unfillable_and_pending_signals_are_never_counted_as_trades():
    up = frames([100, 110, 110], lows=[99, 110, 109], highs=[101, 110, 111], closes=[100, 110, 110])   # locked up
    [r] = strategy_track("s1", journal([d(0)], buys=[(d(0), "AAA", 100.0, None)]), up, COSTS)
    assert r["state"] == "not_filled" and "upper circuit" in r["note"]
    [p] = strategy_track("s1", journal([d(1)], buys=[(d(1), "AAA", 101.0, None)]), frames([100, 101]), COSTS)
    assert p["state"] == "pending" and p["pnl"] == 0.0


def test_verdict_needs_enough_closed_signals(monkeypatch):
    assert verdict({"closed": MIN_CLOSED - 1})[0] == "unknown"
    assert verdict({"closed": MIN_CLOSED, "expectancy_pct": 0.8})[0] == "good"
    assert verdict({"closed": MIN_CLOSED, "expectancy_pct": -0.1})[0] == "bad"
    import scanner.track as t
    monkeypatch.setattr(t, "load_journal", lambda path=None: journal(
        [d(0), d(1), d(2)], buys=[(d(0), "AAA", 100.0, None)], held={d(1): ["AAA"], d(2): ["AAA"]}))
    rep = track_record(frames([100, 101, 102]), COSTS)
    assert rep["overall"]["open"] == 1 and rep["strategies"]["s1"]["level"] == "unknown"
    assert rep["as_of"] == d(2) and rep["signals"][0]["symbol"] == "AAA"


# ------------------------------------------------------------------ strength
def _strat(key, status="working", evidence="STRONG", buys=(), held=()):
    return {"key": key, "name": key.upper(), "lifecycle": "active", "status": status, "evidence": evidence,
            "actions": [{"symbol": s, "action": "BUY"} for s in buys], "positions": [{"symbol": s} for s in held]}


def _order(key, sym, warn=False):
    return {"strategy_key": key, "symbol": sym, "action": "BUY", "comparison_only": False, "results_warning": warn,
            "results_in_days": 2 if warn else None}


def test_strength_adds_up_its_parts_and_rewards_agreement():
    from web.api.services import signal_quality as q
    strategies = [_strat("a", buys=["X"]), _strat("b", evidence="WEAK", held=["X"]),
                  _strat("c", status="not-working", held=["X"]), _strat("d", status="mixed", evidence="MODERATE", buys=["Y"])]
    orders = [_order("a", "X"), _order("d", "Y", warn=True),
              {**_order("a", "Z"), "action": "SELL"}, {**_order("c", "X"), "comparison_only": True}]
    q.attach(orders, {}, strategies, {"a": {"level": "good", "verdict": "Making money"}})
    x, y, sell, cmp_only = (o["strength"] for o in orders)
    assert sell is None and cmp_only is None
    assert x["agree"] == ["B"]                                  # a not-working strategy never counts as agreement
    assert x["score"] == 30 + 25 + 10 + 10 + 10 == sum(p["points"] for p in x["parts"]) and x["grade"] == "strong"
    assert y["score"] == 20 + 12 + 0 + 5 + 0 and y["grade"] == "fair"
    assert all(p["points"] <= p["max"] for p in x["parts"]) and sum(p["max"] for p in x["parts"]) == 100
