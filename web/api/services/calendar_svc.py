"""Market calendar (GET /api/calendar): what is coming up on NSE, your stocks first.

  * Results: board meetings for financial results (NSE's event calendar). Results day moves a stock more than an
    ordinary day, and a stop can gap overnight.
  * Ex-dividend, rights, bonus, split and buyback dates (NSE's corporate actions, cached per quarter). With T+1
    settlement the record date is the ex-date: you must own the shares at the close of the trading day BEFORE it.
  * F&O expiries (NSE's contract list for the index underlyings and one stock): weekly and monthly.
  * Market holidays (NSE's trading-holiday list).
  * Economic events (scanner/econ.py): RBI and US Fed decisions, India's CPI / WPI / IIP / GDP releases, the Budget.
  * IPOs: issues open now and announced (NSE's IPO lists): subscription dates and price band.

Company announcements (GET /api/announcements): NSE's filings of the last few days, for one stock or for your
holdings and watchlists, routine ones (analyst meets, newspaper copies) left out unless asked for.

Every source can fail on its own (NSE refuses or times out): the others still show, and a note says what is missing.
"""
from __future__ import annotations

import math
import re
from datetime import date, timedelta

import pandas as pd

from scanner import dividends, econ, events, options as opt, watch

from . import data
from ..util import today_ist

MAX_DAYS = 90
STOCK_FNO_PROBE = "RELIANCE"         # one stock's contract list gives the stock F&O expiries
BONUS = re.compile(r"\bBONUS\b", re.I)
SPLIT = re.compile(r"SPLIT|SUB[- ]?DIVISION", re.I)
BUYBACK = re.compile(r"BUY\s*-?\s*BACK", re.I)
KINDS = ("econ", "results", "dividend", "rights", "bonus", "split", "buyback", "ipo", "expiry", "holiday", "meeting")
ROUTINE = re.compile(r"analyst|institutional investor|con\.? ?call|newspaper|trading window|certificate|loss of share|"
                     r"duplicate|reg\. ?74|regulation 74|esop|esos|investor presentation|monitoring agency|"
                     r"record date|book closure|shareholders meeting|postal ballot", re.I)


def _holidays(start: date, end: date) -> tuple[list[dict], bool]:
    out, ok = [], False
    for y in range(start.year, end.year + 1):
        got = events.holiday_list(y)
        ok = ok or bool(got)
        out += [h for h in got if start.isoformat() <= h["date"] <= end.isoformat()]
    return out, ok


def _closed(start: date, end: date) -> set[str]:
    days = set()
    for y in range(start.year, end.year + 1):
        days |= {h["date"] for h in events.holiday_list(y)}
    return days


def prev_trading_day(d: date, closed: set[str]) -> date:
    """The trading day before `d` (weekends and NSE holidays skipped)."""
    x = d - timedelta(days=1)
    while x.weekday() >= 5 or x.isoformat() in closed:
        x -= timedelta(days=1)
    return x


def _quarter_rows(start: date, end: date) -> tuple[list[dict], list[str]]:
    rows, missing = [], []
    for y, q in dividends._quarters(start, end):
        got = dividends.fetch_quarter(y, q)
        if got is None:
            missing.append(f"{y} Q{q}")
        else:
            rows += got
    return rows, missing


def corporate_actions(start: date, end: date, closed: set[str]) -> tuple[list[dict], list[str]]:
    """Ex-dated actions between start and end: dividends (Rs a share), rights, bonus, split, buyback."""
    rows, missing = _quarter_rows(start, end)
    out, seen = [], set()
    for r in rows:
        if str(r.get("series") or "").strip() not in dividends.EQUITY_SERIES:
            continue
        sym = str(r.get("symbol") or "").strip().upper()
        ex = dividends._date(r.get("exDate"))
        if not sym or ex is None or not (pd.Timestamp(start) <= ex <= pd.Timestamp(end)):
            continue
        subj = re.sub(r"\s+", " ", str(r.get("subject") or "")).strip()
        try:
            fv = float(str(r.get("faceVal") or "").strip())
        except ValueError:
            fv = None
        kinds = []
        if dividends.DIV_WORD.search(subj) and not re.search(r"DIVISION", subj, re.I):
            kinds.append("dividend")
        if dividends.RIGHTS.search(subj):
            kinds.append("rights")
        if BONUS.search(subj):
            kinds.append("bonus")
        if SPLIT.search(subj):
            kinds.append("split")
        if BUYBACK.search(subj):
            kinds.append("buyback")
        exd = ex.date()
        for k in kinds:
            key = (sym, exd, k, subj.upper())
            if key in seen:                       # NSE lists an action once per series and again when revised
                continue
            seen.add(key)
            ev = {"date": exd.isoformat(), "kind": k, "symbol": sym, "detail": subj,
                  "buy_by": prev_trading_day(exd, closed).isoformat()}
            if k == "dividend":
                ev["amount"] = dividends.dividend_amount(subj, fv)
            out.append(ev)
    # the same dividend amount on the same day from a corrected notice counts once
    uniq: dict[tuple, dict] = {}
    for e in out:
        uniq.setdefault((e["symbol"], e["date"], e["kind"], e.get("amount")), e)
    return list(uniq.values()), missing


