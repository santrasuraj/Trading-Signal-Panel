"""Intraday strategies (5-minute bars, MIS). Rules and parameters come from the literature /
practitioner sources in docs/strategy_catalogue.md (section 6) and are NOT tuned on our data.

Each function returns candidate trades for one symbol-day; the engine picks the best few per day,
sizes them by risk, applies costs and forced square-off.

The last three (gap_fade_largecap, inplay_orb15, niftybees_eod_momentum, added 25 Oct 2026) are
pre-registered RESEARCH tests, not strategies to fund: at Indian MIS costs (~0.05% round trip for
NIFTYBEES, ~0.12-0.32% for stocks) none is expected to be clearly profitable. Their alternative
settings are fixed in advance (PRE_REGISTERED) and every one of them should be reported, never tuned.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from .engine import (FLAT_FNO, FLAT_OTHER, SLOTS, Day, IntradayCosts, IntradayStrategy, Trade, intraday_metrics,
                     slot_of, stop_entry, walk_exit)

OR15_END = 3                     # opening range 09:15-09:30 = bars 0,1,2
S_0945 = slot_of(9, 40)          # bar 09:40-09:45: its close = price at 09:45
S_1015 = slot_of(10, 15)
S_1405 = slot_of(14, 5)
S_1430 = slot_of(14, 30)
S_1445 = slot_of(14, 45)
C_1415 = slot_of(14, 10)         # bar 14:10-14:15: its close = price at 14:15
C_1445 = slot_of(14, 40)         # bar 14:40-14:45: its close = price at 14:45
S_1455 = slot_of(14, 55)         # stop-entry orders are cancelled at 14:55

# stocks with US ADRs: their opening gap is priced from US trading overnight, i.e. it is information
ADR_SYMBOLS = ("INFY", "WIPRO", "HDFCBANK", "ICICIBANK", "DRREDDY")
CAS_START = pd.Timestamp("2026-08-03")        # closing auction for F&O stocks (continuous trading ends 15:15)
PREOPEN_CHANGE = pd.Timestamp("2026-09-07")   # revised pre-open session
# the only settings these research tests may be run with (first value = primary spec); see docs/intraday_data.md §5
PRE_REGISTERED = {
    "gap_fade_largecap": {"threshold_pct": (1.5, 1.0, 2.0)},
    "inplay_orb15": {"stop": ("atr10", "range"), "filter": ("rvol", "rvol_news"),
                     "entry_bar": ("stop_first", "entry_first")},
    "niftybees_eod_momentum": {"rule": ("sign", "agree", "rod")},
}


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
    (early volume >= 2x normal) - the engine keeps the top 10 by relative volume. The 09:20-09:30
    volume is known only at 09:30, so the stop order works from 09:30 (a level crossed earlier fills
    at the first bar from 09:30 that trades through it)."""
    if math.isnan(d.o[0]) or math.isnan(d.c[0]) or d.c[0] == d.o[0] or d.atr_d <= 0:
        return []
    if d.ctx.get("relvol", 0) < p.get("min_relvol", 2.0):
        return []
    side = +1 if d.c[0] > d.o[0] else -1
    hit = stop_entry(d, side, d.h[0] if side > 0 else d.l[0], OR15_END, d.flat_slot)
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
        t = _trade(d, +1, nxt, d.o[nxt], bot, 2 * P - L, priority=d.ctx.get("relvol", 1.0))
    elif d.o[first] < bot and c15 < bot:
        t = _trade(d, -1, nxt, d.o[nxt], top, 2 * P - H, priority=d.ctx.get("relvol", 1.0))
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


# ---------------------------------------------------------------------------- R1 large-cap gap fade (research)
def _by_date(days: list[Day]) -> dict[pd.Timestamp, list[Day]]:
    out: dict[pd.Timestamp, list[Day]] = {}
    for d in days:
        out.setdefault(d.date, []).append(d)
    return out


