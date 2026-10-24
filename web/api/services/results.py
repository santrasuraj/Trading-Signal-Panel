"""Results calendar from the newest cached data/nse/events_*.json (never fetched here)."""
from __future__ import annotations

from . import data
from ..util import days_until, inum, today_ist

RANKED_TOP = 20          # a stock is "relevant" when a strategy ranks it in its top 20 (its ranking lists 40)
RELEVANCE = ("held", "order", "model", "ranked")     # most relevant first


def events(lt: dict | None, days: int = 14, relevant: bool = False) -> dict:
    rows, cached_on = data.results_events()
    lt = lt or {}
    today = today_ist()
    universe = set(data.universe()["symbol"]) | set(data.etfs())
    held = set(data.holdings_df()["symbol"])
    models: dict[str, list[str]] = {}
    orders: dict[str, list[str]] = {}
    ranked: dict[str, tuple[int, str]] = {}          # symbol -> (best rank, strategy name)
    for s in lt.get("strategies") or []:
        if s.get("status") == "not-working":     # comparison only (no orders followed): not "relevant to you"
            continue
        for p in s.get("positions") or []:
            models.setdefault(p.get("symbol"), []).append(s.get("key"))
        for a in s.get("actions") or []:
            orders.setdefault(a.get("symbol"), []).append(s.get("key"))
        for r in s.get("ranking") or []:
            rank = int(r.get("rank") or 0)
            if 0 < rank <= RANKED_TOP and (r.get("symbol") not in ranked or rank < ranked[r.get("symbol")][0]):
                ranked[r.get("symbol")] = (rank, str(s.get("name") or s.get("key")))
    mom: dict[str, int] = {}
    sc = data.screener()
    if sc is not None:
        mom = {s: inum(v) for s, v in zip(sc["symbol"], sc["momentum_rank"])}
    else:
        mom_s = next((s for s in lt.get("strategies") or [] if s.get("key") == "momentum"), None)
        if mom_s:
            mom = {r.get("symbol"): int(r.get("rank") or 0) for r in mom_s.get("ranking") or []}
    meta = data.symbol_meta()
    out, seen = [], set()
    for r in sorted(rows, key=lambda x: x["date"]):
        sym = r["symbol"]
        if sym not in universe and sym not in held:
            continue
        d = days_until(r["date"], today)
        if d is None or d < 0 or d > days or sym in seen:
            continue                 # one row per company: its earliest upcoming board meeting
        seen.add(sym)
        why = ("held" if sym in held else "order" if sym in orders else "model" if sym in models
               else "ranked" if sym in ranked else None)
        if relevant and why is None:
            continue
        m = meta.get(sym, {})
        rk = ranked.get(sym)
        out.append({"symbol": sym, "company": m.get("company") or r.get("company"), "industry": m.get("industry"),
                    "date": r["date"], "days_until": d, "purpose": r["purpose"], "you_hold": sym in held,
                    "in_models": models.get(sym, []), "in_orders": orders.get(sym, []), "momentum_rank": mom.get(sym),
                    "relevance": why, "strategy_rank": rk[0] if rk else None, "ranked_by": rk[1] if rk else None})
    if rows:
        who = (f"of your stocks (held, model, order or a strategy's top {RANKED_TOP})" if relevant
               else "stocks of the scan universe")
        note = f"{len(out)} {who} report results in the next {days} day{'' if days == 1 else 's'}"
    else:
        note = "Results calendar not downloaded yet: it updates with the next scan."
    return {"cached_on": cached_on, "note": note, "events": out}
