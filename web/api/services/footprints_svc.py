"""GET /api/smart-money/live: Big money live (scanner/footprints.py) joined with what the disclosures say about the
same stocks (smart_money_svc, last 30 days), plus the measured next-day result of every past alert. Reads files only.
"""
from __future__ import annotations

import json
from datetime import datetime

import numpy as np

from scanner import footprints as fp

from . import data, smart_money_svc as sm_svc
from ..errors import log
from ..util import now_ist, num

MIN_TO_JUDGE = 30           # alerts with a next-day result before their record means much
STALE_MIN = 15              # a footprints file older than this in market hours is out of date


def _context() -> dict[str, dict]:
    """symbol -> what the disclosures of the last 30 days say (direction, top reasons, money)."""
    try:
        sig = sm_svc._derived(30)["signals"]
    except Exception:
        log.exception("Smart money context for Big money live failed")
        return {}
    out = {}
    for r in sig.to_dict("records"):
        out[r["symbol"]] = {"direction": r["direction"] if r["direction"] in ("up", "down") else "mixed",
                            "reasons": [str(x) for x in (r.get("reasons") or [])[:3]],
                            "deal_net_value": num(r.get("deal_net_value")) or 0.0,
                            "insider_buy_value": num(r.get("insider_buy_value")) or 0.0,
                            "insider_sell_value": num(r.get("insider_sell_value")) or 0.0,
                            "promoter_buying": bool(r.get("promoter_buying")),
                            "promoter_selling": bool(r.get("promoter_selling"))}
    return out


def _stats(moves) -> dict:
    m = np.array([x for x in moves if x == x], dtype=float)
    if not len(m):
        return {"alerts": 0, "hit_rate": None, "avg_move_pct": None}
    return {"alerts": int(len(m)), "hit_rate": round(float((m > 0).mean() * 100), 1),
            "avg_move_pct": round(float(m.mean()), 3)}


def track() -> dict:
    """Next-day result of every logged up/down alert: did the stock keep moving the alert's way by the next close?"""
    log_df = fp.load_log()
    try:
        close = data.store_close()
    except Exception:
        close = None
    if close is None or log_df.empty:
        res = log_df.assign(move_pct=np.nan, next_date=None) if not log_df.empty else log_df
    else:
        res = fp.outcomes(log_df, close)
    ctx = _context()
    directional = res[res["direction"].isin(["up", "down"])] if len(res) else res
    agree = [ctx.get(s, {}).get("direction") == d for s, d in zip(directional["symbol"], directional["direction"])] \
        if len(directional) else []
    all_s = _stats(directional["move_pct"] if len(directional) else [])
    agree_s = _stats(directional["move_pct"][agree] if len(directional) else [])
    n = all_s["alerts"]
    verdict = (f"Too few alerts with a next-day result to judge yet ({n} of {MIN_TO_JUDGE})." if n < MIN_TO_JUDGE else
               f"By the next close, {all_s['hit_rate']:.0f}% of alerts kept moving their way (average "
               f"{all_s['avg_move_pct']:+.2f}%).")
    recent = []
    for r in res.sort_values(["date", "time"], ascending=False).head(40).to_dict("records") if len(res) else []:
        recent.append({"date": str(r["date"]), "time": str(r["time"]), "symbol": r["symbol"], "price": num(r["price"]) or 0.0,
                       "direction": r["direction"] if r["direction"] in ("up", "down") else "mixed",
                       "kinds": [k for k in str(r.get("kinds") or "").split(",") if k],
                       "next_date": r["next_date"] if isinstance(r.get("next_date"), str) else None,   # NaN when missing
                       "move_pct": num(r.get("move_pct"), 3)})
    return {"min_to_judge": MIN_TO_JUDGE, "all": all_s, "with_agreement": agree_s, "verdict": verdict, "recent": recent}


def payload() -> dict:
    try:
        raw = json.loads(fp.FP_FILE.read_text(encoding="utf-8"))
    except Exception:
        raw = {}
    ctx = _context()
    gen = raw.get("generated_at")
    age_min = None
    if gen:
        try:
            age_min = (now_ist() - datetime.fromisoformat(gen)).total_seconds() / 60
        except ValueError:
            pass
    open_now = data_market_open()
    fresh = bool(gen) and age_min is not None and (age_min <= STALE_MIN or not open_now)
    rows = []
    for r in raw.get("rows") or []:
        c = ctx.get(r["symbol"])
        agree = bool(c) and r.get("direction") in ("up", "down") and c["direction"] == r.get("direction")
        rows.append({**r, "company": (data.symbol_meta().get(r["symbol"]) or {}).get("company"),
                     "disclosures": c, "agree": agree})
    rows.sort(key=lambda x: (not x["agree"], -len(x.get("kinds") or []), -(x.get("rvol") or 0)))
    source = raw.get("source")
    note = raw.get("note") or ("Big money live has not run yet: it runs every 5 minutes in market hours."
                               if not gen else "")
    if gen and not fresh:
        note = (f"Out of date: last checked {gen[11:16]}. The 5-minute task runs 09:20-15:05 on trading days "
                "(intraday_sync.py --footprints).")
    return {"generated_at": gen, "market_open": open_now, "fresh": fresh, "source": source,
            "delayed": "yahoo" in (source or ""), "note": note, "thresholds": raw.get("thresholds") or {},
            "universe": int(raw.get("universe") or 0), "rows": rows if fresh or not open_now else [], "track": track()}


def data_market_open() -> bool:
    try:
        from scanner.intraday.live import market_open_now
        return market_open_now()
    except Exception:
        return False
