"""Smart money: which stocks big investors are buying, selling or leaving (docs/smart_money_spec.md).

GET handlers read only data/smart_money/ (never NSE). POST /refresh is the one network job; it runs
scanner.smart_money.refresh in a background thread of this process."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Query

from ..models.smart_money import (SmCategoryFilter, SmDealsResponse, SmFlowsResponse, SmHoldingsResponse,
                                  SmInsiderResponse, SmLiveResponse, SmOverview, SmRefreshAccepted, SmRefreshRequest,
                                  SmStatus, SmStockResponse)
from ..services import footprints_svc, smart_money_svc as svc

router = APIRouter(prefix="/api/smart-money", tags=["smart-money"])


@router.get("/status", response_model=SmStatus)
def status():
    return svc.status()


@router.get("/live", response_model=SmLiveResponse)
def live():
    """Big money live: today's unusual volume, large trades and block deals, with what the disclosures say."""
    return footprints_svc.payload()


@router.get("/overview", response_model=SmOverview)
def overview(days: int = Query(30, ge=1, le=365)):
    return svc.overview(days)


@router.get("/deals", response_model=SmDealsResponse)
def deals(days: int = Query(1, ge=1, le=365), side: Literal["all", "buy", "sell"] = "all",
          kind: Literal["all", "bulk", "block"] = "all", category: SmCategoryFilter = "all",
          symbol: str | None = None, intraday: bool = False, page: int = Query(1, ge=1),
          page_size: int = Query(100, ge=1, le=500)):
    return svc.deals(days, side, kind, category, symbol, intraday, page, page_size)


@router.get("/insider", response_model=SmInsiderResponse)
def insider(days: int = Query(30, ge=1, le=365), side: Literal["all", "buy", "sell"] = "all",
            category: Literal["all", "promoter", "insider"] = "all", mode: Literal["market", "all"] = "market",
            symbol: str | None = None, page: int = Query(1, ge=1), page_size: int = Query(100, ge=1, le=500)):
    return svc.insider(days, side, category, mode, symbol, page, page_size)


@router.get("/holdings", response_model=SmHoldingsResponse)
def holdings(view: Literal["accumulating", "exiting", "all"] = "accumulating", days: int = Query(30, ge=1, le=365),
             category: SmCategoryFilter = "all", symbol: str | None = None):
    return svc.holdings(view, days, category, symbol)


@router.get("/flows", response_model=SmFlowsResponse)
def flows(days: int = Query(30, ge=1, le=3650)):
    return svc.flows(days)


@router.get("/stock/{symbol}", response_model=SmStockResponse)
def stock(symbol: str, days: int = Query(365, ge=1, le=730)):
    return svc.stock(symbol, days)


@router.post("/refresh", response_model=SmRefreshAccepted, status_code=202)
def refresh(body: SmRefreshRequest | None = None):
    return {"accepted": True, "run": svc.start_refresh(body.days if body else 365)}
