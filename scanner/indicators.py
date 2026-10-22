"""Technical indicators computed on daily OHLCV data."""
from __future__ import annotations

import numpy as np
import pandas as pd


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    c, h, l, v = df["close"], df["high"], df["low"], df["volume"]

    df["chg_pct"] = c.pct_change() * 100
    for n in (20, 50, 200):
        df[f"sma{n}"] = c.rolling(n, min_periods=n).mean()
    df["ema9"] = c.ewm(span=9, adjust=False).mean()
    df["ema21"] = c.ewm(span=21, adjust=False).mean()

    # RSI (Wilder's smoothing, 14 days)
    delta = c.diff()
    avg_gain = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    avg_loss = (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    df["rsi"] = (100 - 100 / (1 + rs)).where(avg_loss != 0, 100.0)

    # MACD (12, 26, 9)
    macd = c.ewm(span=12, adjust=False).mean() - c.ewm(span=26, adjust=False).mean()
    df["macd"] = macd
    df["macd_signal"] = macd.ewm(span=9, adjust=False).mean()

    # Volume vs the previous 20 days' average
    df["vol_avg20"] = v.rolling(20, min_periods=20).mean().shift(1)
    df["vol_ratio"] = v / df["vol_avg20"].replace(0, np.nan)

    # 52-week range, excluding today so "breakout" means beating the previous high
    df["high_52w"] = h.rolling(252, min_periods=120).max().shift(1)
    df["low_52w"] = l.rolling(252, min_periods=120).min().shift(1)

    prev_c = c.shift(1)
    tr = pd.concat([h - l, (h - prev_c).abs(), (l - prev_c).abs()], axis=1).max(axis=1)
    df["atr14"] = tr.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    return df
