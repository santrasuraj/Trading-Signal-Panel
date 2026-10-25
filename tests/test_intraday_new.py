"""The three pre-registered intraday research tests (gap_fade_largecap, inplay_orb15, niftybees_eod_momentum),
their engine hooks (prepare / notional sizing / slippage override / gross return) and the daily-data gap-fade
test. Synthetic bars only: every check is about rules (who is picked, when it fills, no look-ahead), not profit."""
import numpy as np
import pandas as pd
import pytest

from scanner.intraday.engine import FLAT_FNO, FLAT_OTHER, SLOTS, Day, IntradayCosts, run_intraday
from scanner.intraday.strategies import (C_1415, C_1445, OR15_END, S_0945, S_1445, build_intraday_strategies,
                                         gap_fade_daily, gap_fade_largecap, gap_fade_prepare, inplay_orb15,
                                         inplay_prepare, niftybees_eod_momentum)

DAY = pd.Timestamp("2026-10-01")


def make_day(symbol="X", open0=100.0, is_fno=True, **kw) -> Day:
    p = np.full(SLOTS, 100.0)
    o, h, l, c = p.copy(), p * 1.001, p * 0.999, p.copy()
    o[0] = open0
    args = dict(symbol=symbol, date=DAY, o=o, h=h, l=l, c=c, v=np.full(SLOTS, 1000.0), prev_close=100.0,
                prev_high=101.0, prev_low=99.0, atr_d=2.0, is_fno=is_fno, large=True, ctx={"liquidity": 500.0})
    args.update(kw)
    return Day(**args)


def strategy(key, cfg=None):
    return next(s for s in build_intraday_strategies(cfg or {}) if s.key == key)


# ------------------------------------------------------------------------------------ gap fade (5-minute)
def gap_days():
    return [make_day("NIFTYBEES", 100.5, is_fno=False),          # market gap +0.5%
            make_day("U1", 103.0), make_day("U2", 102.6), make_day("U3", 102.2),
            make_day("U4", 102.1),                                 # 4th largest: only 3 legs a side
            make_day("D1", 97.0),                                  # idiosyncratic gap -3.5%
            make_day("Q", 101.5),                                  # +1.0% after the market: below 1.5%
            make_day("R", 104.0, results_day=True),                # results news
            make_day("INFY", 104.0),                               # ADR: priced from US trading
            make_day("BIG", 112.0),                                # raw gap > 10%
            make_day("N", 104.0, is_fno=False)]                    # not F&O: no MIS short


def test_gap_fade_picks_market_adjusted_gaps_with_the_exclusions():
    picks = gap_fade_prepare(gap_days(), {})["_picks"]
    assert {k[0]: v[0] for k, v in picks.items()} == {"U1": -1, "U2": -1, "U3": -1, "D1": +1}
    assert picks[("U1", DAY)][1] == pytest.approx(0.025)
    assert gap_fade_prepare(gap_days()[1:], {})["_picks"] == {}           # no NIFTYBEES bar: no trades
    two = gap_fade_prepare(gap_days(), {"threshold_pct": 2.0})["_picks"]
    assert sorted(k[0] for k in two) == ["D1", "U1", "U2"]


def test_gap_fade_picks_ignore_everything_after_the_open():
    days = gap_days()
    before = gap_fade_prepare(days, {})["_picks"]
    for d in days:                                                         # rewrite every bar after 09:15
        d.o[1:], d.h[1:], d.l[1:], d.c[1:] = 50.0, 150.0, 40.0, 60.0
    assert gap_fade_prepare(days, {})["_picks"] == before


def test_gap_fade_enters_at_0920_exits_at_1500_with_equal_notional_legs():
    days = gap_days()
    d1 = next(d for d in days if d.symbol == "D1")
    d1.l[10] = 97.0                                                        # long stop = 100 - 1 x ATR = 98
    res = run_intraday(strategy("gap_fade_largecap"), days, IntradayCosts(), capital=500000, leverage=2.0)
    by = {t.symbol: t for t in res.trades}
    assert set(by) == {"U1", "U2", "U3", "D1"}
    assert all(t.entry_slot == 1 for t in res.trades)                      # first price after the 09:15 decision
    assert by["U1"].exit_slot == FLAT_FNO and by["U1"].side == -1
    assert (by["D1"].reason, by["D1"].exit_slot, by["D1"].exit_px) == ("stop", 10, 98.0)
    assert by["U1"].qty == int(500000 * 2 / 6 / (100.0 * (1 - 0.03 / 100)))   # 1/6 of the leverage limit
    assert by["U1"].gross_pct == pytest.approx(0.0) and by["U1"].pnl < 0      # no move: costs only
    assert res.metrics["avg_trade_gross_pct"] is not None


