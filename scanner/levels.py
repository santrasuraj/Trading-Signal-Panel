"""Price action for one stock or index: key levels, support and resistance, trend structure and candle patterns -
from daily bars (the price store) and, when the stock has them, today's 5-minute bars (intraday store / live feed).

Daily
  pivots      classic floor pivots and the Central Pivot Range from the last completed day (P, BC/TC, R1-R3, S1-S3)
  swing S/R   swing highs / lows (a bar higher / lower than SWING_K bars each side) over the last year, merged when
              within half a daily ATR; a level's strength is how many swings formed there
  trend       price vs the 20/50/200-day averages, higher highs and higher lows (or lower), Supertrend (10, 3)
  patterns    engulfing, hammer, shooting star, doji, inside bar, NR7, morning / evening star, gaps - on the last bars
  chart       double top / bottom, head and shoulders (and inverse), ascending / descending / symmetrical triangles,
              rising / falling wedges, rectangles, bull / bear flags - forming or confirmed (breakout at most 20 bars
              ago), with the breakout level, where the pattern is void, and the textbook target. On 506 stocks
              (30 Oct 2026) about half showed one - so they are common, not rare signals.
Intraday (5-minute bars of the latest session)
  VWAP with 1-SD bands, the 15-minute opening range, the session's high / low, and the volume profile (point of
  control and the 70% value area)

All descriptive. Candle and chart patterns are folklore-grade: this app's own test of NR7 breakouts lost money after costs
(README). None of this is a signal.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

SWING_K = 3                  # a swing high is the highest bar within 3 bars on each side
SWING_LOOKBACK = 250         # about a year of daily bars
LEVELS_EACH_SIDE = 3
PATTERN_BARS = 3             # patterns completed on the last 3 bars are listed
OR_BARS = 3                  # opening range: the first three 5-minute bars (09:15-09:30)
PROFILE_BINS = 40
VALUE_AREA = 0.70


def _f(x, nd: int = 2):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return round(v, nd) if math.isfinite(v) else None


# --------------------------------------------------------------------------- daily
def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    pc = df["close"].shift(1)
    tr = pd.concat([df["high"] - df["low"], (df["high"] - pc).abs(), (df["low"] - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def pivots(h: float, l: float, c: float) -> dict:
    """Classic floor pivots and the Central Pivot Range for the next session."""
    p = (h + l + c) / 3
    bc = (h + l) / 2
    tc = 2 * p - bc
    return {"p": p, "bc": min(bc, tc), "tc": max(bc, tc), "r1": 2 * p - l, "s1": 2 * p - h,
            "r2": p + (h - l), "s2": p - (h - l), "r3": h + 2 * (p - l), "s3": l - 2 * (h - p)}


def _one_per_plateau(mask: pd.Series, k: int) -> pd.Series:
    """Equal highs (or lows) on neighbouring bars are one swing, not several: drop a swing within k bars of the
    previous one kept (otherwise a flat top looks like 'equal highs' and counts twice as a level's strength)."""
    out = mask.to_numpy().copy()
    last = -k - 1
    for i in np.flatnonzero(out):
        if i - last <= k:
            out[i] = False
        else:
            last = i
    return pd.Series(out, index=mask.index)


def swings(df: pd.DataFrame, k: int = SWING_K) -> tuple[pd.Series, pd.Series]:
    """Boolean masks of swing highs and lows (the extreme within k bars on both sides, one per plateau; the last k
    bars cannot be confirmed yet)."""
    win = 2 * k + 1
    hi = df["high"].rolling(win, center=True).max()
    lo = df["low"].rolling(win, center=True).min()
    return (_one_per_plateau((df["high"] == hi) & hi.notna(), k),
            _one_per_plateau((df["low"] == lo) & lo.notna(), k))


def sr_levels(df: pd.DataFrame, close: float, tol: float) -> dict:
    """Swing highs and lows of the last year merged into levels `tol` apart; nearest LEVELS_EACH_SIDE above and
    below the close, each with its strength (swings at the level) and the date it last formed."""
    d = df.iloc[-SWING_LOOKBACK:]
    sh, sl = swings(d)
    pts = pd.concat([d.loc[sh, "high"], d.loc[sl, "low"]]).sort_values()
    levels: list[dict] = []
    for when, px in pts.items():
        if levels and px - levels[-1]["_hi"] <= tol:
            lv = levels[-1]
            lv["_px"].append(px)
            lv["_hi"] = px
            lv["last"] = max(lv["last"], when)
        else:
            levels.append({"_px": [px], "_hi": px, "last": when})
    out = []
    for lv in levels:
        out.append({"price": float(np.mean(lv["_px"])), "touches": len(lv["_px"]),
                    "last": pd.Timestamp(lv["last"]).date().isoformat()})
    above = sorted([x for x in out if x["price"] > close], key=lambda x: x["price"])[:LEVELS_EACH_SIDE]
    below = sorted([x for x in out if x["price"] <= close], key=lambda x: -x["price"])[:LEVELS_EACH_SIDE]
    fmt = lambda xs: [{**x, "price": _f(x["price"]), "dist_pct": _f((x["price"] / close - 1) * 100)} for x in xs]  # noqa: E731
    return {"resistance": fmt(above), "support": fmt(below)}


def structure(df: pd.DataFrame) -> str:
    """'up' when the last two confirmed swing highs AND lows rise, 'down' when both fall, else 'mixed'."""
    sh, sl = swings(df.iloc[-SWING_LOOKBACK:])
    highs = df.loc[sh[sh].index, "high"].iloc[-2:] if sh.any() else pd.Series(dtype=float)
    lows = df.loc[sl[sl].index, "low"].iloc[-2:] if sl.any() else pd.Series(dtype=float)
    if len(highs) < 2 or len(lows) < 2:
        return "mixed"
    if highs.iloc[1] > highs.iloc[0] and lows.iloc[1] > lows.iloc[0]:
        return "up"
    if highs.iloc[1] < highs.iloc[0] and lows.iloc[1] < lows.iloc[0]:
        return "down"
    return "mixed"


def supertrend(df: pd.DataFrame, n: int = 10, mult: float = 3.0) -> tuple[float | None, str | None]:
    """The Supertrend line and its direction ('up' = price above it) on the last bar."""
    a = atr(df, n)
    hl2 = (df["high"] + df["low"]) / 2
    up_b, dn_b = (hl2 - mult * a).to_numpy(), (hl2 + mult * a).to_numpy()
    c = df["close"].to_numpy()
    line, trend = np.full(len(c), np.nan), 1
    fu, fd = np.nan, np.nan
    for i in range(len(c)):
        if math.isnan(up_b[i]):
            continue
        fu = up_b[i] if math.isnan(fu) or c[i - 1] < fu else max(up_b[i], fu)
        fd = dn_b[i] if math.isnan(fd) or c[i - 1] > fd else min(dn_b[i], fd)
        if trend == 1 and c[i] < fu:
            trend = -1
        elif trend == -1 and c[i] > fd:
            trend = 1
        line[i] = fu if trend == 1 else fd
    if math.isnan(line[-1]):
        return None, None
    return float(line[-1]), "up" if trend == 1 else "down"


PATTERN_INFO = {
    "bullish_engulfing": ("Bullish engulfing", "bullish", "A rising candle whose body covers the previous falling one."),
    "bearish_engulfing": ("Bearish engulfing", "bearish", "A falling candle whose body covers the previous rising one."),
    "hammer": ("Hammer", "bullish", "Long lower shadow after a decline: sellers pushed down, buyers closed it near the high."),
    "shooting_star": ("Shooting star", "bearish", "Long upper shadow after a rise: buyers pushed up, sellers closed it near the low."),
    "doji": ("Doji", "neutral", "Open and close almost equal: indecision."),
    "inside_bar": ("Inside bar", "neutral", "The whole range inside the previous bar's: a pause."),
    "nr7": ("NR7", "neutral", "The narrowest range of the last 7 bars: quiet before a move (direction unknown)."),
    "morning_star": ("Morning star", "bullish", "A big falling candle, a small one, then a rising candle closing past the first's middle."),
    "evening_star": ("Evening star", "bearish", "A big rising candle, a small one, then a falling candle closing past the first's middle."),
    "gap_up": ("Gap up", "bullish", "Opened above the previous bar's high."),
    "gap_down": ("Gap down", "bearish", "Opened below the previous bar's low."),
}


def patterns(df: pd.DataFrame, last: int = PATTERN_BARS) -> list[dict]:
    """Candle patterns completed on the last `last` bars (newest first). Needs at least 8 bars."""
    if len(df) < 8:
        return []
    o, h, l, c = (df[x].to_numpy(dtype=float) for x in ("open", "high", "low", "close"))
    rng = h - l
    body = np.abs(c - o)
    up_sh = h - np.maximum(o, c)
    lo_sh = np.minimum(o, c) - l
    prior = pd.Series(c).pct_change(5).shift(1).to_numpy()          # the move before the candle
    out = []
    n = len(df)
    for i in range(max(n - last, 7), n):
        found = []
        po, pc_, ph, pl = o[i - 1], c[i - 1], h[i - 1], l[i - 1]
        if rng[i] <= 0:
            continue
        if pc_ < po and c[i] > o[i] and o[i] <= pc_ and c[i] >= po and body[i] > body[i - 1]:
            found.append("bullish_engulfing")
        if pc_ > po and c[i] < o[i] and o[i] >= pc_ and c[i] <= po and body[i] > body[i - 1]:
            found.append("bearish_engulfing")
        if lo_sh[i] >= 2 * body[i] and up_sh[i] <= 0.25 * rng[i] and prior[i] < 0:
            found.append("hammer")
        if up_sh[i] >= 2 * body[i] and lo_sh[i] <= 0.25 * rng[i] and prior[i] > 0:
            found.append("shooting_star")
        if body[i] <= 0.1 * rng[i] and "hammer" not in found and "shooting_star" not in found:
            found.append("doji")
        if h[i] < ph and l[i] > pl:
            found.append("inside_bar")
        if rng[i] <= np.min(rng[i - 6:i + 1]) and np.sum(rng[i - 6:i + 1] == rng[i]) == 1:
            found.append("nr7")
        b2 = body[i - 2]
        if (c[i - 2] < o[i - 2] and b2 > 0 and body[i - 1] < 0.3 * b2 and c[i] > o[i]
                and c[i] > (o[i - 2] + c[i - 2]) / 2):
            found.append("morning_star")
        if (c[i - 2] > o[i - 2] and b2 > 0 and body[i - 1] < 0.3 * b2 and c[i] < o[i]
                and c[i] < (o[i - 2] + c[i - 2]) / 2):
            found.append("evening_star")
        if o[i] > ph:
            found.append("gap_up")
        elif o[i] < pl:
            found.append("gap_down")
        when = df.index[i]
        for key in found:
            name, bias, what = PATTERN_INFO[key]
            out.append({"key": key, "name": name, "bias": bias, "what": what, "bars_ago": n - 1 - i,
                        "at": pd.Timestamp(when).isoformat()})
    return sorted(out, key=lambda x: x["bars_ago"])


# --------------------------------------------------------------------------- chart patterns
PAT_K = 5                    # chart patterns use bigger swings: the extreme within 5 bars on each side
PAT_RECENT = 40              # a pattern's last swing must be within the last 40 bars (else it is history)
EQ_ATR = 1.0                 # two tops / bottoms are "equal" within one daily ATR; a trendline moving less is "flat"
MIN_DEPTH_ATR = 3.0          # a double top's dip, a head's height: at least 3 ATRs (a real swing, not noise)
MIN_SPAN = 15                # a triangle / wedge / rectangle spans at least 15 bars
FLAG_POLE_ATR = 5.0          # a flag's pole: a move of 5+ ATRs ...
FLAG_POLE_PCT = 8.0          # ... and 8%+ of the price, in 3-12 bars
FLAG_RETRACE = 0.382         # the pause gives back at most 38.2% of the pole (the textbook flag)
MIN_TOUCHES = 5              # a triangle / wedge: 5+ swings on its two lines (2 on one, 3 on the other)
MAX_NARROW = 0.75            # ... and its lines narrow to 3/4 of their starting width or less
CONFIRM_RECENT = 20          # a confirmed pattern is listed while its breakout is at most 20 bars old
FLAG_BARS = (5, 15)          # ... then a 5-15 bar pause
MAX_CHART_PATTERNS = 4
SKETCH_PAD = 5               # bars shown before a pattern's first point

CHART_INFO = {
    "double_top": ("Double top", "bearish", "Two similar highs with a dip between: a close below the dip's low "
                   "(the neckline) completes it."),
    "double_bottom": ("Double bottom", "bullish", "Two similar lows with a rise between: a close above the rise's "
                      "high (the neckline) completes it."),
    "head_shoulders": ("Head and shoulders", "bearish", "A high between two lower, similar highs: a close below the "
                       "neckline through the two lows completes it."),
    "inverse_head_shoulders": ("Inverse head and shoulders", "bullish", "A low between two higher, similar lows: a "
                               "close above the neckline through the two highs completes it."),
    "ascending_triangle": ("Ascending triangle", "bullish", "Flat highs and rising lows: buyers keep paying more "
                           "while sellers wait at one price."),
    "descending_triangle": ("Descending triangle", "bearish", "Falling highs and flat lows: sellers keep accepting "
                            "less while buyers wait at one price."),
    "symmetrical_triangle": ("Symmetrical triangle", "neutral", "Falling highs and rising lows: the range narrows; "
                             "the breakout's direction decides."),
    "rectangle": ("Rectangle", "neutral", "Flat highs and flat lows: a range; the breakout's direction decides."),
    "rising_wedge": ("Rising wedge", "bearish", "Highs and lows both rising, the lows faster: the rise is losing "
                     "room."),
    "falling_wedge": ("Falling wedge", "bullish", "Highs and lows both falling, the highs faster: the fall is losing "
                      "room."),
    "bull_flag": ("Bull flag", "bullish", "A sharp rise (the pole), then a short pause giving back under 38% of it: "
                  "a close above the pause's high completes it."),
    "bear_flag": ("Bear flag", "bearish", "A sharp fall (the pole), then a short pause giving back under 38% of it: "
                  "a close below the pause's low completes it."),
}


def turning_points(df: pd.DataFrame, k: int = PAT_K) -> list[tuple[int, str, float]]:
    """Swing highs and lows as (bar position, 'H' or 'L', price), alternating: of two swings of the same kind in a
    row the more extreme one is kept."""
    sh, sl = swings(df, k)
    hi, lo = df["high"].to_numpy(float), df["low"].to_numpy(float)
    pts = sorted([(int(i), "H", hi[i]) for i in np.flatnonzero(sh.to_numpy())]
                 + [(int(i), "L", lo[i]) for i in np.flatnonzero(sl.to_numpy())])
    out: list[tuple[int, str, float]] = []
    for p in pts:
        if out and out[-1][1] == p[1]:
            if (p[1] == "H" and p[2] >= out[-1][2]) or (p[1] == "L" and p[2] <= out[-1][2]):
                out[-1] = p
        else:
            out.append(p)
    return out


def _sketch(df: pd.DataFrame, key: str, status: str, first: int, *, breakout: float, invalidation: float,
            target: float | None, points: list[tuple[int, float, str]], lines: list[tuple[int, float, int, float]],
            direction: str | None = None, confirmed_at: int | None = None) -> dict:
    """One pattern for the page: levels plus what a small sketch needs - the closes from just before the first
    point to the last bar, the labelled points and the lines (bar positions relative to the sketch's start)."""
    name, bias, what = CHART_INFO[key]
    s0 = max(first - SKETCH_PAD, 0)
    close = float(df["close"].iat[-1])
    idx = df.index
    return {
        "key": key, "name": name, "bias": bias, "status": status, "direction": direction, "what": what,
        "confirmed_bars_ago": len(df) - 1 - confirmed_at if confirmed_at is not None else None,
        "start": pd.Timestamp(idx[first]).date().isoformat(), "end": pd.Timestamp(idx[-1]).date().isoformat(),
        "breakout": _f(breakout), "invalidation": _f(invalidation), "target": _f(target),
        "target_pct": _f((target / close - 1) * 100) if target else None,
        "series": [_f(x) for x in df["close"].iloc[s0:].to_numpy()],
        "points": [{"i": i - s0, "price": _f(p), "label": lab} for i, p, lab in points],
        "lines": [{"i1": a - s0, "p1": _f(pa), "i2": b - s0, "p2": _f(pb)} for a, pa, b, pb in lines],
    }


def _doubles(df: pd.DataFrame, pts: list, a: float) -> list[dict]:
    c, n = df["close"].to_numpy(float), len(df)
    out = []
    for tri in (pts[-3:], pts[-4:-1]):
        if len(tri) < 3:
            continue
        (i1, t1, p1), (im, tm, pm), (i2, t2, p2) = tri
        top = t1 == "H"
        if (t1, tm, t2) not in (("H", "L", "H"), ("L", "H", "L")) or i2 - i1 < 8 or n - 1 - i2 > PAT_RECENT:
            continue
        depth = (min(p1, p2) - pm) if top else (pm - max(p1, p2))
        if abs(p1 - p2) > EQ_ATR * a or depth < MIN_DEPTH_ATR * a:
            continue
        after = c[i2 + 1:]
        extreme = max(p1, p2) if top else min(p1, p2)
        if top and (after > extreme + EQ_ATR * a).any() or not top and (after < extreme - EQ_ATR * a).any():
            continue                                        # price went on past both tops (bottoms): no pattern
        hit = np.flatnonzero(after < pm if top else after > pm)
        height = (p1 + p2) / 2 - pm
        out.append(_sketch(df, "double_top" if top else "double_bottom", "confirmed" if len(hit) else "forming", i1,
                           breakout=pm, invalidation=extreme, target=pm - height,
                           confirmed_at=i2 + 1 + int(hit[0]) if len(hit) else None,
                           points=[(i1, p1, "1"), (im, pm, "N"), (i2, p2, "2")],
                           lines=[(im, pm, n - 1, pm)]))
        break
    return out


def _head_shoulders(df: pd.DataFrame, pts: list, a: float) -> list[dict]:
    c, n = df["close"].to_numpy(float), len(df)
    for five in (pts[-5:], pts[-6:-1]):
        if len(five) < 5:
            continue
        kinds = "".join(t for _, t, _ in five)
        if kinds not in ("HLHLH", "LHLHL"):
            continue
        top = kinds == "HLHLH"
        (ils, ls, _), (in1, n1, _), (ihd, hd, _), (in2, n2, _), (irs, rs, _) = [(i, p, t) for i, t, p in five]
        if n - 1 - irs > PAT_RECENT:
            continue
        neck = lambda j: n1 + (n2 - n1) * (j - in1) / (in2 - in1)     # noqa: E731
        sgn = 1 if top else -1                                         # +1: above is "beyond" the head
        if top:
            ok = (hd - max(ls, rs) >= EQ_ATR * a and hd - neck(ihd) >= MIN_DEPTH_ATR * a
                  and min(ls, rs) > max(n1, n2))
        else:
            ok = (min(ls, rs) - hd >= EQ_ATR * a and neck(ihd) - hd >= MIN_DEPTH_ATR * a
                  and max(ls, rs) < min(n1, n2))
        if not ok or abs(ls - rs) > 2 * EQ_ATR * a:
            continue
        after = range(irs + 1, n)
        if any(sgn * (c[j] - hd) > 0 for j in after):
            continue                                        # beyond the head again: no pattern
        hit = next((j for j in after if sgn * (c[j] - neck(j)) < 0), None)
        now = neck(n - 1)
        return [_sketch(df, "head_shoulders" if top else "inverse_head_shoulders",
                        "confirmed" if hit is not None else "forming", ils, breakout=now, invalidation=rs,
                        target=now - (hd - neck(ihd)), confirmed_at=hit,
                        points=[(ils, ls, "LS"), (ihd, hd, "H"), (irs, rs, "RS"), (in1, n1, ""), (in2, n2, "")],
                        lines=[(in1, n1, n - 1, now)])]
    return []


def _triangles(df: pd.DataFrame, pts: list, a: float) -> list[dict]:
    c, n = df["close"].to_numpy(float), len(df)
    recent = [p for p in pts[-6:] if n - 1 - p[0] <= 80]
    hs = [(i, p) for i, t, p in recent if t == "H"][-3:]
    ls = [(i, p) for i, t, p in recent if t == "L"][-3:]
    if len(hs) < 2 or len(ls) < 2 or len(hs) + len(ls) < MIN_TOUCHES:
        return []
    first, last = min(hs[0][0], ls[0][0]), max(hs[-1][0], ls[-1][0])
    span = last - first
    if span < MIN_SPAN or n - 1 - last > PAT_RECENT // 2:
        return []
    mu, bu = np.polyfit([i for i, _ in hs], [p for _, p in hs], 1)
    ml, bl = np.polyfit([i for i, _ in ls], [p for _, p in ls], 1)
    up, lo = (lambda j: mu * j + bu), (lambda j: ml * j + bl)
    du, dl = mu * span / a, ml * span / a                  # how far each line moves over the pattern, in ATRs
    if up(n - 1) <= lo(n - 1) or up(first) - lo(first) < 2 * a:
        return []                                           # lines crossed (apex passed) or too narrow to matter
    flat_u, flat_l = abs(du) <= EQ_ATR, abs(dl) <= EQ_ATR
    if flat_u and dl > EQ_ATR:
        key = "ascending_triangle"
    elif du < -EQ_ATR and flat_l:
        key = "descending_triangle"
    elif du < -EQ_ATR and dl > EQ_ATR:
        key = "symmetrical_triangle"
    elif flat_u and flat_l and up(first) - lo(first) >= 2.5 * a:
        key = "rectangle"
    elif du > EQ_ATR and dl > du:
        key = "rising_wedge"
    elif dl < -EQ_ATR and du < dl:
        key = "falling_wedge"
    else:
        return []
    if key != "rectangle" and up(n - 1) - lo(n - 1) > MAX_NARROW * (up(first) - lo(first)):
        return []                                           # lines barely narrow: a channel, not a triangle / wedge
    inside = range(first, last + 1)
    if any(c[j] > up(j) + a or c[j] < lo(j) - a for j in inside):
        return []                                           # price left the lines while the pattern formed
    after = range(last + 1, n)
    up_at = next((j for j in after if c[j] > up(j) + 0.2 * a), None)
    dn_at = next((j for j in after if c[j] < lo(j) - 0.2 * a), None)
    broke_up, broke_dn = up_at is not None, dn_at is not None
    if broke_up and broke_dn:
        return []
    bias = CHART_INFO[key][1]
    direction = "up" if broke_up else "down" if broke_dn else None
    height = up(first) - lo(first)
    if bias == "bearish":
        breakout, invalidation, target = lo(n - 1), up(n - 1), lo(n - 1) - height
    else:
        breakout, invalidation, target = up(n - 1), lo(n - 1), up(n - 1) + height
    if bias == "neutral":
        target = (up(n - 1) + height if direction == "up" else lo(n - 1) - height if direction == "down" else None)
    return [_sketch(df, key, "confirmed" if direction else "forming", first, breakout=breakout,
                    invalidation=invalidation, target=target, direction=direction,
                    confirmed_at=up_at if broke_up else dn_at,
                    points=[(i, p, "") for i, p in hs + ls],
                    lines=[(first, up(first), n - 1, up(n - 1)), (first, lo(first), n - 1, lo(n - 1))])]


def _flags(df: pd.DataFrame, a: float) -> list[dict]:
    h, lo, c, n = (df["high"].to_numpy(float), df["low"].to_numpy(float), df["close"].to_numpy(float), len(df))
    for bull in (True, False):
        for L in range(FLAG_BARS[1], FLAG_BARS[0] - 1, -1):          # the longest pause that fits
            s = n - L                                                # first bar of the pause
            if s - 15 < 0:
                continue
            box_h, box_l = h[s:n - 1].max(), lo[s:n - 1].min()         # the pause, without today's bar
            if bull:
                ia = s - 1 - int(np.argmin(lo[s - 15:s][::-1]))         # the LAST bar at the low: where the move began
                ib = ia + int(np.argmax(h[ia:s + 1]))
                base, peak = lo[ia], h[ib]
                pole = peak - base
                ok_shape = box_h <= peak + 0.25 * a and peak - box_l <= FLAG_RETRACE * pole and ib >= s - 2
            else:
                ia = s - 1 - int(np.argmax(h[s - 15:s][::-1]))
                ib = ia + int(np.argmin(lo[ia:s + 1]))
                base, peak = h[ia], lo[ib]
                pole = base - peak
                ok_shape = box_l >= peak - 0.25 * a and box_h - peak <= FLAG_RETRACE * pole and ib >= s - 2
            if not (ok_shape and pole >= FLAG_POLE_ATR * a and pole >= FLAG_POLE_PCT / 100 * base
                    and 3 <= ib - ia <= 12):
                continue
            last = c[-1]
            if (bull and last < box_l) or (not bull and last > box_h):
                break                                                # the pause broke the wrong way: no flag
            done = last > box_h if bull else last < box_l
            key = "bull_flag" if bull else "bear_flag"
            return [_sketch(df, key, "confirmed" if done else "forming", ia,
                            breakout=box_h if bull else box_l, invalidation=box_l if bull else box_h,
                            target=(box_h + pole) if bull else (box_l - pole), confirmed_at=n - 1 if done else None,
                            points=[(ia, base, "pole"), (ib, peak, "")],
                            lines=[(s, box_h, n - 1, box_h), (s, box_l, n - 1, box_l)])]
    return []


def chart_patterns(df: pd.DataFrame) -> list[dict]:
    """Classic chart patterns on the last daily bars, confirmed ones first (at most MAX_CHART_PATTERNS). Rules are
    the textbook ones, made exact: see the constants above. Untested here - like candle patterns, folklore-grade."""
    d = df.dropna(subset=["close"]).iloc[-250:]
    if len(d) < 60:
        return []
    a = float(atr(d).iloc[-1])
    if not a > 0:
        return []
    pts = turning_points(d)
    hs = _head_shoulders(d, pts, a)
    doubles = _doubles(d, pts, a)
    if hs:      # a head and shoulders' two troughs (peaks) also look like a double bottom (top): one reading only
        doubles = [x for x in doubles if x["start"] < hs[0]["start"]]
    found = [p for p in doubles + hs + _triangles(d, pts, a) + _flags(d, a)
             if p["status"] == "forming" or p["confirmed_bars_ago"] <= CONFIRM_RECENT]
    found.sort(key=lambda p: p["start"], reverse=True)                   # newest first ...
    found.sort(key=lambda p: p["status"] != "confirmed")                 # ... confirmed ones before forming ones
    return found[:MAX_CHART_PATTERNS]


def daily(df: pd.DataFrame) -> dict | None:
    """Everything daily for one symbol: `df` has open/high/low/close/volume rows by date (oldest first)."""
    df = df.dropna(subset=["close"]).sort_index()
    if len(df) < 30:
        return None
    last = df.iloc[-1]
    close = float(last["close"])
    a = float(atr(df).iloc[-1])
    sma = {n: df["close"].rolling(n).mean().iloc[-1] for n in (20, 50, 200)}
    yr = df.iloc[-252:]
    st_line, st_dir = supertrend(df)
    piv = pivots(float(last["high"]), float(last["low"]), close)
    prev = df.iloc[-2]
    return {
        "date": pd.Timestamp(df.index[-1]).date().isoformat(), "close": _f(close), "atr": _f(a),
        "atr_pct": _f(a / close * 100),
        "day": {"open": _f(last["open"]), "high": _f(last["high"]), "low": _f(last["low"]), "close": _f(close),
                "prev_close": _f(prev["close"]), "prev_high": _f(prev["high"]), "prev_low": _f(prev["low"])},
        "pivots": {k: _f(v) for k, v in piv.items()},
        "cpr_width_pct": _f((piv["tc"] - piv["bc"]) / close * 100, 3),
        "high_52w": _f(yr["high"].max()), "low_52w": _f(yr["low"].min()),
        "from_high_52w_pct": _f((close / yr["high"].max() - 1) * 100),
        "levels": sr_levels(df, close, tol=0.5 * a if a > 0 else close * 0.01),
        "trend": {
            "above_sma20": bool(close > sma[20]) if pd.notna(sma[20]) else None,
            "above_sma50": bool(close > sma[50]) if pd.notna(sma[50]) else None,
            "above_sma200": bool(close > sma[200]) if pd.notna(sma[200]) else None,
            "sma20": _f(sma[20]), "sma50": _f(sma[50]), "sma200": _f(sma[200]),
            "structure": structure(df), "supertrend": _f(st_line), "supertrend_dir": st_dir,
        },
        "patterns": patterns(df),
        "chart_patterns": chart_patterns(df),
    }


# --------------------------------------------------------------------------- intraday
def volume_profile(bars: pd.DataFrame, bins: int = PROFILE_BINS) -> dict | None:
    """Point of control (the price with the most volume) and the value area holding VALUE_AREA of the volume, from
    5-minute bars (each bar's volume spread evenly over its high-low range)."""
    lo, hi = float(bars["low"].min()), float(bars["high"].max())
    if not (hi > lo) or bars["volume"].sum() <= 0:
        return None
    edges = np.linspace(lo, hi, bins + 1)
    mids = (edges[:-1] + edges[1:]) / 2
    vol = np.zeros(bins)
    for bl, bh, v in bars[["low", "high", "volume"]].itertuples(index=False):
        if v <= 0:
            continue
        a, b = np.searchsorted(edges, bl, "right") - 1, np.searchsorted(edges, bh, "left")
        a, b = max(a, 0), min(max(b, a + 1), bins)
        vol[a:b] += v / (b - a)
    poc = int(np.argmax(vol))
    lo_i = hi_i = poc
    got, need = vol[poc], VALUE_AREA * vol.sum()
    while got < need and (lo_i > 0 or hi_i < bins - 1):
        down = vol[lo_i - 1] if lo_i > 0 else -1
        up = vol[hi_i + 1] if hi_i < bins - 1 else -1
        if up >= down:
            hi_i += 1
            got += vol[hi_i]
        else:
            lo_i -= 1
            got += vol[lo_i]
    return {"poc": _f(mids[poc]), "vah": _f(edges[hi_i + 1]), "val": _f(edges[lo_i])}


def intraday(bars: pd.DataFrame) -> dict | None:
    """Today's (the latest session's) 5-minute levels. `bars`: ts, open, high, low, close, volume of one symbol."""
    if bars is None or bars.empty:
        return None
    b = bars.sort_values("ts")
    day = b["ts"].dt.date.max()
    b = b[b["ts"].dt.date == day].reset_index(drop=True)
    if b.empty:
        return None
    tp = (b["high"] + b["low"] + b["close"]) / 3
    v = b["volume"].clip(lower=0)
    cv = v.cumsum()
    vwap = (tp * v).cumsum() / cv.where(cv > 0)
    var = ((tp - vwap) ** 2 * v).cumsum() / cv.where(cv > 0)
    sd = float(np.sqrt(var.iloc[-1])) if pd.notna(var.iloc[-1]) else math.nan
    last = float(b["close"].iloc[-1])
    vw = float(vwap.iloc[-1]) if pd.notna(vwap.iloc[-1]) else math.nan
    orb = b.iloc[:OR_BARS]
    or_hi, or_lo = float(orb["high"].max()), float(orb["low"].min())
    full_or = len(b) >= OR_BARS
    d = b.set_index("ts")[["open", "high", "low", "close", "volume"]]
    return {
        "date": day.isoformat(), "bars": len(b), "last_bar": pd.Timestamp(b["ts"].iloc[-1]).isoformat(),
        "last": _f(last), "open": _f(b["open"].iloc[0]), "high": _f(b["high"].max()), "low": _f(b["low"].min()),
        "vwap": _f(vw), "vwap_upper": _f(vw + sd), "vwap_lower": _f(vw - sd),
        "above_vwap": bool(last > vw) if math.isfinite(vw) else None,
        "or_high": _f(or_hi) if full_or else None, "or_low": _f(or_lo) if full_or else None,
        "or_state": (None if not full_or else "above" if last > or_hi else "below" if last < or_lo else "inside"),
        "profile": volume_profile(b),
        "patterns": patterns(d),
    }


def analyse(daily_bars: pd.DataFrame, intraday_bars: pd.DataFrame | None = None) -> dict:
    return {"daily": daily(daily_bars), "intraday": intraday(intraday_bars)}
