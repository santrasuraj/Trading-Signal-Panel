"""Option chains: open interest, PCR, max pain, implied volatility and OI levels per strike (scanner/options.py).

GET handlers read only data/options/ (never NSE). POST /refresh is the one network job; it runs
scanner.options.refresh in a background thread of this process."""
from __future__ import annotations

from fastapi import APIRouter, Query

from ..models.options import (OptBigTradesResponse, OptChainResponse, OptHistoryResponse, OptRefreshAccepted,
                              OptRefreshRequest, OptResearchResponse, OptStatus)
from ..services import options_svc as svc

router = APIRouter(prefix="/api/options", tags=["options"])


@router.get("/status", response_model=OptStatus)
def status():
    return svc.status()


@router.get("/chain/{symbol}", response_model=OptChainResponse)
def chain(symbol: str, expiry: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
          window: int = Query(15, ge=5, le=180)):
    """One stored chain (the newest, or `expiry`), analysed; `window`: minutes over which OI change is measured."""
    return svc.chain(symbol, expiry, window)


@router.get("/history/{symbol}", response_model=OptHistoryResponse)
def history(symbol: str, expiry: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$")):
    """The chain's day so far: spot, max pain, PCR, ATM IV, straddle and the top OI levels per stored chain."""
    return svc.history(symbol, expiry)


@router.get("/bigtrades", response_model=OptBigTradesResponse)
def bigtrades():
    """Large index futures / options trades today, from the FYERS live feed (scanner/fno_live.py)."""
    return svc.bigtrades()


@router.get("/research", response_model=OptResearchResponse)
def research():
    """Do PCR, max pain and the straddle's expected move hold up on the stored days? (scanner/options_research.py)"""
    return svc.research()


@router.post("/refresh", response_model=OptRefreshAccepted, status_code=202)
def refresh(body: OptRefreshRequest | None = None):
    return {"accepted": True, "run": svc.start_refresh(body.symbols if body else None)}
