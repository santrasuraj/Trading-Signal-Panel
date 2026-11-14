"""Compiled hot loops of the intraday engine (Numba).

The backtest and the live signals walk every 5-minute bar of every stock-day in Python loops: the stop / target walk,
stop-entry orders, VWAP, Supertrend, the VWAP trend flips and the sweep / retest setups. Measured on 30 sessions x 151
stocks (13 Nov 2026) those loops were most of the 10.5 s the 15 strategies took. Here they are plain numeric
functions over the Day's float64 arrays, compiled to machine code by Numba (LLVM) on first use and cached on disk
(__pycache__), so later runs start compiled.

Compiling is switched on with enable(): the dashboard server does it at start-up (its live signal engine and the
auto-trader run all day) and so does the year-long backtest. A short-lived job such as the 5-minute signals task does
not: importing Numba and loading the compiled code costs ~4 s there, more than the ~0.6 s its strategies take. Before
enable(), and without Numba installed, the very same functions run as ordinary Python: same source, same results, only
slower. tests/test_fast.py checks the compiled and the Python versions agree, and every strategy's trades were checked
identical, trade for trade, against the pre-Numba engine on 30 stored sessions (1,947 trades, 13 Nov 2026).

Conventions: "none" is NaN for prices and -1 for bar slots. Comparisons copy Python's min()/max() exactly (the first
argument wins ties and NaN), so a compiled run can never pick a different price than the Python one.
"""
from __future__ import annotations

import math
import threading

import numpy as np

STOP, TARGET, END = 0, 1, 2                       # walk_exit's exit codes
_PY: dict = {}                                    # name -> the plain Python function
_enable_lock = threading.Lock()
ENABLED = False                                   # True once the compiled versions are in place


def _jit(f):
    """Register a kernel: plain Python until enable() swaps in the compiled version."""
    _PY[f.__name__] = f
    return f


def enable() -> bool:
    """Swap every kernel in this module for its Numba-compiled version (compiled on first call, cached on disk in
    __pycache__). Callers look kernels up as fast.<name> on every call, so they switch over at once. False when Numba
    is not installed (everything keeps running as Python)."""
    global ENABLED
    with _enable_lock:
        if ENABLED:
            return True
        try:
            import numba
        except Exception:
            return False
        g = globals()
        for name, f in _PY.items():
            g[name] = numba.njit(cache=True, nogil=True)(f)
        ENABLED = True
        return True


def f64(a) -> np.ndarray:
    """The array as float64 (no copy when it already is)."""
    return np.asarray(a, dtype=np.float64)


@_jit
def first_valid(a, start, end):
    """First index in [start, min(end, len)) whose value is not NaN, else -1."""
    stop = end if end < a.shape[0] else a.shape[0]
    for i in range(start, stop):
        if not math.isnan(a[i]):
            return i
    return -1


@_jit
def vwap(h, l, c, v):
    """Session VWAP from 09:20, seeded by the 09:15 typical price (its volume is ignored: Yahoo history has none);
    the typical price where there is no volume yet. Same sums in the same order as the numpy version it replaces."""
    n = c.shape[0]
    out = np.empty(n)
    pv = 0.0
    cv = 0.0
    for i in range(n):
        tp = (h[i] + l[i] + c[i]) / 3
        vi = 0.0 if i == 0 or math.isnan(v[i]) else v[i]
        pv += (0.0 if math.isnan(tp) else tp) * vi
        cv += vi
        x = pv / cv if cv > 0 else np.nan
        out[i] = tp if math.isnan(x) else x
    return out