def test_gap_fade_skips_a_day_without_a_0920_price():
    d = make_day("U1", 103.0)
    d.o[1:3] = np.nan
    assert gap_fade_largecap(d, {"_picks": {("U1", DAY): (-1, 0.025)}}) == []


# ------------------------------------------------------------------------------------ stocks in play ORB-15
def inplay_day(symbol, relvol, trigger_slot=None, **kw):
    d = make_day(symbol, ctx={"relvol": relvol, "liquidity": 500.0}, **kw)
    d.h[:OR15_END], d.l[:OR15_END], d.c[OR15_END - 1] = 100.5, 99.5, 100.3   # up first 15 minutes, range 99.5-100.5
    if trigger_slot is not None:
        i = trigger_slot
        d.o[i], d.h[i], d.l[i], d.c[i] = 100.2, 101.0, 100.2, 100.9
        d.o[i + 1:], d.h[i + 1:], d.l[i + 1:], d.c[i + 1:] = 101.0, 101.1, 100.9, 101.0
    return d


def test_inplay_picks_are_made_at_0930_and_an_untriggered_pick_stays_empty():
    days = [inplay_day("A", 3.0),                    # most in play, never breaks out
            inplay_day("B", 2.5, trigger_slot=10),
            inplay_day("C", 2.0, trigger_slot=5),    # triggers first, but ranked 3rd at 09:30
            inplay_day("D", 1.0, trigger_slot=5),    # exactly 1.0 = fewer than 5 earlier sessions: unknown
            inplay_day("E", 0.8, trigger_slot=5)]    # below the 100% threshold
    assert inplay_prepare(days, {})["_picks"] == {("A", DAY): 1, ("B", DAY): 1}
    res = run_intraday(strategy("inplay_orb15"), days, IntradayCosts())
    assert [t.symbol for t in res.trades] == ["B"]   # C does not fill A's empty slot


def test_inplay_entry_waits_for_0930_and_both_entry_bar_orderings():
    d = inplay_day("B", 2.5, trigger_slot=10)
    picks = {("B", DAY): 1}
    first = inplay_orb15(d, {"_picks": picks})[0]
    assert first.entry_slot >= OR15_END and first.entry_px == pytest.approx(100.5)
    # stop 100.5 - 10% x ATR 2 = 100.3; the entry bar's low 100.2 is below it
    assert (first.reason, first.exit_slot, first.exit_px) == ("stop", 10, pytest.approx(100.3))
    late = inplay_orb15(d, {"_picks": picks, "entry_bar": "entry_first"})[0]   # bar closed at 100.9, above the stop
    assert (late.reason, late.exit_slot, late.exit_px) == ("square-off", FLAT_FNO, 101.0)
    rng = inplay_orb15(d, {"_picks": picks, "stop": "range"})[0]
    assert rng.stop == 99.5 and rng.reason == "square-off"


def test_inplay_news_filter_and_short_direction():
    plain = inplay_day("P", 1.5)
    news = inplay_day("R", 1.5, results_day=True)
    gap = inplay_day("G", 1.6, open0=103.0)          # |gap| 3% counts as news
    gap.c[OR15_END - 1] = 102.0                      # below its 09:15 open: short
    assert inplay_prepare([plain, news, gap], {"filter": "rvol_news", "top_n": 5})["_picks"] == {
        ("R", DAY): 1, ("G", DAY): -1}


# ------------------------------------------------------------------------------------ NIFTYBEES last half hour
def bees(**kw):
    d = make_day("NIFTYBEES", is_fno=False, **kw)
    d.c[S_0945] = 100.4                              # up 0.4% at 09:45
    d.o[S_1445], d.o[FLAT_OTHER] = 100.6, 100.9
    return d


def test_niftybees_momentum_enters_1445_exits_1515():
    t = niftybees_eod_momentum(bees(), {})[0]
    assert (t.side, t.entry_slot, t.entry_px, t.exit_slot, t.exit_px) == (1, S_1445, 100.6, FLAT_OTHER, 100.9)
    assert t.entry_slot > C_1445 > S_0945            # every input is a close before the entry bar
    assert t.stop == pytest.approx(100.6 * 0.99)
    assert niftybees_eod_momentum(make_day("RELIANCE"), {}) == []


