"""Signal strength: a transparent 0-100 ranking of today's BUY signals, the sum of five parts.

  evidence   30  how well the strategy's idea is documented (STRONG 30, MODERATE 20, WEAK 10, else 5)
  status     25  how the strategy does in its own backtest today (working 25, mixed 12, unknown 5)
  agreement  25  other working (not comparison-only) strategies buying or holding the same stock: 10 each, max 25
  track      10  the strategy's live signal record (track_svc): making money 10, losing 0, too few closed yet 5
  results    10  no quarterly results inside the warning window 10 (a results day can move the stock either way)

It ranks signals against each other; it is not a forecast and never changes an order. Comparison-only
strategies and SELL orders get no score.
"""
from __future__ import annotations

EVIDENCE_PTS = {"STRONG": 30, "MODERATE": 20, "WEAK": 10}
STATUS_PTS = {"working": 25, "mixed": 12}
AGREE_EACH, AGREE_MAX = 10, 25


def grade(score: int) -> str:
    return "strong" if score >= 70 else "good" if score >= 50 else "fair" if score >= 30 else "weak"


def _agreeing(strategies: list[dict]) -> dict[str, set[str]]:
    """symbol -> keys of the working strategies that buy it today or hold it in their model portfolio."""
    out: dict[str, set[str]] = {}
    for s in strategies:
        if s.get("lifecycle") != "active" or s.get("status") == "not-working":
            continue
        syms = {a["symbol"] for a in s.get("actions") or [] if a.get("action") == "BUY"}
        sells = {a["symbol"] for a in s.get("actions") or [] if a.get("action") == "SELL"}
        syms |= {p["symbol"] for p in s.get("positions") or [] if p["symbol"] not in sells}
        for sym in syms:
            out.setdefault(sym, set()).add(s["key"])
    return out


def strength(o: dict, s: dict, agree_keys: set[str], names: dict[str, str], track: dict | None) -> dict:
    ev = s.get("evidence") or "EXPERIMENTAL"
    status = s.get("status") or "unknown"
    others = sorted(names.get(k, k) for k in agree_keys - {s["key"]})
    tr = track or {}
    level = tr.get("level") or "unknown"
    t_pts = {"good": 10, "bad": 0}.get(level, 5)
    warn = bool(o.get("results_warning"))
    parts = [
        {"key": "evidence", "label": "Evidence", "points": EVIDENCE_PTS.get(ev, 5), "max": 30,
         "note": f"{ev.capitalize()} evidence for this kind of strategy"},
        {"key": "status", "label": "Backtest", "points": STATUS_PTS.get(status, 5), "max": 25,
         "note": {"working": "Working in its own backtest", "mixed": "Mixed in its own backtest"}.get(
             status, "Not enough backtest history to judge")},
        {"key": "agreement", "label": "Agreement", "points": min(AGREE_EACH * len(others), AGREE_MAX), "max": AGREE_MAX,
         "note": f"Also bought or held by {', '.join(others)}" if others else "No other working strategy has it"},
        {"key": "track", "label": "Live record", "points": t_pts, "max": 10,
         "note": str(tr.get("verdict") or "No live signals recorded yet")},
        {"key": "results", "label": "Results", "points": 0 if warn else 10, "max": 10,
         "note": (f"Reports results in {o.get('results_in_days')} day(s)" if warn else "No results day soon")},
    ]
    score = int(round(sum(p["points"] for p in parts)))
    return {"score": score, "grade": grade(score), "agree": others, "parts": parts}


def attach(orders: list[dict], lt: dict, strategies: list[dict], track: dict[str, dict]) -> list[dict]:
    """Adds `strength` to every BUY order of a strategy that is not comparison-only (in place; returns orders).
    `strategies`: the normalised active strategies (strategies.all_strategies), `track`: track_svc stats."""
    by_key = {s["key"]: s for s in strategies}
    names = {s["key"]: s.get("name") or s["key"] for s in strategies}
    agree = _agreeing(strategies)
    for o in orders:
        s = by_key.get(o["strategy_key"])
        if o["action"] != "BUY" or o["comparison_only"] or s is None:
            o["strength"] = None
            continue
        o["strength"] = strength(o, s, agree.get(o["symbol"], set()), names, track.get(o["strategy_key"]))
    return orders
