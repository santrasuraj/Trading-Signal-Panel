"""AI analyst: Claude explains one symbol from this platform's own data (the key stays in .env on this PC)."""
from __future__ import annotations

from fastapi import APIRouter

from ..models.ai import AiAnalysis, AiAnalyzeRequest, AiStatus
from ..services import ai_svc

router = APIRouter(prefix="/api/ai", tags=["ai"])


@router.get("/status", response_model=AiStatus)
def status():
    """Files only: whether a key is set (never the key itself)."""
    return ai_svc.status()


@router.post("/analyze", response_model=AiAnalysis)
def analyze(body: AiAnalyzeRequest):
    return ai_svc.analyze(body.symbol, body.question)