def test_niftybees_variants():
    d = bees()
    d.c[C_1415], d.c[C_1445] = 100.5, 100.2          # 14:15 -> 14:45 falls while the morning was up
    assert niftybees_eod_momentum(d, {"rule": "agree"}) == []
    d.c[C_1445] = 99.5                               # below yesterday's close at 14:45
    assert niftybees_eod_momentum(d, {"rule": "rod"})[0].side == -1
    assert niftybees_eod_momentum(d, {})[0].side == 1


def test_niftybees_is_sized_at_1x_with_its_own_slippage():
    res = run_intraday(strategy("niftybees_eod_momentum"), [bees()], IntradayCosts(), capital=500000, leverage=2.0)
    t = res.trades[0]
    assert t.qty == int(500000 * 1.0 / (100.6 * (1 + 0.02 / 100)))
    assert t.gross_pct == pytest.approx((100.9 / 100.6 - 1) * 100)
    robust = strategy("niftybees_eod_momentum", {"intraday_strategies": {"niftybees_eod_momentum": {"slippage_pct": 0.07}}})
    assert robust.slippage_pct == 0.07


def test_only_pre_registered_settings_are_accepted():
    keys = [s.key for s in build_intraday_strategies({})]
    assert {"gap_fade_largecap", "inplay_orb15", "niftybees_eod_momentum"} <= set(keys)
    assert strategy("orb15").prepare is None and strategy("orb15").notional_x is None
    with pytest.raises(ValueError):
        build_intraday_strategies({"intraday_strategies": {"gap_fade_largecap": {"threshold_pct": 1.2}}})
    with pytest.raises(ValueError):
        build_intraday_strategies({"intraday_strategies": {"inplay_orb15": {"stop": "atr20"}}})


# ------------------------------------------------------------------------------------ gap fade on daily data
def daily_frames():
    idx = pd.bdate_range("2026-06-01", periods=30)
    cols = ["S0", "S1", "S2", "INFY", "NIFTYBEES"]
    o = pd.DataFrame(200.0, index=idx, columns=cols)
    c = pd.DataFrame(200.0, index=idx, columns=cols)
    t = idx[25]
    o.loc[t, "S0"], c.loc[t, "S0"] = 206.0, 202.0    # +3% gap, partly reverses
    o.loc[t, "S1"] = 194.0                           # -3% gap, but a member only from that day
    o.loc[t, "S2"] = 210.0                           # results the day before
    o.loc[t, "INFY"] = 210.0                         # ADR
    frames = {"open": o, "close": c, "volume": pd.DataFrame(1e6, index=idx, columns=cols)}
    uni = pd.DataFrame(True, index=idx, columns=["S0", "S1", "S2", "INFY"])
    uni.loc[idx[:25], "S1"] = False                  # row t is built with day t's data: day 25 uses row 24
    return frames, uni, idx


def test_gap_fade_daily_open_to_close_with_point_in_time_members():
    frames, uni, idx = daily_frames()
    out = gap_fade_daily(frames, universe=uni, results={"S2": [idx[24].date()]})
    assert [(t.symbol, t.date, t.side) for t in out["trades"]] == [("S0", idx[25].date().isoformat(), -1)]
    t = out["trades"][0]
    entry, exitp = 206.0 * (1 - 0.0005), 202.0 * (1 + 0.0003)
    qty = int(500000 * 2.0 / 6 / entry)
    assert t.qty == qty
    assert t.pnl == pytest.approx((entry - exitp) * qty - IntradayCosts().charges(exitp * qty, entry * qty))
    assert t.gross_pct == pytest.approx((1 - 202.0 / 206.0) * 100)
    assert out["daily"].index[0] == idx[15]          # first day with a 20-day turnover known before the open
    assert out["periods"]["before_cas"]["trades"] == 1 and out["periods"]["after_new_preopen"]["days"] == 0


def test_gap_fade_daily_needs_the_market_and_a_registered_threshold():
    frames, uni, _ = daily_frames()
    with pytest.raises(ValueError):
        gap_fade_daily(frames, universe=uni, threshold_pct=1.2)
    with pytest.raises(ValueError):
        gap_fade_daily({k: v.drop(columns="NIFTYBEES") for k, v in frames.items()}, universe=uni)
