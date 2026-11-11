"""Company numbers from NSE's quarterly filings: revenue, profit, EPS, and what follows from them (growth, margin,
P/E), point in time.

Source: NSE's "Integrated Filing - Financials" (every listed company's quarterly results in XBRL since 2025):
  https://www.nseindia.com/api/integrated-filing-results?index=equities&symbol=X   the list of filings
  https://nsearchives.nseindia.com/corporate/xbrl/...xml                          each quarter's numbers
The consolidated statement is used when the company files one (the group's numbers), else the standalone one; a
company is never mixed between the two. Each quarter's numbers count from the day they were filed, so a backtest
using them only sees what was public then (point in time).

Stored per company in data/fundamentals/{SYMBOL}.json (each filing parsed once). A background job fills the universe
(about 100 KB a filing, `QUARTERS` filings per company); the nightly job adds new filings after results.
"""
from __future__ import annotations

import json
import math
import re
import time
from datetime import date, datetime

import numpy as np
import pandas as pd

from . import events, nse
from .settings import DATA_DIR

DIR = DATA_DIR / "fundamentals"
QUARTERS = 6                        # enough for a trailing-twelve-month EPS and two year-on-year growth readings
TAGS = {
    "revenue": ("RevenueFromOperations", "InterestEarned", "TotalRevenueFromOperations"),
    "other_income": ("OtherIncome",),
    "total_income": ("Income", "TotalIncome"),
    "expenses": ("Expenses", "TotalExpenses"),
    "finance_costs": ("FinanceCosts", "InterestExpended"),
    "depreciation": ("DepreciationDepletionAndAmortisationExpense",),
    "pbt": ("ProfitBeforeTax", "ProfitLossBeforeTax"),
    "profit": ("ProfitLossForPeriod", "ProfitLossForThePeriod", "NetProfitLossForThePeriod"),
    "profit_owners": ("ProfitOrLossAttributableToOwnersOfParent", "ProfitLossAttributableToOwnersOfParent"),
    "eps": ("BasicEarningsLossPerShareFromContinuingOperations", "BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations",
            "BasicEarningsLossPerShare", "BasicEarningsPerShareAfterExtraordinaryItems"),
}


def folder():
    return DIR


def _file(sym: str):
    return folder() / f"{sym.upper()}.json"


def load(sym: str) -> dict:
    try:
        return json.loads(_file(sym).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"symbol": sym.upper(), "basis": None, "quarters": {}, "checked": None}


def _save(sym: str, v: dict) -> None:
    folder().mkdir(parents=True, exist_ok=True)
    tmp = _file(sym).with_suffix(".tmp")
    tmp.write_text(json.dumps(v, indent=0), encoding="utf-8")
    tmp.replace(_file(sym))