@_jit
def walk_exit(o, h, l, c, side, entry_slot, stop, target, last, start, slots):
    """Bars from `start` until `last`: stop (wins inside a bar that touches both), target (never inside the entry bar),
    else the open of bar `last` (or the latest earlier close). stop / target NaN = none. Returns (slot, price, code)."""
    has_stop = not math.isnan(stop)
    has_target = not math.isnan(target)
    for i in range(start, last):
        if math.isnan(l[i]):
            continue
        oi = o[i]
        if has_stop:
            if side > 0 and l[i] <= stop:
                if i > entry_slot:
                    return i, (stop if stop < oi else oi), STOP
                return i, stop, STOP
            if side < 0 and h[i] >= stop:
                if i > entry_slot:
                    return i, (stop if stop > oi else oi), STOP
                return i, stop, STOP
        if has_target and i > entry_slot:
            if side > 0 and h[i] >= target:
                return i, (target if target > oi else oi), TARGET
            if side < 0 and l[i] <= target:
                return i, (target if target < oi else oi), TARGET
    if last < slots and last < o.shape[0] and not math.isnan(o[last]):
        return last, o[last], END
    for j in range(last - 1, entry_slot - 1, -1):
        if not math.isnan(c[j]):
            return j, c[j], END
    return entry_slot, c[entry_slot], END


@_jit
def stop_entry(o, h, l, side, level, start, end):
    """First bar in [start, end) whose range reaches `level`: (slot, fill at the level or the gap open), else (-1, NaN)."""
    for i in range(start, end):
        if math.isnan(h[i]):
            continue
        if side > 0 and h[i] >= level:
            return i, (level if level > o[i] else o[i])
        if side < 0 and l[i] <= level:
            return i, (level if level < o[i] else o[i])
    return -1, np.nan


@_jit
def supertrend_flips(o, h, l, c, n, mult, flat_slot):
    """Supertrend(ATR n, mult) on the day's bars: each flip as (new trend, slot of the next bar's open). A flip with no
    later bar ends the list (the position is then held to the square-off)."""
    m = c.shape[0]
    tr = np.full(m, np.nan)
    for i in range(m):
        if math.isnan(c[i]):
            continue
        pc = c[i - 1] if i > 0 and not math.isnan(c[i - 1]) else c[i]
        r = h[i] - l[i]
        b = abs(h[i] - pc)
        if b > r:
            r = b
        b = abs(l[i] - pc)
        if b > r:
            r = b
        tr[i] = r
    atr = np.full(m, np.nan)
    a, have = 0.0, False
    for i in range(m):
        if math.isnan(tr[i]):
            continue
        a = tr[i] if not have else (a * (n - 1) + tr[i]) / n
        have = True
        atr[i] = a
    out = np.empty((m, 2), np.int64)
    k, trend, fu, fl = 0, 0, np.nan, np.nan
    for i in range(n, flat_slot - 1):
        if math.isnan(c[i]) or math.isnan(atr[i]):
            continue
        mid = (h[i] + l[i]) / 2
        bu, bl = mid + mult * atr[i], mid - mult * atr[i]
        if math.isnan(fu) or bu < fu or c[i - 1] > fu:
            fu = bu
        if math.isnan(fl) or bl > fl or c[i - 1] < fl:
            fl = bl
        new = 1 if c[i] > fu else (-1 if c[i] < fl else trend)
        if new != trend and new != 0:
            trend = new
            nxt = first_valid(o, i + 1, flat_slot)
            if nxt < 0:
                break
            out[k, 0], out[k, 1] = trend, nxt
            k += 1
    return out[:k]


@_jit
def vwap_trend_flips(o, c, vw, band, flat_slot):
    """VWAP trend: decided on bar closes beyond VWAP x (1 +/- band), filled at the next open, each position held at least
    2 bars. Each change as (new side, slot of the fill)."""
    out = np.empty((c.shape[0], 2), np.int64)
    k, pos, entry = 0, 0, -1
    for i in range(1, flat_slot - 1):
        if math.isnan(c[i]) or math.isnan(vw[i]):
            continue
        if c[i] > vw[i] * (1 + band):
            want = 1
        elif c[i] < vw[i] * (1 - band):
            want = -1
        else:
            want = pos
        if want == pos:
            continue
        nxt = first_valid(o, i + 1, flat_slot)
        if nxt >= 0 and (pos == 0 or nxt - entry >= 2):
            out[k, 0], out[k, 1] = want, nxt
            k += 1
            pos, entry = want, nxt
    return out[:k]


