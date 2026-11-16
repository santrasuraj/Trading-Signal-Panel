"""Market replay (services/replay_svc.py): past sessions bar by bar for practice, and your practice record."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Path, Query
from pydantic import Field

from ..errors import SafeJSONResponse
from ..models import Model
from ..services import replay_svc

router = APIRouter(prefix="/api/replay", tags=["replay"])

Tf = Literal["5m", "15m", "1d"]
DATE = r"^\d{4}-\d{2}-\d{2}$"


class ReplayTrade(Model):
    side: Literal["LONG", "SHORT"]
    qty: int = Field(..., ge=1, le=10_000_000)
    entry_i: int = Field(..., ge=0)
    exit_i: int = Field(..., ge=0)
    entry: float = Field(..., gt=0)
    exit: float = Field(..., gt=0)
    stop: float | None = Field(None, gt=0)
    target: float | None = Field(None, gt=0)
    reason: Literal["manual", "stop", "target", "square_off", "end"] = "manual"


class ReplayResult(Model):
    symbol: str = Field(..., max_length=25)
    tf: Tf
    date: str = Field(..., pattern=DATE)
    blind: bool = False
    last_i: int = Field(0, ge=0)
    trades: list[ReplayTrade] = Field(default_factory=list, max_length=500)


@router.get("/info", response_model=None, response_class=SafeJSONResponse)
def info(symbol: str | None = Query(None, max_length=25)):
    """What can be replayed: intraday symbols, one symbol's sessions and its daily range."""
    return replay_svc.info(symbol)


@router.get("/random", response_model=None, response_class=SafeJSONResponse)
def random(tf: Tf = "5m"):
    """A random stock and day (blind mode: the page hides both until the end)."""
    return replay_svc.random_pick(tf)


@router.get("/bars/{symbol}", response_model=None, response_class=SafeJSONResponse)
def bars(symbol: str = Path(..., max_length=25), tf: Tf = "5m", date: str | None = Query(None, pattern=DATE)):
    """Context bars, then the bars to replay (the page reveals them one at a time)."""
    return replay_svc.load(symbol, tf, date or replay_svc.default_day(tf, symbol))


@router.get("/results", response_model=None, response_class=SafeJSONResponse)
def results(limit: int = Query(30, ge=1, le=200)):
    """Your practice record: sessions, win rate, expectancy, exits by reason."""
    return replay_svc.history(limit)


@router.post("/results", response_model=None, response_class=SafeJSONResponse)
def save(body: ReplayResult):
    """Save a finished replay; the P&L is recomputed from the bars and the cost model."""
    return replay_svc.save_result(body.model_dump())
