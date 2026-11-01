"""Price action (scanner/levels.py): key levels, support and resistance, trend and candle patterns for one symbol."""
from __future__ import annotations

from typing import Literal

from .common import ISODate, ISODateTime, Model


class LvPattern(Model):
    key: str
    name: str
    bias: Literal["bullish", "bearish", "neutral"]
    what: str
    bars_ago: int                                 # 0 = the last bar
    at: ISODateTime


class LvPoint(Model):
    i: int                                        # bar position within `series`
    price: float | None = None
    label: str


class LvLine(Model):
    i1: int
    p1: float | None = None
    i2: int
    p2: float | None = None


class LvChartPattern(Model):
    key: str
    name: str
    bias: Literal["bullish", "bearish", "neutral"]
    status: Literal["forming", "confirmed"]
    direction: Literal["up", "down"] | None = None   # the breakout's direction (triangles, rectangles, wedges)
    confirmed_bars_ago: int | None = None
    what: str
    start: ISODate
    end: ISODate
    breakout: float | None = None                 # the level whose break completes the pattern
    invalidation: float | None = None             # beyond this the pattern is void
    target: float | None = None                   # the textbook measured move (folklore, untested)
    target_pct: float | None = None
    series: list[float | None]                    # closes from just before the pattern to the last bar (sketch)
    points: list[LvPoint]
    lines: list[LvLine]


class LvLevel(Model):
    price: float | None = None
    touches: int                                  # swings that formed at this level
    last: ISODate                                 # when it last formed
    dist_pct: float | None = None                 # from the last close


class LvLevels(Model):
    resistance: list[LvLevel]                     # nearest first
    support: list[LvLevel]


class LvPivots(Model):
    p: float | None = None
    bc: float | None = None
    tc: float | None = None
    r1: float | None = None
    r2: float | None = None
    r3: float | None = None
    s1: float | None = None
    s2: float | None = None
    s3: float | None = None


class LvDay(Model):
    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float | None = None
    prev_close: float | None = None
    prev_high: float | None = None
    prev_low: float | None = None


class LvTrend(Model):
    above_sma20: bool | None = None
    above_sma50: bool | None = None
    above_sma200: bool | None = None
    sma20: float | None = None
    sma50: float | None = None
    sma200: float | None = None
    structure: Literal["up", "down", "mixed"]
    supertrend: float | None = None
    supertrend_dir: Literal["up", "down"] | None = None


class LvDaily(Model):
    date: ISODate
    close: float | None = None
    atr: float | None = None
    atr_pct: float | None = None
    day: LvDay
    pivots: LvPivots                              # for the next session, from this day's bar
    cpr_width_pct: float | None = None
    high_52w: float | None = None
    low_52w: float | None = None
    from_high_52w_pct: float | None = None
    levels: LvLevels
    trend: LvTrend
    patterns: list[LvPattern]
    chart_patterns: list[LvChartPattern]


class LvProfile(Model):
    poc: float | None = None                      # point of control: most volume traded here
    vah: float | None = None                      # value area (70% of volume) high / low
    val: float | None = None


class LvIntraday(Model):
    date: ISODate
    bars: int
    last_bar: ISODateTime
    last: float | None = None
    open: float | None = None
    high: float | None = None
    low: float | None = None
    vwap: float | None = None
    vwap_upper: float | None = None
    vwap_lower: float | None = None
    above_vwap: bool | None = None
    or_high: float | None = None                  # 15-minute opening range
    or_low: float | None = None
    or_state: Literal["above", "below", "inside"] | None = None
    profile: LvProfile | None = None
    patterns: list[LvPattern]


class LevelsResponse(Model):
    symbol: str
    daily: LvDaily | None = None
    intraday: LvIntraday | None = None
    intraday_source: str | None = None            # "live" (FYERS feed today) or "stored" 5-minute bars
    note: str


__all__ = ["LvPattern", "LvPoint", "LvLine", "LvChartPattern", "LvLevel", "LvLevels", "LvPivots", "LvDay", "LvTrend", "LvDaily", "LvProfile", "LvIntraday",
           "LevelsResponse"]
