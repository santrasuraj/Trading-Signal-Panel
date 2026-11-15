"""Intraday strategies (5-minute bars, MIS). Each function returns candidate trades for one symbol-day; the engine picks
the best few per day, sizes them by risk, applies costs and forced square-off.

Only the new-era price-action setups are here (liquidity sweep + retest at yesterday's high / low and at the opening
range, opening-range break-and-retest with VWAP). The twelve earlier strategies (opening-range breakouts, VWAP trend
and pullback, gap-and-go, intraday momentum, closing-hour trend, CPR, Supertrend and the three pre-registered research
tests) all lost money after costs in their backtests and were removed on 15 Nov 2026; they are in git history before
that date. Your own strategies from the strategy builder are in scanner/intraday/custom.py.
"""
from __future__ import annotations

import math

import numpy as np

from . import fast
from .engine import Day, IntradayStrategy, Trade, slot_of, walk_exit

OR15_END = 3                     # opening range 09:15-09:30 = bars 0,1,2
S_0945 = slot_of(9, 40)          # bar 09:40-09:45: its close = price at 09:45 (run.build_days' 09:45 move)
S_1430 = slot_of(14, 30)         # no new entry after 14:30


def _trade(d: Day, side: int, slot: int, px: float, stop: float | None, target: float | None,
           exit_slot: int | None = None, stop_entry_fill: bool = False, priority: float = 0.0,
           entry_first: bool = False) -> Trade | None:
    """entry_first: inside the entry bar, assume the fill came before the bar's low/high, so the stop counts
    there only when the bar closed beyond it (default: the stop is assumed hit first - conservative)."""
    if px is None or math.isnan(px) or slot >= d.flat_slot:
        return None
    if stop is not None and side * (px - stop) <= 0:
        return None                      # entry already beyond the stop: that stop order cannot be placed
    if target is not None and side * (target - px) <= 0:
        return None                      # target already passed at entry: no setup
    if entry_first and stop is not None and not math.isnan(d.c[slot]) and side * (d.c[slot] - stop) <= 0:
        xs, xp, why = slot, stop, "stop"
    else:
        xs, xp, why = walk_exit(d, side, slot, stop, target, exit_slot, check_entry_bar=not entry_first)
    return Trade("", d.symbol, d.date.date().isoformat(), side, slot, float(px), xs, float(xp),
                 stop, why, stop_entry_fill, priority)


def _first_valid(a: np.ndarray, start: int, end: int) -> int | None:
    i = fast.first_valid(fast.f64(a), int(start), int(end))
    return None if i < 0 else int(i)


# ---------------------------------------------------------------------------- new era: liquidity sweeps and retests
# Price-action / "smart money" setups as taught by Indian trading channels (13 Nov 2026). No peer-reviewed evidence:
# they are backtested here like every other strategy and their signals are labelled with that result.
SWEEP_STOP_BUFFER = 0.0005           # 0.05% beyond the sweep's extreme


def _one_sweep(d: Day, side: int, level: float, start: int, last: int, p: dict) -> Trade | None:
    """The first sweep of `level` from `start`: price trades through it (where the stop-losses sit), closes back on the
    original side within `reclaim_bars` (the trap), then a later bar comes back to the level and closes on the right
    side (the retest). Entry at the next bar's open, stop just beyond the sweep's extreme, target `rr` x the risk.
    side +1: a sweep BELOW a support level, then long; side -1: a sweep ABOVE a resistance level, then short.
    A close beyond the level for longer than `reclaim_bars` (a real break) or a new extreme before the retest (the
    trap failed) cancels the setup for the day."""
    tol = float(p.get("tol_pct", 0.05)) / 100
    reclaim_bars, retest_bars = int(p.get("reclaim_bars", 6)), int(p.get("retest_bars", 12))
    rr, max_risk = float(p.get("rr", 2.0)), float(p.get("max_risk_pct", 1.5)) / 100
    nxt, extreme = fast.sweep_setup(d.o, d.h, d.l, d.c, int(side), float(level),
                                    int(start), int(last), tol, reclaim_bars, retest_bars, d.flat_slot)
    if nxt < 0:
        return None
    nxt = int(nxt)
    px = float(d.o[nxt])
    stop = extreme * (1 - SWEEP_STOP_BUFFER) if side > 0 else extreme * (1 + SWEEP_STOP_BUFFER)
    risk = abs(px - stop)
    if not (0.001 <= risk / px <= max_risk):
        return None                                      # too tight for 5-minute bars, or too wide to size
    return _trade(d, side, nxt, px, stop, px + side * rr * risk, priority=d.ctx.get("relvol", 1.0))


