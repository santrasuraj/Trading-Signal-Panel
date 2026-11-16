"""One answer per stock (BUY / SELL / HOLD / NO EDGE) and today's actions: services/action_svc.py."""
from __future__ import annotations

from fastapi import APIRouter, Path

from ..models import ActionCard, TodayResponse
from ..services import action_svc

router = APIRouter(prefix="/api", tags=["action"])


@router.get("/action/{symbol}", response_model=ActionCard)
def action(symbol: str = Path(..., pattern=r"^[A-Za-z0-9][A-Za-z0-9&_.-]{0,24}$")):
    """The one tested answer for this stock, with the strategy, its backtest and live record, and risk chips."""
    return action_svc.one(symbol)


@router.get("/today", response_model=TodayResponse)
def today():
    """Every tested BUY and SELL for the next open (your holdings first), and every HOLD."""
    return action_svc.today()
