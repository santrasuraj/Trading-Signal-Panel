"""Big-money footprints beyond smart_money.py, from NSE's own public data (nothing here is non-public; trading on
non-public information is insider trading under SEBI's PIT Regulations):

  www.nseindia.com/api/corporate-pledgedata      promoter holding and the shares promoters pledged / encumbered
                                                 (SEBI SAST Reg 31), plus every pledged share in the depository system
  www.nseindia.com/api/corporate-sast-reg29      substantial acquisitions and disposals: anyone crossing 5% of a
                                                 company, and every 2% change after that (SEBI SAST Reg 29), with the
                                                 filing's link on NSE
  nsearchives.nseindia.com/content/fo/fo_secban.csv   F&O stocks in the ban period (open interest above 95% of the
                                                 market-wide limit: no new positions until it falls below 80%)
  delivery volume (NSE's day files, already in the price store): shares taken into demat, not traded intraday

Network only in refresh(); the loaders read data/smart_money/big_money/. Every request goes through
smart_money._fetch (polite spacing, cookies, stops on 403/429, never raises). Disclosed data: late by design and
not a prediction.
"""
from __future__ import annotations

import json
import math
from datetime import date, timedelta

import numpy as np
import pandas as pd

from . import smart_money as sm
from .settings import ist_now, ist_today

BM_DIR = sm.SM_DIR / "big_money"
PLEDGE_URL = sm.API + "corporate-pledgedata"
PLEDGE_PAGE = "https://www.nseindia.com/companies-listing/corporate-filings-pledged-data"
SAST_URL = sm.API + "corporate-sast-reg29"
SAST_PAGE = "https://www.nseindia.com/companies-listing/corporate-filings-regulation-29"
BAN_URL = "https://nsearchives.nseindia.com/content/fo/fo_secban.csv"
PLEDGE_MAX_AGE_DAYS = 7       # a symbol's pledge data is re-read after a week (it changes with quarterly filings)
SAST_MONTHS = 12              # months of acquisition / disposal filings kept
MAX_PLEDGE_LOOKUPS = 40       # per refresh
DELIV_SPIKE = 2.0             # delivery quantity at least 2x its 20-day average ...
DELIV_MIN_PCT = 40.0          # ... with at least 40% of the day's volume delivered


def _dir():
    return BM_DIR


def _read_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _f(x, nd: int = 2):
    try:
        v = float(str(x).strip().replace(",", ""))
    except (TypeError, ValueError):
        return None
    return round(v, nd) if math.isfinite(v) else None


# --------------------------------------------------------------------------- parsers
def parse_pledge(payload) -> dict | None:
    """NSE's pledge record for one company (the latest quarter)."""
    rows = (payload or {}).get("data") if isinstance(payload, dict) else None
    if not rows:
        return None
    r = rows[0]
    return {
        "quarter": sm._iso(r.get("shp")), "broadcast": sm._iso_dt(r.get("broadcastDt")), "company": r.get("comName"),
        "promoter_pct": _f(r.get("percPromoterHolding")),             # promoter holding, % of the company
        "promoter_shares": _f(r.get("totPromoterHolding"), 0),
        "promoter_pledged_shares": _f(r.get("totPromoterShares"), 0), # promoter shares pledged / encumbered
        "promoter_pledged_pct": _f(r.get("percPromoterShares")),      # ... as % of the promoter holding
        "promoter_pledged_total_pct": _f(r.get("percTotShares")),     # ... as % of all shares
        "depository_pledged_shares": _f(r.get("numSharesPledged"), 0),  # every pledged share (any holder) in demat
        "depository_pledged_pct": _f(r.get("percSharesPledged")),     # ... as % of demat shares
        "source": PLEDGE_PAGE,
    }


