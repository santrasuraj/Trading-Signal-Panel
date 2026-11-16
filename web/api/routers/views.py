"""Seasonality and the market heatmap (services/market_views.py)."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Path

from ..errors import SafeJSONResponse
from ..services import market_views, orderflow_svc

router = APIRouter(prefix="/api", tags=["views"])


@router.get("/seasonality/{symbol}", response_model=None, response_class=SafeJSONResponse)
def seasonality(symbol: str = Path(..., max_length=25)):
    """Each calendar month's average return over the years in the store, with how often it was up and a t-statistic."""
    return market_views.seasonality(symbol)


@router.get("/orderflow/{symbol}", response_model=None, response_class=SafeJSONResponse)
def orderflow(symbol: str = Path(..., max_length=25), tf: Literal["1m", "5m", "15m"] = "5m"):
    """Today's estimated order flow: buy / sell volume and delta per bar, cumulative delta, volume profile."""
    return orderflow_svc.flow(symbol, tf)


@router.get("/heatmap", response_model=None, response_class=SafeJSONResponse)
def heatmap(period: Literal["1d", "1w", "1m", "3m", "12m"] = "1d"):
    """Today's universe grouped by industry, sized by traded value, coloured by the period's move (live today)."""
    return market_views.heatmap(period)
