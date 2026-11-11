"""Live intraday setups (the "alert stream"): events found in today's bars, newest first.

Every event is read from COMPLETED bars only (a forming bar can still turn), so an event never disappears once shown.
The list is recomputed from the bars each time (no state to lose when the service restarts):

  gap_up / gap_down      the first bar opens 2%+ away from the previous close
  orb_up / orb_down      the first close above / below the first 15 minutes' range (the opening range)
  new_high / new_low     a new high / low of the day after 30+ minutes without one (a fresh break, not every tick of
                         a trend), from 09:30
  vwap_up / vwap_down    the close crosses the day's VWAP after 30+ minutes on the other side, from 09:30
  volume_spike           a bar trading 4x the stock's average bar so far today, and at least Rs 20 lakh a minute
  high_52w / low_52w     the first trade above the 52-week high / below the 52-week low (from the daily store)

These are facts about the tape, not signals: none of them has a tested edge here (the page says so).
"""
from __future__ import annotations

from datetime import time

import numpy as np
import pandas as pd

KINDS = ("gap_up", "gap_down", "orb_up", "orb_down", "new_high", "new_low", "vwap_up", "vwap_down", "volume_spike",
         "high_52w", "low_52w")
LABELS = {"gap_up": "Gap up", "gap_down": "Gap down", "orb_up": "Opening-range breakout", "orb_down": "Opening-range breakdown",
          "new_high": "New high of the day", "new_low": "New low of the day", "vwap_up": "Crossed above VWAP",
          "vwap_down": "Crossed below VWAP", "volume_spike": "Volume spike", "high_52w": "52-week high",
          "low_52w": "52-week low"}
BULLISH = {"gap_up", "orb_up", "new_high", "vwap_up", "high_52w"}
GAP_PCT = 2.0
OPENING_MIN = 15
FRESH_MIN = 30
SIDE_MIN = 30
SPIKE_X = 4.0
SPIKE_VALUE_PER_MIN = 2e6            # Rs 20 lakh a minute: a spike in an illiquid stock is noise
SESSION_START = time(9, 15)


def _ev(sym: str, ts, kind: str, price: float, detail: str, prev_close: float | None, value: float | None = None) -> dict:
    return {"time": pd.Timestamp(ts).isoformat(), "symbol": sym, "kind": kind, "label": LABELS[kind],
            "bullish": kind in BULLISH if kind != "volume_spike" else None, "price": round(float(price), 2),
            "change_pct": round((price / prev_close - 1) * 100, 2) if prev_close else None,
            "value_cr": round(value / 1e7, 2) if value is not None else None, "detail": detail}