def parse_sast(payload) -> pd.DataFrame:
    rows = (payload or {}).get("data") if isinstance(payload, dict) else payload
    out = []
    for r in rows or []:
        sym = str(r.get("symbol") or "").strip().upper()
        if not sym:
            continue
        sale = str(r.get("acqSaleType") or "").lower().startswith("sale") or str(r.get("acqSaleType") or "").lower().startswith("dispos")
        out.append({
            "symbol": sym, "company": r.get("company"), "filed": sm._iso_dt(r.get("timestamp") or r.get("sysTime")),
            "period": str(r.get("acquirerDate") or "").strip() or None, "acquirer": str(r.get("acquirerName") or "").strip(),
            "side": "SELL" if sale else "BUY", "mode": r.get("acquisitionMode"), "security": r.get("acqType"),
            "promoter": str(r.get("promoterType") or "").upper() == "Y", "regulation": r.get("regType"),
            "shares": _f(r.get("noOfShareSale") if sale else r.get("noOfShareAcq"), 0),
            "pct": _f(r.get("totSaleShare") if sale else r.get("totAcqShare"), 2),
            "after_shares": _f(r.get("noOfShareAft"), 0), "after_pct": _f(r.get("totAftShare"), 2),
            "link": r.get("attachement") or None, "id": str(r.get("application_no") or ""),
        })
    return pd.DataFrame(out, columns=["symbol", "company", "filed", "period", "acquirer", "side", "mode", "security",
                                      "promoter", "regulation", "shares", "pct", "after_shares", "after_pct", "link", "id"])


def parse_ban(text: str) -> dict:
    """'Securities in Ban For Trade Date 05-NOV-2026:' then '1,KAYNES' lines."""
    lines = [x.strip() for x in text.replace(sm._BOM, "").splitlines() if x.strip()]
    day = None
    if lines and ":" in lines[0]:
        day = sm._iso(lines[0].split("Date")[-1].strip(" :"))
    syms = [x.split(",", 1)[1].strip().upper() for x in lines[1:] if "," in x and x.split(",", 1)[1].strip()]
    return {"trade_date": day, "symbols": syms, "source": BAN_URL}


# --------------------------------------------------------------------------- refresh (network)
def refresh(symbols: list[str] = (), log=print, today: date | None = None) -> dict:
    """Ban list (daily), acquisition filings (the current and previous month, older months once), pledge data for
    `symbols` older than a week. Never raises for network problems."""
    today = today or ist_today()
    d = _dir()
    d.mkdir(parents=True, exist_ok=True)
    sm._reset_api()
    rep = {"ban": None, "sast_months": [], "pledges": [], "errors": []}
    code, body = sm._fetch(BAN_URL)
    if code == 200 and body:
        ban = parse_ban(body.decode("utf-8", "replace"))
        if ban["trade_date"]:
            sm._save_json({**ban, "fetched_at": sm._now()}, d / "fo_ban.json")
            rep["ban"] = ban
    else:
        rep["errors"].append(f"F&O ban list: HTTP {code}")
    state = _read_json(d / "state.json", {"sast_final": [], "pledge_at": {}})
    sast = load_sast()
    first = date(today.year, today.month, 1)
    months = []
    for k in range(SAST_MONTHS):
        y, m = first.year, first.month - k
        while m <= 0:
            y, m = y - 1, m + 12
        months.append(date(y, m, 1))
    for start in months:
        key = f"{start:%Y-%m}"
        if key in state["sast_final"]:
            continue
        end = (date(start.year + (start.month == 12), start.month % 12 + 1, 1) - timedelta(days=1))
        code, body = sm._fetch(SAST_URL, {"index": "equities", "from_date": f"{start:%d-%m-%Y}",
                                          "to_date": f"{min(end, today):%d-%m-%Y}"}, api=True, referer=SAST_PAGE)
        if code != 200 or not sm._readable(body):
            rep["errors"].append(f"Acquisition filings {key}: HTTP {code}")
            continue
        rows = parse_sast(json.loads(body))
        log(f"Big money: {len(rows)} acquisition / disposal filings in {key}")
        sast = pd.concat([sast[~sast["filed"].astype(str).str.startswith(key)], rows], ignore_index=True)
        rep["sast_months"].append(key)
        if end < today - timedelta(days=sm.PAST_MONTH_GRACE_DAYS) and len(rows):
            state["sast_final"].append(key)       # a past month is final once fetched with rows
    if rep["sast_months"]:
        sast = sast.drop_duplicates(subset=["id", "symbol", "acquirer", "filed"], keep="last")
        sm._save_parquet(sast.astype({c: "object" for c in sast.columns}), d / "sast.parquet")
    pledges = _read_json(d / "pledge.json", {})
    stale = [s for s in dict.fromkeys(str(x).upper() for x in symbols)
             if (pd.Timestamp(today) - pd.Timestamp(state["pledge_at"].get(s, "2000-01-01"))).days >= PLEDGE_MAX_AGE_DAYS]
    for s in stale[:MAX_PLEDGE_LOOKUPS]:
        code, body = sm._fetch(PLEDGE_URL, {"index": "equities", "symbol": s}, api=True, referer=PLEDGE_PAGE)
        if code != 200 or not sm._readable(body):
            rep["errors"].append(f"Pledge {s}: HTTP {code}")
            continue
        rec = parse_pledge(json.loads(body))
        pledges[s] = rec            # None: NSE has no pledge record for it (stored, so it is not asked every time)
        state["pledge_at"][s] = today.isoformat()
        rep["pledges"].append(s)
    if rep["pledges"]:
        sm._save_json(pledges, d / "pledge.json")
    sm._save_json(state, d / "state.json")
    sm._save_json({"refreshed_at": sm._now(), **{k: v for k, v in rep.items() if k != "ban"}}, d / "last_refresh.json")
    return rep


