"""Capital gains and tax harvesting (GET /api/tax): your holdings' lots as short or long term, this financial year's
tax position, and what to sell before 31 March to pay less tax. Indian rules for listed shares (STT paid):

  * Held more than 12 months = long term: 12.5% (+4% cess) on the year's net long-term gains above Rs 1.25 lakh.
    Otherwise short term: 20% (+4% cess). Rates and the exemption come from `tax:` in config.yaml (TaxModel).
  * A short-term loss is set off against short-term gains, then long-term gains; a long-term loss only against
    long-term gains. What is left is carried forward 8 years (only if you file your return on time).
  * Gain harvesting: the Rs 1.25 lakh exemption is lost if unused. Selling long-term winners up to it and buying them
    back raises your cost price tax-free. Sell one day and buy back on a LATER day: a same-day sell and buy of the
    same stock is netted by the exchange as an intraday trade and your cost doesn't change. The bought-back shares
    start a new 12-month clock.
  * Loss harvesting: selling a loser this year cuts the tax on gains you already booked. India has no wash-sale rule,
    but buy back on a later day, not the same day.

Gains already booked this year come from your broker's tax P&L (you type them) or, by default, from the real orders
Quant Desk recorded (data/fills.jsonl). Shares bought before 1 Feb 2018 have a grandfathered cost (their 31 Jan 2018
price) that is not computed here: they are flagged. Not tax advice: check with your broker's report or an adviser.
"""
from __future__ import annotations

import math
from datetime import date, timedelta

import pandas as pd

from scanner import events, fills
from scanner.costs import CostModel, TaxModel

from . import data, quotes_svc
from ..util import num, today_ist

GRANDFATHER_BEFORE = date(2018, 2, 1)
WAIT_DAYS = 90                         # short-term winners that turn long term within this many days are listed


# ---- rules ---------------------------------------------------------------------------------------------------------
def fy_of(d: date) -> int:
    """The financial year (April-March) by its starting year: 2026-27 -> 2026."""
    return d.year if d.month >= 4 else d.year - 1


def long_term_from(buy: date) -> date:
    """The first day a sale counts as long term: the day after the 12-month anniversary."""
    ann = (pd.Timestamp(buy) + pd.DateOffset(years=1)).date()      # 29 Feb -> 28 Feb next year
    return ann + timedelta(days=1)


def tax_due(st: float, lt: float, tax: TaxModel, fy: int) -> dict:
    """Tax on a year's net short-term (`st`) and long-term (`lt`) gains, losses negative, after the set-off rules."""
    exempt = tax.exempt_for_fy(fy)
    st_net, lt_net, carry_st, carry_lt = st, lt, 0.0, 0.0
    if lt_net < 0:                               # a long-term loss can't touch short-term gains
        carry_lt, lt_net = -lt_net, 0.0
    if st_net < 0:                               # a short-term loss: long-term gains next
        use = min(-st_net, lt_net)
        lt_net -= use
        carry_st = -st_net - use
        st_net = 0.0
    taxable_lt = max(lt_net - exempt, 0.0)
    st_rate, lt_rate = tax.stcg_pct, tax.ltcg_pct
    amount = st_net * st_rate / 100 + taxable_lt * lt_rate / 100
    return {"tax": round(amount, 2), "st_net": round(st_net, 2), "lt_net": round(lt_net, 2),
            "taxable_lt": round(taxable_lt, 2), "exempt": exempt, "exempt_used": round(min(lt_net, exempt), 2),
            "exempt_left": round(max(exempt - lt_net, 0.0), 2), "carry_forward": round(carry_st + carry_lt, 2),
            "carry_st": round(carry_st, 2), "carry_lt": round(carry_lt, 2)}


def trade_by(fy: int, closed: set[str] | None = None) -> date:
    """The last day to SELL so the trade settles (T+1) by 31 March: the trading day before March's last one."""
    closed = closed or set()
    d = date(fy + 1, 3, 31)
    days = []
    while len(days) < 2:
        if d.weekday() < 5 and d.isoformat() not in closed:
            days.append(d)
        d -= timedelta(days=1)
    return days[1]


