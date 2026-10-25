"""Allocation-aware order sizing (mirrors daily.sized for BUYs; fixes SELL sizing - review item A1).

  alloc   = allocations ? capital * pct / 100 : capital
  per_pos = alloc / max_positions
  BUY     qty = floor(per_pos / price)
          risk sizing (event strategy, sizing == 'risk', stop < price):
              qty = min(floor(alloc * risk_pct / 100 / (price - stop)), floor(2 * per_pos / price))
  SELL    qty = what you hold (holdings.csv)                         -> qty_basis 'your_holding'
          else floor(alloc * model_weight_pct / 100 / price)          -> qty_basis 'model_weight'
          (also, capped at your holding, when another strategy you allocate to still holds the stock)
          (the backtest compounds - ~11x by now - so its own share count is never a share count for you)
With no allocations the BUY rows equal latest.json / Telegram exactly.
"""
from __future__ import annotations

import math
import re
from datetime import date

from . import data, strategies as st
from ..errors import ApiException
from ..util import days_until, fmt_date, inr, num

_ALLOC_RE = re.compile(r"^\s*([A-Za-z0-9_\-]+)\s*:\s*([0-9]+(?:\.[0-9]+)?)\s*$")


def parse_allocations(text: str | None) -> dict[str, float] | None:
    if text is None or not text.strip():
        return None
    out = {}
    for part in text.split(","):
        if not part.strip():
            continue
        m = _ALLOC_RE.match(part)
        if not m:
            raise ApiException("VALIDATION", f"Invalid allocation '{part.strip()}': use key:percent, e.g. momentum:60.",
                               details={"param": "allocations"})
        pct = float(m.group(2))
        if pct > 100:
            raise ApiException("VALIDATION", f"Allocation for {m.group(1)} is over 100%.", details={"param": "allocations"})
        out[m.group(1)] = pct
    return out


def resolve(query: str | None, active_keys: list[str]) -> tuple[dict[str, float] | None, str, str | None]:
    """(allocations or None, source, warning)."""
    q = parse_allocations(query)
    if q is not None:
        unknown = [k for k in q if k not in active_keys]
        if unknown:
            raise ApiException("VALIDATION", f"Unknown strategy in allocations: {', '.join(unknown)}.",
                               details={"param": "allocations", "unknown": unknown})
        alloc, source = q, "query"
    else:
        cfg = data.config().get("allocations") or {}
        alloc = {str(k): float(v) for k, v in cfg.items() if num(v) is not None} or None
        source = "config" if alloc else "none"
    if alloc is None:
        cap = num((data.latest() or {}).get("capital")) or 0
        return None, "none", (f"Each strategy is sized on your full capital ({inr(cap)}). Following more than one? "
                              "Set allocations so they share it.")
    warn = []
    total = sum(alloc.values())
    if total > 100.0001:
        warn.append(f"Allocations add up to {total:g}% of capital (more than 100%).")
    missing = [k for k in active_keys if k not in alloc]
    if missing:
        warn.append(f"No allocation (sized at ₹0): {', '.join(missing)}.")
    return alloc, source, " ".join(warn) or None


def alloc_capital(capital: float, alloc: dict[str, float] | None, key: str) -> float:
    if alloc is None:
        return capital
    return capital * alloc.get(key, 0.0) / 100


