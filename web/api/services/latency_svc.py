"""Latency of the live path, measured where it happens: P50 / P95 / P99 on the Auto-trader page (GET
/api/autotrade/speed) and as Prometheus metrics (GET /api/metrics) for Grafana or any other scraper.

What is measured (seconds):
  tick_transport       the live feed received a tick -> the dashboard had it (ZeroMQ, same PC)
  tick_age             the exchange's time on a tick -> the live feed received it (FYERS + internet; the exchange
                       stamps whole seconds and the PC clock may be off, so read it as +/- 1 s)
  bar_to_signals       a 5-minute bar closed -> the live signal engine's signals were ready
  signal_compute       the live signal engine's own work per new bar
  signal_to_fill       signals ready -> the auto-trader's practice fill
  decision_to_fill     the strategy's decision (its entry bar starts) -> the practice fill: the end-to-end number
  tick_to_exit         a tick crossed a stop / target -> the position was closed
  engine_pass          one pass of the auto-trader's loop
Samples are kept in memory (the last MAX_SAMPLES of each); nothing is written to disk.
"""
from __future__ import annotations

import threading
from collections import deque

import numpy as np

MAX_SAMPLES = 5000
NAMES = ("tick_transport", "tick_age", "bar_to_signals", "signal_compute", "signal_to_fill", "decision_to_fill",
         "tick_to_exit", "engine_pass")
LABELS = {"tick_transport": "Tick: live feed to dashboard", "tick_age": "Tick: exchange to your PC",
          "bar_to_signals": "Bar close to signals ready", "signal_compute": "Signal engine work per bar",
          "signal_to_fill": "Signals ready to practice fill", "decision_to_fill": "Strategy decision to fill",
          "tick_to_exit": "Stop / target tick to exit", "engine_pass": "Auto-trader loop pass"}
# Prometheus buckets: 100 us .. 10 min
BUCKETS = (0.0001, 0.0005, 0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30, 60, 120, 300, 600)

_lock = threading.Lock()
_samples: dict[str, deque] = {n: deque(maxlen=MAX_SAMPLES) for n in NAMES}
_prom = None                      # name -> prometheus_client Histogram, when prometheus_client is installed
_registry = None


def _prometheus():
    global _prom, _registry
    if _prom is None:
        try:
            from prometheus_client import CollectorRegistry, Histogram
            _registry = CollectorRegistry()
            _prom = {n: Histogram(f"quantdesk_{n}_seconds", LABELS[n], buckets=BUCKETS, registry=_registry)
                     for n in NAMES}
        except Exception:
            _prom = {}
    return _prom


def record(name: str, seconds: float | None) -> None:
    if seconds is None or seconds != seconds or seconds < 0 or name not in _samples:
        return
    with _lock:
        _samples[name].append(float(seconds))
    h = _prometheus().get(name)
    if h is not None:
        h.observe(float(seconds))


def summary() -> list[dict]:
    out = []
    with _lock:
        snap = {n: list(v) for n, v in _samples.items()}
    for n in NAMES:
        xs = np.asarray(snap[n], dtype=float)
        row = {"name": n, "label": LABELS[n], "n": int(len(xs)), "p50": None, "p95": None, "p99": None, "max": None}
        if len(xs):
            p50, p95, p99 = np.percentile(xs, [50, 95, 99])
            row.update(p50=float(p50), p95=float(p95), p99=float(p99), max=float(xs.max()))
        out.append(row)
    return out


def prometheus_text() -> tuple[bytes, str] | None:
    """(body, content type) in Prometheus' text format, or None without prometheus_client."""
    if not _prometheus():
        return None
    from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
    return generate_latest(_registry), CONTENT_TYPE_LATEST


def reset() -> None:
    """Tests only."""
    global _prom, _registry
    with _lock:
        for v in _samples.values():
            v.clear()
    _prom, _registry = None, None
