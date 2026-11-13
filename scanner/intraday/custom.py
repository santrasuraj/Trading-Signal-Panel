"""Your own intraday backtests on the stored 5-minute bars (scanner/intraday/engine.py: risk sizing, MIS costs,
slippage, forced square-off). Three templates with your settings:

  orb   opening-range breakout: the high / low of the first N minutes (15 / 30 / 60); a stop order beyond it
        until the cutoff time; stop at the other side of the range (or a fraction of the daily ATR); target at
        R times the risk (or none: out at the square-off)
  vwap  VWAP reclaim: from 10:00, the first close back above VWAP after 30+ minutes below (long; short mirrored);
        stop at the day's low (high) so far; target R times the risk
  gap   gaps of X%+ at the open: "fade" trades back toward yesterday's close from 09:30, stopped beyond the first
        15 minutes' extreme; "go" trades with the gap once the first 15 minutes hold it, stopped at their other end

The stored history is short (5-minute bars from about July 2026): every result carries its number of days and
trades, and a t-statistic, so a lucky few months can be told apart from an edge.
"""
from __future__ import annotations

import math

import numpy as np

from .engine import Day, IntradayStrategy, Trade, slot_of, stop_entry, walk_exit

TEMPLATES = ("orb", "vwap", "gap")


def _orb(d: Day, p: dict) -> list[Trade]:
    n = max(1, int(p.get("or_minutes", 15)) // 5)
    hi, lo = np.nanmax(d.h[:n]), np.nanmin(d.l[:n])
    if not (hi > lo) or math.isnan(hi):
        return []
    cutoff = slot_of(*divmod(int(p.get("cutoff_min", 13 * 60)), 60))
    out = []
    for side in ((1, -1) if p.get("direction", "both") == "both" else (1,) if p.get("direction") == "long" else (-1,)):
        lvl = hi if side > 0 else lo
        hit = stop_entry(d, side, lvl, n, cutoff)
        if not hit:
            continue
        i, px = hit
        if p.get("stop", "range") == "atr" and d.atr_d > 0:
            stop = px - side * d.atr_d * float(p.get("atr_frac", 0.5))
        else:
            stop = lo if side > 0 else hi
        risk = abs(px - stop)
        if risk <= 0:
            continue
        r = p.get("target_r")
        target = px + side * risk * float(r) if r else None
        xi, xp, why = walk_exit(d, side, i, stop, target)
        out.append(Trade("custom", d.symbol, d.date.date().isoformat(), side, i, px, xi, xp, stop, why,
                         stop_entry=True, priority=-i))
    out.sort(key=lambda t: t.entry_slot)
    return out[:1]                                     # the first break of the day only


def _vwap(d: Day, p: dict) -> list[Trade]:
    vw = d.vwap()
    start, below_n = slot_of(10, 0), 6
    cutoff = slot_of(*divmod(int(p.get("cutoff_min", 14 * 60)), 60))
    sides = (1, -1) if p.get("direction", "both") == "both" else (1,) if p.get("direction") == "long" else (-1,)
    for i in range(max(start, below_n), min(cutoff, d.flat_slot)):
        if math.isnan(d.c[i]) or math.isnan(vw[i]):
            continue
        prev = d.c[i - below_n:i] - vw[i - below_n:i]
        for side in sides:
            if side > 0 and d.c[i] > vw[i] and np.all(prev < 0):
                stop = float(np.nanmin(d.l[:i + 1]))
            elif side < 0 and d.c[i] < vw[i] and np.all(prev > 0):
                stop = float(np.nanmax(d.h[:i + 1]))
            else:
                continue
            if i + 1 >= d.flat_slot or math.isnan(d.o[i + 1]):
                return []
            px = float(d.o[i + 1])
            risk = abs(px - stop)
            if risk <= 0:
                return []
            r = p.get("target_r")
            target = px + side * risk * float(r) if r else None
            xi, xp, why = walk_exit(d, side, i + 1, stop, target)
            return [Trade("custom", d.symbol, d.date.date().isoformat(), side, i + 1, px, xi, xp, stop, why)]
    return []


def _gap(d: Day, p: dict) -> list[Trade]:
    if not d.prev_close or math.isnan(d.o[0]):
        return []
    gap = (d.o[0] / d.prev_close - 1) * 100
    if abs(gap) < float(p.get("gap_pct", 2.0)):
        return []
    n = 3                                              # the first 15 minutes
    hi, lo = np.nanmax(d.h[:n]), np.nanmin(d.l[:n])
    if math.isnan(d.o[n]) or not hi > lo:
        return []
    up = gap > 0
    px = float(d.o[n])
    if p.get("mode", "fade") == "fade":
        side = -1 if up else 1
        stop = hi if up else lo
        target = d.prev_close
    else:
        if (up and d.c[n - 1] < d.o[0]) or (not up and d.c[n - 1] > d.o[0]):
            return []                                  # the first 15 minutes gave the gap back: no "go"
        side = 1 if up else -1
        stop = lo if up else hi
        r = p.get("target_r")
        target = px + side * abs(px - stop) * float(r) if r else None
    if (side > 0 and stop >= px) or (side < 0 and stop <= px):
        return []
    xi, xp, why = walk_exit(d, side, n, stop, target)
    return [Trade("custom", d.symbol, d.date.date().isoformat(), side, n, px, xi, xp, stop, why, priority=abs(gap))]


def strategy(spec: dict) -> IntradayStrategy:
    t = spec.get("template")
    fn = {"orb": _orb, "vwap": _vwap, "gap": _gap}.get(t)
    if fn is None:
        raise ValueError(f"template must be one of {', '.join(TEMPLATES)}")
    return IntradayStrategy(key=f"custom_{t}", name=f"Your {t.upper()} test", description="", evidence="your settings",
                            day_trades=fn, params=dict(spec), universe="liquid",
                            max_trades_per_day=int(spec.get("max_trades", 3)))
