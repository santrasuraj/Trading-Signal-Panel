"""1. system: /api/health, /api/status (polled every 1-10 s: file stats and cached reads only)."""
from __future__ import annotations

import time

from fastapi import APIRouter

from ..models import AppStatus, Health
from ..paths import P
from ..services import clock, data, fyers_svc, scan_runner, settings_svc, strategies as st
from ..util import num

VERSION = "3.0.0"
STARTED = time.monotonic()
router = APIRouter(prefix="/api", tags=["system"])


@router.get("/health", response_model=Health)
def health():
    return {"ok": True, "version": VERSION, "uptime_s": round(time.monotonic() - STARTED, 1)}


def features(lt: dict | None) -> dict:
    lt = lt or {}
    return {"paper": data.journal_info() is not None,
            "pit": lt.get("backtest_universe") == "point_in_time",
            "intraday": P.intraday.exists(),
            "trades_artifact": data.trades() is not None,
            "screener_artifact": data.screener() is not None,
            "rejected_tested": bool(lt.get("rejected_strategies")),
            "config_edit": False}


def ticker(lt: dict | None) -> dict | None:
    if not lt or not lt.get("market"):
        return None
    m = lt["market"]
    n500 = next((r for r in (lt.get("indices") or {}).get("factors", []) if r.get("name") == "Nifty 500"), {})
    label = m.get("label") if m.get("label") in ("Bullish", "Mixed", "Bearish") else "Mixed"
    return {"nifty": num(m.get("nifty")), "nifty_change_pct": num(m.get("nifty_change_pct")),
            "nifty500": num(n500.get("last")), "nifty500_change_pct": num(n500.get("chg_1d")),
            "vix": num(m.get("vix")), "vix_change_pct": num(m.get("vix_change_pct")),
            "advances": int(m.get("advances") or 0), "declines": int(m.get("declines") or 0), "label": label}


@router.get("/status", response_model=AppStatus)
def status():
    lt = data.latest()
    clk = clock.market_clock()
    return {"server_version": VERSION, "latest": st.as_of(lt, clk) if lt else None, "scan": scan_runner.status(),
            "fyers": fyers_svc.status(verify=False, lt=lt), "clock": clk, "features": features(lt),
            "ticker": ticker(lt), "config_changed_since_scan": settings_svc.config_changed_since_scan(lt)}