def detect_one(sym: str, g: pd.DataFrame, step_min: int, prev: dict | None) -> list[dict]:
    """Events in one symbol's bars of one session (sorted by time, completed bars only)."""
    prev = prev or {}
    pc = prev.get("close")
    ts = pd.to_datetime(g["ts"]).to_numpy()
    o, h, l, c, v = (g[k].to_numpy(dtype=float) for k in ("open", "high", "low", "close", "volume"))
    n = len(c)
    if n == 0:
        return []
    out: list[dict] = []
    first = pd.Timestamp(ts[0])
    if pc and first.time() == SESSION_START:
        gap = (o[0] / pc - 1) * 100
        if abs(gap) >= GAP_PCT:
            out.append(_ev(sym, ts[0], "gap_up" if gap > 0 else "gap_down", o[0],
                           f"opened {gap:+.1f}% from yesterday's close {pc:,.2f}", pc))
    n_or = max(1, OPENING_MIN // step_min)
    started = first.time() == SESSION_START
    if started and n > n_or:
        orh, orl = h[:n_or].max(), l[:n_or].min()
        up = np.nonzero(c[n_or:] > orh)[0]
        dn = np.nonzero(c[n_or:] < orl)[0]
        if len(up):
            i = n_or + up[0]
            out.append(_ev(sym, ts[i], "orb_up", c[i], f"closed above the first {OPENING_MIN} minutes' high {orh:,.2f}", pc))
        if len(dn):
            i = n_or + dn[0]
            out.append(_ev(sym, ts[i], "orb_down", c[i], f"closed below the first {OPENING_MIN} minutes' low {orl:,.2f}", pc))
    fresh = max(1, FRESH_MIN // step_min)
    side = max(2, SIDE_MIN // step_min)
    hi_at = lo_at = 0
    for i in range(1, n):
        if h[i] > h[hi_at]:
            if started and i >= n_or and i - hi_at >= fresh:
                out.append(_ev(sym, ts[i], "new_high", c[i], f"above {h[hi_at]:,.2f}, the high since "
                               f"{pd.Timestamp(ts[hi_at]).strftime('%H:%M')}", pc))
            hi_at = i
        if l[i] < l[lo_at]:
            if started and i >= n_or and i - lo_at >= fresh:
                out.append(_ev(sym, ts[i], "new_low", c[i], f"below {l[lo_at]:,.2f}, the low since "
                               f"{pd.Timestamp(ts[lo_at]).strftime('%H:%M')}", pc))
            lo_at = i
    tp = (h + l + c) / 3
    cv = np.cumsum(v)
    vwap = np.where(cv > 0, np.cumsum(tp * v) / np.where(cv > 0, cv, 1), np.nan)
    above = c > vwap
    if started:
        for i in range(max(n_or, side), n):
            if np.isnan(vwap[i]):
                continue
            prior = above[i - side:i]
            if above[i] and not prior.any():
                out.append(_ev(sym, ts[i], "vwap_up", c[i], f"VWAP {vwap[i]:,.2f}", pc))
            elif not above[i] and prior.all() and c[i] < vwap[i]:
                out.append(_ev(sym, ts[i], "vwap_down", c[i], f"VWAP {vwap[i]:,.2f}", pc))
    for i in range(max(n_or, 3), n):
        base = v[1:i].mean()                       # the first bar (the opening auction) is always heavy
        val = v[i] * c[i]
        if base > 0 and v[i] >= SPIKE_X * base and val >= SPIKE_VALUE_PER_MIN * step_min:
            out.append(_ev(sym, ts[i], "volume_spike", c[i], f"{v[i] / base:.0f}x the average bar today, "
                           f"{'up' if c[i] >= o[i] else 'down'} bar", pc, val))
    hi52, lo52 = prev.get("high_52w"), prev.get("low_52w")
    if hi52:
        k = np.nonzero(h > hi52)[0]
        if len(k):
            out.append(_ev(sym, ts[k[0]], "high_52w", c[k[0]], f"traded above the 52-week high {hi52:,.2f}", pc))
    if lo52:
        k = np.nonzero(l < lo52)[0]
        if len(k):
            out.append(_ev(sym, ts[k[0]], "low_52w", c[k[0]], f"traded below the 52-week low {lo52:,.2f}", pc))
    return out


def detect(bars: pd.DataFrame, step_min: int, prev: dict[str, dict]) -> list[dict]:
    """Events for every symbol in one session's bars, newest first."""
    if bars is None or bars.empty:
        return []
    df = bars.sort_values(["symbol", "ts"])
    out: list[dict] = []
    for sym, g in df.groupby("symbol", sort=False):
        out += detect_one(str(sym), g, step_min, prev.get(str(sym)))
    out.sort(key=lambda e: (e["time"], e["symbol"]), reverse=True)
    return out


def previous_day(store: dict[str, pd.DataFrame], day) -> dict[str, dict]:
    """{symbol: {close, high_52w, low_52w}} from the daily store's sessions before `day`."""
    close = store["close"]
    idx = close.index[close.index < pd.Timestamp(day)]
    if not len(idx):
        return {}
    last = idx[-1]
    win = close.index[(close.index > last - pd.Timedelta(days=365)) & (close.index <= last)]
    hi = store["high"].loc[win].max()
    lo = store["low"].loc[win].min()
    pc = close.loc[last]
    out = {}
    for s in close.columns:
        if pd.notna(pc.get(s)):
            out[str(s)] = {"close": float(pc[s]), "high_52w": float(hi[s]) if pd.notna(hi.get(s)) else None,
                           "low_52w": float(lo[s]) if pd.notna(lo.get(s)) else None}
    return out