def gap_fade_prepare(days: list[Day], p: dict) -> dict:
    """Decided at 09:15 from each stock's first price and the previous official close only. Universe that
    day: F&O stocks, previous close >= Rs 100, the `top_n` by 20-day traded value to the previous day; no
    results day (or the day after), no ADR stock, no raw gap above 10%. Idiosyncratic gap = gap - NIFTYBEES
    gap (beta 1). Short the `legs` largest idiosyncratic gaps >= threshold, buy the `legs` most negative
    <= -threshold. No NIFTYBEES bar that morning = no trades. Returns {"_picks": {(symbol, date): (side, idio)}}."""
    thr = float(p.get("threshold_pct", 1.5)) / 100
    legs, top_n = int(p.get("legs", 3)), int(p.get("top_n", 100))
    market, excl = str(p.get("market", "NIFTYBEES")), set(p.get("exclude", ADR_SYMBOLS))
    min_price, max_gap = float(p.get("min_price", 100)), float(p.get("max_gap_pct", 10.0)) / 100
    picks: dict[tuple[str, pd.Timestamp], tuple[int, float]] = {}
    for dt, ds in _by_date(days).items():
        mk = next((d for d in ds if d.symbol == market), None)
        if mk is None or mk.prev_close <= 0 or math.isnan(mk.o[0]):
            continue
        g_m = mk.o[0] / mk.prev_close - 1
        pool = [d for d in ds if d.is_fno and d.symbol != market and d.symbol not in excl and not d.results_day
                and d.prev_close >= min_price and d.atr_d > 0 and not math.isnan(d.o[0])]
        pool.sort(key=lambda d: (-d.ctx.get("liquidity", 0.0), d.symbol))
        idio = [(d.o[0] / d.prev_close - 1 - g_m, d.symbol) for d in pool[:top_n]
                if abs(d.o[0] / d.prev_close - 1) <= max_gap]
        for x, sym in sorted([z for z in idio if z[0] >= thr], reverse=True)[:legs]:
            picks[(sym, dt)] = (-1, x)
        for x, sym in sorted([z for z in idio if z[0] <= -thr])[:legs]:
            picks[(sym, dt)] = (+1, x)
    return {"_picks": picks}


def gap_fade_largecap(d: Day, p: dict) -> list[Trade]:
    """Fade the stock's own (market-adjusted) opening gap: enter at the 09:20 bar open (the first price after
    the 09:15 decision; a pre-open auction fill is not assumed), stop 1 x daily ATR from entry for MIS risk
    control, exit at the 15:00 bar open. No target."""
    pick = (p.get("_picks") or {}).get((d.symbol, d.date))
    if pick is None:
        return []
    side, idio = pick
    slot = _first_valid(d.o, 1, 3)
    if slot is None:
        return []
    px = d.o[slot]
    t = _trade(d, side, slot, px, px - side * float(p.get("stop_atr", 1.0)) * d.atr_d, None, exit_slot=FLAT_FNO,
               priority=abs(idio))
    return [t] if t else []


# ---------------------------------------------------------------------------- R2 stocks-in-play ORB-15 (research)
def inplay_prepare(days: list[Day], p: dict) -> dict:
    """Decided once at 09:30 and never revised: F&O stocks whose 09:20-09:30 volume is >= `min_relvol` x its
    average of the previous 14 sessions (run.build_days' relvol; Yahoo's 09:15 bar has no volume, so both
    sources use the 09:20 and 09:25 bars), optionally only on news (results day or |gap| >= 2%); the top
    `top_n` by that ratio. Direction = sign of price at 09:30 vs the 09:15 open. A pick that never triggers
    leaves its slot empty - no lower-ranked stock replaces it. Returns {"_picks": {(symbol, date): side}}."""
    n, min_rv = int(p.get("top_n", 2)), float(p.get("min_relvol", 1.0))
    news, min_gap = p.get("filter", "rvol") == "rvol_news", float(p.get("news_gap_pct", 2.0)) / 100
    picks: dict[tuple[str, pd.Timestamp], int] = {}
    for dt, ds in _by_date(days).items():
        cands = []
        for d in ds:
            rv = d.ctx.get("relvol")
            # build_days sets exactly 1.0 when fewer than 5 earlier sessions exist: unknown, not 'normal'
            if not d.is_fno or rv is None or rv == 1.0 or rv < min_rv or d.atr_d <= 0 or d.prev_close <= 0:
                continue
            o0, c30 = d.o[0], d.c[OR15_END - 1]
            if math.isnan(o0) or math.isnan(c30) or c30 == o0:
                continue
            if news and not (d.results_day or abs(o0 / d.prev_close - 1) >= min_gap):
                continue
            cands.append((rv, d.symbol, 1 if c30 > o0 else -1))
        for rv, sym, side in sorted(cands, key=lambda x: (-x[0], x[1]))[:n]:
            picks[(sym, dt)] = side
    return {"_picks": picks}


