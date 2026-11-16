"""The late-entry study (scanner/late_entry.py) for the API: computed once per backtest (trades.parquet), in the
background, and kept in memory and in data/results/late_entry.json. Callers that must not wait (the Action card)
get None until it is ready; GET /api/strategies/{key}/late-entry waits for it."""
from __future__ import annotations

import json
import threading

import pandas as pd

from scanner import late_entry, scans

from ..caches import file_key
from ..errors import log
from ..paths import P

_lock = threading.Lock()
_state: dict = {"key": None, "report": None, "running": False}


def _file():
    return P.results / "late_entry.json"


def _compute(key) -> dict | None:
    try:
        trades = pd.read_parquet(P.trades)
        _, ctx = scans._pit_ctx()
        rep = late_entry.study(trades, ctx.p.open, ctx.p.universe)
        rep["trades_key"] = [str(k) for k in key]
        try:
            _file().write_text(json.dumps(rep), encoding="utf-8")
        except OSError:
            pass
        return rep
    except Exception:
        log.exception("Late-entry study failed")
        return None


def _from_disk(key) -> dict | None:
    try:
        rep = json.loads(_file().read_text(encoding="utf-8"))
        return rep if rep.get("trades_key") == [str(k) for k in key] else None
    except Exception:
        return None


def report(wait: bool = True) -> dict | None:
    key = file_key(P.trades)
    if key[1] is None:
        return None
    with _lock:
        if _state["key"] == key and _state["report"] is not None:
            return _state["report"]
        disk = _from_disk(key)
        if disk is not None:
            _state.update(key=key, report=disk)
            return disk
        if not wait:
            if not _state["running"]:
                _state["running"] = True
                threading.Thread(target=_background, args=(key,), name="late-entry", daemon=True).start()
            return None
    rep = _compute(key)
    with _lock:
        if rep is not None:
            _state.update(key=key, report=rep)
    return rep


def _background(key) -> None:
    try:
        rep = _compute(key)
        with _lock:
            if rep is not None:
                _state.update(key=key, report=rep)
    finally:
        with _lock:
            _state["running"] = False


def for_strategy(key: str, wait: bool = True) -> dict | None:
    rep = report(wait)
    if rep is None:
        return None
    s = (rep.get("strategies") or {}).get(key)
    return {"key": key, "lags": rep.get("lags"), "cost_pct": rep.get("cost_pct"), "generated_at": rep.get("generated_at"),
            "trades": (s or {}).get("trades", 0), "results": (s or {}).get("lags", {}), "note": rep.get("note")}
