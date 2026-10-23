"""Intraday strategies (5-minute bars, MIS). Rules and parameters come from the literature /
practitioner sources in docs/strategy_catalogue.md (section 6) and are NOT tuned on our data.

Each function returns candidate trades for one symbol-day; the engine picks the best few per day,
sizes them by risk, applies costs and forced square-off.
"""
from __future__ import annotations

import math

import numpy as np

from .engine import Day, IntradayStrategy, Trade, slot_of, stop_entry, walk_exit

OR15_END = 3                     # opening range 09:15-09:30 = bars 0,1,2
S_0945 = slot_of(9, 40)          # bar 09:40-09:45: its close = price at 09:45
S_1015 = slot_of(10, 15)
S_1405 = slot_of(14, 5)
S_1430 = slot_of(14, 30)
S_1445 = slot_of(14, 45)


def _trade(d: Day, side: int, slot: int, px: float, stop: float | None, target: float | None,
           exit_slot: int | None = None, stop_entry_fill: bool = False, priority: float = 0.0) -> Trade | None:
    if px is None or math.isnan(px) or slot >= d.flat_slot:
        return None
    xs, xp, why = walk_exit(d, side, slot, stop, target, exit_slot)
    return Trade("", d.symbol, d.date.date().isoformat(), side, slot, float(px), xs, float(xp),
                 stop, why, stop_entry_fill, priority)


def _first_valid(a: np.ndarray, start: int, end: int) -> int | None:
    for i in range(start, min(end, len(a))):
        if not math.isnan(a[i]):
            return i
    return None


# ---------------------------------------------------------------------------- I1 opening range breakout
def orb15(d: Day, p: dict) -> list[Trade]:
    """Classic 15-minute ORB: OCO stop orders 0.05% beyond the 09:15-09:30 range; stop at the other
    side (mid-point if the range is wide); target 2R; one trade a day."""
    if np.isnan(d.h[:OR15_END]).all():
        return []
    orh, orl = np.nanmax(d.h[:OR15_END]), np.nanmin(d.l[:OR15_END])
    buf = p.get("buffer_pct", 0.05) / 100
    long_lvl, short_lvl = orh * (1 + buf), orl * (1 - buf)
    wide = (orh - orl) > 1.5 * d.atr_d / 4 if d.atr_d > 0 else False
    up = stop_entry(d, +1, long_lvl, OR15_END, d.flat_slot)
    dn = stop_entry(d, -1, short_lvl, OR15_END, d.flat_slot)
    if up and dn and up[0] == dn[0]:
        return []                                    # both sides in one bar: ambiguous, skip
    first = min([x for x in (up, dn) if x], key=lambda x: x[0], default=None)
    if first is None:
        return []
    side = +1 if first is up else -1
    slot, px = first
    stop = (orh + orl) / 2 if wide else (orl if side > 0 else orh)
    risk = abs(px - stop)
    t = _trade(d, side, slot, px, stop, px + side * 2 * risk, stop_entry_fill=True,
               priority=d.ctx.get("relvol", 1.0))
    return [t] if t else []


def orb5_inplay(d: Day, p: dict) -> list[Trade]:
    """Zarattini-Barbon-Aziz (2024): trade in the direction of the first 5-minute candle with a stop
    entry at its high/low; stop = 10% of daily ATR; hold to the close. Only 'in play' stocks
    (early volume >= 2x normal) - the engine keeps the top 20 by relative volume."""
    if math.isnan(d.o[0]) or math.isnan(d.c[0]) or d.c[0] == d.o[0] or d.atr_d <= 0:
        return []
    if d.ctx.get("relvol", 0) < p.get("min_relvol", 2.0):
        return []
    side = +1 if d.c[0] > d.o[0] else -1
    hit = stop_entry(d, side, d.h[0] if side > 0 else d.l[0], 1, d.flat_slot)
    if not hit:
        return []
    slot, px = hit
    t = _trade(d, side, slot, px, px - side * 0.10 * d.atr_d, None, stop_entry_fill=True,
               priority=d.ctx.get("relvol", 0))
    return [t] if t else []