def _purpose_kind(purpose: str) -> str:
    p = purpose.lower()
    if "result" in p:
        return "results"
    return "meeting"


def expiries(start: date, end: date) -> tuple[list[dict], bool]:
    """F&O expiries in the window: each index underlying's (weekly / monthly) and the stock F&O monthly one."""
    unders = list(dict.fromkeys(opt.DEFAULTS["underlyings"] + [STOCK_FNO_PROBE]))
    by_date: dict[str, dict] = {}
    ok = False
    for u in unders:
        try:
            got, _code = opt.expiries(u)
        except Exception:
            got = []
        ok = ok or bool(got)
        month_last: dict[tuple[int, int], date] = {}
        for d in got:
            k = (d.year, d.month)
            month_last[k] = max(month_last.get(k, d), d)
        for d in got:
            if not (start <= d <= end):
                continue
            monthly = month_last[(d.year, d.month)] == d
            name = "Stock F&O" if u == STOCK_FNO_PROBE else u
            e = by_date.setdefault(d.isoformat(), {"date": d.isoformat(), "kind": "expiry", "symbol": None,
                                                   "monthly": False, "names": []})
            e["names"].append(f"{name} {'monthly' if monthly or u == STOCK_FNO_PROBE else 'weekly'}")
            e["monthly"] = e["monthly"] or monthly
    for e in by_date.values():
        e["detail"] = ", ".join(e.pop("names"))
    return sorted(by_date.values(), key=lambda e: e["date"]), ok


def ipos(start: date, end: date) -> tuple[list[dict], bool]:
    """Issues open now and announced on NSE, by their subscription dates."""
    out, ok = [], False
    for path, params in (("ipo-current-issue", None), ("all-upcoming-issues", {"category": "ipo"})):
        try:
            rows = events._cached(f"ipo_{path}_{start:%Y%m%d}.json", 3 * 3600, lambda p=path, q=params: events._get_json(p, q))
            ok = True
        except Exception:
            continue
        for r in rows if isinstance(rows, list) else []:
            if not isinstance(r, dict):
                continue
            o, c = events._nse_date(r.get("issueStartDate")), events._nse_date(r.get("issueEndDate"))
            name = str(r.get("companyName") or r.get("symbol") or "IPO").strip()
            sym = str(r.get("symbol") or "").strip().upper() or None
            band = str(r.get("issuePrice") or r.get("priceBand") or "").strip()
            size = str(r.get("issueSize") or "").strip()
            kind = "SME" if str(r.get("series") or "").upper() in ("SM", "ST") or "sme" in str(r.get("isBse") or "").lower() else "Mainboard"
            for d, what in ((o, "opens"), (c, "closes")):
                if d and start <= d <= end:
                    out.append({"date": d.isoformat(), "kind": "ipo", "symbol": None, "ipo_symbol": sym,
                                "detail": f"{name} IPO {what}" + (f" · price {band}" if band else "") + (f" · {kind}" if kind else "")
                                          + (f" · {size} shares" if size and size.replace(',', '').isdigit() else ""),
                                "open": o.isoformat() if o else None, "close": c.isoformat() if c else None})
    seen, uniq = set(), []
    for e in out:
        k = (e["date"], e["detail"])
        if k not in seen:
            seen.add(k)
            uniq.append(e)
    return uniq, ok


def _ann_rows(days: int, today: date) -> list[dict]:
    start = today - timedelta(days=days)
    return events._cached(f"ann_{start:%Y%m%d}_{today:%Y%m%d}.json", 30 * 60,
                          lambda: events._get_json("corporate-announcements", {"index": "equities",
                                                                              "from_date": start.strftime("%d-%m-%Y"),
                                                                              "to_date": today.strftime("%d-%m-%Y")}))


def _ann(r: dict) -> dict:
    when = str(r.get("an_dt") or r.get("exchdisstime") or "")
    try:
        iso = pd.to_datetime(when, format="%d-%b-%Y %H:%M:%S").isoformat()
    except (ValueError, TypeError):
        iso = None
    subj = str(r.get("desc") or "").strip()
    text = re.sub(r"\s+", " ", str(r.get("attchmntText") or "")).strip()
    url = str(r.get("attchmntFile") or "")
    return {"symbol": str(r.get("symbol") or "").upper(), "company": r.get("sm_name"), "time": iso, "subject": subj,
            "text": text[:400], "url": url if url.startswith("https://nsearchives.nseindia.com/") else None,
            "routine": bool(ROUTINE.search(subj)) or bool(ROUTINE.search(text[:120]))}


