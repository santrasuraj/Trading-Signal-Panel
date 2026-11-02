"""Price action for one stock or index (scanner/levels.py): pivots, support / resistance, trend, candle patterns and
today's VWAP / opening range / volume profile. Files only."""
from __future__ import annotations

from fastapi import APIRouter

from ..models.levels import LevelsResponse, PatternEvidenceResponse
from ..services import levels_svc

router = APIRouter(prefix="/api/levels", tags=["levels"])


@router.get("/evidence", response_model=PatternEvidenceResponse)
def evidence():
    """How every candle and chart pattern did on 8 years of the point-in-time top 500 (scanner/pattern_study.py)."""
    return levels_svc.evidence_table()


@router.get("/{symbol}", response_model=LevelsResponse)
def levels(symbol: str):
    return levels_svc.levels_for(symbol)
