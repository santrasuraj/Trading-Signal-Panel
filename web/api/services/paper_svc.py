"""Paper trading: a thin, cached wrapper over scanner.paper.paper_report().

Cached by (store generation, journal file identity, costs config) - the report is rebuilt from the
journal and the stored prices, exactly as the scan and the old dashboard do. Reads files only.
"""
from __future__ import annotations

import json

from scanner import paper
from scanner.costs import CostModel

from . import data
from ..caches import KeyedCache, file_key, register
from ..paths import P
from ..util import num

_report = register(KeyedCache(2))


def report() -> dict | None:
    """paper_report() output, or None when there is no journal yet."""
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
        return paper.paper_report(frames=frames, costs=CostModel.from_config(costs_cfg), path=P.journal, etfs=etfs)
    return _report.get(key, build)


def summary(key: str, rep: dict) -> dict:
    """PaperSummary: the summary dict plus the key / kind it lacks."""
    s = dict(rep.get("summary") or {})
    rng = s.get("expected_range_pct")
    return {**s, "key": key, "kind": rep.get("kind") if rep.get("kind") in ("rank", "event") else None,
            "name": s.get("name") or rep.get("name") or key,
            "expected_range_pct": [num(rng[0]), num(rng[1])] if isinstance(rng, list) and len(rng) == 2 else None,
            "trades": int(s.get("trades") or 0), "open": int(s.get("open") or 0), "pending": int(s.get("pending") or 0),
            "fees": num(s.get("fees")) or 0.0, "slippage": num(s.get("slippage")) or 0.0,
            "equity": num(s.get("equity")) or 0.0, "pnl": num(s.get("pnl")) or 0.0,
            "level": s.get("level") if s.get("level") in ("good", "neutral", "bad") else "neutral",
            "verdict": s.get("verdict") or ""}


def summaries() -> dict[str, dict]:
    rep = report()
    if not rep:
        return {}
    return {k: summary(k, v) for k, v in (rep.get("strategies") or {}).items()}


def pulse(s: dict | None) -> dict | None:
    if not s:
        return None
    return {"return_pct": s.get("return_pct"), "days": int(s.get("days") or 0), "level": s["level"]}


def columnar_equity(rep: dict) -> dict:
    """[[date, value]] pairs -> TimeSeries (ids 'paper', 'nifty50', 'nifty500', rupees)."""
    series = [("paper", "Paper portfolio", "paper", rep.get("equity") or []),
              ("nifty50", "NIFTY 50", "benchmark", rep.get("nifty50") or []),
              ("nifty500", "NIFTY 500", "benchmark", rep.get("nifty500") or [])]
    dates = sorted({d for _, _, _, pts in series for d, _ in pts})
    out = []
    for sid, label, role, pts in series:
        m = dict((d, v) for d, v in pts)
        if pts:
            out.append({"id": sid, "label": label, "role": role, "v": [num(m.get(d)) for d in dates]})
    return {"t": dates, "series": out}


def survivorship_haircut() -> float:
    return float(paper.SURVIVORSHIP_HAIRCUT_PCT)


def min_days() -> int:
    return int(paper.MIN_DAYS_TO_JUDGE)
