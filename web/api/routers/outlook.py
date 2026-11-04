"""Outlook for one symbol: setup, what happened next in similar setups, ranges, levels, signals, the options verdict
and big-money disclosures. GET is files only - base rates measured on the past, never a forecast. POST refresh
fetches the symbol's NSE disclosures (pledges, acquisition filings, F&O ban list) in the background."""
from __future__ import annotations

from fastapi import APIRouter

from ..models.outlook import BigMoneyRefreshAccepted, OutlookResponse
from ..services import outlook_svc

router = APIRouter(prefix="/api/outlook", tags=["outlook"])


@router.get("/{symbol}", response_model=OutlookResponse)
def outlook(symbol: str):
    return outlook_svc.outlook_for(symbol)


@router.post("/{symbol}/big-money/refresh", response_model=BigMoneyRefreshAccepted, status_code=202)
def refresh_big_money(symbol: str):
    return outlook_svc.start_big_money(symbol)