def inplay_orb15(d: Day, p: dict) -> list[Trade]:
    """Zarattini-Barbon-Aziz (2024), 15-minute version: for a stock picked at 09:30, a buy-stop at the
    09:15-09:30 high (sell-stop at the low), working 09:30-14:55; stop 10% of daily ATR from the fill
    ('atr10') or the other side of the range ('range'); exit at the 15:00 bar open. No target."""
    side = (p.get("_picks") or {}).get((d.symbol, d.date))
    if side is None or np.isnan(d.h[:OR15_END]).all():
        return []
    orh, orl = np.nanmax(d.h[:OR15_END]), np.nanmin(d.l[:OR15_END])
    hit = stop_entry(d, side, orh if side > 0 else orl, OR15_END, S_1455)
    if not hit:
        return []
    slot, px = hit
    stop = px - side * 0.10 * d.atr_d if p.get("stop", "atr10") == "atr10" else (orl if side > 0 else orh)
    t = _trade(d, side, slot, px, stop, None, exit_slot=FLAT_FNO, stop_entry_fill=True,
               priority=d.ctx.get("relvol", 0.0), entry_first=p.get("entry_bar", "stop_first") == "entry_first")
    return [t] if t else []


# ---------------------------------------------------------------------------- R3 NIFTYBEES end-of-day momentum
def niftybees_eod_momentum(d: Day, p: dict) -> list[Trade]:
    """Gao, Han, Li & Zhou (2018) on the index ETF only: r1 = previous close -> 09:45. At the 14:45 bar open go
    long if r1 > 0, short if r1 < 0 ('sign'); 'agree' also needs the 14:15 -> 14:45 move in the same
    direction; 'rod' uses the previous close -> 14:45 move instead (Baltussen et al. 2021). Exit at the 15:15
    bar open; emergency stop 1% from entry. Since the closing auction (3 Aug 2026) 14:45-15:15 is the last
    half hour of continuous trading in the Nifty stocks; stocks cannot use it under MIS, NIFTYBEES can."""
    if d.symbol != p.get("symbol", "NIFTYBEES") or d.prev_close <= 0:
        return []
    rule = p.get("rule", "sign")
    p1415, p1445 = d.c[C_1415], d.c[C_1445]
    base = p1445 if rule == "rod" else d.c[S_0945]
    if math.isnan(base):
        return []
    r = base / d.prev_close - 1
    if rule == "agree" and (math.isnan(p1415) or math.isnan(p1445) or np.sign(p1445 / p1415 - 1) != np.sign(r)):
        return []
    if r == 0:
        return []
    side = 1 if r > 0 else -1
    slot = _first_valid(d.o, S_1445, S_1445 + 2)
    if slot is None:
        return []
    px = d.o[slot]
    t = _trade(d, side, slot, px, px * (1 - side * 0.01), None, exit_slot=FLAT_OTHER, priority=abs(r))
    return [t] if t else []


def _check_registered(key: str, p: dict) -> None:
    for name, allowed in PRE_REGISTERED.get(key, {}).items():
        v = p.get(name, allowed[0])
        if v not in allowed:
            raise ValueError(f"intraday_strategies.{key}.{name} = {v!r} is not pre-registered; allowed: {allowed} "
                             "(choosing a setting after seeing results would make the test meaningless)")


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
        # research tests (25 Oct 2026): pre-registered, expected to struggle after costs - see the module docstring
        ("gap_fade_largecap", "Large-cap gap fade (research)", "WEAK",
         "RESEARCH ONLY. Each morning, among the 100 most-traded F&O stocks without results news, short the 3 "
         "with the biggest opening gap above the market's (>= 1.5%) and buy the 3 with the biggest gap below "
         "it; equal size, stop 1x daily ATR, exit 15:00. US studies (Berkman et al. 2012) find overnight gaps "
         "partly reverse during the day; no Indian study. Needs ~0.12% per leg just to cover costs.",
         gap_fade_largecap, "liquid", 6),
        ("inplay_orb15", "Stocks-in-play ORB-15 (research)", "WEAK",
         "RESEARCH ONLY. At 09:30 pick the 2 F&O stocks with the most unusual early volume (>= their 14-day "
         "normal), then trade a break of their 09:15-09:30 range in the direction of that first 15 minutes; "
         "stop 10% of daily ATR, exit 15:00 (Zarattini, Barbon & Aziz 2024, US). Indian costs are about 0.5-1.5x "
         "the risk per trade, so a loss is the expected result; 5-minute bars cannot judge so tight a stop.",
         inplay_orb15, "liquid", 2),
        ("niftybees_eod_momentum", "NIFTYBEES last-half-hour momentum (research)", "WEAK",
         "RESEARCH ONLY. If NIFTYBEES is up from yesterday's close at 09:45, buy it at 14:45 (short if down) and "
         "exit at 15:15 (Gao, Han, Li & Zhou 2018, US index). The cheapest intraday trade there is (~0.05% "
         "round trip), but the documented edge (~0.02-0.03% a trade) is smaller than that cost.",
         niftybees_eod_momentum, "liquid", 1),
    ]
    lev = float((cfg.get("intraday") or {}).get("leverage", 2.0))
    hooks = {
        # equal notional legs: 3 long + 3 short, each an equal share of the leverage limit (about market-neutral)
        "gap_fade_largecap": {"prepare": gap_fade_prepare, "notional_x": lev / 6},
        "inplay_orb15": {"prepare": inplay_prepare},
        # fixed 1x equity; NIFTYBEES trades about one tick (~0.004%) wide - 0.02% a side, 0.07% to check robustness
        "niftybees_eod_momentum": {"notional_x": 1.0,
                                   "slippage_pct": float(params("niftybees_eod_momentum").get("slippage_pct", 0.02))},
    }
    out = []
    for key, name, ev, desc, fn, uni, mx in specs:
        if on(key):
            _check_registered(key, params(key))
            out.append(IntradayStrategy(key, name, desc, ev, fn, params(key), uni,
                                        int((conf.get(key) or {}).get("max_trades_per_day", mx)),
                                        **hooks.get(key, {})))
    return out


