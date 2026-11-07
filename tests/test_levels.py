"""Price action (scanner/levels.py): pivots, swing levels, trend structure, candle patterns and intraday VWAP /
opening range / volume profile on hand-made bars."""
import numpy as np
import pandas as pd
import pytest

from scanner import levels as lv


def bars(closes, opens=None, highs=None, lows=None, start="2026-01-01", freq="B"):
    c = np.asarray(closes, dtype=float)
    o = np.asarray(opens if opens is not None else np.r_[c[0], c[:-1]], dtype=float)
    h = np.asarray(highs if highs is not None else np.maximum(o, c) * 1.01, dtype=float)
    lo = np.asarray(lows if lows is not None else np.minimum(o, c) * 0.99, dtype=float)
    idx = pd.date_range(start, periods=len(c), freq=freq)
    return pd.DataFrame({"open": o, "high": h, "low": lo, "close": c, "volume": 1000.0}, index=idx)


def test_pivots_by_hand():
    p = lv.pivots(110, 90, 105)
    assert p["p"] == pytest.approx(305 / 3) and p["r1"] == pytest.approx(2 * 305 / 3 - 90)
    assert p["s1"] == pytest.approx(2 * 305 / 3 - 110) and p["bc"] <= p["p"] <= p["tc"]


def test_swing_levels_and_structure():
    wave = np.r_[np.linspace(100, 120, 10), np.linspace(120, 105, 10), np.linspace(105, 125, 10),
                 np.linspace(125, 110, 10), np.linspace(110, 118, 10)]
    df = bars(wave)
    out = lv.sr_levels(df, close=118.0, tol=1.0)
    assert out["resistance"] and all(x["price"] > 118 for x in out["resistance"])
    assert out["support"] and all(x["price"] <= 118 for x in out["support"])
    assert lv.structure(df) == "up"                                   # 120 -> 125 highs, 105 -> 110 lows
    assert lv.structure(bars(wave[::-1])) == "down"


def test_patterns_engulfing_and_inside_bar():
    c = [100, 99, 98, 97, 96, 95, 94, 93, 95.5]
    o = [100, 100, 99, 98, 97, 96, 95, 94.5, 92.5]                    # last: rising body covering the falling one
    df = bars(c, opens=o)
    keys = {p["key"] for p in lv.patterns(df) if p["bars_ago"] == 0}
    assert "bullish_engulfing" in keys
    h = [101, 101, 101, 101, 101, 101, 101, 105, 104]
    lo = [99, 99, 99, 99, 99, 99, 99, 95, 96]
    df2 = bars([100] * 9, opens=[100] * 8 + [100.5], highs=h, lows=lo)
    assert "inside_bar" in {p["key"] for p in lv.patterns(df2) if p["bars_ago"] == 0}


def test_daily_payload_is_complete():
    rng = np.random.default_rng(1)
    df = bars(100 * np.cumprod(1 + rng.normal(0.0005, 0.01, 300)))
    d = lv.daily(df)
    assert d["date"] == df.index[-1].date().isoformat() and d["trend"]["structure"] in ("up", "down", "mixed")
    assert d["trend"]["supertrend_dir"] in ("up", "down") and d["high_52w"] >= d["close"] >= d["low_52w"]
    assert lv.daily(df.iloc[:10]) is None


