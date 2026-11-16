"""Seasonality and the market heatmap (web/api/services/market_views.py) on synthetic data."""
import numpy as np
import pandas as pd
import pytest

from web.api.services import data, market_views as mv, quotes_svc


def test_seasonality_averages_each_month_and_marks_only_strong_ones(monkeypatch):
    idx = pd.bdate_range("2014-01-01", "2025-12-31")
    rng = np.random.default_rng(1)
    r = rng.normal(0, 0.004, len(idx)) + np.where(idx.month == 4, 0.004, 0.0)   # April is strongly up every year
    close = pd.DataFrame({"ABC": 100 * np.cumprod(1 + r), "NIFTY50": 100 * np.cumprod(1 + rng.normal(0, 0.003, len(idx)))}, index=idx)
    monkeypatch.setattr(data, "store", lambda: {"close": close})
    s = mv.seasonality("ABC")
    apr = next(m for m in s["months"] if m["name"] == "Apr")
    assert apr["n"] == 12 and apr["avg"] > 5 and apr["up_pct"] == 100 and apr["pattern"]
    assert sum(m["pattern"] for m in s["months"]) <= 3                     # the random months stay noise
    assert apr["vs_nifty"]["avg"] > 4 and len(s["years"]) == 12


def test_heatmap_groups_by_industry_and_uses_live_moves(monkeypatch):
    sc = pd.DataFrame({"symbol": ["A", "B", "C"], "company": ["a", "b", "c"], "industry": ["IT", "IT", None],
                       "price": [10.0, 20.0, 30.0], "turnover_cr": [100.0, 50.0, 10.0], "change_pct": [1.0, -2.0, 0.5],
                       "ret_1w": [1, 2, 3], "ret_1m": [1, 2, 3], "ret_3m": [1, 2, 3], "ret_12m": [1, 2, 3], "scan_id": "s"})
    monkeypatch.setattr(data, "screener", lambda: sc)
    monkeypatch.setattr(quotes_svc, "quotes", lambda syms, allow_network=True: {
        "session": "open", "quotes": [{"symbol": "A", "price": 11.0, "change_pct": 3.0, "source": "live"}]})
    h = mv.heatmap("1d")
    it = next(g for g in h["groups"] if g["industry"] == "IT")
    assert [s["symbol"] for s in it["stocks"]] == ["A", "B"] and it["stocks"][0]["move"] == 3.0 and h["live"] == 1
    assert it["move"] == pytest.approx((3.0 * 100 - 2.0 * 50) / 150, abs=0.01)   # weighted by traded value
    assert any(g["industry"] == "Other" for g in h["groups"])
    assert mv.heatmap("1m")["live"] == 0
