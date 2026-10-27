"""GET /api/intraday: data/results/intraday.json (scanner/intraday/run.py) in the contract shape.

Honesty: square-off times, cost rules and the SEBI facts are server text from that file (never hard-coded in
the UI); the summary line states plainly how many strategies lost money after costs.
"""
from __future__ import annotations

from . import data, intraday_job
from ..util import num, spct, today_ist

EVIDENCE = {"STRONG", "MODERATE", "WEAK", "FOLKLORE", "EXPERIMENTAL"}
STATUS = {"working", "mixed", "not-working", "unknown"}


def _sebi() -> dict:
    try:
        from scanner.intraday.run import SEBI_FACTS
        return dict(SEBI_FACTS)
    except Exception:   # pragma: no cover - the module ships with the scanner
        return {"source": "SEBI (July 2024)", "url": "https://www.sebi.gov.in", "points": []}


def _costs(params: dict | None = None) -> dict | None:
    """Round trip on Rs 1 lakh: with the cost parameters the shown results were run with (intraday.json
    cost_params) when the file has them, else with today's config."""
    try:
        from scanner.intraday.engine import IntradayCosts
    except Exception:   # pragma: no cover
        return None
    c = IntradayCosts.from_config(params if isinstance(params, dict) and params
                                  else (data.config().get("intraday") or {}).get("costs"))
    value = 100000.0
    total = c.charges(value, value) + 2 * value * c.slippage_other_pct / 100
    return {"value": value, "round_trip_pct": round(total / value * 100, 4)}


def _strategy(s: dict) -> dict:
    m = s.get("metrics") or {}
    ci = m.get("ci95_day_pct")
    eq = s.get("equity") or []
    return {
        "key": s.get("key"), "name": s.get("name") or s.get("key"), "description": s.get("description") or "",
        "evidence": s.get("evidence") if s.get("evidence") in EVIDENCE else "EXPERIMENTAL", "horizon": "intraday",
        "status": s.get("status") if s.get("status") in STATUS else "unknown",
        "metrics": {"days": int(m.get("days") or 0), "trades": int(m.get("trades") or 0),
                    **{k: num(m.get(k)) for k in ("trades_per_day", "return_pct", "after_tax_return_pct", "annualised_pct",
                                                  "sharpe", "max_dd_pct", "win_rate", "avg_trade_pct", "profit_factor",
                                                  "avg_day_pct", "t_stat")},
                    "ci95_day_pct": [num(ci[0]), num(ci[1])] if isinstance(ci, list) and len(ci) == 2
                    and num(ci[0]) is not None and num(ci[1]) is not None else None,
                    "significant": bool(m.get("significant")), "start": m.get("start"), "end": m.get("end")},
        "equity": {"t": [str(d)[:10] for d, _ in eq],
                   "series": [{"id": "equity", "label": "Equity (₹)", "role": "strategy", "v": [num(v) for _, v in eq]}]},
    }


def summary_text(strats: list[dict], sessions: int | None) -> str:
    if not strats:
        return "No intraday strategies have been tested yet."
    n = len(strats)
    rets = [(x["metrics"]["return_pct"], x["name"]) for x in strats if x["metrics"]["return_pct"] is not None]
    losers = sum(1 for r, _ in rets if r <= 0)
    # "significant" = the 95% range of the average day excludes zero, in EITHER direction
    sig_pos = [x for x in strats if x["metrics"]["significant"] and (x["metrics"]["avg_day_pct"] or 0) > 0]
    sig_neg = [x for x in strats if x["metrics"]["significant"] and (x["metrics"]["avg_day_pct"] or 0) < 0]
    span = f" over {sessions} sessions" if sessions else ""
    best = max(rets) if rets else None
    if losers == n:
        text = f"All {n} intraday strategies lost money after costs{span}"
    else:
        text = f"{losers} of {n} intraday strategies lost money after costs{span}"
    if best is not None:
        text += f" (best: {best[1]} {spct(best[0], 1)})."
    else:
        text += "."
    if sig_pos:
        text += (f" {len(sig_pos)} show{'s' if len(sig_pos) == 1 else ''} a statistically significant positive daily "
                 "average - still a short sample.")
    else:
        text += " None shows a statistically significant profit"
        text += f"; {len(sig_neg)} of {n} lose money by a statistically significant margin." if sig_neg else "."
    if sig_pos and sig_neg:
        text += f" {len(sig_neg)} of {n} lose money by a statistically significant margin."
    return text + " Only a strategy with a real edge after costs gives live signals (Signals page, Intraday tab)."


