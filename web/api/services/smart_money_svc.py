"""Smart-money payloads from data/smart_money/ (scanner.smart_money loaders), cached by the files' identity; the
refresh runs in a background thread with a lock. No GET path touches the network.

Contract: docs/smart_money_spec.md section 6. Every sm.* call passes folder=_folder() (P.data / "smart_money"), so
paths.configure() repoints it for the contract tests without touching scanner globals. NaN never reaches JSON: every
value goes through _s / _f / _i / _b. Cached frames are shared between requests: only ever filtered, never mutated.
"""
from __future__ import annotations

import math
import re
import threading
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from scanner import smart_money as sm

from . import data
from .. import errors
from ..caches import KeyedCache, file_key, register
from ..errors import ApiException
from ..paths import P
from ..util import inum, now_ist, num, today_ist

NOTE_MAIN = ("What you see here are deals and holdings that big investors must report by law. It is not live, and "
             "it is not a tip. Bulk and block deals show up after the market closes. Insider trades can be reported "
             "up to about 4 trading days late, and shareholding only once a quarter, up to 3 weeks late. Many "
             "\"bulk deals\" are trading firms that buy and sell the same day: we mark those as \"intraday\" and "
             "leave them out of the buyer and seller lists. Studies on Indian stocks find most of the price move "
             "around bulk deals happens before or on the deal day. Promoter buying in small companies has been "
             "followed by gains on average, but averages hide many losers, and those stocks can be hard to trade. "
             "A famous name buying does not mean the price will rise. Big investors also lose money, and they can "
             "sell without anyone knowing until the next filing. A stock dropping off the shareholding list only "
             "means they now hold less than 1%, not always a full exit. Use this as one clue next to your own "
             "analysis, never as a buy or sell signal. This is not investment advice.")
NOTE_DEALS = ("Bulk deal = one client traded more than 0.5% of a company's shares in a day. Block deal = a single "
              "trade of at least ₹25 crore in NSE's special morning or afternoon window. Both are published after "
              "the close. Trading firms that bought and sold about the same quantity the same day are listed "
              "separately under 'Intraday / arbitrage'.")
NOTE_INSIDER = ("Promoters, directors and key staff must report trades over ₹10 lakh a quarter: they tell the "
                "company within 2 trading days and the company tells NSE within 2 more, so a filing can be about 4 "
                "or more trading days old. Only 'Market Purchase' and 'Market Sale' are real buy/sell decisions; "
                "ESOPs, gifts, transfers and pledges are not. A pledge 'invocation' means a lender sold the shares.")
NOTE_HOLDINGS = ("Shareholding is filed once a quarter, up to 21 days after the quarter ends, and only holders with "
                 "1% or more are named - so 'no longer shown' means they now hold less than 1%, not always a full "
                 "exit. Bulk/block deals and insider trades here are from the last {days} days.")
NOTE_FLOWS = ("Market-wide buying and selling in the cash market by foreign (FII/FPI) and domestic (DII) "
              "institutions, in ₹ crore, as NSE publishes it the same evening (provisional). It is not per stock, "
              "and studies find these flows mostly follow the market rather than predict it. History builds up from "
              "the day of your first refresh.")
NOTE_STOCK = ("Disclosed data only: bulk/block deals, insider filings and the quarterly shareholding pattern. It is "
              "not live and not a buy or sell signal.")

SOURCES = ("deals", "insider", "flows", "holdings")
SOURCE_STATES = ("ok", "partial", "failed", "skipped", "never")
MODE_KINDS = ("market", "pledge", "pledge_invoked", "off_market", "esop", "gift", "inter_se", "preferential", "other")
EXIT_KINDS = ("full_exit", "below_1pct", "category_exit")      # what counts as an "exit" (sold_part does not)
PCT_COLS = ("promoter_pct", "public_pct", "fii_pct", "dii_pct", "mf_pct", "insurance_pct", "banks_pct",
            "pension_pct", "aif_pct")
FLOW_VALUE_COLS = ("fii_buy_cr", "fii_sell_cr", "fii_net_cr", "dii_buy_cr", "dii_sell_cr", "dii_net_cr")
SYMBOL_RE = re.compile(r"^[A-Z0-9&\-_.]{1,30}$")
STALE_DAYS = 5
NEVER = {"status": "never", "message": None, "rows_added": 0, "last_ok_at": None, "latest_date": None}