@_jit
def sweep_setup(o, h, l, c, side, level, start, last, tol, reclaim_bars, retest_bars, flat_slot):
    """The first liquidity sweep of `level` from `start` (strategies._one_sweep): trade through it, close back within
    `reclaim_bars`, then a retest that holds within `retest_bars` without a new extreme. Returns (entry slot, the
    sweep's extreme) or (-1, NaN) when the day has no such setup."""
    for i in range(start, last):
        if math.isnan(l[i]):
            continue
        if not ((l[i] < level) if side > 0 else (h[i] > level)):
            continue
        extreme = l[i] if side > 0 else h[i]
        reclaim = -1
        end = i + reclaim_bars if i + reclaim_bars < last else last
        for k in range(i, end):
            if math.isnan(c[k]):
                continue
            if side > 0:
                if l[k] < extreme:
                    extreme = l[k]
            elif h[k] > extreme:
                extreme = h[k]
            if (c[k] > level) if side > 0 else (c[k] < level):
                reclaim = k
                break
        if reclaim < 0:
            return -1, np.nan
        end = reclaim + 1 + retest_bars if reclaim + 1 + retest_bars < last else last
        for k in range(reclaim + 1, end):
            if math.isnan(c[k]):
                continue
            if (l[k] < extreme) if side > 0 else (h[k] > extreme):
                return -1, np.nan
            touch = (l[k] <= level * (1 + tol)) if side > 0 else (h[k] >= level * (1 - tol))
            hold = (c[k] > level) if side > 0 else (c[k] < level)
            if touch and hold:
                nxt = first_valid(o, k + 1, flat_slot)
                if nxt < 0 or nxt > last:
                    return -1, np.nan
                return nxt, extreme
        return -1, np.nan
    return -1, np.nan


@_jit
def orb_retest_setup(o, h, l, c, vw, orh, orl, tol, retest_bars, start, last, flat_slot):
    """strategies.orb_retest_vwap's scan: the first close beyond the opening range on VWAP's side, then a retest of the
    range edge that holds within `retest_bars`. Returns (side, entry slot, retest bar) or (0, -1, -1)."""
    for i in range(start, last):
        if math.isnan(c[i]) or math.isnan(vw[i]):
            continue
        side = 1 if (c[i] > orh and c[i] > vw[i]) else (-1 if (c[i] < orl and c[i] < vw[i]) else 0)
        if side == 0:
            continue
        level = orh if side > 0 else orl
        end = i + 1 + retest_bars if i + 1 + retest_bars < last else last
        for k in range(i + 1, end):
            if math.isnan(c[k]):
                continue
            if (c[k] < level) if side > 0 else (c[k] > level):
                return 0, -1, -1
            touch = (l[k] <= level * (1 + tol)) if side > 0 else (h[k] >= level * (1 - tol))
            if touch and ((c[k] > vw[k]) if side > 0 else (c[k] < vw[k])):
                nxt = first_valid(o, k + 1, flat_slot)
                if nxt < 0 or nxt > last:
                    return 0, -1, -1
                return side, nxt, k
        return 0, -1, -1
    return 0, -1, -1


def warm_up() -> float:
    """enable(), then compile (or load from the disk cache) every kernel once so the first live bar does not pay for it.
    Seconds taken."""
    import time
    t = time.perf_counter()
    enable()
    a = np.linspace(100.0, 101.0, 75)
    first_valid(a, 0, 75)
    vwap(a, a, a, a)
    walk_exit(a, a, a, a, 1, 3, 99.0, 102.0, 69, 3, 75)
    stop_entry(a, a, a, 1, 100.5, 3, 69)
    supertrend_flips(a, a, a, a, 10, 3.0, 69)
    vwap_trend_flips(a, a, a, 0.001, 69)
    sweep_setup(a, a, a, a, 1, 100.2, 0, 60, 0.0005, 6, 12, 69)
    orb_retest_setup(a, a, a, a, a, 100.1, 99.9, 0.0005, 12, 3, 60, 69)
    vw = vwap(a, a, a, a)
    vw.flags.writeable = False                     # Day.vwap() hands out a read-only array: its own specialisation
    vwap_trend_flips(a, a, vw, 0.001, 69)
    orb_retest_setup(a, a, a, a, vw, 100.1, 99.9, 0.0005, 12, 3, 60, 69)
    return time.perf_counter() - t
