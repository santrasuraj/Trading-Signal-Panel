"""Company page (services/company_svc.py): ten-plus years of financials, peers, segments - from NSE's filings."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Query

from ..errors import SafeJSONResponse
from ..services import company_svc, documents_svc, investors_svc, ivrank_svc

router = APIRouter(prefix="/api", tags=["company"])


@router.get("/company/{symbol}", response_model=None, response_class=SafeJSONResponse)
def company(symbol: str, basis: Literal["consolidated", "standalone"] | None = Query(None),
            refresh: bool = Query(False, description="fetch from NSE now, even when stored recently")):
    """P&L, balance sheet, cash flow, ratios, growth, segments, quarters and industry peers."""
    return company_svc.view(symbol, basis, refresh)


@router.get("/company/{symbol}/documents", response_model=None, response_class=SafeJSONResponse)
def documents(symbol: str, refresh: bool = Query(False)):
    """The company's filings timeline: call transcripts, presentations, results, annual reports... with NSE's links."""
    return documents_svc.documents(symbol, refresh)


@router.get("/investors", response_model=None, response_class=SafeJSONResponse)
def investors(category: str = Query("famous", max_length=12), q: str = Query("", max_length=60)):
    """Big investors' portfolios from the shareholding filings (1%+ holders): famous, mf, fii, insurance, pension, ..."""
    return investors_svc.investors(category, q)


@router.get("/investors/{key}", response_model=None, response_class=SafeJSONResponse)
def investor(key: str):
    """One investor's holdings, each with the change since the previous quarter."""
    return investors_svc.investor(key)


@router.get("/iv-rank", response_model=None, response_class=SafeJSONResponse)
def iv_rank():
    """Every F&O underlying's ~30-day ATM implied volatility with its IV rank and IV percentile over the past year."""
    return ivrank_svc.table()


@router.get("/iv-rank/{symbol}", response_model=None, response_class=SafeJSONResponse)
def iv_rank_one(symbol: str):
    """One underlying's IV, rank, percentile and its past year of daily IV."""
    return ivrank_svc.one(symbol)


@router.post("/iv-rank/backfill", response_model=None, response_class=SafeJSONResponse, status_code=202)
def iv_rank_backfill():
    """Fetch a year of NSE's daily F&O files in the background (~5 minutes) for a fair rank."""
    return ivrank_svc.start_backfill()