def _d(s) -> date | None:
    for fmt in ("%d-%b-%Y %H:%M:%S", "%d-%b-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(str(s).strip().title(), fmt).date()
        except ValueError:
            pass
    return None


def filings(sym: str, get=None) -> list[dict]:
    """Quarterly financial filings, newest first: {qe, filed, basis consolidated/standalone, xbrl}."""
    get = get or events._get_json
    out = []
    for page in (1, 2):
        r = get("integrated-filing-results", {"index": "equities", "symbol": sym.upper(), "page": page, "size": 20}
                if page > 1 else {"index": "equities", "symbol": sym.upper()})
        rows = (r or {}).get("data") or [] if isinstance(r, dict) else []
        for x in rows:
            if "Financial" not in str(x.get("type")) or not str(x.get("xbrl", "")).startswith("https://nsearchives.nseindia.com/"):
                continue
            qe, filed = _d(x.get("qe_Date")), _d(x.get("broadcast_Date") or x.get("creation_Date"))
            if qe and filed:
                out.append({"qe": qe.isoformat(), "filed": filed.isoformat(),
                            "basis": "consolidated" if str(x.get("consolidated")).lower().startswith("consol") else "standalone",
                            "xbrl": x["xbrl"], "revised": bool(x.get("revised_Date"))})
        if isinstance(r, dict) and int(r.get("totalCount") or 0) <= len(rows) * page:
            break
    out.sort(key=lambda f: (f["qe"], f["filed"]), reverse=True)
    return out


_CTX = re.compile(r"<xbrli:context id=\"([^\"]+)\">(.*?)</xbrli:context>", re.S)
_FACT = re.compile(r"<[\w-]+:(\w+)\s[^>]*contextRef=\"([^\"]+)\"[^>]*>\s*([-\d.Ee+]+)\s*</")


def parse_xbrl(text: str, qe: str) -> dict:
    """The quarter's own numbers (the 3-month context ending on `qe`, no segment dimension), in rupees."""
    end = date.fromisoformat(qe)
    ctxs = set()
    for cid, body in _CTX.findall(text):
        if "explicitMember" in body or "typedMember" in body:
            continue
        m = re.search(r"<xbrli:startDate>([^<]+)</xbrli:startDate>\s*<xbrli:endDate>([^<]+)</xbrli:endDate>", body)
        if not m:
            continue
        s, e = date.fromisoformat(m.group(1)[:10]), date.fromisoformat(m.group(2)[:10])
        if e == end and 80 <= (e - s).days <= 100:
            ctxs.add(cid)
    facts: dict[str, float] = {}
    for name, ctx, val in _FACT.findall(text):
        if ctx in ctxs and name not in facts:
            try:
                facts[name] = float(val)
            except ValueError:
                pass
    out = {}
    for k, names in TAGS.items():
        out[k] = next((facts[n] for n in names if n in facts), None)
    if out["profit_owners"] is not None:
        out["profit"] = out["profit_owners"]           # the group's profit that belongs to shareholders
    out.pop("profit_owners")
    return out


def update(sym: str, n: int = QUARTERS, get=None, get_bytes=None, pause: float = 0.3) -> dict:
    """Fetch the company's newest `n` quarters not stored yet. Returns the stored record."""
    get_bytes = get_bytes or nse._get_bytes
    rec = load(sym)
    fs = filings(sym, get)
    if not fs:
        rec["checked"] = date.today().isoformat()
        _save(sym, rec)
        return rec
    basis = "consolidated" if any(f["basis"] == "consolidated" for f in fs[:4]) else "standalone"
    if rec.get("basis") not in (None, basis):
        rec["quarters"] = {}                           # the company changed basis: start again, never mix
    rec["basis"] = basis
    chosen: dict[str, dict] = {}
    for f in fs:
        if f["basis"] == basis and f["qe"] not in chosen:
            chosen[f["qe"]] = f                        # newest filing per quarter (a revision wins)
    for qe in sorted(chosen, reverse=True)[:n]:
        f = chosen[qe]
        have = rec["quarters"].get(qe)
        if have and have.get("xbrl") == f["xbrl"]:
            continue
        code, body = get_bytes(f["xbrl"])
        if code != 200:
            continue
        nums = parse_xbrl(body.decode("utf-8", "replace"), qe)
        rec["quarters"][qe] = {**nums, "filed": f["filed"], "xbrl": f["xbrl"]}
        time.sleep(pause)
    rec["checked"] = date.today().isoformat()
    _save(sym, rec)
    return rec


def table(rec: dict) -> pd.DataFrame:
    """Quarters oldest first with year-on-year growth, margin and trailing-twelve-month EPS."""
    q = rec.get("quarters") or {}
    if not q:
        return pd.DataFrame()
    df = pd.DataFrame([{"qe": k, **v} for k, v in q.items()]).sort_values("qe").reset_index(drop=True)
    df["qe"] = pd.to_datetime(df["qe"])
    for c in ("revenue", "profit", "eps"):
        if c not in df:
            df[c] = np.nan
        df[c] = pd.to_numeric(df[c], errors="coerce")
    prev = {r.qe: r for r in df.itertuples()}
    yoy_rev, yoy_np, ttm = [], [], []
    for r in df.itertuples():
        ly = prev.get(r.qe - pd.DateOffset(years=1))
        ly = ly if ly is not None else prev.get((r.qe - pd.DateOffset(years=1)) + pd.offsets.MonthEnd(0))
        yoy_rev.append((r.revenue / ly.revenue - 1) * 100 if ly is not None and ly.revenue and r.revenue is not None and ly.revenue > 0 else np.nan)
        yoy_np.append((r.profit / ly.profit - 1) * 100 if ly is not None and ly.profit and ly.profit > 0 and r.profit is not None else np.nan)
        last4 = df[(df["qe"] <= r.qe) & (df["qe"] > r.qe - pd.DateOffset(months=12))]
        ttm.append(float(last4["eps"].sum()) if len(last4) == 4 and last4["eps"].notna().all() else np.nan)
    df["sales_growth"], df["profit_growth"], df["eps_ttm"] = yoy_rev, yoy_np, ttm
    df["net_margin"] = df["profit"] / df["revenue"].where(df["revenue"] > 0) * 100
    return df


def frames(symbols: list[str], dates: pd.DatetimeIndex) -> dict[str, pd.DataFrame]:
    """Point-in-time wide frames (dates x symbols): eps_ttm, sales_growth, profit_growth, net_margin, each value from
    the day its quarter was filed."""
    cols = ("eps_ttm", "sales_growth", "profit_growth", "net_margin")
    out = {c: pd.DataFrame(np.nan, index=dates, columns=symbols) for c in cols}
    for s in symbols:
        p = _file(s)
        if not p.exists():
            continue
        t = table(load(s))
        if t.empty:
            continue
        t = t.dropna(subset=["filed"]).sort_values("filed")
        idx = pd.to_datetime(t["filed"])
        for c in cols:
            ser = pd.Series(t[c].to_numpy(float), index=idx)
            ser = ser[~ser.index.duplicated(keep="last")]
            out[c][s] = ser.reindex(dates, method="ffill").to_numpy()
    return out


def summary(rec: dict, price: float | None) -> dict:
    t = table(rec)
    if t.empty:
        return {"quarters": [], "latest": None}
    last = t.iloc[-1]
    eps = last["eps_ttm"]

    def f(x, nd=2):
        return None if x is None or (isinstance(x, float) and math.isnan(x)) else round(float(x), nd)
    return {"basis": rec.get("basis"), "checked": rec.get("checked"),
            "latest": {"qe": last["qe"].date().isoformat(), "filed": last.get("filed"), "revenue_cr": f(last["revenue"] / 1e7),
                       "profit_cr": f(last["profit"] / 1e7), "sales_growth": f(last["sales_growth"], 1),
                       "profit_growth": f(last["profit_growth"], 1), "net_margin": f(last["net_margin"], 1),
                       "eps_ttm": f(eps), "pe": f(price / eps, 1) if price and eps and not math.isnan(eps) and eps > 0 else None},
            "quarters": [{"qe": r.qe.date().isoformat(), "filed": r.filed, "revenue_cr": f(r.revenue / 1e7),
                          "profit_cr": f(r.profit / 1e7), "eps": f(r.eps), "sales_growth": f(r.sales_growth, 1),
                          "profit_growth": f(r.profit_growth, 1), "net_margin": f(r.net_margin, 1)} for r in t.itertuples()]}


def refresh(symbols: list[str], log=print, progress=lambda d, t: None, stop=lambda: False, max_age_days: int = 20,
            n: int = QUARTERS) -> dict:
    """Update every symbol not checked in `max_age_days` days (all, the first time). Never raises for NSE trouble."""
    today = date.today()
    todo = [s for s in symbols if not (load(s).get("checked") and (today - date.fromisoformat(load(s)["checked"])).days < max_age_days)]
    rep = {"wanted": len(todo), "updated": 0, "errors": []}
    for i, s in enumerate(todo):
        if stop():
            break
        try:
            update(s, n)
            rep["updated"] += 1
        except Exception as e:
            rep["errors"].append(f"{s}: {type(e).__name__}: {e}")
        progress(i + 1, len(todo))
        if i % 50 == 49:
            log(f"  company numbers: {i + 1} of {len(todo)}")
    return rep