def payload() -> dict:
    r = data.intraday()
    run = intraday_job.run_status()
    if not r:
        return {"available": False, "reason": "Intraday backtest not run yet", "generated_at": None, "elapsed_s": None,
                "data": None, "rules": {}, "sebi": _sebi(), "costs": _costs(), "strategies": [],
                "summary": "Intraday backtest not run yet.", "run": run}
    d = r.get("data") or {}
    strats = [_strategy(s) for s in r.get("strategies") or []]
    data_block = None
    if d:
        data_block = {"source": str(d.get("source") or ""), "interval": "5m", "from": str(d.get("from") or ""),
                      "to": str(d.get("to") or ""), "sessions": int(d.get("sessions") or 0),
                      "symbols": int(d.get("symbols") or 0), "note": str(d.get("note") or "")}
    sebi = r.get("sebi") if isinstance(r.get("sebi"), dict) else _sebi()
    return {"available": True, "reason": None, "generated_at": r.get("generated_at"), "elapsed_s": num(r.get("elapsed_s")),
            "data": data_block, "rules": {str(k): str(v) for k, v in (r.get("rules") or {}).items()},
            "sebi": {"source": str(sebi.get("source") or ""), "url": str(sebi.get("url") or ""),
                     "points": [str(x) for x in sebi.get("points") or []]},
            "costs": _costs(r.get("cost_params")), "strategies": strats, "summary": summary_text(strats, d.get("sessions")),
            "run": run}


def count() -> int:
    r = data.intraday()
    return len(r.get("strategies") or []) if r else 0


def signals_payload() -> dict:
    """GET /api/intraday/signals. Only strategies that are 'working' in the CURRENT backtest may give signals;
    data/results/intraday_signals.json (scanner/intraday/run.run_intraday_signals) is served only when it is
    from today and was computed against that backtest, so a strategy that has since failed never shows."""
    bt = data.intraday() or {}
    tested = bt.get("strategies") or []
    proven = [{"key": str(s.get("key")), "name": str(s.get("name") or s.get("key"))}
              for s in tested if s.get("status") == "working"]
    out = {"generated_at": None, "backtest_at": bt.get("generated_at"), "tested": len(tested), "proven": proven,
           "signals": [], "source": None, "delayed": False, "bars_to": None}
    if not bt:
        return {**out, "note": "The intraday backtest has not run yet, so no strategy is proven: no signals."}
    if not proven:
        return {**out, "note": f"No intraday strategy has a proven edge after costs ({len(tested)} tested): no signals. "
                               "A strategy gives signals here only once its backtest shows a profit beyond luck."}
    f = data.intraday_signals() or {}
    fresh = (str(f.get("generated_at") or "")[:10] == today_ist().isoformat()
             and f.get("backtest_at") == bt.get("generated_at"))
    if not fresh:
        return {**out, "note": "Signals have not been computed today yet: the intraday signals task refreshes them "
                               "every 5 minutes in market hours (or run intraday_sync.py --signals)."}
    keys = {p["key"] for p in proven}
    source = f.get("source") or None
    return {**out, "generated_at": f.get("generated_at"), "source": source,
            "delayed": "yahoo" in (source or ""), "bars_to": f.get("bars_to"),
            "signals": [x for x in f.get("signals") or [] if x.get("strategy_key") in keys],
            "note": str(f.get("note") or "")}