def test_intraday_vwap_opening_range_and_profile():
    ts = pd.date_range("2026-10-30 09:15", periods=12, freq="5min")
    b = pd.DataFrame({"ts": ts, "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1000.0})
    b.loc[11, ["open", "high", "low", "close"]] = [101.0, 103.0, 101.0, 102.5]     # a break above the range
    i = lv.intraday(b)
    assert i["or_high"] == 101.0 and i["or_low"] == 99.0 and i["or_state"] == "above"
    assert 100 < i["vwap"] < 101 and i["above_vwap"] is True
    assert 99 <= i["profile"]["val"] <= i["profile"]["poc"] <= i["profile"]["vah"] <= 103
    assert lv.intraday(b.iloc[0:0]) is None


# ------------------------------------------------------------------ chart patterns
def path(points, n=None):
    """Closes along straight lines between (bar, price) waypoints."""
    xs, ys = zip(*points)
    return np.interp(np.arange(n or xs[-1] + 1), xs, ys)


def found(df):
    return {(p["key"], p["status"]) for p in lv.chart_patterns(df)}


def test_double_top_confirmed_below_the_neckline():
    df = bars(path([(0, 80), (30, 100), (45, 88), (60, 100), (75, 85)]))
    pats = [p for p in lv.chart_patterns(df) if p["key"] == "double_top"]
    assert pats and pats[0]["status"] == "confirmed" and pats[0]["bias"] == "bearish"
    p = pats[0]
    assert p["invalidation"] > p["breakout"] > p["target"]
    assert [x["label"] for x in p["points"]] == ["1", "N", "2"] and len(p["series"]) == len(df) - 30 + lv.SKETCH_PAD


def test_head_and_shoulders_forming_and_not_also_a_double_bottom():
    df = bars(path([(0, 80), (20, 95), (30, 88), (45, 105), (60, 88), (75, 95), (85, 90)]))
    keys = found(df)
    assert ("head_shoulders", "forming") in keys
    assert not any(k == "double_bottom" for k, _ in keys)
    inv = bars(200 - path([(0, 80), (20, 95), (30, 88), (45, 105), (60, 88), (75, 95), (85, 90)]))
    assert ("inverse_head_shoulders", "forming") in found(inv)


def test_ascending_triangle():
    df = bars(path([(0, 90), (10, 100), (20, 92), (30, 100), (40, 95), (50, 100), (60, 97), (70, 100), (78, 99)]))
    p = [x for x in lv.chart_patterns(df) if x["key"] == "ascending_triangle"]
    assert p and p[0]["status"] == "forming" and p[0]["bias"] == "bullish" and len(p[0]["lines"]) == 2
    assert p[0]["target"] > p[0]["breakout"] > p[0]["invalidation"]


def test_bull_flag_confirmed_on_the_breakout():
    df = bars(path([(0, 100), (40, 100), (50, 125), (62, 121), (63, 128)]))
    p = [x for x in lv.chart_patterns(df) if x["key"] == "bull_flag"]
    assert p and p[0]["status"] == "confirmed" and p[0]["target"] > p[0]["breakout"]


ASC_TRIANGLE = [(0, 90), (10, 100), (20, 92), (30, 100), (40, 95), (50, 100), (60, 97), (70, 100), (78, 99)]
RISING_WEDGE = [(0, 85), (10, 100), (20, 90), (30, 106), (40, 98), (50, 110), (60, 104), (70, 113), (78, 110)]
BULL_FLAG = [(0, 100), (40, 100), (50, 125), (62, 121), (63, 128)]
DOUBLE_TOP = [(0, 80), (30, 100), (45, 88), (60, 100), (75, 85)]
HEAD_SHOULDERS = [(0, 80), (20, 95), (30, 88), (45, 105), (60, 88), (75, 95), (85, 90)]
# (pattern, closes, status): one textbook shape per chart pattern; the bearish / bullish twins are mirror images
SHAPES = [
    ("double_top", path(DOUBLE_TOP), "confirmed"),
    ("double_bottom", 200 - path(DOUBLE_TOP), "confirmed"),
    ("head_shoulders", path(HEAD_SHOULDERS), "forming"),
    ("inverse_head_shoulders", 200 - path(HEAD_SHOULDERS), "forming"),
    ("ascending_triangle", path(ASC_TRIANGLE), "forming"),
    ("descending_triangle", 200 - path(ASC_TRIANGLE), "forming"),
    ("symmetrical_triangle", path([(0, 90), (10, 110), (20, 92), (30, 107), (40, 95), (50, 104), (60, 97), (70, 102),
                                   (78, 99)]), "forming"),
    ("rectangle", path([(0, 90), (10, 110), (20, 95), (30, 110), (40, 95), (50, 110), (60, 95), (70, 110), (78, 102)]),
     "forming"),
    ("rising_wedge", path(RISING_WEDGE), "forming"),
    ("falling_wedge", 200 - path(RISING_WEDGE), "forming"),
    ("bull_flag", path(BULL_FLAG), "confirmed"),
    ("bear_flag", 200 - path(BULL_FLAG), "confirmed"),
]


def test_every_chart_pattern_has_a_shape_here():
    assert sorted(k for k, _, _ in SHAPES) == sorted(lv.CHART_INFO)


@pytest.mark.parametrize("key,closes,status", SHAPES, ids=[s[0] for s in SHAPES])
def test_each_chart_pattern_on_its_textbook_shape(key, closes, status):
    df = bars(closes)
    pats = [p for p in lv.chart_patterns(df) if p["key"] == key]
    assert pats, f"{key} not found; found {found(df)}"
    p = pats[0]
    assert p["status"] == status
    bias = lv.CHART_INFO[key][1]
    up = bias == "bullish" or (bias == "neutral" and p["direction"] == "up")
    if p["target"] is not None:                       # the measured move points the pattern's way
        assert (p["target"] > p["breakout"]) if up else (p["target"] < p["breakout"])
    assert (p["confirmed_on"] is not None) == (status == "confirmed")
    if p["confirmed_on"]:
        assert df.index[len(df) - 1 - p["confirmed_bars_ago"]].date().isoformat() == p["confirmed_on"]


@pytest.mark.parametrize("key,closes,status", SHAPES, ids=[s[0] for s in SHAPES])
def test_chart_pattern_geometry_matches_the_bars(key, closes, status):
    """What the chart draws: every point and line end sits on a real bar (`t` and `ago` agree), a point is that
    bar's exact high or low, and a line's two ends lie on the line the sketch draws."""
    df = bars(closes)
    p = next(p for p in lv.chart_patterns(df) if p["key"] == key)
    last = len(df) - 1
    day = lambda j: df.index[j].date().isoformat()        # noqa: E731
    assert p["end"] == day(last)
    s0 = last - (len(p["series"]) - 1)
    for pt in p["points"]:
        j = last - pt["ago"]
        assert pt["t"] == day(j) and pt["i"] == j - s0
        bar = df.iloc[j]
        assert pt["price"] == pytest.approx(bar["high"] if pt["side"] == "high" else bar["low"], abs=0.01)
    for ln in p["lines"]:
        assert ln["t1"] == day(last - ln["ago1"]) and ln["t2"] == day(last - ln["ago2"])
        assert ln["ago1"] > ln["ago2"] >= 0 and ln["i1"] == last - ln["ago1"] - s0
    highs = [pt for pt in p["points"] if pt["side"] == "high"]
    lows = [pt for pt in p["points"] if pt["side"] == "low"]
    assert highs and lows
    if len(p["lines"]) == 2 and not key.endswith("flag"):      # triangles, wedges, rectangles: upper, lower line
        upper, lower = p["lines"]
        assert upper["t1"] == min(pt["t"] for pt in highs) and lower["t1"] == min(pt["t"] for pt in lows)


def test_no_chart_pattern_in_a_steady_trend_or_short_history():
    assert lv.chart_patterns(bars(np.linspace(100, 160, 200))) == []
    assert lv.chart_patterns(bars(np.linspace(100, 110, 40))) == []
