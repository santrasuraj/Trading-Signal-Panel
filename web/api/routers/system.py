"""1. system: /api/health, /api/status (polled every 1-10 s: file stats and cached reads only)."""
from __future__ import annotations

import re
import time
from pathlib import Path

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


UI_INDEX = Path(__file__).resolve().parents[2] / "ui" / "dist" / "index.html"
_ENTRY = re.compile(r"/assets/(index-[\w-]+\.js)")
_ui: dict = {"mtime": None, "build": None}


def ui_build() -> str | None:
    """The entry script of the app build being served (e.g. index-CMbVnSWU.js; its name changes with every build).
    A tab loaded from an older build compares it with its own and offers to reload: without that, a page left open
    keeps showing the old screens after an update. A file stat per call; the file is read only when it changed."""
    try:
        m = UI_INDEX.stat().st_mtime
    except OSError:
        return None
    if _ui["mtime"] != m:
        hit = _ENTRY.search(UI_INDEX.read_text(encoding="utf-8", errors="replace"))
        _ui.update(mtime=m, build=hit.group(1) if hit else None)
    return _ui["build"]


@router.get("/status", response_model=AppStatus)
def status():
    lt = data.latest()
    clk = clock.market_clock()
    return {"server_version": VERSION, "ui_build": ui_build(), "latest": st.as_of(lt, clk) if lt else None,
            "scan": scan_runner.status(), "fyers": fyers_svc.status(verify=False, lt=lt), "clock": clk,
            "features": features(lt), "ticker": ticker(lt),
            "config_changed_since_scan": settings_svc.config_changed_since_scan(lt)}
