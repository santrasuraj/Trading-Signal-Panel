"""Compiled intraday bar loops (scanner/intraday/fast.py): the Numba versions must give exactly what the plain Python
versions give - same slots, same prices - on random sessions with gaps, and VWAP must equal the numpy formula it
replaced. The strategies themselves were checked trade-for-trade on 30 stored sessions when this was written."""
import math

import numpy as np
import pytest

from scanner.intraday import fast
from scanner.intraday.engine import SLOTS

numba = pytest.importorskip("numba")


def _session(rng, gaps=True):
    px = 100 * np.exp(np.cumsum(rng.normal(0, 0.004, SLOTS)))
    o = np.r_[px[0], px[:-1]]
    h = np.maximum(o, px) * (1 + rng.uniform(0, 0.003, SLOTS))
    lo = np.minimum(o, px) * (1 - rng.uniform(0, 0.003, SLOTS))
    v = rng.uniform(1e3, 1e5, SLOTS)
    if gaps:
        for i in rng.choice(SLOTS, size=rng.integers(0, 8), replace=False):
            o[i] = h[i] = lo[i] = px[i] = v[i] = np.nan
    return o, h, lo, px.copy(), v


def _same(a, b):
    if isinstance(a, tuple):
        return len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b))
    if isinstance(a, np.ndarray):
        return np.array_equal(a, b, equal_nan=True)
    if isinstance(a, float) and math.isnan(a):
        return isinstance(b, float) and math.isnan(b)
    return a == b


@pytest.fixture(scope="module")
def compiled():
    assert fast.enable()
    return {name: getattr(fast, name) for name in fast._PY}


def test_vwap_equals_the_numpy_formula_it_replaced():
    rng = np.random.default_rng(1)
    for _ in range(200):
        o, h, lo, c, v = _session(rng)
        tp = (h + lo + c) / 3
        vv = np.nan_to_num(v)
        vv[0] = 0.0
        pv, cv = np.nancumsum(np.nan_to_num(tp) * vv), np.cumsum(vv)
        with np.errstate(invalid="ignore", divide="ignore"):
            ref = np.where(cv > 0, pv / cv, np.nan)
        ref = np.where(np.isnan(ref), tp, ref)
        assert np.array_equal(fast._PY["vwap"](h, lo, c, v), ref, equal_nan=True)


def test_compiled_kernels_match_python_exactly_on_random_sessions(compiled):
    rng = np.random.default_rng(7)
    py = fast._PY
    for _ in range(400):
        o, h, lo, c, v = _session(rng)
        side = int(rng.choice([-1, 1]))
        entry = int(rng.integers(0, 60))
        ref_px = c[entry] if not math.isnan(c[entry]) else 100.0
        stop = float(ref_px * (1 - side * rng.uniform(0.002, 0.02))) if rng.random() < 0.8 else math.nan
        target = float(ref_px * (1 + side * rng.uniform(0.002, 0.03))) if rng.random() < 0.7 else math.nan
        last = int(rng.integers(entry, 73))
        vw = py["vwap"](h, lo, c, v)
        cases = [
            ("first_valid", (o, int(rng.integers(0, 75)), int(rng.integers(0, 90)))),
            ("vwap", (h, lo, c, v)),
            ("walk_exit", (o, h, lo, c, side, entry, stop, target, last, entry + int(rng.integers(0, 2)), SLOTS)),
            ("stop_entry", (o, h, lo, side, float(ref_px * (1 + side * 0.004)), 3, 69)),
            ("sweep_setup", (o, h, lo, c, side, float(np.nanmin(lo[:3]) if side > 0 else np.nanmax(h[:3])), 3, 60,
                             0.0005, 6, 12, 69)),
            ("orb_retest_setup", (o, h, lo, c, vw, float(np.nanmax(h[:3])), float(np.nanmin(lo[:3])), 0.0005, 12, 3,
                                  60, 69)),
        ]
        for name, args in cases:
            a, b = py[name](*args), compiled[name](*args)
            assert _same(tuple(a) if isinstance(a, tuple) else a, tuple(b) if isinstance(b, tuple) else b), name


def test_walk_exit_copies_pythons_min_max_on_a_gap_through_the_stop(compiled):
    o = np.full(SLOTS, 100.0)
    h, lo, c = o * 1.001, o * 0.999, o.copy()
    o[6], lo[6] = 97.0, 96.5                                     # gaps below the 98 stop: filled at the open
    for f in (fast._PY["walk_exit"], compiled["walk_exit"]):
        assert tuple(f(o, h, lo, c, 1, 5, 98.0, 102.0, 69, 5, SLOTS)) == (6, 97.0, fast.STOP)
        assert tuple(f(o, h, lo, c, 1, 5, math.nan, math.nan, 69, 5, SLOTS)) == (69, 100.0, fast.END)


def test_warm_up_compiles_every_kernel():
    assert fast.warm_up() >= 0 and fast.ENABLED
    assert all(hasattr(getattr(fast, n), "py_func") for n in fast._PY)      # numba dispatchers now
