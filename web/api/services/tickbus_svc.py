"""The dashboard's end of the ZeroMQ tick bus (scanner/intraday/bus.py): every tick of the live feed, as it arrives.

start() subscribes (the server's lifespan calls it). Other services register handlers: the auto-trader checks its stops
and targets on each tick of a stock it holds; the live signal engine recomputes when new 5-minute bars are written.
Without pyzmq, or while the live feed isn't running, nothing arrives and those services fall back to the files.
"""
from __future__ import annotations

import logging

from scanner.intraday import bus

from . import data, latency_svc

log = logging.getLogger("quantdesk")
_sub: bus.Subscriber | None = None
_tick_handlers: list = []
_bar_handlers: list = []


def on_tick(f) -> None:
    """f(symbol, quote) on the bus thread for every tick: keep it quick."""
    if f not in _tick_handlers:
        _tick_handlers.append(f)


def on_bars(f) -> None:
    """f(interval, n, written_at) when the live feed has written new bars."""
    if f not in _bar_handlers:
        _bar_handlers.append(f)


def _tick(sym: str, q: dict) -> None:
    latency_svc.record("tick_transport", q["bus_ts"] - q["recv_ts"])
    if q.get("exch_ts"):
        latency_svc.record("tick_age", q["recv_ts"] - q["exch_ts"])
    for f in list(_tick_handlers):
        try:
            f(sym, q)
        except Exception:
            log.exception("tick handler failed")


def _bars(interval: str, n: int, written: float) -> None:
    for f in list(_bar_handlers):
        try:
            f(interval, n, written)
        except Exception:
            log.exception("bars handler failed")


def start() -> bool:
    """Subscribe (idempotent). False without pyzmq."""
    global _sub
    if _sub is not None:
        return True
    if not bus.available():
        log.info("tick bus: pyzmq is not installed - live prices come from quotes.json")
        return False
    _sub = bus.Subscriber(bus.port(data.config()), on_tick=[_tick], on_bars=[_bars]).start()
    return True


def stop() -> None:
    global _sub
    if _sub is not None:
        _sub.stop()
        _sub = None


def latest(symbol: str, max_age_s: float = bus.ALIVE_S) -> dict | None:
    """The bus's latest tick for `symbol` when it is recent, else None."""
    return _sub.latest(symbol, max_age_s) if _sub is not None else None


def status() -> dict:
    return {"available": bus.available(), "subscribed": _sub is not None,
            "connected": bool(_sub and _sub.alive()), "port": _sub.port if _sub else bus.port(data.config()),
            "ticks": (_sub.counts.get("T", 0) if _sub else 0), "bar_events": (_sub.counts.get("B", 0) if _sub else 0),
            "symbols": len(_sub.quotes) if _sub else 0}