# ---------------------------------------------------------------------------- gap fade on daily data (test 1)
def _window_metrics(trades: list[Trade], daily: pd.Series, capital: float, costs: IntradayCosts,
                    lo: pd.Timestamp | None, hi: pd.Timestamp | None) -> dict:
    """Metrics for the days in [lo, hi), starting from the equity reached just before lo."""
    if daily.empty:
        return {"days": 0, "trades": 0}
    keep = np.ones(len(daily), dtype=bool)
    if lo is not None:
        keep &= np.asarray(daily.index >= lo)
    if hi is not None:
        keep &= np.asarray(daily.index < hi)
    sel = daily[keep]
    if sel.empty:
        return {"days": 0, "trades": 0}
    before = daily[daily.index < sel.index[0]]
    a, z = sel.index[0].date().isoformat(), sel.index[-1].date().isoformat()
    return intraday_metrics([t for t in trades if a <= t.date <= z], sel,
                            float(before.iloc[-1]) if len(before) else capital, costs)


def gap_fade_daily(frames: dict[str, pd.DataFrame], costs: IntradayCosts | None = None,
                   universe: pd.DataFrame | None = None, results: dict | None = None, fno: set[str] | None = None,
                   threshold_pct: float = 1.5, legs: int = 3, top_n: int = 100, min_price: float = 100.0,
                   max_gap_pct: float = 10.0, market: str = "NIFTYBEES", exclude=ADR_SYMBOLS,
                   capital: float = 500000.0, leverage: float = 2.0,
                   entry_slip_pct: float = 0.05, exit_slip_pct: float = 0.03) -> dict:
    """gap_fade_largecap's first test on DAILY data (2019-2026, ~1,800 sessions instead of 60 intraday ones):
    the same picks, entered at the official open x (1 +/- entry_slip_pct%) and exited at the official close
    -/+ exit_slip_pct%, with the intraday charges (IntradayCosts) and equal notional legs of
    leverage x equity / (2 x legs). No stop (daily bars cannot order it against the path).

    frames: daily open/close/volume (rows = dates, columns = symbols; `market` must be a column).
    universe: bool frame of point-in-time members (pit.PitData.universe); row t is computed with day t's data,
      so day t uses row t-1. Without it every column counts - then pass `fno` or drop ETFs/indices first.
    results: {symbol: [result dates]}: a result date excludes its trading day (the next one if it fell on a
      holiday) and the day after, as in run.build_days.
    Exits at the close, not 15:00: the last half hour can flatter it (end-of-day reversal), so a result here
    still needs the 5-minute check. Not wired into the scan; returns {"params", "metrics", "periods" (split at
    3 Aug and 7 Sep 2026), "trades", "daily"}."""
    if threshold_pct not in PRE_REGISTERED["gap_fade_largecap"]["threshold_pct"]:
        raise ValueError(f"threshold_pct {threshold_pct} is not pre-registered "
                         f"{PRE_REGISTERED['gap_fade_largecap']['threshold_pct']}")
    costs = costs or IntradayCosts()
    c_df = frames["close"]
    if market not in c_df.columns:
        raise ValueError(f"{market} is missing from the daily frames (needed for the market gap)")
    idx = c_df.index
    excl = set(exclude)
    stocks = [s for s in c_df.columns if s != market and s not in excl and (fno is None or s in fno)]
    o_df = frames["open"].reindex(index=idx, columns=c_df.columns)
    v_df = frames["volume"].reindex(index=idx, columns=c_df.columns)
    O, C = o_df[stocks].to_numpy(dtype=float), c_df[stocks].to_numpy(dtype=float)
    T = len(idx)
    PC = np.full_like(C, np.nan)
    PC[1:] = C[:-1]
    # 20-day traded value up to the previous day: known before the open
    tv = (c_df[stocks] * v_df[stocks]).rolling(20, min_periods=15).mean().to_numpy(dtype=float)
    TV = np.full_like(tv, np.nan)
    TV[1:] = tv[:-1]
    mo, mc = o_df[market].to_numpy(dtype=float), c_df[market].to_numpy(dtype=float)
    gm = np.full(T, np.nan)
    mem = np.ones_like(C, dtype=bool)
    with np.errstate(invalid="ignore", divide="ignore"):
        gap = O / PC - 1
        gm[1:] = mo[1:] / mc[:-1] - 1
    if universe is not None:
        u = universe.reindex(index=idx, columns=stocks, fill_value=False).fillna(False).to_numpy(dtype=bool)
        mem[0] = False
        mem[1:] = u[:-1]
    res = np.zeros_like(C, dtype=bool)
    col = {s: j for j, s in enumerate(stocks)}
    for sym, ds in (results or {}).items():
        if sym in col and ds:
            pos = idx.searchsorted(pd.DatetimeIndex(pd.to_datetime(list(ds))))
            res[pos[pos < T], col[sym]] = True
    blocked = res.copy()
    blocked[1:] |= res[:-1]
    thr, max_gap = threshold_pct / 100, max_gap_pct / 100
    es, xs = entry_slip_pct / 100, exit_slip_pct / 100
    equity, curve, trades = capital, [], []
    for t in range(1, T):
        base = mem[t] & ~blocked[t] & (np.nan_to_num(PC[t]) >= min_price) & np.isfinite(TV[t]) & np.isfinite(O[t])
        cand = np.flatnonzero(base)
        if not curve and (math.isnan(gm[t]) or not len(cand)):
            continue                                  # before the first testable day
        day_pnl = 0.0
        if not math.isnan(gm[t]) and len(cand):
            top = cand[np.argsort(-TV[t, cand], kind="stable")][:top_n]
            top = top[np.isfinite(C[t, top]) & np.isfinite(gap[t, top]) & (np.abs(gap[t, top]) <= max_gap)]
            idio = gap[t, top] - gm[t]
            order = np.argsort(-idio, kind="stable")
            shorts = [k for k in order if idio[k] >= thr][:legs]
            longs = [k for k in order[::-1] if idio[k] <= -thr][:legs]
            notional = equity * leverage / (2 * legs)
            for k, side in [(k, -1) for k in shorts] + [(k, 1) for k in longs]:
                j = top[k]
                entry, exitp = O[t, j] * (1 + side * es), C[t, j] * (1 - side * xs)
                qty = int(notional / entry)
                if qty < 1:
                    continue
                buy_v, sell_v = (entry * qty, exitp * qty) if side > 0 else (exitp * qty, entry * qty)
                tr = Trade("gap_fade_largecap_daily", stocks[j], idx[t].date().isoformat(), side, 0, float(O[t, j]),
                           SLOTS - 1, float(C[t, j]), None, "close", False, float(abs(idio[k])))
                tr.qty = qty
                tr.pnl = (exitp - entry) * qty * side - costs.charges(buy_v, sell_v)
                tr.ret_pct = tr.pnl / (entry * qty) * 100
                tr.gross_pct = side * (C[t, j] / O[t, j] - 1) * 100
                day_pnl += tr.pnl
                trades.append(tr)
        equity += day_pnl
        curve.append((idx[t], equity))
    daily = pd.Series({d: e for d, e in curve}, dtype=float)
    return {
        "params": {"threshold_pct": threshold_pct, "legs": legs, "top_n": top_n, "min_price": min_price,
                   "max_gap_pct": max_gap_pct, "market": market, "exclude": sorted(excl), "leverage": leverage,
                   "entry_slip_pct": entry_slip_pct, "exit_slip_pct": exit_slip_pct, "exit": "official close"},
        "metrics": intraday_metrics(trades, daily, capital, costs),
        "periods": {"before_cas": _window_metrics(trades, daily, capital, costs, None, CAS_START),
                    "cas_to_new_preopen": _window_metrics(trades, daily, capital, costs, CAS_START, PREOPEN_CHANGE),
                    "after_new_preopen": _window_metrics(trades, daily, capital, costs, PREOPEN_CHANGE, None)},
        "trades": trades, "daily": daily,
    }
