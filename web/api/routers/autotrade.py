"""High-speed auto-trader on the practice account (services/autotrade_svc.py): nothing is ever sent to FYERS."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse, Response
from pydantic import Field

from ..errors import SafeJSONResponse
from ..models import Model
from ..services import autotrade_svc, latency_svc

router = APIRouter(prefix="/api", tags=["autotrade"])


class AutoSettings(Model):
    on: bool | None = None                        # the engine trades intraday signals every second while true
    mode: Literal["all", "proven"] | None = None  # proven = only strategies whose backtest beat costs
    intraday: bool | None = None                  # the intraday strategies' signals
    oi: bool | None = None                        # live F&O OI build-ups
    options: bool | None = None                   # BUY CALL / BUY PUT index option verdicts (one lot each)
    daily: bool | None = None                     # the daily strategies through the practice bot
    max_positions: int | None = Field(None, ge=1, le=50)
    max_trades_per_day: int | None = Field(None, ge=1, le=200)
    daily_loss_pct: float | None = Field(None, ge=0.1, le=20)
    max_late_min: int | None = Field(None, ge=1, le=60)


@router.get("/autotrade", response_model=None, response_class=SafeJSONResponse)
def view():
    """Files only: the engine's settings, positions, today's trades, its speed and its record."""
    return autotrade_svc.view()


@router.get("/autotrade/speed", response_model=None, response_class=SafeJSONResponse)
def speed():
    """The live path's latency (P50 / P95 / P99 per step), the ZeroMQ tick bus and the live signal engine."""
    return autotrade_svc.speed()


@router.get("/metrics", response_class=PlainTextResponse, include_in_schema=False)
def metrics():
    """The same latencies in Prometheus' text format, for Grafana or any scraper (needs prometheus-client)."""
    out = latency_svc.prometheus_text()
    if out is None:
        return PlainTextResponse("prometheus-client is not installed (pip install -r requirements.txt)",
                                 status_code=503)
    body, ctype = out
    return Response(body, media_type=ctype)


@router.post("/autotrade/settings", response_model=None, response_class=SafeJSONResponse)
def settings(body: AutoSettings):
    return autotrade_svc.settings(body.model_dump(exclude_none=True))


@router.post("/autotrade/stop", response_model=None, response_class=SafeJSONResponse)
def stop():
    """Kill switch: the engine off and every engine position closed at the live price."""
    return autotrade_svc.stop_all()


@router.post("/autotrade/reset", response_model=None, response_class=SafeJSONResponse)
def reset():
    return autotrade_svc.reset()