# ---------------------------------------------------------------------------- I2/I3 VWAP
def vwap_trend(d: Day, p: dict) -> list[Trade]:
    """Zarattini-Aziz VWAP trend: long above VWAP x1.001, short below x0.999 (decided on bar closes,
    filled at the next open), held at least 2 bars, flat at the forced square-off."""
    vw = d.vwap()
    band = p.get("band_pct", 0.1) / 100
    trades, pos, entry_slot, entry_px = [], 0, None, None
    for i in range(1, d.flat_slot - 1):
        if math.isnan(d.c[i]) or math.isnan(vw[i]):
            continue
        want = +1 if d.c[i] > vw[i] * (1 + band) else -1 if d.c[i] < vw[i] * (1 - band) else pos
        nxt = _first_valid(d.o, i + 1, d.flat_slot)
        if want != pos and nxt is not None and (pos == 0 or nxt - entry_slot >= 2):
            if pos != 0:
                trades.append(Trade("", d.symbol, d.date.date().isoformat(), pos, entry_slot, entry_px, nxt,
                                    float(d.o[nxt]), None, "flip", False, d.ctx.get("liquidity", 0)))
            pos, entry_slot, entry_px = want, nxt, float(d.o[nxt])
    if pos != 0:
        xs, xp, why = walk_exit(d, pos, entry_slot, None, None)
        trades.append(Trade("", d.symbol, d.date.date().isoformat(), pos, entry_slot, entry_px, xs, float(xp),
                            None, why, False, d.ctx.get("liquidity", 0)))
    return trades


def vwap_pullback(d: Day, p: dict) -> list[Trade]:
    """On a trend day (first hour +/-1% and >=80% of bars on one side of VWAP), buy the first pullback
    that touches VWAP and closes back above it (mirror for shorts). Stop below the pullback bar,
    target 2R."""
    vw = d.vwap()
    first = _first_valid(d.o, 0, 3)
    if first is None or math.isnan(d.c[S_1015 - 1]):
        return []
    hr_ret = d.c[S_1015 - 1] / d.o[first] - 1
    side = +1 if hr_ret >= 0.01 else -1 if hr_ret <= -0.01 else 0
    if side == 0:
        return []
    closes = d.c[:S_1015]
    ok = ~np.isnan(closes)
    above = (closes[ok] > vw[:S_1015][ok]) if side > 0 else (closes[ok] < vw[:S_1015][ok])
    if above.mean() < 0.8:
        return []
    for i in range(S_1015, d.flat_slot - 1):
        if math.isnan(d.c[i]):
            continue
        touch = d.l[i] <= vw[i] < d.c[i] if side > 0 else d.h[i] >= vw[i] > d.c[i]
        if touch:
            nxt = _first_valid(d.o, i + 1, d.flat_slot)
            if nxt is None:
                return []
            stop = d.l[i] * 0.999 if side > 0 else d.h[i] * 1.001
            px = d.o[nxt]
            t = _trade(d, side, nxt, px, stop, px + side * 2 * abs(px - stop), priority=abs(hr_ret))
            return [t] if t else []
    return []


# ---------------------------------------------------------------------------- I4 gaps
def gap_go_fade(d: Day, p: dict) -> list[Trade]:
    """Gap >= 2%: WITH news (results day) and heavy early volume -> trade the gap's direction on a break
    of the 15-minute range; WITHOUT news and failing in the first 15 minutes -> fade it toward the
    previous close."""
    first = _first_valid(d.o, 0, 2)
    if first is None or d.prev_close <= 0 or np.isnan(d.h[:OR15_END]).all():
        return []
    gap = d.o[first] / d.prev_close - 1
    if abs(gap) < p.get("min_gap_pct", 2.0) / 100:
        return []
    side_gap = 1 if gap > 0 else -1
    orh, orl = np.nanmax(d.h[:OR15_END]), np.nanmin(d.l[:OR15_END])
    if d.results_day and d.ctx.get("relvol", 0) >= 3:
        lvl = orh if side_gap > 0 else orl
        hit = stop_entry(d, side_gap, lvl, OR15_END, d.flat_slot)
        if not hit:
            return []
        t = _trade(d, side_gap, hit[0], hit[1], orl if side_gap > 0 else orh, None, stop_entry_fill=True,
                   priority=abs(gap))
        return [t] if t else []
    c15 = d.c[OR15_END - 1]
    failed = (not math.isnan(c15)) and (c15 < d.o[first] if side_gap > 0 else c15 > d.o[first])
    no_ext = (np.nanmax(d.h[1:OR15_END]) <= d.h[first]) if side_gap > 0 else (np.nanmin(d.l[1:OR15_END]) >= d.l[first])
    if not (failed and no_ext):
        return []
    side = -side_gap
    lvl = orl if side < 0 else orh
    hit = stop_entry(d, side, lvl, OR15_END, d.flat_slot)
    if not hit:
        return []
    t = _trade(d, side, hit[0], hit[1], orh if side < 0 else orl, d.prev_close, stop_entry_fill=True,
               priority=abs(gap))
    return [t] if t else []