# --------------------------------------------------------------------------- loaders (files only)
def load_sast() -> pd.DataFrame:
    p = _dir() / "sast.parquet"
    if p.exists():
        try:
            return pd.read_parquet(p)
        except Exception:
            pass
    return parse_sast([])


def load_pledges() -> dict:
    return _read_json(_dir() / "pledge.json", {})


def load_ban() -> dict | None:
    return _read_json(_dir() / "fo_ban.json", None)


def last_refresh() -> dict | None:
    return _read_json(_dir() / "last_refresh.json", None)


# --------------------------------------------------------------------------- delivery (price store, no network)
def delivery_frames(close: pd.DataFrame, volume: pd.DataFrame, deliv_pct: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Delivery quantity, its prior 20-day average, and the accumulation / distribution spikes (only past data)."""
    dq = volume * deliv_pct / 100
    avg = dq.rolling(20, min_periods=15).mean().shift(1)
    spike = (dq >= DELIV_SPIKE * avg) & (deliv_pct >= DELIV_MIN_PCT) & avg.notna() & (avg > 0)
    up = close >= close.shift(1)
    return {"dq": dq, "avg": avg, "ratio": dq / avg.where(avg > 0), "accumulation": spike & up, "distribution": spike & ~up}


def delivery_now(df: pd.DataFrame) -> dict | None:
    """Today's delivery picture for one symbol (daily bars with a deliv_pct column)."""
    if "deliv_pct" not in df.columns or df["deliv_pct"].dropna().empty:
        return None
    one = {k: df[[k]].rename(columns={k: "x"}) for k in ("close", "volume", "deliv_pct")}
    fr = delivery_frames(one["close"], one["volume"], one["deliv_pct"])
    last = df.index[-1]
    pct = df["deliv_pct"]
    events = []
    for kind in ("accumulation", "distribution"):
        hits = fr[kind]["x"].iloc[-20:]
        for day in hits[hits].index:
            events.append({"date": day.date().isoformat(), "kind": kind, "ratio": _f(fr["ratio"]["x"].loc[day], 1),
                           "deliv_pct": _f(pct.loc[day], 1), "chg_pct": _f((df["close"].loc[day] / df["close"].shift(1).loc[day] - 1) * 100, 2)})
    return {
        "date": last.date().isoformat(), "deliv_pct": _f(pct.iloc[-1], 1),
        "deliv_pct_avg20": _f(pct.iloc[-21:-1].mean(), 1), "deliv_qty": _f(fr["dq"]["x"].iloc[-1], 0),
        "deliv_ratio": _f(fr["ratio"]["x"].iloc[-1], 2),
        "state": "accumulation" if bool(fr["accumulation"]["x"].iloc[-1]) else
                 "distribution" if bool(fr["distribution"]["x"].iloc[-1]) else "normal",
        "events": sorted(events, key=lambda e: e["date"], reverse=True),
    }


def refreshed_today() -> bool:
    r = last_refresh()
    return bool(r and str(r.get("refreshed_at", ""))[:10] == ist_now().date().isoformat())