def announcements(symbol: str | None = None, days: int = 3, routine: bool = False, limit: int = 100,
                  today: date | None = None) -> dict:
    """NSE company announcements of the last `days` days: one stock, or your holdings and watchlists."""
    today = today or today_ist()
    days = max(1, min(int(days), 30))
    try:
        if symbol:
            sym = symbol.upper()
            start = today - timedelta(days=days)
            rows = events._cached(f"ann_{sym}_{today:%Y%m%d}.json", 60 * 60,
                                  lambda: events._get_json("corporate-announcements", {"index": "equities", "symbol": sym}))
            rows = [r for r in rows if isinstance(r, dict) and (events._nse_date(str(r.get("an_dt", ""))[:11]) or today) >= start]
            mine = {sym}
        else:
            rows = _ann_rows(days, today)
            held, watched = _held_and_watched()
            mine = held | watched
    except Exception:
        return {"items": [], "hidden": 0, "note": "NSE's announcements are unavailable right now (NSE did not respond)."}
    items = [_ann(r) for r in rows if isinstance(r, dict)]
    items = [x for x in items if x["symbol"] in mine]
    hidden = sum(1 for x in items if x["routine"])
    if not routine:
        items = [x for x in items if not x["routine"]]
    items.sort(key=lambda x: x["time"] or "", reverse=True)
    return {"items": items[:max(1, min(limit, 300))], "hidden": hidden if not routine else 0, "days": days,
            "note": "NSE filings: open the PDF for the full text. Routine filings (analyst meets, newspaper copies, "
                    "trading-window notices) are hidden unless you ask for them."}


def _last_close() -> dict[str, float]:
    try:
        c = data.store()["close"]
        last = c.ffill().iloc[-1]
        return {str(k): float(v) for k, v in last.items() if pd.notna(v) and v > 0}
    except Exception:
        return {}


def _held_and_watched() -> tuple[set[str], set[str]]:
    try:
        held = {str(s).upper() for s in data.holdings_df()["symbol"]}
    except Exception:
        held = set()
    try:
        watched = {s for lst in watch.watchlists()["lists"] for s in lst["symbols"]}
    except Exception:
        watched = set()
    return held, watched


def calendar(days: int = 30, today: date | None = None) -> dict:
    """Every dated event from today for `days` days, nearest first, your stocks flagged."""
    today = today or today_ist()
    days = max(1, min(int(days), MAX_DAYS))
    end = today + timedelta(days=days)
    uni = data.universe()
    names = dict(zip(uni["symbol"], uni["company"])) if len(uni) else {}
    held, watched = _held_and_watched()
    keep = set(names) | held | watched
    notes: list[str] = []

    hols, hol_ok = _holidays(today, end)
    closed = _closed(today, end)
    if not hol_ok:
        notes.append("NSE's holiday list is unavailable: market holidays are not shown.")
    out: list[dict] = [{"date": h["date"], "kind": "holiday", "symbol": None, "detail": h["name"]} for h in hols]

    try:
        for m in events.board_meetings(today, days):
            if m["symbol"] in keep:
                out.append({"date": m["date"], "kind": _purpose_kind(m["purpose"]), "symbol": m["symbol"],
                            "detail": m["purpose"] or "Board meeting"})
    except Exception:
        notes.append("NSE's results calendar is unavailable (NSE did not respond): results dates are not shown.")

    acts, missing = corporate_actions(today, end, closed)
    if missing:
        notes.append(f"NSE's corporate actions are unavailable for {', '.join(missing)}: ex-dates may be missing.")
    close = _last_close()
    for a in acts:
        if a["symbol"] not in keep:
            continue
        px = close.get(a["symbol"])
        if a["kind"] == "dividend" and a.get("amount") and px:
            a["yield_pct"] = round(a["amount"] / px * 100, 2)
        out.append(a)

    exps, exp_ok = expiries(today, end)
    if not exp_ok:
        notes.append("NSE's F&O contract list is unavailable: expiries are not shown.")
    out += exps

    try:
        from ..paths import P
        for e in econ.events(today, end, P.data):
            out.append({"date": e["date"], "kind": "econ", "symbol": None, "detail": f"{e['name']} · {e['detail']}",
                        "time": e["time"], "importance": e["importance"], "country": e["country"], "source": e["source"]})
    except Exception:
        notes.append("The economic calendar could not be read.")
    ip, ip_ok = ipos(today, end)
    if not ip_ok:
        notes.append("NSE's IPO lists are unavailable: IPOs are not shown.")
    out += ip

    for e in out:
        s = e.get("symbol")
        e["company"] = names.get(s) if s else None
        e["mine"] = bool(s and s in held)
        e["watch"] = bool(s and s in watched)
        e["price"] = close.get(s) if s else None
        if e.get("amount") is not None and isinstance(e["amount"], float) and math.isnan(e["amount"]):
            e["amount"] = None
    order = {k: i for i, k in enumerate(KINDS)}
    out.sort(key=lambda e: (e["date"], not e["mine"], not e["watch"], order.get(e["kind"], 99), e.get("symbol") or ""))
    counts = {k: sum(1 for e in out if e["kind"] == k) for k in KINDS}
    mine = [e for e in out if e["mine"]]
    return {"from": today.isoformat(), "to": end.isoformat(), "days": days, "events": out, "counts": counts,
            "mine": len(mine), "watch": sum(1 for e in out if e["watch"]), "notes": notes}