def _sweep_retest(d: Day, support: float, resistance: float, start: int, p: dict) -> list[Trade]:
    last = min(int(p.get("last_entry_slot", S_1430)), d.flat_slot - 1)
    out = [t for side, lvl in ((+1, support), (-1, resistance))
           if lvl is not None and lvl > 0 and not math.isnan(lvl)
           for t in [_one_sweep(d, side, float(lvl), start, last, p)] if t is not None]
    return sorted(out, key=lambda t: t.entry_slot)[:1]  # one trade a day: whichever side set up first


def sweep_pdhl(d: Day, p: dict) -> list[Trade]:
    """Liquidity sweep + retest at yesterday's low (long) or high (short), from the open until 14:30."""
    return _sweep_retest(d, d.prev_low, d.prev_high, 0, p)


def sweep_or15(d: Day, p: dict) -> list[Trade]:
    """Liquidity sweep + retest at the 09:15-09:30 low (long) or high (short), from 09:30 until 14:30."""
    if np.isnan(d.h[:OR15_END]).all():
        return []
    return _sweep_retest(d, float(np.nanmin(d.l[:OR15_END])), float(np.nanmax(d.h[:OR15_END])), OR15_END, p)


def orb_retest_vwap(d: Day, p: dict) -> list[Trade]:
    """A 5-minute close beyond the 09:15-09:30 range on the same side of VWAP, then a retest of the range edge that
    holds (and stays on that side of VWAP): entry at the next open, stop beyond the retest bar, target `rr` x the risk.
    A close back inside the range before the retest = a failed breakout: no trade."""
    if np.isnan(d.h[:OR15_END]).all():
        return []
    orh, orl = float(np.nanmax(d.h[:OR15_END])), float(np.nanmin(d.l[:OR15_END]))
    vw = d.vwap()
    tol = float(p.get("tol_pct", 0.05)) / 100
    retest_bars, rr = int(p.get("retest_bars", 12)), float(p.get("rr", 2.0))
    max_risk = float(p.get("max_risk_pct", 1.5)) / 100
    last = min(int(p.get("last_entry_slot", S_1430)), d.flat_slot - 1)
    side, nxt, k = fast.orb_retest_setup(d.o, d.h, d.l, d.c, vw, orh, orl, tol,
                                         retest_bars, OR15_END, last, d.flat_slot)
    if side == 0:
        return []                                        # no breakout, a failed one, or no retest in time
    side, nxt, k = int(side), int(nxt), int(k)
    px = float(d.o[nxt])
    stop = d.l[k] * (1 - SWEEP_STOP_BUFFER) if side > 0 else d.h[k] * (1 + SWEEP_STOP_BUFFER)
    risk = abs(px - stop)
    if not (0.001 <= risk / px <= max_risk):
        return []
    t = _trade(d, side, nxt, px, stop, px + side * rr * risk, priority=d.ctx.get("relvol", 1.0))
    return [t] if t else []


def build_intraday_strategies(cfg: dict) -> list[IntradayStrategy]:
    conf = cfg.get("intraday_strategies") or {}

    def on(k):
        return bool((conf.get(k) or {}).get("enabled", True))

    def params(k):
        return {kk: v for kk, v in (conf.get(k) or {}).items() if kk != "enabled"}

    specs = [
        ("sweep_pdhl", "Liquidity sweep + retest (yesterday's high / low)", "EXPERIMENTAL",
         "NEW ERA. Price trades through yesterday's low (or high), where traders' stop-losses sit, closes back inside "
         "within 30 minutes (the trap), then comes back to retest the level and holds: enter on the next bar, stop just "
         "beyond the sweep's extreme, target twice the risk. Popular with Indian price-action ('smart money') traders; "
         "no peer-reviewed evidence.", sweep_pdhl, "liquid", 5),
        ("sweep_or15", "Liquidity sweep + retest (opening range)", "EXPERIMENTAL",
         "NEW ERA. The same trap-and-retest at the 09:15-09:30 high or low, from 09:30: a sweep through the opening "
         "range's edge, a close back inside, a retest that holds; stop beyond the sweep, target twice the risk.",
         sweep_or15, "liquid", 5),
        ("orb_retest_vwap", "Opening-range break-and-retest with VWAP", "EXPERIMENTAL",
         "NEW ERA. A 5-minute close beyond the 09:15-09:30 range on the same side of VWAP, then a pullback that "
         "retests the range edge and holds: enter on the next bar, stop beyond the retest bar, target twice the risk. "
         "A close back inside the range cancels it (failed breakout).", orb_retest_vwap, "liquid", 5),
    ]
    return [IntradayStrategy(key, name, desc, ev, fn, params(key), uni,
                             int((conf.get(key) or {}).get("max_trades_per_day", mx)))
            for key, name, ev, desc, fn, uni, mx in specs if on(key)]
