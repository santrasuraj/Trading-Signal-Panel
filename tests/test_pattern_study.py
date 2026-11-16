"""Pattern evidence study (scanner/pattern_study.py): events dated without look-ahead, excess returns against the
average universe stock over the same open-to-close stretch, monthly-clustered statistics and verdicts."""
import numpy as np
import pandas as pd
import pytest

from scanner import levels as lv
from scanner import pattern_study as ps


def bars(closes):
    c = np.asarray(closes, dtype=float)
    o = np.r_[c[0], c[:-1]]
    idx = pd.bdate_range("2024-01-01", periods=len(c))
    return pd.DataFrame({"open": o, "high": np.maximum(o, c) * 1.01, "low": np.minimum(o, c) * 0.99, "close": c,
                         "volume": 1000.0}, index=idx)


def path(points):
    xs, ys = zip(*points)
    return np.interp(np.arange(xs[-1] + 1), xs, ys)


def test_chart_events_have_no_look_ahead():
    df = bars(path([(0, 80), (60, 82), (90, 100), (105, 88), (120, 100), (140, 84), (170, 86)]))
    member = np.ones(len(df), dtype=bool)
    ev = ps.chart_events(df, member, step=10)
    assert any(k == "double_top" and side == -1 for _, k, side in ev)
    for e, key, _ in ev:
        now = [p for p in lv.chart_patterns(df.iloc[:e + 1]) if p["key"] == key and p["status"] == "confirmed"]
        assert now, (e, key)                                                  # visible with data up to e ...
        before = [p for p in lv.chart_patterns(df.iloc[:e]) if p["key"] == key and p["status"] == "confirmed"
                  and p["start"] == now[0]["start"]]
        assert not before, (e, key)                                           # ... and not a bar earlier
    assert ps.chart_events(df, np.zeros(len(df), dtype=bool)) == []            # never a member: nothing sampled


def test_candle_events_match_the_detector():
    df = bars(100 + np.sin(np.arange(200) / 3) * 5)
    ev = ps.candle_events(df)
    assert ev and all(0 <= b < len(df) and side in (-1, 0, 1) for b, _, side in ev)
    last = {(len(df) - 1 - p["bars_ago"], p["key"]) for p in lv.patterns(df, last=3)}
    assert last <= {(b, k) for b, k, _ in ev}


def test_forward_excess_against_the_average_stock():
    idx = pd.bdate_range("2024-01-01", periods=30)
    close = pd.DataFrame({"A": np.linspace(100, 129, 30), "B": 100.0, "C": 100.0}, index=idx)
    frames = {"open": close.shift(1).fillna(100.0), "close": close}
    uni = pd.DataFrame(True, index=idx, columns=close.columns)
    ev = pd.DataFrame({"symbol": ["A"], "bar": [5], "date": [idx[5]], "key": ["x"], "family": ["candle"], "side": [1]})
    out = ps.forward_excess(frames, uni, ev)
    entry_open, exit_close = frames["open"].iat[6, 0], close.iat[6 + 4, 0]   # buy the next open, 5 bars held
    assert out["ret_5"].iat[0] == pytest.approx(exit_close / entry_open - 1)
    assert out["bench_5"].iat[0] == pytest.approx((exit_close / entry_open - 1) / 3)    # A, B and C equally
    assert out["excess_5"].iat[0] == pytest.approx(out["ret_5"].iat[0] - out["bench_5"].iat[0])
    late = ev.assign(bar=[29])
    assert np.isnan(ps.forward_excess(frames, uni, late)["ret_5"].iat[0])     # no future yet: no return


def events(excess, side, months):
    dates = [pd.Timestamp("2018-01-15") + pd.DateOffset(months=m) for m in months]
    return pd.DataFrame({"date": dates, "side": side, "excess_10": excess})


def test_stats_and_verdicts():
    rng = np.random.default_rng(0)
    m = np.repeat(np.arange(36), 5)                                           # 180 events over 36 months
    good = events(0.02 + rng.normal(0, 0.01, len(m)), 1, m)
    s = ps.stats(good, 10)
    assert s["n"] == 180 and s["months"] == 36 and s["excess_pct"] == pytest.approx(2.0, abs=0.3)
    assert s["after_cost_pct"] == pytest.approx(s["excess_pct"] - ps.COST_PCT, abs=0.01)
    assert ps.verdict(s, True) == "edge"
    bear = events(-0.02 + rng.normal(0, 0.01, len(m)), -1, m)                 # bearish pattern, stock lagged: works
    assert ps.verdict(ps.stats(bear, 10), True) == "edge"
    noise = events(rng.normal(0, 0.03, len(m)), 1, m)
    assert ps.verdict(ps.stats(noise, 10), True) in ("no_edge", "opposite")
    assert ps.verdict(ps.stats(good.iloc[:20], 10), True) == "too_few"
    assert ps.verdict(s, False) == "no_direction"
    small = events(0.003 + rng.normal(0, 0.001, len(m)), 1, m)                # real but under the costs
    assert ps.verdict(ps.stats(small, 10), True) == "edge_before_costs"
