"""F&O positioning: participant-wise open interest (FII, DII, Pro, Client) and the day's futures build-ups
(scanner/fno.py). GET handlers read only data/fno/; POST /refresh fetches NSE's end-of-day files in a background
thread of this process."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Query

from ..models.fno import (FnoFuturesResponse, FnoLiveAccepted, FnoLiveResponse, FnoPositionsResponse,
                          FnoRefreshAccepted, FnoStatus)
from ..services import fno_svc as svc

router = APIRouter(prefix="/api/fno", tags=["fno"])


@router.get("/status", response_model=FnoStatus)
def status():
    return svc.status()


@router.get("/positions", response_model=FnoPositionsResponse)
def positions(days: int = Query(20, ge=1, le=250)):
    return svc.positions(days)


@router.get("/futures", response_model=FnoFuturesResponse)
def futures(date: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
            kind: Literal["all", "stock", "index"] = "all",
            buildup: Literal["all", "long_buildup", "short_buildup", "short_covering", "long_unwinding"] = "all",
            sort: Literal["oi_chg", "chg", "value", "pcr"] = "oi_chg", limit: int = Query(300, ge=1, le=1000)):
    return svc.futures(date, kind, buildup, sort, limit)


@router.post("/refresh", response_model=FnoRefreshAccepted, status_code=202)
def refresh(days: int = Query(30, ge=1, le=250)):
    return {"accepted": True, "run": svc.start_refresh(days)}


@router.get("/live", response_model=FnoLiveResponse)
def live(kind: Literal["all", "stock", "index"] = "all",
         buildup: Literal["all", "long_buildup", "short_buildup", "short_covering", "long_unwinding"] = "all",
         sort: Literal["oi_chg", "chg", "oi", "volume"] = "oi_chg", limit: int = Query(300, ge=1, le=1000)):
    """Files only: the last live snapshot (NSE OI spurts + prices) written by POST /live/refresh."""
    return svc.live(kind, buildup, sort, limit)


@router.post("/live/refresh", response_model=FnoLiveAccepted, status_code=202)
def live_refresh():
    """Fetch NSE's live open interest and the prices now (at most every 90 s)."""
    return svc.start_live()