# ------------------------------------------------------------------ folder and caches
def _folder() -> Path:
    return P.data / "smart_money"


def _key() -> tuple:
    return tuple(file_key(p) for p in sm.files(_folder()).values())


_base_cache = register(KeyedCache(1))
_derived_cache = register(KeyedCache(8))


def _base(key: tuple | None = None) -> dict:
    """Every stored table plus the net deals and company names; recomputed only when one of the files changes."""
    return _base_cache.get(key if key is not None else _key(), _build_base)


def _build_base() -> dict:
    f = _folder()
    deals = sm.load_deals(folder=f)
    insider = sm.load_insider(folder=f)
    flows = sm.load_flows(folder=f)
    holdings = sm.load_holdings(folder=f)
    holders = sm.load_holders(folder=f)
    state = sm.load_state(folder=f)
    net = sm.net_deals(deals, sm.promoter_sets(holders, insider), sm.share_counts(holdings))
    # the universe's company names win over the names in NSE's filings (those vary in spelling)
    companies = {**sm.company_names(net, insider, holdings),
                 **{s: m["company"] for s, m in data.symbol_meta().items() if m.get("company")}}
    return {"deals": deals, "net": net, "insider": insider, "flows": flows, "holdings": holdings,
            "holders": holders, "state": state if isinstance(state, dict) else {}, "companies": companies,
            "deals_asof": sm.latest(deals, "date"), "insider_asof": sm.latest(insider, "disclosed"),
            "flows_asof": sm.latest(flows, "date"), "period": sm.latest(holdings, "period")}


def _derived(days: int) -> dict:
    """Events and per-stock signals of a `days` window; d["base"] is the base they were computed from."""
    key = _key()
    b = _base(key)                  # before the derived cache's lock (its compute must not wait on another cache)
    return _derived_cache.get((key, days), lambda: _build_derived(b, days))


def _anchor(b: dict) -> str:
    """The later of the newest deal and insider dates, so "30 days" means the last 30 days of data."""
    return max([d for d in (b["deals_asof"], b["insider_asof"]) if d], default=today_ist().isoformat())


def _build_derived(b: dict, days: int) -> dict:
    anchor = _anchor(b)
    since = sm.window(anchor, days)
    shp_since = sm.window(anchor, max(days, sm.SHP_EVENT_DAYS))
    ev = sm.events(b["net"], b["insider"], b["holdings"], b["holders"], since, shp_since, b["companies"])
    sig = sm.stock_signals(ev, b["net"], b["holdings"], since)
    return {"base": b, "anchor": anchor, "since": since, "events": ev, "signals": sig}


def _has_data(b: dict) -> bool:
    return any(len(b[k]) for k in ("deals", "insider", "flows", "holdings"))


# ------------------------------------------------------------------ value conversion (NaN never reaches JSON)
def _s(x) -> str | None:
    """A scalar as str; None for None / NaN / '' (and for lists, which are not scalars)."""
    if x is None or isinstance(x, (list, tuple, dict, set, np.ndarray)):
        return None
    try:
        if pd.isna(x):
            return None
    except (TypeError, ValueError):
        return None
    s = str(x)
    return s or None


def _f(x, nd: int | None = None) -> float | None:
    return num(x, nd)


def _f0(x, nd: int | None = None) -> float:
    """For required float fields: unknown -> 0.0 (sums, where NaN already means nothing)."""
    v = num(x, nd)
    return v if v is not None else 0.0


def _i(x) -> int | None:
    return inum(x)


def _i0(x) -> int:
    v = inum(x)
    return v if v is not None else 0


def _b(x) -> bool:
    """bool(NaN) is True: a missing flag must be False."""
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return False
    try:
        return bool(x)
    except (TypeError, ValueError):
        return False


def _list(x) -> list[str]:
    return [str(v) for v in x] if isinstance(x, (list, tuple, np.ndarray)) else []


def _pick(x, allowed: tuple, default):
    v = _s(x)
    return v if v in allowed else default