# ---- lots ----------------------------------------------------------------------------------------------------------
def lots(holdings: pd.DataFrame, prices: dict[str, float], today: date) -> list[dict]:
    """One row per holdings.csv row: gain now, short or long term, when it turns long term."""
    out = []
    for i, r in enumerate(holdings.itertuples(index=False)):
        qty, buy, px = num(r.qty), num(r.buy_price), prices.get(r.symbol)
        bd = r.buy_date if isinstance(r.buy_date, date) and not pd.isna(r.buy_date) else None
        row = {"id": i, "symbol": r.symbol, "qty": qty, "buy_price": buy, "buy_date": bd.isoformat() if bd else None,
               "price": px, "value": None, "gain": None, "gain_pct": None, "term": "unknown", "lt_from": None,
               "days_to_lt": None, "grandfathered": bool(bd and bd < GRANDFATHER_BEFORE)}
        if qty and buy and px:
            row["value"] = round(qty * px, 2)
            row["gain"] = round((px - buy) * qty, 2)
            row["gain_pct"] = round((px / buy - 1) * 100, 2)
        if bd:
            lf = long_term_from(bd)
            row["lt_from"] = lf.isoformat()
            row["term"] = "long" if today >= lf else "short"
            row["days_to_lt"] = max((lf - today).days, 0)
        out.append(row)
    return out


def _usable(lot: dict) -> bool:
    return lot["gain"] is not None and lot["term"] != "unknown" and not lot["grandfathered"] and lot["qty"]


def _round_trip_cost(value: float, cm: CostModel) -> float:
    """Selling `value` today and buying it back on a later day (brokerage, STT, fees, stamp duty, DP charge)."""
    return cm.sell_cost(value) + cm.buy_cost(value)


# ---- suggestions ---------------------------------------------------------------------------------------------------
def harvest_gains(lts: list[dict], exempt_left: float, tax: TaxModel, cm: CostModel) -> dict:
    """Long-term winners to sell (and buy back later) to use the year's unused exemption. Highest gain % first:
    the fewest rupees traded per rupee of gain."""
    rows, left = [], exempt_left
    cands = sorted((x for x in lts if _usable(x) and x["term"] == "long" and x["gain"] > 0),
                   key=lambda x: -x["gain_pct"])
    for x in cands:
        if left < 1:
            break
        per = x["price"] - x["buy_price"]
        q = min(x["qty"], math.floor(left / per)) if per > 0 else 0
        if q <= 0:
            continue
        gain, value = per * q, x["price"] * q
        rows.append({"id": x["id"], "symbol": x["symbol"], "qty": q, "of_qty": x["qty"], "price": x["price"],
                     "value": round(value, 2), "gain": round(gain, 2), "cost": round(_round_trip_cost(value, cm), 2)})
        left -= gain
    gain = sum(r["gain"] for r in rows)
    cost = sum(r["cost"] for r in rows)
    saved = gain * tax.ltcg_pct / 100
    return {"rows": rows, "gain": round(gain, 2), "tax_saved": round(saved, 2), "cost": round(cost, 2),
            "net": round(saved - cost, 2), "worth_it": bool(rows) and saved > cost}


def harvest_losses(lts: list[dict], st: float, lt: float, tax: TaxModel, cm: CostModel, fy: int) -> dict:
    """Losers to sell this year to cut the tax on gains already booked, short-term losses first (they offset both
    kinds). Each lot only as far as it still lowers the tax; the rest of a loss would only be carried forward."""
    base = tax_due(st, lt, tax, fy)["tax"]
    rows, cur_st, cur_lt = [], st, lt
    cands = sorted((x for x in lts if _usable(x) and x["gain"] < 0), key=lambda x: (x["term"] != "short", x["gain"]))
    for x in cands:
        now = tax_due(cur_st, cur_lt, tax, fy)["tax"]
        if now <= 0.5:
            break
        per = x["buy_price"] - x["price"]
        # the smallest quantity that takes the tax as low as this lot can: binary search on whole shares
        def after(q):
            return tax_due(cur_st - per * q, cur_lt, tax, fy)["tax"] if x["term"] == "short" else \
                tax_due(cur_st, cur_lt - per * q, tax, fy)["tax"]
        best = after(x["qty"])
        if best >= now - 0.5:
            continue
        lo, hi = 1, int(x["qty"])
        while lo < hi:
            mid = (lo + hi) // 2
            if after(mid) <= best + 0.5:
                hi = mid
            else:
                lo = mid + 1
        q = lo
        loss, value = per * q, x["price"] * q
        saved_here = now - after(q)                      # before the running totals move on
        if x["term"] == "short":
            cur_st -= loss
        else:
            cur_lt -= loss
        rows.append({"id": x["id"], "symbol": x["symbol"], "qty": q, "of_qty": x["qty"], "price": x["price"],
                     "term": x["term"], "value": round(value, 2), "loss": round(loss, 2),
                     "tax_saved": round(saved_here, 2), "cost": round(_round_trip_cost(value, cm), 2)})
    saved = base - tax_due(cur_st, cur_lt, tax, fy)["tax"]
    cost = sum(r["cost"] for r in rows)
    return {"rows": rows, "loss": round(sum(r["loss"] for r in rows), 2), "tax_saved": round(saved, 2),
            "cost": round(cost, 2), "net": round(saved - cost, 2), "worth_it": bool(rows) and saved > cost}


