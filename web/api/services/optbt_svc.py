"""Options backtester (GET /api/options-backtest/status, POST /api/options-backtest/run, POST .../history): strategies
tested on NSE's daily index-option prices (scanner/options_backtest.py, scanner/option_history.py). The history is
fetched once in the background (about 1.2 MB a trading day from NSE) and then kept current by the nightly F&O refresh.
"""
from __future__ import annotations

import threading

from scanner import option_history as oh, options_backtest as ob

from ..errors import ApiException
from ..util import now_ist

_job = {"running": False, "done": 0, "total": 0, "started": None, "finished": None, "report": None, "error": None}
_lock = threading.Lock()
_cache: dict = {}


def status() -> dict:
    return {"history": oh.summary(), "job": dict(_job), "strategies": list(ob.STRATEGIES),
            "underlyings": list(oh.UNDERLYINGS)}


def start_history(days: int) -> dict:
    with _lock:
        if _job["running"]:
            return status()
        _job.update(running=True, done=0, total=0, started=now_ist().isoformat(timespec="seconds"), finished=None,
                    report=None, error=None)

    def work():
        try:
            rep = oh.backfill(days, log=lambda *_: None, progress=lambda d, t: _job.update(done=d, total=t))
            _job["report"] = rep
        except Exception as e:                     # never kill the server for NSE trouble
            _job["error"] = f"{type(e).__name__}: {e}"
        finally:
            _job.update(running=False, finished=now_ist().isoformat(timespec="seconds"))
            _cache.clear()

    threading.Thread(target=work, name="option-history", daemon=True).start()
    return status()


def _hist(symbol: str):
    p = oh.path()
    key = (symbol, p.stat().st_mtime_ns if p.exists() else None)
    if _cache.get("key") != key:
        _cache.clear()
        _cache["key"], _cache["df"] = key, oh.load(symbol)
    return _cache["df"]


def run(spec: dict) -> dict:
    hist = _hist(spec["underlying"])
    if hist.empty:
        raise ApiException("FEATURE_UNAVAILABLE", "No option history stored yet.",
                           "Press 'Fetch history' on this page (about 2 years of NSE's daily option prices, once).",
                           {"feature": "options_backtest"})
    try:
        res = ob.backtest(hist, spec)
    except ValueError as e:
        raise ApiException("VALIDATION", str(e)) from e
    first, last = ob.today_range(hist)
    return {"spec": spec, **res, "history": {"first": first.isoformat() if first else None,
                                             "last": last.isoformat() if last else None},
            "note": "Daily closes only: a stop is seen at the close, not at an intraday spike. Charges are FYERS' and "
                    "the exchange's; margin and its cost are not included. Past results, a small sample of cycles."}