# ---------------------------------------------------------------------------- I5/I8 intraday momentum
def intraday_momentum(d: Day, p: dict) -> list[Trade]:
    """Gao, Han, Li & Zhou (2018): the return from the previous close to 09:45 predicts the last
    half hour. Enter 14:30 in that direction, exit 15:00 (F&O cut-off); only when the morning move
    is larger than half its usual size."""
    sd = d.ctx.get("r1_sd")
    if not sd or math.isnan(d.c[S_0945]) or d.prev_close <= 0:
        return []
    r1 = d.c[S_0945] / d.prev_close - 1
    if abs(r1) < 0.5 * sd:
        return []
    side = 1 if r1 > 0 else -1
    entry, exit_s = (S_1430, d.flat_slot) if d.is_fno else (S_1445, d.flat_slot)
    slot = _first_valid(d.o, entry, entry + 2)
    if slot is None:
        return []
    t = _trade(d, side, slot, d.o[slot], None, None, exit_slot=exit_s, priority=abs(r1) / sd)
    return [t] if t else []


def closing_hour_trend(d: Day, p: dict) -> list[Trade]:
    """At 14:05, a stock up >=1% on the day, above VWAP and within 0.3% of its high is bought (mirror
    for shorts) and held to the square-off."""
    vw = d.vwap()
    i = S_1405
    if math.isnan(d.c[i]) or d.prev_close <= 0:
        return []
    day_ret = d.c[i] / d.prev_close - 1
    hi, lo = np.nanmax(d.h[:i + 1]), np.nanmin(d.l[:i + 1])
    if day_ret >= 0.01 and d.c[i] > vw[i] and d.c[i] >= hi * 0.997:
        side = 1
    elif day_ret <= -0.01 and d.c[i] < vw[i] and d.c[i] <= lo * 1.003:
        side = -1
    else:
        return []
    nxt = _first_valid(d.o, i + 1, i + 3)
    if nxt is None:
        return []
    t = _trade(d, side, nxt, d.o[nxt], None, None, priority=abs(day_ret))
    return [t] if t else []


# ---------------------------------------------------------------------------- I6 CPR
def cpr_breakout(d: Day, p: dict) -> list[Trade]:
    """Narrow Central Pivot Range day (width in the lowest 20% of the last 20 days): open and first
    15-minute close above the top of the CPR -> long, stop below the bottom, target R1 (mirror)."""
    if not d.ctx.get("cpr_narrow") or d.prev_high <= 0:
        return []
    H, L, C = d.prev_high, d.prev_low, d.prev_close
    P = (H + L + C) / 3
    BC = (H + L) / 2
    TC = 2 * P - BC
    top, bot = max(TC, BC), min(TC, BC)
    first = _first_valid(d.o, 0, 2)
    c15 = d.c[OR15_END - 1]
    if first is None or math.isnan(c15):
        return []
    nxt = _first_valid(d.o, OR15_END, OR15_END + 2)
    if nxt is None:
        return []
    if d.o[first] > top and c15 > top:
        t = _trade(d, +1, nxt, d.o[nxt], bot, 2 * P - L)
    elif d.o[first] < bot and c15 < bot:
        t = _trade(d, -1, nxt, d.o[nxt], top, 2 * P - H)
    else:
        return []
    return [t] if t else []


