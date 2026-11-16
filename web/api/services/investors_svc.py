"""Investor portfolios (GET /api/investors, GET /api/investors/{key}): each big investor's holdings across companies
and what they added, cut or left since the previous quarter - the "superstar portfolios" Trendlyne shows, from the
source it uses: the quarterly shareholding filings, which name every public holder with 1% or more of a company
(scanner/smart_money.py stores them for the scan universe).

An investor is the well-known person (the RJ estate, Ashish Kacholia, ...), the fund house (all of SBI Mutual Fund's
schemes together) or the institution. Limits of the source: a holding under 1% is not disclosed, so "left" can also
mean "now below 1%"; the newest quarter is filed up to 21 days after it ends; promoters are not listed here."""
from __future__ import annotations

import math
import re

import pandas as pd

from scanner import smart_money as sm

from . import data
from ..errors import ApiException

CATS = ("famous", "mf", "fii", "insurance", "pension", "bank", "aif", "other")
ACRONYMS = {"SBI", "ICICI", "UTI", "LIC", "IDBI", "IIFL", "PGIM", "WOC", "BNP", "UBS", "HSBC", "DSP", "NPS", "HDFC", "IDFC",
            "GIC", "AMC", "LLP", "FPI", "PLC", "ICVC", "SICAV", "HUF", "PPFAS", "JM", "ITI", "LIC", "AB", "EPFO"}
_cache: dict = {}


def _title(name: str) -> str:
    """'HDFC MUTUAL FUND' -> 'HDFC Mutual Fund' (acronyms stay capitals)."""
    out = []
    for w in name.split():
        core = re.sub(r"[^A-Za-z]", "", w).upper()
        out.append(w.upper() if core in ACRONYMS or (core and not re.search(r"[AEIOU]", core)) else w.capitalize())
    return " ".join(out)


def _key(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:80]


def _base() -> pd.DataFrame:
    """One row per (investor, symbol, period): the investor's accounts added up. Cached until the filings change."""
    f = sm.files()
    try:
        ver = (f["holders"].stat().st_mtime_ns, f["holdings"].stat().st_mtime_ns)
    except OSError:
        return pd.DataFrame()
    if _cache.get("ver") == ver:
        return _cache["base"]
    try:
        h = pd.read_parquet(f["holders"])
    except Exception:
        return pd.DataFrame()
    h = h[h["group"] != "promoter"].copy()
    if h.empty:
        return pd.DataFrame()
    labels = {n: sm.classify(n) for n in h["holder"].unique()}
    h["category"] = h["holder"].map(lambda n: labels[n].category)
    h["investor"] = [labels[n].investor or _title(sm.parent_key(n) or n) for n in h["holder"]]
    h = h[h["category"].isin(CATS)]
    g = h.groupby(["investor", "category", "symbol", "period"], as_index=False).agg(
        shares=("shares", "sum"), pct=("pct", "sum"), accounts=("holder", lambda s: sorted(set(s))))
    g["key"] = g["investor"].map(_key)
    _cache.update(ver=ver, base=g, pos=None)
    return g


def _prices() -> dict[str, float]:
    sc = data.screener()
    if sc is None or sc.empty:
        return {}
    return {r.symbol: float(r.price) for r in sc.itertuples(index=False) if r.price == r.price}


def _periods() -> dict[str, list[str]]:
    """symbol -> its stored shareholding periods, newest first (a company's own quarters)."""
    try:
        hd = pd.read_parquet(sm.files()["holdings"], columns=["symbol", "period"])
    except Exception:
        return {}
    return {s: sorted(set(g["period"]), reverse=True) for s, g in hd.groupby("symbol")}


def _positions(g: pd.DataFrame) -> pd.DataFrame:
    """Each (investor, symbol): the latest quarter's holding next to the previous quarter's, and what changed."""
    if g.empty:
        return pd.DataFrame()
    per = _periods()
    cur_p = {s: (ps[0] if ps else None) for s, ps in per.items()}
    prev_p = {s: (ps[1] if len(ps) > 1 else None) for s, ps in per.items()}
    latest_seen = g.groupby("symbol")["period"].max().to_dict()      # a symbol missing from holdings: its own newest
    cp = g["symbol"].map(lambda s: cur_p.get(s) or latest_seen.get(s))
    pp = g["symbol"].map(prev_p)
    ids = ["key", "investor", "category", "symbol"]
    cur = g[g["period"] == cp].rename(columns={"period": "cur_period", "shares": "shares", "pct": "pct", "accounts": "acc_c"})
    prev = g[g["period"] == pp][ids + ["period", "pct", "accounts"]].rename(
        columns={"period": "prev_period_x", "pct": "prev_pct", "accounts": "acc_p"})
    m = cur.merge(prev, on=ids, how="outer")
    if m.empty:
        return pd.DataFrame()
    m["period"] = m["symbol"].map(lambda s: cur_p.get(s) or latest_seen.get(s))
    m["prev_period"] = m["symbol"].map(prev_p)
    has_c, has_p = m["pct"].notna(), m["prev_pct"].notna()
    m["change"] = "same"
    m.loc[has_c & m["prev_period"].isna(), "change"] = "held"
    m.loc[has_c & m["prev_period"].notna() & ~has_p, "change"] = "new"
    m.loc[~has_c, "change"] = "left"
    both = has_c & has_p
    m.loc[both & (m["pct"] > m["prev_pct"] + 0.005), "change"] = "added"
    m.loc[both & (m["pct"] < m["prev_pct"] - 0.005), "change"] = "cut"
    m["pct"] = m["pct"].round(2)
    m["prev_pct"] = m["prev_pct"].round(2)
    m["shares"] = m["shares"].where(has_c)
    m["accounts"] = [sorted(set(a if isinstance(a, list) else b if isinstance(b, list) else []))
                     for a, b in zip(m["acc_c"], m["acc_p"])]
    return m[ids + ["period", "prev_period", "pct", "prev_pct", "shares", "change", "accounts"]]


