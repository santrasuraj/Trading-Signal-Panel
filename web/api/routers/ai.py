"""AI analyst and option-chain forecasts: Claude reads this platform's own data (the key stays in .env on this PC)."""
from __future__ import annotations

from fastapi import APIRouter, Query

from ..models.ai import AiAnalysis, AiAnalyzeRequest, AiForecast, AiForecastReport, AiForecastRequest, AiStatus
from ..services import ai_svc, forecast_svc

router = APIRouter(prefix="/api/ai", tags=["ai"])


@router.get("/status", response_model=AiStatus)
def status():
    """Files only: whether a key is set (never the key itself)."""
    return ai_svc.status()


@router.post("/analyze", response_model=AiAnalysis)
def analyze(body: AiAnalyzeRequest):
    return ai_svc.analyze(body.symbol, body.question)


@router.get("/forecasts", response_model=AiForecastReport)
def forecasts(symbol: str | None = Query(None, min_length=1, max_length=20, pattern=r"^[A-Za-z0-9&-]+$"),
              limit: int = Query(40, ge=1, le=500)):
    """Files only: Claude's option-chain forecasts scored against NSE's official closes, and their record."""
    return forecast_svc.report(symbol, limit)


@router.post("/forecast", response_model=AiForecast)
def forecast(body: AiForecastRequest):
    """One forecast now from the stored chain (costs roughly Rs 8-13 on the Anthropic account)."""
    return forecast_svc.forecast_now(body.symbol)
