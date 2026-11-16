"""IV rank and IV percentile (GET /api/iv-rank, /api/iv-rank/{symbol}, POST /api/iv-rank/backfill): where each F&O
underlying's ~30-day at-the-money implied volatility sits within its past year (scanner/iv_history.py), as Sensibull
or Opstra show it. Kept current by the nightly F&O refresh; a year of history is fetched once on request."""
from __future__ import annotations

import threading

from scanner import iv_history as ivh

from ..util import now_ist

_job = {"running": False, "done": 0, "total": 0, "started": None, "finished": None, "report": None, "error": None}
_lock = threading.Lock()
_cache: dict = {}


def _ver():
    p = ivh.path()
    return p.stat().st_mtime_ns if p.exists() else None


def table() -> dict:
    v = _ver()
    if _cache.get("ver") != v or "table" not in _cache:
        t = ivh.ranks()
        _cache.update(ver=v, table=t)
    t = _cache["table"]
    rows = [] if t is None or t.empty else t.sort_values("rank", ascending=False, na_position="last").to_dict("records")
    days = max((r["days"] for r in rows), default=0)
    return {"rows": rows, "days": days, "date": rows[0]["date"] if rows else None, "job": status(),
            "note": "Each underlying's at-the-money implied volatility of the expiry nearest 30 days out, from NSE's daily "
                    "F&O file. IV rank: where today's IV sits between the past year's low (0) and high (100). IV percentile: "
                    "the share of the year's days with a lower IV. High = options are expensive against their own past "
                    "(sellers' side), low = cheap (buyers' side). Neither says where the price goes."
                    + ("" if days >= 120 else " Less than half a year stored yet: fetch a year of history for a fair rank.")}


def one(symbol: str) -> dict:
    return ivh.one(symbol)


def status() -> dict:
    return {**_job, "days_stored": len(ivh.days_stored()) if ivh.path().exists() else 0}


def start_backfill(days: int = ivh.LOOKBACK) -> dict:
    with _lock:
        if _job["running"]:
            return status()
        _job.update(running=True, done=0, total=0, started=now_ist().isoformat(timespec="seconds"), finished=None,
                    report=None, error=None)

    def work():
        try:
            _job["report"] = ivh.backfill(days, log=lambda *_: None, progress=lambda d, t: _job.update(done=d, total=t))
        except Exception as e:                       # never kill the server for NSE trouble
            _job["error"] = f"{type(e).__name__}: {e}"
        finally:
            _job.update(running=False, finished=now_ist().isoformat(timespec="seconds"))
            _cache.clear()

    threading.Thread(target=work, name="iv-history", daemon=True).start()
    return status()
