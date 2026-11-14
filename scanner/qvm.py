"""Our own quality / value / momentum score (0-100): one transparent number per stock, in the spirit of Trendlyne's
DVM scores but with a formula you can read here, and backtested by the same engine as every other strategy
("Quality-value-momentum score" in scanner/strategies.py: the 20 best-scored liquid stocks, reviewed quarterly).

  Quality  = the average percentile of ROE (higher is better) and debt / equity (lower is better; banks: ROE only)
  Value    = the average percentile of earnings yield (profit / market cap) and book yield (equity / market cap)
  Momentum = the percentile of the momentum strategy's score (6- and 12-month returns over their volatility)
  Score    = 100 x the average of the three, ranked among the stocks that have all three that day

Fundamentals come from ten years of NSE filings (scanner/financials.py), each from the day it was filed, so the
backtest never sees a number before it was public. Stocks whose filings are not stored get no score. The academic
evidence for each part (quality, value and momentum premia, also in Indian data) is real but weaker after costs
than on paper - the backtest shows what is left.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _pct(x: pd.DataFrame | pd.Series, mask=None, axis: int = 1):
    """Percentile rank 0..1 (1 = best = highest) within each row (dates) or the series, NaN stays NaN."""
    if mask is not None:
        x = x.where(mask)
    return x.rank(axis=axis, pct=True) if isinstance(x, pd.DataFrame) else x.rank(pct=True)


def parts(close: pd.DataFrame, momentum: pd.DataFrame, fin: dict, mask: pd.DataFrame | None = None) -> dict:
    """Point-in-time frames (dates x symbols) of quality, value, momentum and the score, all 0..100.
    `fin`: financials.frames(...) (roe, de, profit, equity, shares, bank)."""
    roe, de = fin["roe"], fin["de"]
    mcap = close * fin["shares"]
    ey = fin["profit"] / mcap.where(mcap > 0)
    by = fin["equity"] / mcap.where(mcap > 0)
    have = roe.notna() & ey.notna() & by.notna() & momentum.notna() & (fin["shares"] > 0)
    if mask is not None:
        have &= mask
    q_roe = _pct(roe, have)
    q_de = _pct(-de, have & de.notna() & (fin["bank"] != 1))
    quality = (q_roe + q_de.fillna(q_roe)) / 2              # banks (no debt / equity): ROE alone
    value = (_pct(ey, have) + _pct(by, have)) / 2
    mom = _pct(momentum, have)
    raw = (quality + value + mom) / 3
    score = _pct(raw, have)
    return {"quality": quality * 100, "value": value * 100, "momentum": mom * 100, "score": score * 100}


def current(rows: pd.DataFrame) -> pd.DataFrame:
    """Today's score for a table of stocks with columns symbol, roe, de, bank, earnings_yield, book_yield,
    momentum_score. Returns symbol, quality, value, momentum, score (0..100), NaN where a part is missing."""
    r = rows.copy()
    have = r[["roe", "earnings_yield", "book_yield", "momentum_score"]].notna().all(axis=1)
    q_roe = r["roe"].where(have).rank(pct=True)
    q_de = (-r["de"]).where(have & r["de"].notna() & ~r["bank"].astype(bool)).rank(pct=True)
    quality = (q_roe + q_de.fillna(q_roe)) / 2
    value = (r["earnings_yield"].where(have).rank(pct=True) + r["book_yield"].where(have).rank(pct=True)) / 2
    mom = r["momentum_score"].where(have).rank(pct=True)
    raw = (quality + value + mom) / 3
    out = pd.DataFrame({"symbol": r["symbol"], "quality": quality * 100, "value": value * 100, "momentum": mom * 100,
                        "score": raw.rank(pct=True) * 100})
    return out.round(1).replace({np.nan: None})
