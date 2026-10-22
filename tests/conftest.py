import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def make_frames(closes: dict[str, list[float]], start="2024-01-01", opens=None, volume=1_000_000):
    """Wide OHLCV frames from close paths (open = previous close unless given)."""
    n = len(next(iter(closes.values())))
    idx = pd.bdate_range(start, periods=n, name="date")
    close = pd.DataFrame(closes, index=idx, dtype=float)
    open_ = pd.DataFrame(opens, index=idx, dtype=float) if opens else close.shift(1).fillna(close)
    return {
        "open": open_, "close": close,
        "high": np.maximum(open_, close) * 1.005, "low": np.minimum(open_, close) * 0.995,
        "volume": pd.DataFrame(volume, index=idx, columns=close.columns, dtype=float),
    }


@pytest.fixture
def frames_factory():
    return make_frames