def investors(category: str = "famous", q: str = "") -> dict:
    if category not in CATS + ("all",):
        raise ApiException("VALIDATION", f"category must be one of {', '.join(CATS + ('all',))}.")
    g = _base()
    if g.empty:
        return {"rows": [], "periods": [], "note": "No shareholding filings stored yet: refresh Smart money first."}
    if category != "all":
        g = g[g["category"] == category]
    if q:
        g = g[g["investor"].str.contains(q, case=False, regex=False)]
    pos = _positions(g)
    if pos.empty:
        return {"rows": [], "periods": [], "note": "Nobody matches."}
    pos = pos.astype({"shares": float})
    px = _prices()
    pos["value_cr"] = pos["shares"].to_numpy(float) * pos["symbol"].map(px).to_numpy(float) / 1e7
    ch = pos["change"].astype(object).to_numpy()            # plain objects: one comparison each, not Arrow's per group
    flags = pd.DataFrame({"held": ch != "left", "new": ch == "new", "added": ch == "added", "cut": ch == "cut",
                          "left": ch == "left"}, index=pos.index)
    pos = pd.concat([pos, flags], axis=1)
    pos["v"] = pos["value_cr"].where(pos["held"])
    ids = ["key", "investor", "category"]
    agg = pos.groupby(ids, as_index=False).agg(stocks=("held", "sum"), value_cr=("v", "sum"), valued=("v", "count"),
                                               new=("new", "sum"), added=("added", "sum"), cut=("cut", "sum"),
                                               left=("left", "sum"))
    tops = (pos[pos["held"]].sort_values("v", ascending=False).groupby("key")["symbol"]
            .apply(lambda s: list(s.head(3))).to_dict())
    out = [{"key": r.key, "investor": r.investor, "category": r.category, "label": sm.CATEGORY_LABELS.get(r.category, r.category),
            "stocks": int(r.stocks), "value_cr": round(float(r.value_cr), 0) if r.valued else None, "new": int(r.new),
            "added": int(r.added), "cut": int(r.cut), "left": int(r.left), "top": tops.get(r.key, [])}
           for r in agg.itertuples(index=False)]
    out.sort(key=lambda r: -(r["value_cr"] or 0))
    periods = sorted(set(pos["period"]), reverse=True)
    return {"rows": out[:400], "periods": periods[:2],
            "note": "From the quarterly shareholding filings of the scan universe: every public holder with 1%+ of a "
                    "company. Fund houses add up their schemes. 'Left' can also mean the stake fell below 1% (no longer "
                    "disclosed). Value at the last scan's price."}


def investor(key: str) -> dict:
    g = _base()
    g = g[g["key"] == key] if not g.empty else g
    if g.empty:
        raise ApiException("NOT_FOUND", f"No investor {key!r} in the stored shareholding filings.")
    pos = _positions(g)
    px = _prices()
    meta = data.symbol_meta()
    rows = []
    for r in pos.itertuples(index=False):
        price = px.get(r.symbol)
        rows.append({"symbol": r.symbol, "company": (meta.get(r.symbol) or {}).get("company"), "period": r.period,
                     "prev_period": r.prev_period, "pct": r.pct, "prev_pct": r.prev_pct, "change": r.change,
                     "shares": r.shares, "price": price,
                     "value_cr": round(r.shares * price / 1e7, 1) if r.shares and price else None,
                     "accounts": list(r.accounts)})
    rows.sort(key=lambda r: (r["change"] == "left", -(r["value_cr"] or 0)))
    first = pos.iloc[0]
    return {"key": key, "investor": first["investor"], "category": first["category"],
            "label": sm.CATEGORY_LABELS.get(first["category"], first["category"]), "rows": rows,
            "value_cr": round(sum(r["value_cr"] or 0 for r in rows if r["change"] != "left"), 0),
            "note": "Holdings of 1% or more, as filed each quarter (the newest quarter of each company). Value at the last "
                    "scan's price. A position under 1% is not disclosed, so it is missing here."}