# ---------------------------------------------------------------------------- I7 Supertrend
def supertrend(d: Day, p: dict) -> list[Trade]:
    """Supertrend (ATR 10, multiplier 3) on 5-minute bars within the day: follow each flip (next-bar
    open), flat at the square-off."""
    n, mult = int(p.get("atr_n", 10)), float(p.get("mult", 3.0))
    h, l, c = d.h, d.l, d.c
    m = len(c)
    tr = np.full(m, np.nan)
    for i in range(m):
        if math.isnan(c[i]):
            continue
        pc = c[i - 1] if i > 0 and not math.isnan(c[i - 1]) else c[i]
        tr[i] = max(h[i] - l[i], abs(h[i] - pc), abs(l[i] - pc))
    atr, a = np.full(m, np.nan), None
    for i in range(m):
        if math.isnan(tr[i]):
            continue
        a = tr[i] if a is None else (a * (n - 1) + tr[i]) / n
        atr[i] = a
    trend, fu, fl, trades = 0, np.nan, np.nan, []
    pos, e_slot, e_px = 0, None, None
    for i in range(n, d.flat_slot - 1):
        if math.isnan(c[i]) or math.isnan(atr[i]):
            continue
        mid = (h[i] + l[i]) / 2
        bu, bl = mid + mult * atr[i], mid - mult * atr[i]
        fu = bu if math.isnan(fu) or bu < fu or c[i - 1] > fu else fu
        fl = bl if math.isnan(fl) or bl > fl or c[i - 1] < fl else fl
        new = 1 if c[i] > fu else -1 if c[i] < fl else trend
        if new != trend and new != 0:
            trend = new
            nxt = _first_valid(d.o, i + 1, d.flat_slot)
            if nxt is None:
                break
            if pos != 0:
                trades.append(Trade("", d.symbol, d.date.date().isoformat(), pos, e_slot, e_px, nxt,
                                    float(d.o[nxt]), None, "flip", False, d.ctx.get("liquidity", 0)))
            pos, e_slot, e_px = trend, nxt, float(d.o[nxt])
    if pos != 0:
        xs, xp, why = walk_exit(d, pos, e_slot, None, None)
        trades.append(Trade("", d.symbol, d.date.date().isoformat(), pos, e_slot, e_px, xs, float(xp), None, why,
                            False, d.ctx.get("liquidity", 0)))
    return trades


def build_intraday_strategies(cfg: dict) -> list[IntradayStrategy]:
    conf = cfg.get("intraday_strategies") or {}

    def on(k):
        return bool((conf.get(k) or {}).get("enabled", True))

    def params(k):
        return {kk: v for kk, v in (conf.get(k) or {}).items() if kk != "enabled"}

    specs = [
        ("orb15", "Opening range breakout (15-min)", "WEAK",
         "Break of the 09:15-09:30 high or low (OCO stop orders), stop at the other side of the range, target "
         "twice the risk. The most popular intraday setup; US studies are positive before costs, independent "
         "replications find roughly zero after costs.", orb15, "liquid", 5),
        ("orb5_inplay", "ORB-5 'stocks in play'", "WEAK",
         "Zarattini, Barbon & Aziz (2024): only stocks with unusual early volume; trade the direction of the "
         "first 5-minute candle, tight stop (10% of daily ATR), hold to the close.", orb5_inplay, "liquid", 10),
        ("vwap_trend", "VWAP trend", "WEAK",
         "Long above VWAP, short below (with a small band), flipping as price crosses. One working paper on "
         "QQQ; each flip costs ~0.1-0.2% here.", vwap_trend, "top30", 5),
        ("vwap_pullback", "VWAP pullback on trend days", "EXPERIMENTAL",
         "After a strong first hour, buy the first dip to VWAP that closes back above it (mirror for down days).",
         vwap_pullback, "liquid", 5),
        ("gap_go_fade", "Gap-and-go / gap fade", "WEAK",
         "Big opening gaps: follow them when there is news (results) and heavy volume, fade them when there is "
         "no news and the gap fails in the first 15 minutes.", gap_go_fade, "liquid", 5),
        ("intraday_momentum", "Intraday momentum (morning predicts close)", "MODERATE",
         "Gao, Han, Li & Zhou (2018, JFE): the move from yesterday's close to 09:45 predicts the last half hour. "
         "Enter 14:30, exit 15:00. Tiny edge per trade - costs decide.", intraday_momentum, "liquid", 10),
        ("closing_hour_trend", "Closing-hour trend", "WEAK",
         "At 14:05, buy stocks up 1%+ near their day high and above VWAP (mirror for losers), exit at the "
         "square-off.", closing_hour_trend, "liquid", 5),
        ("cpr_breakout", "Narrow CPR breakout", "EXPERIMENTAL",
         "Popular in India: on narrow Central Pivot Range days, trade the side the market opens and holds "
         "(first 15 minutes), stop at the other side of the CPR, target R1/S1. No peer-reviewed evidence.",
         cpr_breakout, "liquid", 5),
        ("supertrend", "Supertrend (10, 3) on 5-min", "EXPERIMENTAL",
         "Follow each Supertrend flip within the day. An ATR trailing stop - trend following with lots of "
         "whipsaw.", supertrend, "top30", 5),
    ]
    out = []
    for key, name, ev, desc, fn, uni, mx in specs:
        if on(key):
            out.append(IntradayStrategy(key, name, desc, ev, fn, params(key), uni,
                                        int((conf.get(key) or {}).get("max_trades_per_day", mx))))
    return out
