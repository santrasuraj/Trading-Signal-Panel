"""Rebalancing planner (POST /api/rebalance): your holdings brought to target weights, as a list of trades you review
and send as a basket (practice or real, through the Orders checks; nothing is sent from here).

  equal        every holding the same weight
  equal_risk   weights inversely proportional to each stock's volatility (1 year of daily returns): a calmer stock
               gets more money, so each contributes about the same day-to-day swing
  custom       your own % per stock (the rest of the money stays as cash)

`add_cash` adds (or, negative, withdraws) money. Trades below `min_trade` rupees are skipped (charges eat them).
Sales sell the oldest lots first: the plan shows the gain they book and whether it is short or long term
(tax_svc rules), so a rebalance's tax cost is visible before you act.
"""
from __future__ import annotations

import math
from datetime import date

import numpy as np
import pandas as pd

from scanner.costs import CostModel, TaxModel

from . import data, quotes_svc, tax_svc
from ..errors import ApiException
from ..util import num, today_ist


def plan(holdings: pd.DataFrame, prices: dict[str, float], close: pd.DataFrame, mode: str, add_cash: float = 0.0,
         custom: dict[str, float] | None = None, min_trade: float = 2000.0, cm: CostModel | None = None,
         tax: TaxModel | None = None, today: date | None = None) -> dict:
    cm, tax, today = cm or CostModel(), tax or TaxModel(), today or date.today()
    pos: dict[str, dict] = {}
    for r in holdings.itertuples(index=False):
        q, px = num(r.qty), prices.get(r.symbol)
        if not q or not px:
            continue
        p = pos.setdefault(r.symbol, {"symbol": r.symbol, "qty": 0, "price": px})
        p["qty"] += int(q)
    if not pos:
        raise ApiException("VALIDATION", "No holdings with a quantity and a live or last price.")
    value = sum(p["qty"] * p["price"] for p in pos.values())
    budget = value + float(add_cash)
    if budget <= 0:
        raise ApiException("VALIDATION", "Nothing left to invest after the withdrawal.")
    syms = sorted(pos)
    if mode == "equal":
        w = {s: 1 / len(syms) for s in syms}
    elif mode == "equal_risk":
        rets = close[[s for s in syms if s in close.columns]].iloc[-253:].pct_change(fill_method=None)
        vol = rets.std() * math.sqrt(252)
        inv = {s: 1 / float(vol[s]) for s in syms if s in vol and vol[s] == vol[s] and vol[s] > 0}
        if not inv:
            raise ApiException("VALIDATION", "Not enough price history for equal risk.")
        tot = sum(inv.values())
        w = {s: inv.get(s, 0) / tot for s in syms}
    elif mode == "custom":
        c = {k.upper(): float(v) for k, v in (custom or {}).items() if float(v) >= 0}
        if sum(c.values()) > 100.0001:
            raise ApiException("VALIDATION", "The custom weights add up to more than 100%.")
        w = {s: c.get(s, 0.0) / 100 for s in syms}
    else:
        raise ApiException("VALIDATION", "mode is equal, equal_risk or custom.")
    lots = [x for x in tax_svc.lots(holdings, prices, today) if x["symbol"] in pos]
    rows, buys, sells, charges = [], 0.0, 0.0, 0.0
    st_gain = lt_gain = 0.0
    for s in syms:
        p = pos[s]
        tgt_value = budget * w[s]
        tgt_qty = int(tgt_value // p["price"])
        diff = tgt_qty - p["qty"]
        trade_value = abs(diff) * p["price"]
        side = "BUY" if diff > 0 else "SELL" if diff < 0 else None
        skipped = bool(side) and trade_value < min_trade
        gain = None
        if side == "SELL" and not skipped:
            left = -diff
            gain = {"st": 0.0, "lt": 0.0}
            for lt in sorted((x for x in lots if x["symbol"] == s and x["qty"]), key=lambda x: x["buy_date"] or "9999"):
                take = min(left, int(lt["qty"]))
                if lt["buy_price"]:
                    g = (p["price"] - lt["buy_price"]) * take
                    gain["lt" if lt["term"] == "long" else "st"] += g
                left -= take
                if left <= 0:
                    break
            st_gain += gain["st"]
            lt_gain += gain["lt"]
        if side and not skipped:
            charges += cm.buy_cost(trade_value) if side == "BUY" else cm.sell_cost(trade_value)
            if side == "BUY":
                buys += trade_value
            else:
                sells += trade_value
        rows.append({"symbol": s, "price": round(p["price"], 2), "qty": p["qty"], "value": round(p["qty"] * p["price"], 2),
                     "weight_pct": round(p["qty"] * p["price"] / value * 100, 2), "target_pct": round(w[s] * 100, 2),
                     "target_qty": tgt_qty, "side": None if skipped else side, "trade_qty": 0 if skipped else abs(diff),
                     "trade_value": 0.0 if skipped else round(trade_value, 2), "skipped_small": skipped,
                     "gain_st": round(gain["st"], 2) if gain else None, "gain_lt": round(gain["lt"], 2) if gain else None})
    fy = tax_svc.fy_of(today)
    tax_now = tax_svc.tax_due(st_gain, lt_gain, tax, fy)
    cash_after = budget - sum(r["target_qty"] * r["price"] if not r["skipped_small"] else r["value"] for r in rows)
    return {"mode": mode, "value": round(value, 2), "budget": round(budget, 2), "rows": rows,
            "totals": {"buys": round(buys, 2), "sells": round(sells, 2), "charges": round(charges, 2),
                       "cash_after": round(cash_after, 2), "gain_st": round(st_gain, 2), "gain_lt": round(lt_gain, 2),
                       "tax_if_alone": tax_now["tax"]},
            "note": "Sales sell the oldest lots first. 'Tax if alone' is the tax on these sales if they were your only "
                    "gains this financial year (Tax harvesting has the full picture). Sells go first in the basket."}


def view(mode: str, add_cash: float, custom: dict | None, min_trade: float) -> dict:
    h = data.holdings_df()
    syms = sorted({str(s) for s in h["symbol"]}) if len(h) else []
    if not syms:
        raise ApiException("VALIDATION", "Add your holdings on the Portfolio page first.")
    q = quotes_svc.quotes(syms)
    prices = {x["symbol"]: float(x["price"]) for x in q["quotes"] if x.get("price")}
    cfg = data.config()
    out = plan(h, prices, data.store_close(), mode, add_cash, custom, min_trade,
               CostModel.from_config(cfg.get("costs")), TaxModel.from_config(cfg.get("tax")), today_ist())
    out["price_source"] = q.get("source")
    return out
