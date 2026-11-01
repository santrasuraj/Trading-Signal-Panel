"""Price action for one stock or index (scanner/levels.py): pivots, support / resistance, trend, candle patterns and
today's VWAP / opening range / volume profile. Files only."""
from __future__ import annotations

from fastapi import APIRouter

from ..models.levels import LevelsResponse
from ..services import levels_svc

router = APIRouter(prefix="/api/levels", tags=["levels"])


@router.get("/{symbol}", response_model=LevelsResponse)
def levels(symbol: str):
    return levels_svc.levels_for(symbol)
