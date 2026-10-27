"""10. scan, 11. fyers, 12. config / costs / data health, 13. intraday."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Query

from ..models import (ConfigResponse, CostPreview, DataHealth, FyersLoginCompleteRequest, FyersLoginCompleteResponse,
                      FyersLoginRequest, FyersLoginResponse, FyersStatus, IntradayResponse, IntradayRunAccepted,
                      IntradayRunRequest, IntradaySignalsResponse, ScanAccepted, ScanHistory, ScanLog, ScanRequest)
from ..services import alerts, fyers_svc, intraday_job, intraday_view, scan_runner, settings_svc

router = APIRouter(prefix="/api", tags=["operations"])


# ------------------------------------------------------------------ scan
@router.post("/scan", response_model=ScanAccepted, status_code=202)
def start_scan(body: ScanRequest | None = None):
    status = scan_runner.start(update=True if body is None else body.update)
    return {"accepted": True, "status": status}


@router.get("/scan/history", response_model=ScanHistory)
def scan_history(limit: int = Query(60, ge=1, le=500)):
    out = []
    for h in alerts.scan_files()[:limit]:
        out.append({"scan_id": h.get("generated_at") or "", "file": h["file"], "data_date": h.get("data_date"),
                    "live": h.get("live") if isinstance(h.get("live"), bool) else None,
                    "elapsed_s": h.get("elapsed_s"), "strategies": h.get("strategies")})
    return {"scans": out}


@router.get("/scan/log", response_model=ScanLog)
def scan_log(lines: int = Query(200, ge=1, le=2000), level: Literal["all", "error"] = "all"):
    return settings_svc.scan_log(lines, level)


# ------------------------------------------------------------------ fyers
@router.get("/fyers/status", response_model=FyersStatus)
def fyers_status(verify: bool = False):
    return fyers_svc.status(verify=verify)


@router.post("/fyers/login", response_model=FyersLoginResponse)
def fyers_login(body: FyersLoginRequest | None = None):
    return fyers_svc.login((body.mode if body else "paste"))


@router.post("/fyers/login/complete", response_model=FyersLoginCompleteResponse)
def fyers_login_complete(body: FyersLoginCompleteRequest):
    return fyers_svc.complete(body.redirect_url)


# ------------------------------------------------------------------ config, costs, data health
@router.get("/config", response_model=ConfigResponse)
def config():
    return settings_svc.config_response()


@router.get("/costs/preview", response_model=CostPreview)
def costs_preview(value: float = Query(33333, gt=0, le=1e10)):
    return settings_svc.cost_preview(value)


@router.get("/data/health", response_model=DataHealth)
def data_health():
    return settings_svc.data_health()


# ------------------------------------------------------------------ intraday
@router.get("/intraday", response_model=IntradayResponse)
def intraday():
    return intraday_view.payload()


@router.get("/intraday/signals", response_model=IntradaySignalsResponse)
def intraday_signals():
    return intraday_view.signals_payload()


@router.post("/intraday/run", response_model=IntradayRunAccepted, status_code=202)
def intraday_run(body: IntradayRunRequest | None = None):
    run = intraday_job.start(update=True if body is None else body.update)
    return {"accepted": True, "run": run}