def _cat(x) -> str:
    return _pick(x, tuple(sm.CATEGORY_LABELS), "other")


def _label(cat: str) -> str:
    return sm.CATEGORY_LABELS.get(cat, "Other")


def _sym(symbol: str | None) -> str:
    return (symbol or "").strip().upper()


# ------------------------------------------------------------------ frame helpers
def _records(df: pd.DataFrame) -> list[dict]:
    return df.to_dict("records")


def _flag(df: pd.DataFrame, col: str) -> pd.Series:
    """A bool column as a clean mask (an object column with NaN would count NaN as True)."""
    s = df[col]
    return s if s.dtype == bool else s.map(_b).astype(bool)


def _since(df: pd.DataFrame, col: str, since: str | None) -> pd.DataFrame:
    """Rows whose ISO date `col` is on or after `since` (ISO strings compare correctly as text)."""
    if not since or not len(df):
        return df.iloc[0:0]
    s = df[col]
    if s.dtype.kind in "fiub":      # an all-missing column read back as numbers: no dates at all
        return df.iloc[0:0]
    return df[s >= since]


def _newest_first(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    return df.sort_values(cols, ascending=[False] * len(cols), na_position="last", kind="stable")


def _first(df: pd.DataFrame, col: str) -> str | None:
    v = df[col].dropna()
    return _s(v.iloc[0]) if len(v) else None


def _earliest(df: pd.DataFrame, col: str) -> str | None:
    v = df[col].dropna()
    return _s(v.min()) if len(v) else None


def _page(df: pd.DataFrame, page: int, page_size: int) -> pd.DataFrame:
    start = (page - 1) * page_size
    return df.iloc[start:start + page_size]


def _prev_quarter_end(period: str | None) -> str | None:
    """'2026-09-30' -> '2026-06-30' (the calendar quarter end before)."""
    try:
        d = date.fromisoformat(str(period)[:10])
    except ValueError:
        return None
    q_start = date(d.year, (d.month - 1) // 3 * 3 + 1, 1)
    return (q_start - timedelta(days=1)).isoformat()


def _streak(values: list) -> int:
    """values newest first: +n = n buying days in a row up to the newest, -n = n selling days, 0 = none/zero."""
    vals = [num(v) for v in values]
    if not vals or not vals[0]:
        return 0
    up = vals[0] > 0
    n = 0
    for v in vals:
        if not v or (v > 0) != up:
            break
        n += 1
    return n if up else -n


# ------------------------------------------------------------------ rows -> JSON (fields exactly as the models)
def _deal(r: dict, companies: dict) -> dict:
    sym = _s(r.get("symbol")) or ""
    cat = _cat(r.get("category"))
    return {"id": _s(r.get("id")) or "", "date": _s(r.get("date")) or "", "symbol": sym,
            "company": companies.get(sym) or _s(r.get("security")),
            "kind": _pick(r.get("kind"), ("bulk", "block", "both"), "bulk"),
            "side": _pick(r.get("side"), ("BUY", "SELL", "FLAT"), "FLAT"),
            "client": _s(r.get("client")) or "", "client_key": _s(r.get("client_key")) or "",
            "category": cat, "category_label": _label(cat), "sub_label": _s(r.get("sub_label")),
            "investor": _s(r.get("investor")), "round_trip": _b(r.get("round_trip")),
            "buy_qty": _i0(r.get("buy_qty")), "sell_qty": _i0(r.get("sell_qty")), "net_qty": _i0(r.get("net_qty")),
            "buy_value": _f0(r.get("buy_value"), 0), "sell_value": _f0(r.get("sell_value"), 0),
            "net_value": _f0(r.get("net_value"), 0), "avg_price": _f(r.get("avg_price"), 2),
            "pct_equity": _f(r.get("pct_equity"), 3), "counterparties": _list(r.get("counterparties"))}


def _insider(r: dict, companies: dict) -> dict:
    sym = _s(r.get("symbol")) or ""
    cat = _cat(r.get("category"))
    return {"id": _s(r.get("id")) or "", "symbol": sym, "company": companies.get(sym) or _s(r.get("company")),
            "person": _s(r.get("person")) or "",
            "role": _pick(r.get("role"), ("promoter", "insider", "other"), "other"),
            "person_category": _s(r.get("person_category")), "category": cat, "category_label": _label(cat),
            "sub_label": _s(r.get("sub_label")), "investor": _s(r.get("investor")),
            "side": _pick(r.get("side"), ("BUY", "SELL"), None), "mode": _s(r.get("mode")),
            "mode_kind": _pick(r.get("mode_kind"), MODE_KINDS, "other"), "is_market": _b(r.get("is_market")),
            "qty": _i(r.get("qty")), "value": _f(r.get("value"), 0), "avg_price": _f(r.get("avg_price"), 2),
            "before_pct": _f(r.get("before_pct"), 2), "after_pct": _f(r.get("after_pct"), 2),
            "change_pts": _f(r.get("change_pts"), 2), "before_shares": _i(r.get("before_shares")),
            "after_shares": _i(r.get("after_shares")), "trade_from": _s(r.get("trade_from")),
            "trade_to": _s(r.get("trade_to")), "disclosed": _s(r.get("disclosed")),
            "delay_days": _i(r.get("delay_days")), "fully_exited": _b(r.get("fully_exited")),
            "xbrl": _s(r.get("xbrl"))}


def _event(r: dict, companies: dict) -> dict:
    sym = _s(r.get("symbol")) or ""
    cat = _cat(r.get("category"))
    return {"id": _s(r.get("id")) or "", "date": _s(r.get("date")) or "", "symbol": sym,
            "company": companies.get(sym) or _s(r.get("company")), "event": _s(r.get("event")),
            "direction": _s(r.get("direction")), "source": _s(r.get("source")), "who": _s(r.get("who")),
            "investor": _s(r.get("investor")), "category": cat, "category_label": _label(cat),
            "sub_label": _s(r.get("sub_label")), "value": _f(r.get("value"), 0), "qty": _i(r.get("qty")),
            "pct_before": _f(r.get("pct_before"), 2), "pct_after": _f(r.get("pct_after"), 2),
            "change_pts": _f(r.get("change_pts"), 2), "pct_equity": _f(r.get("pct_equity"), 3),
            "period": _s(r.get("period")), "prev_period": _s(r.get("prev_period")),
            "exit_kind": _pick(r.get("exit_kind"), ("full_exit", "below_1pct", "sold_part", "category_exit"), None),
            "text": _s(r.get("text")) or ""}


def _stock(r: dict, companies: dict) -> dict:
    sym = _s(r.get("symbol")) or ""
    return {"symbol": sym, "company": companies.get(sym) or _s(r.get("company")),
            "direction": _pick(r.get("direction"), ("up", "down", "mixed"), "mixed"),
            "up_events": _i0(r.get("up_events")), "down_events": _i0(r.get("down_events")),
            "up_score": _i0(r.get("up_score")), "down_score": _i0(r.get("down_score")),
            "deal_buy_value": _f0(r.get("deal_buy_value"), 0), "deal_sell_value": _f0(r.get("deal_sell_value"), 0),
            "deal_net_value": _f0(r.get("deal_net_value"), 0), "inst_buyers": _i0(r.get("inst_buyers")),
            "inst_sellers": _i0(r.get("inst_sellers")), "famous_buyers": _list(r.get("famous_buyers")),
            "famous_sellers": _list(r.get("famous_sellers")),
            "insider_buy_value": _f0(r.get("insider_buy_value"), 0),
            "insider_sell_value": _f0(r.get("insider_sell_value"), 0),
            "promoter_buying": _b(r.get("promoter_buying")), "promoter_selling": _b(r.get("promoter_selling")),
            "pledge_invoked": _b(r.get("pledge_invoked")), "exits": _i0(r.get("exits")),
            "fii_chg_pts": _f(r.get("fii_chg_pts"), 2), "dii_chg_pts": _f(r.get("dii_chg_pts"), 2),
            "mf_chg_pts": _f(r.get("mf_chg_pts"), 2), "promoter_chg_pts": _f(r.get("promoter_chg_pts"), 2),
            "period": _s(r.get("period")), "last_date": _s(r.get("last_date")) or "",
            "reasons": _list(r.get("reasons"))}


def _period(r: dict) -> dict:
    bc = _s(r.get("broadcast"))
    return {"period": _s(r.get("period")) or "", "broadcast": bc[:10] if bc else None,
            "source": _pick(r.get("source"), ("xbrl", "master"), "master"), "total_shares": _i(r.get("total_shares")),
            **{c: _f(r.get(c), 2) for c in PCT_COLS}}


def _holder(r: dict) -> dict:
    cat = _cat(r.get("category"))
    return {"holder": _s(r.get("holder")) or "", "holder_key": _s(r.get("holder_key")) or "",
            "group": _pick(r.get("group"), ("promoter", "public"), "public"), "category": cat,
            "category_label": _label(cat), "sub_label": _s(r.get("sub_label")), "investor": _s(r.get("investor")),
            "pct": _f(r.get("pct"), 2), "prev_pct": _f(r.get("prev_pct"), 2), "change_pts": _f(r.get("change_pts"), 2),
            "shares": _i(r.get("shares")), "status": _s(r.get("status"))}


def _flow(r: dict) -> dict:
    return {"date": _s(r.get("date")) or "", **{c: _f(r.get(c), 2) for c in FLOW_VALUE_COLS}}


def _with_reasons(stocks: pd.DataFrame, ev: pd.DataFrame, direction: str, companies: dict) -> list[dict]:
    """Stocks as SmStock with `reasons` rebuilt from `ev` for one direction, so a list of sellers explains the
    selling even for a stock that is also being bought."""
    by_sym = {s: g for s, g in ev.groupby("symbol", sort=False)} if len(ev) else {}
    out = []
    for r in _records(stocks):
        row = _stock(r, companies)
        g = by_sym.get(row["symbol"])
        row["reasons"] = _list(sm.top_reasons(g, direction)) if g is not None else []
        out.append(row)
    return out


# ------------------------------------------------------------------ freshness and status
def _age_days(iso: str) -> int:
    try:
        return (today_ist() - date.fromisoformat(str(iso)[:10])).days
    except ValueError:
        return 10 ** 6


def _freshness(b: dict) -> dict:
    last_run = b["state"].get("last_run")
    refreshed = _s(last_run.get("finished_at")) if isinstance(last_run, dict) else None
    asof = b["deals_asof"]
    return {"deals": asof, "insider": b["insider_asof"], "flows": b["flows_asof"], "holdings_period": b["period"],
            "refreshed_at": refreshed, "stale": refreshed is None or asof is None or _age_days(asof) > STALE_DAYS}


def _source(s) -> dict:
    if not isinstance(s, dict):
        return dict(NEVER)
    return {"status": _pick(s.get("status"), SOURCE_STATES, "never"), "message": _s(s.get("message")),
            "rows_added": _i0(s.get("rows_added")), "last_ok_at": _s(s.get("last_ok_at")),
            "latest_date": _s(s.get("latest_date"))}


def _state_errors(state: dict) -> list[str]:
    errs = state.get("errors")
    return [str(e) for e in errs] if isinstance(errs, list) else []


def status() -> dict:
    b = _base()
    srcs = b["state"].get("sources")
    srcs = srcs if isinstance(srcs, dict) else {}
    return {"run": run_status(), "freshness": _freshness(b), "sources": {n: _source(srcs.get(n)) for n in SOURCES},
            "errors": _state_errors(b["state"])}


# ------------------------------------------------------------------ endpoints
def overview(days: int) -> dict:
    d = _derived(days)
    b = d["base"]
    since, ev, sig, comp = d["since"], d["events"], d["signals"], b["companies"]
    has = _has_data(b)

    net_w = _since(b["net"], "date", since)
    rt = _flag(net_w, "round_trip")
    firm = net_w[~rt]                              # positions kept, not intraday round trips
    big = firm[firm["category"].isin(list(sm.BIG_MONEY))]["net_value"]
    inst = firm[firm["category"].isin(list(sm.INSTITUTIONS))]["net_value"]
    ins_w = _since(b["insider"], "disclosed", since)
    mkt = ins_w[_flag(ins_w, "is_market")]
    fl = b["flows"]
    last_flow = fl.iloc[-1].to_dict() if len(fl) else {}
    kpis = {"days": days, "since": since if has else None,
            "big_buy_value": _f0(big[big > 0].sum(), 0), "big_sell_value": _f0(abs(big[big < 0].sum()), 0),
            "inst_net_value": _f0(inst.sum(), 0),
            "stocks_bought": int((sig["deal_net_value"] > 0).sum()),
            "stocks_sold": int((sig["deal_net_value"] < 0).sum()),
            "insider_buy_value": _f0(mkt[mkt["side"] == "BUY"]["value"].sum(), 0),
            "insider_sell_value": _f0(mkt[mkt["side"] == "SELL"]["value"].sum(), 0),
            "exits": int(ev["exit_kind"].isin(EXIT_KINDS).sum()), "intraday_rows": int(rt.sum()),
            "fii_net_cr": _f(last_flow.get("fii_net_cr"), 2), "dii_net_cr": _f(last_flow.get("dii_net_cr"), 2),
            "flows_date": _s(last_flow.get("date"))}

    asof = b["deals_asof"]
    net = b["net"]
    day = net[net["date"] == asof] if asof else net.iloc[0:0]
    day = day[~_flag(day, "round_trip")]
    day = day.assign(_big=day["category"].isin(list(sm.BIG_MONEY)), _abs=day["net_value"].abs())
    day = _newest_first(day, ["_big", "_abs"]).head(20)       # big money first, then the largest

    ins = b["insider"]
    latest_ins = _newest_first(ins[_flag(ins, "is_market")], ["disclosed", "value"]).head(10)
    exits = ev[(ev["direction"] == "down") & ev["exit_kind"].notna()]
    exits = _newest_first(exits, ["date", "weight"]).head(10)

    return {"freshness": _freshness(b), "run": run_status(), "days": days, "kpis": kpis,
            "top_bought": _with_reasons(sm.accumulating(sig).head(10), ev, "up", comp),
            "top_sold": _with_reasons(sm.exiting(sig).head(10), ev, "down", comp),
            "latest_deals_date": asof, "latest_deals": [_deal(r, comp) for r in _records(day)],
            "latest_insider": [_insider(r, comp) for r in _records(latest_ins)],
            "exits": [_event(r, comp) for r in _records(exits)],
            "flows": [_flow(r) for r in _records(fl.iloc[::-1].head(10))],
            "has_data": has, "errors": _state_errors(b["state"]), "note": NOTE_MAIN}


def deals(days: int, side: str, kind: str, category: str, symbol: str | None, intraday: bool, page: int,
          page_size: int) -> dict:
    b = _base()
    asof = b["deals_asof"]
    since = sm.window(asof, days)              # anchored at the newest deal day: days=1 is always that day
    rows = _since(b["net"], "date", since)
    if kind == "bulk":
        rows = rows[rows["kind"].isin(["bulk", "both"])]
    elif kind == "block":
        rows = rows[rows["kind"].isin(["block", "both"])]
    sym = _sym(symbol)
    if sym:
        rows = rows[rows["symbol"] == sym]
    rt = _flag(rows, "round_trip")
    firm = rows[~rt]
    counts = {"buys": int((firm["side"] == "BUY").sum()), "sells": int((firm["side"] == "SELL").sum()),
              "intraday": int(rt.sum()),
              "by_category": {str(k): int(v) for k, v in firm["category"].value_counts().items()}}
    rows = rows[rt == intraday]
    rows = rows[sm.category_mask(rows["category"], category)]
    if side == "buy":
        rows = rows[rows["side"] == "BUY"]
    elif side == "sell":
        rows = rows[rows["side"] == "SELL"]
    comp = b["companies"]
    return {"freshness": _freshness(b), "days": days, "since": since, "until": asof, "intraday": intraday,
            "total": len(rows), "page": page, "page_size": page_size,
            "rows": [_deal(r, comp) for r in _records(_page(rows, page, page_size))], "counts": counts,
            "note": NOTE_DEALS}


def insider(days: int, side: str, category: str, mode: str, symbol: str | None, page: int, page_size: int) -> dict:
    b = _base()
    asof = b["insider_asof"]
    since = sm.window(asof, days)
    rows = _since(b["insider"], "disclosed", since)
    sym = _sym(symbol)
    if sym:
        rows = rows[rows["symbol"] == sym]
    if category in ("promoter", "insider"):
        rows = rows[rows["role"] == category]
    mk = _flag(rows, "is_market")
    m = rows[mk]
    counts = {"buys": int((m["side"] == "BUY").sum()), "sells": int((m["side"] == "SELL").sum()),
              "buy_value": _f0(m[m["side"] == "BUY"]["value"].sum(), 0),
              "sell_value": _f0(m[m["side"] == "SELL"]["value"].sum(), 0),
              "pledge_invoked": int((rows["mode_kind"] == "pledge_invoked").sum()),
              "full_exits": int(_flag(rows, "fully_exited").sum())}
    if mode == "market":                       # open-market trades plus forced pledge sales
        rows = rows[mk | (rows["mode_kind"] == "pledge_invoked")]
    if side == "buy":
        rows = rows[rows["side"] == "BUY"]
    elif side == "sell":
        rows = rows[rows["side"] == "SELL"]
    rows = _newest_first(rows, ["disclosed", "value"])
    comp = b["companies"]
    return {"freshness": _freshness(b), "days": days, "since": since, "until": asof, "total": len(rows),
            "page": page, "page_size": page_size,
            "rows": [_insider(r, comp) for r in _records(_page(rows, page, page_size))], "counts": counts,
            "note": NOTE_INSIDER}


def holdings(view: str, days: int, category: str, symbol: str | None) -> dict:
    d = _derived(days)
    b = d["base"]
    comp = b["companies"]
    ev = d["events"]
    if view == "accumulating":
        ev = ev[ev["direction"] == "up"]
    elif view == "exiting":
        ev = ev[ev["direction"] == "down"]
    ev = ev[sm.category_mask(ev["category"], category)]
    sym = _sym(symbol)
    if sym:
        ev = ev[ev["symbol"] == sym]
    sig = d["signals"]
    stocks = sm.accumulating(sig) if view == "accumulating" else sm.exiting(sig) if view == "exiting" else sig
    stocks = stocks[stocks["symbol"].isin(ev["symbol"].dropna().unique())].head(200)
    if view == "all":
        rows = [_stock(r, comp) for r in _records(stocks)]
    else:
        rows = _with_reasons(stocks, ev, "up" if view == "accumulating" else "down", comp)
    return {"freshness": _freshness(b), "view": view, "days": days, "since": d["since"] if _has_data(b) else None,
            "latest_period": b["period"], "previous_period": _prev_quarter_end(b["period"]),
            "coverage": int(b["holdings"]["symbol"].nunique()), "stocks": rows,
            "events": [_event(r, comp) for r in _records(ev.head(500))], "note": NOTE_HOLDINGS.format(days=days)}


def flows(days: int) -> dict:
    b = _base()
    fl = b["flows"]                            # date ascending
    since = sm.window(b["flows_asof"], days)
    w = _since(fl, "date", since)
    full = fl.iloc[::-1]
    return {"freshness": _freshness(b), "days": days, "since": since, "first_date": _earliest(fl, "date"),
            "rows": [_flow(r) for r in _records(w.iloc[::-1])],
            "fii_net_cr_total": _f(w["fii_net_cr"].sum(min_count=1), 2),
            "dii_net_cr_total": _f(w["dii_net_cr"].sum(min_count=1), 2),
            "fii_streak": _streak(full["fii_net_cr"].tolist()), "dii_streak": _streak(full["dii_net_cr"].tolist()),
            "note": NOTE_FLOWS}


def stock(symbol: str, days: int) -> dict:
    sym = _sym(symbol)
    if not SYMBOL_RE.fullmatch(sym):
        raise ApiException("VALIDATION", "Invalid symbol.", "Use an NSE symbol such as RELIANCE or M&M.",
                           {"param": "symbol"})
    b = _base()
    comp = b["companies"]
    anchor = _anchor(b)                           # the same window as _derived(days)
    since = sm.window(anchor, days)
    shp_since = sm.window(anchor, max(days, sm.SHP_EVENT_DAYS))
    # events, signals and holder changes all work stock by stock: computed on this stock's rows alone they are the
    # same rows as _derived(days) gives, without building a year of the whole market for one Chart side panel
    net = b["net"][b["net"]["symbol"] == sym]
    ins = b["insider"][b["insider"]["symbol"] == sym]
    hd_sym = b["holdings"][b["holdings"]["symbol"] == sym]
    hs_sym = b["holders"][b["holders"]["symbol"] == sym]
    ev = sm.events(net, ins, hd_sym, hs_sym, since, shp_since, comp)
    sig = sm.stock_signals(ev, net, hd_sym, since)
    dl = _since(net, "date", since).head(200)
    il = _newest_first(_since(ins, "disclosed", since), ["disclosed", "value"]).head(200)
    hp = _newest_first(hd_sym, ["period"]).head(4)
    hc = sm.holder_changes(hs_sym, hd_sym)
    es = ev.head(200)
    srow = _records(sig.head(1))
    return {"symbol": sym, "company": comp.get(sym), "freshness": _freshness(b), "days": days,
            "has_data": bool(len(dl) or len(il) or len(hp) or len(hc) or len(es)),
            "summary": _stock(srow[0], comp) if srow else None,
            "deals": [_deal(r, comp) for r in _records(dl)], "insider": [_insider(r, comp) for r in _records(il)],
            "holdings": [_period(r) for r in _records(hp)], "holders_period": _first(hc, "period"),
            "holders_prev_period": _first(hc, "prev_period"), "holders": [_holder(r) for r in _records(hc)],
            "events": [_event(r, comp) for r in _records(es)], "note": NOTE_STOCK}


# ------------------------------------------------------------------ background refresh
_run_lock = threading.Lock()
_run: dict = {"thread": None, "state": "idle", "message": None, "started_at": None, "finished_at": None, "errors": []}


def run_status() -> dict:
    """SmRefreshRun: our own background refresh, or one the daily scan (another process) holds the lock for."""
    alive = _run["thread"] is not None and _run["thread"].is_alive()
    other = not alive and sm.refresh_running(_folder())
    state = "running" if alive or other else _run["state"]
    message = "Refresh started by the daily scan" if other else _run["message"]
    return {"state": state, "running": alive or other, "message": message, "started_at": _run["started_at"],
            "finished_at": _run["finished_at"], "errors": list(_run["errors"])}


def start_refresh(days: int) -> dict:
    with _run_lock:
        if (_run["thread"] is not None and _run["thread"].is_alive()) or sm.refresh_running(_folder()):
            raise ApiException("SCAN_BUSY", "A smart-money refresh is already running.",
                               "Wait for it to finish - this page updates by itself.",
                               {"started": str(_run["started_at"] or "?"), "by": "smart-money", "pid": None})
        _run.update(state="running", message="Starting...", started_at=now_ist().isoformat(timespec="seconds"),
                    finished_at=None, errors=[])
        t = threading.Thread(target=_worker, args=(days,), name="smart-money-refresh", daemon=True)
        _run["thread"] = t
        t.start()
    return run_status()


def _worker(days: int) -> None:
    """Runs sm.refresh (never raises for network problems); the caches see the new files by their identity."""
    try:
        rep = sm.refresh(days=days, log=lambda m: _run.update(message=str(m)[:300]), folder=_folder())
        srcs = [s for s in (rep.get("sources") or {}).values() if isinstance(s, dict)]
        errs = [str(e) for e in rep.get("errors") or []]
        failed = all(s.get("status") in ("failed", "skipped") for s in srcs)
        took = num(rep.get("elapsed_s")) or 0.0
        if failed:
            msg = f"Nothing could be refreshed ({took:.0f} s)" + (f": {errs[0]}" if errs else "")
        else:
            msg = f"Done in {took:.0f} s" + (" with problems" if errs else "")
        _run.update(state="failed" if failed else "done", message=msg[:300], errors=errs)
    except Exception as e:
        errors.log.exception("smart-money refresh failed")
        _run.update(state="failed", message=f"{type(e).__name__}: {e}"[:300])
    finally:
        _run["finished_at"] = now_ist().isoformat(timespec="seconds")
