"""Intraday engine rules: costs, fills, stop-first ambiguity, forced square-off."""
import numpy as np
import pandas as pd
import pytest

from scanner.intraday.engine import (FLAT_FNO, FLAT_OTHER, SLOTS, Day, IntradayCosts, IntradayStrategy, run_intraday,
                                     slot_of, stop_entry, walk_exit)
from scanner.intraday.strategies import orb15


def make_day(prices=None, is_fno=True, **kw) -> Day:
    p = np.full(SLOTS, 100.0) if prices is None else np.asarray(prices, dtype=float)
    o = p.copy()
    h, l, c = p * 1.001, p * 0.999, p.copy()
    v = np.full(SLOTS, 1000.0)
    args = dict(symbol="X", date=pd.Timestamp("2026-10-01"), o=o, h=h, l=l, c=c, v=v, prev_close=100.0,
                prev_high=101.0, prev_low=99.0, atr_d=2.0, is_fno=is_fno, large=True)
    args.update(kw)
    return Day(**args)


def test_slots_and_square_off_times():
    assert slot_of(9, 15) == 0 and slot_of(15, 0) == FLAT_FNO == 69 and slot_of(15, 15) == FLAT_OTHER == 72


def test_intraday_charges_match_fyers_model():
    c = IntradayCosts()
    # 1 lakh each side: brokerage Rs20 x2, STT 0.025% on 1L sell = 25, stamp 0.003% = 3, exch+sebi on 2L, GST
    exch, sebi = 200000 * 0.0000307, 200000 * 0.000001
    expected = 40 + exch + sebi + 0.18 * (40 + exch + sebi) + 25 + 3
    assert c.charges(100000, 100000) == pytest.approx(expected, rel=1e-6)


def test_stop_wins_when_bar_hits_stop_and_target():
    d = make_day()
    d.h[10], d.l[10] = 103.0, 97.0               # one bar spans both levels
    slot, px, why = walk_exit(d, +1, 5, stop=98.0, target=102.0)
    assert (slot, px, why) == (10, 98.0, "stop")


def test_gap_through_stop_fills_at_open():
    d = make_day()
    d.o[12], d.h[12], d.l[12], d.c[12] = 95.0, 95.5, 94.5, 95.0
    slot, px, why = walk_exit(d, +1, 5, stop=98.0, target=None)
    assert (slot, px, why) == (12, 95.0, "stop")


def test_forced_square_off_at_1500_for_fno_and_1515_others():
    s1, px1, why1 = walk_exit(make_day(is_fno=True), +1, 5, None, None)
    s2, _, _ = walk_exit(make_day(is_fno=False), +1, 5, None, None)
    assert (s1, why1) == (FLAT_FNO, "square-off") and s2 == FLAT_OTHER


def test_stop_entry_fills_at_level_or_gapped_open():
    d = make_day()
    d.h[4] = 101.5                                    # trades through 101 inside the bar
    assert stop_entry(d, +1, 101.0, 3, 60) == (4, 101.0)
    d2 = make_day()
    d2.o[4], d2.h[4] = 102.0, 102.5                   # opens above the level
    assert stop_entry(d2, +1, 101.0, 3, 60) == (4, 102.0)


def test_orb15_long_breakout_with_2r_target():
    d = make_day(atr_d=4.0)                           # range 1.0 < 1.5 x ATR/4 -> stop at the range low
    d.h[:3], d.l[:3] = 100.5, 99.5                    # opening range 99.5 - 100.5
    d.h[5], d.o[5], d.c[5] = 101.0, 100.4, 100.9      # breakout bar
    d.h[8], d.c[8] = 103.0, 102.8                     # reaches 2R
    t = orb15(d, {})[0]
    assert t.side == 1 and t.entry_slot == 5 and t.reason == "target"
    assert t.exit_px == pytest.approx(t.entry_px + 2 * (t.entry_px - 99.5))


def test_costs_turn_zero_edge_into_loss():
    """A strategy with zero gross edge must lose roughly its costs - the core intraday reality check."""
    days = []
    for k in range(20):
        d = make_day(date=pd.Timestamp("2026-09-01") + pd.Timedelta(days=k))
        days.append(d)
    flat = IntradayStrategy("flat", "flat", "", "TEST",
                            lambda d, p: [__import__("scanner.intraday.engine", fromlist=["Trade"]).Trade(
                                "", d.symbol, str(d.date.date()), 1, 10, 100.0, 60, 100.0, 99.0, "time")])
    res = run_intraday(flat, days, IntradayCosts(), capital=500000)
    assert res.metrics["trades"] == 20 and res.metrics["return_pct"] < 0
    assert all(t.pnl < 0 for t in res.trades)
