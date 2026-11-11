"""Saved chart layouts (GET / PUT /api/chart-layouts): named sets of indicators, chart type, timeframe and options,
kept on this PC (data/chart_layouts.json) so every browser on it sees them."""
from __future__ import annotations

import json
import threading

from ..paths import P

FILE = "chart_layouts.json"
_lock = threading.Lock()


def read() -> dict:
    try:
        v = json.loads((P.data / FILE).read_text(encoding="utf-8"))
        return {"layouts": v.get("layouts", []) if isinstance(v, dict) else []}
    except (OSError, ValueError):
        return {"layouts": []}


def write(layouts: list[dict]) -> dict:
    seen, out = set(), []
    for x in layouts:
        key = x["name"].strip().lower()
        if key and key not in seen:
            seen.add(key)
            out.append({**x, "name": x["name"].strip()})
    with _lock:
        p = P.data / FILE
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps({"layouts": out}, indent=1), encoding="utf-8")
        tmp.replace(p)
    return {"layouts": out}
