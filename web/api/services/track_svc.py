"""Signal track record: a thin, cached wrapper over scanner.track.track_record().

Cached by (store generation, journal file identity, costs config): rebuilt from the journal and the stored prices
only when one of them changes. Reads files only.
"""
from __future__ import annotations

import json

from scanner import track
from scanner.costs import CostModel

from . import data, strategies as st
from ..caches import KeyedCache, file_key, register
from ..errors import log
from ..paths import P
from ..util import num

_report = register(KeyedCache(2))
STATES = ("pending", "not_filled", "open", "closed")
STATUS = ("working", "mixed", "not-working", "unknown")


def report() -> dict | None:
    """track_record() output, or None when there is no journal or no prices yet."""
    if data.journal_info() is None:
        return None
    cfg = data.config()
    costs_cfg = cfg.get("costs") or {}
    etfs = [str(e).upper() for e in (cfg.get("etfs") or [])]
    key = (data.store_version(), file_key(P.journal), json.dumps(costs_cfg, sort_keys=True, default=str), tuple(etfs))

    def build():
        frames = data.store()
        if frames["close"].empty:
            return None
        return track.track_record(frames, CostModel.from_config(costs_cfg), path=P.journal, etfs=etfs)
    try:
        return _report.get(key, build)
    except Exception:      # the track record must never take down the Signals page
        log.exception("Signal track record failed")
        return None


def stats_by_strategy() -> dict[str, dict]:
    """{strategy key: live stats} (empty without a journal): used by the signal strength score."""
    rep = report()
    return (rep or {}).get("strategies") or {}


def _stats(s: dict) -> dict:
    return {**{k: int(s.get(k) or 0) for k in ("signals", "closed", "open", "pending", "not_filled")},
            **{k: num(s.get(k)) for k in ("win_rate", "avg_win_pct", "avg_loss_pct", "expectancy_pct",
                                          "profit_factor", "avg_days")},
            "realised_pnl": num(s.get("realised_pnl")) or 0.0, "open_pnl": num(s.get("open_pnl")) or 0.0,
            "level": s.get("level") if s.get("level") in ("good", "bad") else "unknown",
            "verdict": str(s.get("verdict") or "")}


def _empty() -> dict:
    level, text = track.verdict({"closed": 0})
    return _stats({"level": level, "verdict": text})


def payload(strategy: str | None = None, state: str | None = None) -> dict:
    rep = report() or {}
    lt = data.latest() or {}
    now = {s["key"]: s for s in st.all_strategies(lt)} if lt else {}
    strategies = []
    for k, s in (rep.get("strategies") or {}).items():
        cur = now.get(k)
        full = ((cur or {}).get("metrics") or {}).get("full") or {}
        bt = None
        if full.get("trades"):
            bt = {"trades": int(full["trades"]), **{x: num(full.get(x)) for x in ("win_rate", "expectancy_pct",
                                                                              "profit_factor", "avg_days")}}
        strategies.append({"key": k, "name": (cur or {}).get("name") or s.get("name") or k,
                           "status": cur["status"] if cur and cur.get("status") in STATUS else None,
                           "live": _stats(s), "backtest": bt})
    strategies.sort(key=lambda x: (-x["live"]["signals"], x["name"]))
    rows = rep.get("signals") or []
    shown = [r for r in rows if (not strategy or r["strategy_key"] == strategy) and (not state or r["state"] == state)]
    signals = [{**r, "status_then": r.get("status_then") if r.get("status_then") in STATUS else None,
                "state": r["state"] if r["state"] in STATES else "pending"} for r in shown]
    return {"as_of": rep.get("as_of"), "min_closed": int(rep.get("min_closed") or track.MIN_CLOSED),
            "overall": _stats(rep["overall"]) if rep.get("overall") else _empty(),
            "strategies": strategies, "signals": signals, "total": len(rows)}