def order(a: dict, s: dict, lt: dict, alloc: dict[str, float] | None, held: dict[str, float | None],
          warn_days: int, today: date) -> dict:
    """One Order row for action `a` of normalised strategy `s`."""
    capital = num(lt.get("capital")) or 0.0
    rules, _ = st.rules(s)
    max_pos = int(s.get("max_positions") or rules.get("max_positions") or 1)
    a_cap = alloc_capital(capital, alloc, s["key"])
    per_pos = a_cap / max_pos
    price = num(a.get("price"))
    stop = num(a.get("stop"))
    side = "SELL" if a.get("action") == "SELL" else "BUY"
    sym = a.get("symbol")
    you_hold = held.get(sym) if sym in held else None
    qty, basis = None, "sized"
    if side == "BUY":
        if alloc is None and num(a.get("qty")) is not None:
            # the scan sized it on the unrounded close: recomputing from the 2-dp price can be a share off
            qty = int(num(a["qty"]))
        elif price and price > 0:
            qty = int(math.floor(per_pos / price))
            if (s["kind"] == "event" and rules.get("sizing") == "risk" and stop and price > stop
                    and num(rules.get("risk_pct"))):
                qty = min(int(math.floor(a_cap * float(rules["risk_pct"]) / 100 / (price - stop))),
                          int(math.floor(2 * per_pos / price)))
    elif sym in held and you_hold:
        # holdings.csv does not say which strategy a lot belongs to: when another strategy you follow (allocation
        # > 0) still holds the stock and is not selling it, sell only this strategy's share, never the whole holding
        others = [] if alloc is None else [
            x for x in lt.get("strategies") or [] if x.get("key") != s["key"] and alloc.get(x.get("key"), 0) > 0
            and x.get("status") != "not-working" and any(p.get("symbol") == sym for p in x.get("positions") or [])
            and not any(b.get("symbol") == sym and b.get("action") == "SELL" for b in x.get("actions") or [])]
        if others:
            basis = "model_weight"
            pos = next((p for p in s.get("positions") or [] if p.get("symbol") == sym), None)
            w = st.model_weight(pos, s, capital, lt) if pos else None
            if w is not None and price and price > 0:
                qty = min(int(math.floor(a_cap * w / 100 / price)), int(math.floor(you_hold)))
        else:
            qty, basis = int(math.floor(you_hold)), "your_holding"
    else:
        basis = "model_weight"
        pos = next((p for p in s.get("positions") or [] if p.get("symbol") == sym), None)
        w = st.model_weight(pos, s, capital, lt) if pos else None
        if w is not None and price and price > 0:
            qty = int(math.floor(a_cap * w / 100 / price))
    amount = round(qty * price, 2) if qty is not None and price else None
    rdays = days_until(a.get("results_on"), today)
    meta = data.symbol_meta().get(sym, {})
    return {
        "strategy_key": s["key"], "strategy_name": s.get("name") or s["key"], "strategy_status": s["status"],
        "horizon": s["horizon"], "comparison_only": st.comparison_only(s), "action": side, "symbol": sym,
        "company": a.get("company") or meta.get("company"), "industry": a.get("industry") or meta.get("industry"),
        "reason": str(a.get("reason") or ""), "price": price, "qty": qty, "qty_basis": basis, "amount": amount,
        "stop": stop, "stop_distance_pct": round((stop / price - 1) * 100, 2) if stop and price else None,
        "risk_amount": round(qty * (price - stop), 2) if side == "BUY" and qty is not None and stop and price else None,
        "results_on": a.get("results_on"), "results_in_days": rdays,
        "results_warning": bool(side == "BUY" and rdays is not None and 0 <= rdays <= warn_days),
        "provisional": bool(a.get("provisional") or lt.get("live")),
        "below_min_position": bool(side == "BUY" and amount is not None and amount < st.min_position(lt)),
        "you_hold_qty": you_hold,
    }


def warn_days() -> int:
    return int(num((data.config().get("results") or {}).get("warn_days")) or 7)


def orders_for(s: dict, lt: dict, alloc, held, today: date) -> list[dict]:
    if s["lifecycle"] != "active":
        return []
    wd = warn_days()
    return [order(a, s, lt, alloc, held, wd, today) for a in s.get("actions") or []]


def empty_reason(summ: dict) -> str:
    if summ["blocked_by_regime"]:
        return (f"Regime filter on: no new buys while Nifty is below its 200-DMA "
                f"(holding {summ['positions']} of {summ['max_positions']}).")
    if summ["kind"] == "rank" and summ.get("next_rebalance"):
        return f"No changes until the next review on {fmt_date(summ['next_rebalance'], year=False)}."
    return "No entry signals today."
