"""Runs the live signal engine (scanner/intraday/live_engine.py) inside the dashboard server.

A worker thread waits for new 5-minute bars - the tick bus's event (tickbus_svc), else the live bars file changing,
checked every second - and recomputes today's signals at once, about a second after the bar closes instead of on the
5-minute scheduled task. Listeners (the auto-trader) are woken with the new signals. At start the Numba kernels are
compiled / loaded (fast.warm_up), and shortly before the open the day's caches are built so the first bar is quick.
"""
from __future__ import annotations

import logging
import threading
import time

import pandas as pd

from . import data, latency_svc, tickbus_svc

log = logging.getLogger("quantdesk")
_engine = None
_thread: threading.Thread | None = None
_wake = threading.Event()
_listeners: list = []
_state = {"numba": None, "numba_warmup_s": None, "last_trigger": None, "last_error": None}


def engine():
    global _engine
    if _engine is None:
        from scanner.intraday.live_engine import LiveEngine
        _engine = LiveEngine(log=lambda m: log.info(m), frames_fn=data.store, cfg_fn=data.config)
    return _engine


def on_signals(f) -> None:
    """f(signals) after every refresh that produced signals (called on the worker thread)."""
    if f not in _listeners:
        _listeners.append(f)


def latest() -> tuple[dict | None, float | None]:
    """The engine's last signals and when they were ready (epoch s); (None, None) before its first run."""
    e = _engine
    return (e.latest, e.ready_at) if e is not None else (None, None)


def _bars(interval: str, n: int, written: float) -> None:
    if interval == "5m":
        _state["last_trigger"] = "bus"
        _wake.set()


def _bar_close_epoch(bars_to: str | None) -> float | None:
    """The close of the latest bar the signals used (its start + 5 min), as epoch seconds."""
    try:
        ts = pd.Timestamp(bars_to)
        ts = ts.tz_localize("Asia/Kolkata") if ts.tzinfo is None else ts
        return ts.timestamp() + 300
    except Exception:
        return None


def _live_mtime() -> float | None:
    from scanner.intraday import live as live_feed
    from scanner.intraday.run import INTRADAY_DIR
    try:
        return live_feed.live_file(INTRADAY_DIR).stat().st_mtime
    except OSError:
        return None


def run_once(force: bool = False) -> dict | None:
    """One refresh plus its timings and listeners (the loop calls it; tests call it directly)."""
    e = engine()
    out = e.refresh(force=force)
    if out is None:
        return None
    latency_svc.record("signal_compute", e.stats["last_compute_s"])
    close = _bar_close_epoch(out.get("bars_to"))
    if close is not None and e.ready_at is not None:
        latency_svc.record("bar_to_signals", e.ready_at - close)
    for f in list(_listeners):
        try:
            f(out)
        except Exception:
            log.exception("signals listener failed")
    return out


def _loop() -> None:
    from scanner.intraday import fast
    from scanner.intraday import live as live_feed
    try:
        _state["numba_warmup_s"] = round(fast.warm_up(), 2)
        _state["numba"] = fast.ENABLED
    except Exception as e:                                # compiled loops are an optimisation, never a requirement
        _state["numba"] = False
        log.warning("numba warm-up failed: %s", e)
    seen = _live_mtime()
    while True:
        try:
            by_bus = _wake.wait(timeout=1.0)
            _wake.clear()
            m = _live_mtime()
            if not by_bus:
                if live_feed.market_open_now(lead_minutes=10) and engine().day != pd.Timestamp.now(tz="Asia/Kolkata").date():
                    engine().prebuild()
                if m is None or m == seen:
                    continue
                _state["last_trigger"] = "file"
            seen = m
            run_once()
            _state["last_error"] = None
        except Exception as e:                            # never let the loop die
            _state["last_error"] = f"{type(e).__name__}: {e}"
            log.exception("live signal engine failed")
            time.sleep(1.0)


def start() -> None:
    """Start the worker (idempotent) and listen for the bus's new-bar events."""
    global _thread
    tickbus_svc.on_bars(_bars)
    if _thread and _thread.is_alive():
        return
    _thread = threading.Thread(target=_loop, name="live-signals", daemon=True)
    _thread.start()


def status() -> dict:
    e = _engine
    return {"running": bool(_thread and _thread.is_alive()), "numba": _state["numba"],
            "numba_warmup_s": _state["numba_warmup_s"], "last_trigger": _state["last_trigger"],
            "last_error": _state["last_error"] or (e.stats["last_error"] if e else None),
            "day_ready": bool(e and e.day), "runs": e.stats["runs"] if e else 0,
            "last_compute_s": e.stats["last_compute_s"] if e else None,
            "last_day_build_s": e.stats["last_day_build_s"] if e else None,
            "signals_at": (e.latest or {}).get("generated_at") if e else None,
            "bars_to": (e.latest or {}).get("bars_to") if e else None}
