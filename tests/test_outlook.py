"""Outlook base rates (scanner/outlook.py): features only look back, outcomes start at the next open, the setup
lookup falls back to coarser setups, and the web endpoint keeps the API contract."""
import numpy as np
import pandas as pd
import pytest

from scanner import outlook as ol
from tests.conftest import make_frames


def _random_frames(n_days=420, n_stocks=12, seed=7):
    rng = np.random.default_rng(seed)
    paths = {f"S{i}": list(100 * np.exp(np.cumsum(rng.normal(0.0004, 0.02, n_days)))) for i in range(n_stocks)}
    fr = make_frames(paths)
    fr["volume"] = fr["volume"] * pd.DataFrame(rng.uniform(0.5, 2.5, fr["close"].shape), index=fr["close"].index,
                                               columns=fr["close"].columns)
    return fr


def test_features_never_look_ahead():
    fr = _random_frames()
    member = pd.DataFrame(True, index=fr["close"].index, columns=fr["close"].columns)
    cut = 330
    base = ol.features(fr, member)
    changed = {k: v.copy() for k, v in fr.items()}
    for k in changed:                                   # rewrite everything after the cut
        changed[k].iloc[cut + 1:] = changed[k].iloc[cut + 1:] * 3.0
    after = ol.features(changed, member)
    for k in ol.FEATURES:
        pd.testing.assert_frame_equal(base[k].iloc[:cut + 1], after[k].iloc[:cut + 1], check_dtype=False)


def test_feature_codes():
    fr = make_frames({"UP": list(np.linspace(100, 300, 300)), "FLAT": list(np.linspace(100, 101, 300)),
                      "DOWN": list(np.linspace(300, 100, 300))})
    f = ol.features(fr, None)
    last = fr["close"].index[-1]
    assert f["trend"].at[last, "UP"] == 0                # above both averages
    assert f["trend"].at[last, "DOWN"] == 3              # below both
    assert f["high52"].at[last, "UP"] == 0               # at the high
    assert f["high52"].at[last, "DOWN"] == 3             # far below the 52-week high
    assert f["rsi"].at[last, "UP"] == 2 and f["rsi"].at[last, "DOWN"] == 0
    assert f["mom"].at[last, "UP"] == 2 and f["mom"].at[last, "DOWN"] == 0


def test_outcomes_start_at_the_next_open():
    closes = [100.0] * 30
    opens = [100.0] * 30
    opens[11] = 110.0                                   # the day after the event day 10
    closes[15] = 121.0                                  # 5 days after the event day
    fr = make_frames({"A": closes, "B": [100.0] * 30}, opens={"A": opens, "B": [100.0] * 30})
    member = pd.DataFrame(True, index=fr["close"].index, columns=["A", "B"])
    y = ol.outcomes(fr, member)
    day = fr["close"].index[10]
    assert y["ret_5"].at[day, "A"] == pytest.approx(121 / 110 - 1)
    assert y["ret_5"].at[day, "B"] == pytest.approx(0.0)
    bench = (121 / 110 - 1) / 2
    assert y["excess_5"].at[day, "A"] == pytest.approx(121 / 110 - 1 - bench)


def test_match_falls_back_to_a_coarser_setup():
    study = {"min_events": 10, "min_months": 1, "groups": {
        ol.key_of(ol.LEVELS[0], dict(trend=0, mom=2, rsi=1, high52=0, vol=2)): {"n": 3, "months": 1},
        ol.key_of(ol.LEVELS[1], dict(trend=0, mom=2, rsi=1, high52=0)): {"n": 50, "months": 5},
    }}
    m = ol.match(study, dict(trend=0, mom=2, rsi=1, high52=0, vol=2))
    assert m["level"] == list(ol.LEVELS[1]) and m["dropped"] == ["vol"]
    assert ol.match(study, dict(trend=3, mom=0, rsi=0, high52=3, vol=0)) is None


def test_summary_base_excess_is_zero_on_average():
    fr = _random_frames(n_days=400, n_stocks=20)
    member = pd.DataFrame(True, index=fr["close"].index, columns=fr["close"].columns)
    ev = ol.events(fr, member)
    rep = ol.summarise(ev, "2024-01-01", "2025-06-01")
    assert rep["base"]["20"]["excess_pct"] == pytest.approx(0.0, abs=0.05)
    assert rep["events"] == len(ev) and rep["groups"]


def test_verdict_needs_t_beyond_luck():
    assert ol.verdict({"20": {"t": 2.5, "excess_pct": 1.0}}, 20) == "better"
    assert ol.verdict({"20": {"t": -3.0, "excess_pct": -1.0}}, 20) == "worse"
    assert ol.verdict({"20": {"t": 1.2, "excess_pct": 2.0}}, 20) == "same"
    assert ol.verdict({"20": None}, 20) == "unknown"