def waiting(lts: list[dict], tax: TaxModel, days: int = WAIT_DAYS) -> list[dict]:
    """Short-term winners that turn long term soon: selling after that date is taxed at the lower rate."""
    out = []
    for x in lts:
        if _usable(x) and x["term"] == "short" and x["gain"] > 0 and x["days_to_lt"] is not None and x["days_to_lt"] <= days:
            out.append({"id": x["id"], "symbol": x["symbol"], "qty": x["qty"], "gain": x["gain"], "lt_from": x["lt_from"],
                        "days": x["days_to_lt"],
                        "tax_saved": round(x["gain"] * (tax.stcg_pct - tax.ltcg_pct) / 100, 2)})
    return sorted(out, key=lambda r: r["days"])


def booked_from_fills(fy: int) -> dict:
    """Gains booked this financial year by the real delivery orders Quant Desk recorded (FIFO)."""
    try:
        closed, _ = fills.round_trips(fills.read())
    except Exception:
        closed = []
    st = lt = 0.0
    n = 0
    for t in closed:
        if t.get("product") not in (None, "CNC"):
            continue
        try:
            entry = pd.Timestamp(t["entry_time"]).date()
            exit_ = pd.Timestamp(t["exit_time"]).date()
        except Exception:
            continue
        if fy_of(exit_) != fy:
            continue
        n += 1
        if exit_ >= long_term_from(entry):
            lt += t["pnl"]
        else:
            st += t["pnl"]
    return {"st": round(st, 2), "lt": round(lt, 2), "trades": n}


def plan(holdings: pd.DataFrame, prices: dict[str, float], today: date, st: float | None, lt: float | None,
         tax: TaxModel, cm: CostModel, closed: set[str] | None = None) -> dict:
    fy = fy_of(today)
    booked = booked_from_fills(fy)
    source = "input" if st is not None or lt is not None else "fills"
    st = booked["st"] if st is None and source == "fills" else (st or 0.0)
    lt = booked["lt"] if lt is None and source == "fills" else (lt or 0.0)
    lts = lots(holdings, prices, today)
    pos = tax_due(st, lt, tax, fy)
    tb = trade_by(fy, closed)
    notes = []
    if any(x["grandfathered"] for x in lts):
        notes.append("Shares bought before 1 Feb 2018 have a grandfathered cost (their 31 Jan 2018 price): they are "
                     "left out here. Your broker's tax P&L shows their real gain.")
    if any(x["term"] == "unknown" for x in lts):
        notes.append("Holdings without a buy date can't be classed as short or long term: add the date on Portfolio.")
    if pos["carry_forward"] > 0:
        notes.append("This year's losses exceed the gains they can offset: the rest carries forward 8 years if you file "
                     "your income-tax return on time.")
    unreal = [x for x in lts if x["gain"] is not None]
    return {
        "fy": f"{fy}-{str(fy + 1)[2:]}", "today": today.isoformat(), "fy_end": date(fy + 1, 3, 31).isoformat(),
        "trade_by": tb.isoformat(), "days_left": (tb - today).days,
        "rates": {"stcg_pct": tax.stcg_pct, "ltcg_pct": tax.ltcg_pct, "exempt": tax.exempt_for_fy(fy)},
        "booked": {"st": round(st, 2), "lt": round(lt, 2), "source": source, "fills": booked},
        "position": pos, "lots": lts,
        "unrealised": {"st": round(sum(x["gain"] for x in unreal if x["term"] == "short"), 2),
                       "lt": round(sum(x["gain"] for x in unreal if x["term"] == "long"), 2),
                       "unknown": round(sum(x["gain"] for x in unreal if x["term"] == "unknown"), 2)},
        "harvest_gains": harvest_gains(lts, pos["exempt_left"], tax, cm),
        "harvest_losses": harvest_losses(lts, st, lt, tax, cm, fy),
        "wait": waiting(lts, tax),
        "notes": notes,
    }


def view(st: float | None = None, lt: float | None = None) -> dict:
    today = today_ist()
    h = data.holdings_df()
    syms = sorted({str(s) for s in h["symbol"]}) if len(h) else []
    prices = {}
    source = "close"
    if syms:
        q = quotes_svc.quotes(syms)
        prices = {x["symbol"]: float(x["price"]) for x in q["quotes"] if x.get("price")}
        source = q.get("source", "close")
    cfg = data.config()
    closed = {x["date"] for x in events.holiday_list(fy_of(today) + 1)}
    out = plan(h, prices, today, st, lt, TaxModel.from_config(cfg.get("tax")), CostModel.from_config(cfg.get("costs")),
               closed)
    out["price_source"] = source
    return out
