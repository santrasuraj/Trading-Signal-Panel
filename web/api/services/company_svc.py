"""Company page (GET /api/company/{symbol}): ten-plus years of financials from NSE's filings (scanner/financials.py) -
profit & loss, balance sheet, cash flow, ratios, compounded growth, segments, the last twelve quarters - and the
company's industry peers side by side. A company is fetched the first time its page asks (a few seconds) and again
when it is more than STALE_DAYS old; the whole universe in the background (fund_svc.start_refresh)."""
from __future__ import annotations

import math
from datetime import date

from scanner import financials as fin

from . import data, quotes_svc
from ..errors import ApiException

STALE_DAYS = 7
_score_cache: dict = {}
PEERS = 12
CR = 1e7
YEAR_LINES = [                      # (key, label, kind): kind cr = rupees shown in crore, pct, x, num
    ("revenue", "Revenue", "cr"), ("opex", "Operating expenses", "cr"), ("ebitda", "Operating profit", "cr"),
    ("opm", "Operating margin %", "pct"), ("other_income", "Other income", "cr"), ("depreciation", "Depreciation", "cr"),
    ("finance_costs", "Interest", "cr"), ("pbt", "Profit before tax", "cr"), ("tax_rate", "Tax %", "pct"),
    ("profit", "Net profit (to shareholders)", "cr"), ("eps", "EPS ₹", "num"), ("payout", "Dividend payout %", "pct"),
]
BANK_LINES = [
    ("revenue", "Interest earned", "cr"), ("finance_costs", "Interest expended", "cr"), ("nii", "Net interest income", "cr"),
    ("other_income", "Other income", "cr"), ("opex", "Operating expenses", "cr"), ("cost_to_income", "Cost to income %", "pct"),
    ("provisions", "Provisions", "cr"), ("pbt", "Profit before tax", "cr"), ("tax_rate", "Tax %", "pct"),
    ("profit", "Net profit (to shareholders)", "cr"), ("eps", "EPS ₹", "num"), ("gross_npa_pct", "Gross NPA %", "pct"),
    ("net_npa_pct", "Net NPA %", "pct"),
]
BS_LINES = [
    ("equity", "Equity (capital + reserves)", "cr"), ("borrowings", "Borrowings", "cr"), ("deposits", "Deposits", "cr"),
    ("total_assets", "Total assets", "cr"), ("ppe", "Fixed assets", "cr"), ("cwip", "Capital work in progress", "cr"),
    ("advances", "Advances (loans)", "cr"), ("receivables", "Trade receivables", "cr"), ("inventories", "Inventories", "cr"),
    ("cash", "Cash and equivalents", "cr"), ("current_investments", "Current investments", "cr"),
]
CF_LINES = [
    ("cfo", "Cash from operations", "cr"), ("cfi", "Cash from investing", "cr"), ("cff", "Cash from financing", "cr"),
    ("capex", "Capital expenditure", "cr"), ("fcf", "Free cash flow", "cr"), ("cash_conversion", "Cash from operations / profit %", "pct"),
    ("dividends_paid", "Dividends paid", "cr"),
]
RATIO_LINES = [
    ("roce", "ROCE %", "pct"), ("roe", "ROE %", "pct"), ("roa", "ROA %", "pct"), ("de", "Debt / equity", "x"),
    ("npm", "Net margin %", "pct"), ("sales_growth", "Sales growth %", "pct"), ("profit_growth", "Profit growth %", "pct"),
]
Q_LINES = [
    ("revenue", "Revenue", "cr"), ("ebitda", "Operating profit", "cr"), ("opm", "Operating margin %", "pct"),
    ("other_income", "Other income", "cr"), ("finance_costs", "Interest", "cr"), ("depreciation", "Depreciation", "cr"),
    ("pbt", "Profit before tax", "cr"), ("profit", "Net profit", "cr"), ("eps", "EPS ₹", "num"),
    ("sales_growth", "Sales y/y %", "pct"), ("profit_growth", "Profit y/y %", "pct"),
]


def _v(x, kind: str):
    if x is None or (isinstance(x, float) and not math.isfinite(x)):
        return None
    x = float(x)
    return round(x / CR, 0 if abs(x) >= 1e9 else 2) if kind == "cr" else round(x, 2 if kind in ("x", "num") else 1)


def _table(df, lines: list[tuple], sym: str = "") -> dict:
    """{'periods': [...], 'rows': [{key, label, kind, values}]} - rows with no value at all are left out."""
    if df is None or df.empty:
        return {"periods": [], "rows": [], "sources": []}
    rows = []
    for key, label, kind in lines:
        if key not in df:
            continue
        vals = [_v(x, kind) for x in df[key].tolist()]
        if any(v is not None for v in vals):
            rows.append({"key": key, "label": label, "kind": kind, "values": vals})
    src = []
    for r in df.itertuples():
        rid = str(getattr(r, "id", "") or "")
        url = rid if rid.startswith("http") else (            # NSE's page of a pre-XBRL result
            f"https://nsearchives.nseindia.in/archives/financial_results/financial_res_{sym}_{rid}.html"
            if rid.isdigit() and sym else None)
        src.append({"filed": getattr(r, "filed", None), "src": getattr(r, "src", None), "url": url})
    return {"periods": df["end"].tolist(), "rows": rows, "sources": src}


def _price(sym: str) -> float | None:
    try:
        q = quotes_svc.quotes([sym], allow_network=False).get("quotes") or []
        if q and q[0].get("price"):
            return float(q[0]["price"])
    except Exception:
        pass
    sc = data.screener()
    if sc is not None and not sc.empty:
        row = sc[sc["symbol"] == sym]
        if len(row) and row["price"].iloc[0] == row["price"].iloc[0]:
            return float(row["price"].iloc[0])
    return None


def _peer_price() -> dict[str, float]:
    sc = data.screener()
    if sc is None or sc.empty:
        return {}
    return {r.symbol: float(r.price) for r in sc.itertuples(index=False) if r.price == r.price}


def _snap_row(sym: str, rec: dict, price: float | None) -> dict:
    s = fin.snapshot(rec, price)
    meta = data.symbol_meta().get(sym) or {}
    return {"symbol": sym, "company": meta.get("company") or rec.get("name"), "price": price,
            "market_cap_cr": _v(s.get("market_cap"), "cr"), "pe": _v(s.get("pe"), "x"), "pb": _v(s.get("pb"), "x"),
            "roce": _v(s.get("roce"), "pct"), "roe": _v(s.get("roe"), "pct"), "de": _v(s.get("de"), "x"),
            "opm": _v(s.get("opm"), "pct"), "sales_cagr_3y": _v(s.get("sales_cagr_3y"), "pct"),
            "profit_cagr_3y": _v(s.get("profit_cagr_3y"), "pct"), "sales_ttm_cr": _v(s.get("sales_ttm"), "cr"),
            "profit_ttm_cr": _v(s.get("profit_ttm"), "cr"), "dividend_yield": _v(s.get("dividend_yield"), "pct")}


def scores() -> dict[str, dict]:
    """Today's quality / value / momentum score (scanner/qvm.py) of every scan-universe stock whose financials are
    stored: symbol -> {quality, value, momentum, score}. Cached until a filing or the scan changes."""
    import pandas as pd
    from scanner import qvm
    sc = data.screener()
    if sc is None or sc.empty:
        return {}
    d = fin.folder()
    ver = (d.stat().st_mtime_ns if d.exists() else None, str(sc["scan_id"].iloc[0]) if "scan_id" in sc else len(sc))
    if _score_cache.get("ver") == ver:
        return _score_cache["out"]
    rows = []
    for r in sc.itertuples(index=False):
        if not fin._file(r.symbol).exists():
            continue
        rec = fin.load(r.symbol)
        s = fin.snapshot(rec, float(r.price) if r.price == r.price else None)
        pb = s.get("pb")
        rows.append({"symbol": r.symbol, "roe": s.get("roe"), "de": s.get("de"), "bank": bool(rec.get("bank")),
                     "earnings_yield": s.get("earnings_yield"), "book_yield": (1 / pb) if pb else None,
                     "momentum_score": float(r.momentum_score) if r.momentum_score == r.momentum_score else None})
    out = {}
    if rows:
        t = qvm.current(pd.DataFrame(rows))
        out = {r["symbol"]: {k: r[k] for k in ("quality", "value", "momentum", "score")} for r in t.to_dict("records")}
    _score_cache.update(ver=ver, out=out)
    return out


def peers(sym: str) -> dict:
    """Stocks of the same industry (the universe's classification) whose financials are stored, largest first."""
    meta = data.symbol_meta()
    ind = (meta.get(sym) or {}).get("industry")
    if not ind:
        return {"industry": None, "rows": [], "missing": 0}
    same = [s for s, m in meta.items() if (m or {}).get("industry") == ind]
    prices = _peer_price()
    bank = bool(fin.load(sym).get("bank"))
    rows, missing = [], 0
    for s in same:
        if not fin._file(s).exists():
            missing += 1
            continue
        rec = fin.load(s)
        if bool(rec.get("bank")) != bank:              # banks next to banks, not to NBFCs or insurers
            continue
        rows.append(_snap_row(s, rec, _price(s) if s == sym else prices.get(s)))
    rows.sort(key=lambda r: -(r["market_cap_cr"] or 0))
    top = rows[:PEERS]
    if sym not in {r["symbol"] for r in top}:
        top += [r for r in rows if r["symbol"] == sym]
    return {"industry": ind, "rows": top, "missing": missing, "total": len(same)}


def view(symbol: str, basis: str | None = None, refresh: bool = False) -> dict:
    sym = symbol.upper().strip()
    if not sym.replace("-", "").replace("&", "").isalnum() or len(sym) > 20:
        raise ApiException("VALIDATION", f"{symbol!r} is not a stock symbol.")
    rec = fin.load(sym)
    note = None
    checked = rec.get("checked")
    if refresh or not checked or (date.today() - date.fromisoformat(checked)).days >= STALE_DAYS:
        try:
            rec = fin.update(sym, pause=0.12)
        except Exception as e:                       # NSE down: what is stored still shows
            note = f"NSE did not answer ({type(e).__name__}); showing what is stored."
    b = fin.basis_for(rec, basis)
    price = _price(sym)
    years = fin.years_table(rec, b)
    quarters = fin.quarters_table(rec, b)
    if not years.empty:
        years = years.tail(fin.YEARS)
    snap = fin.snapshot(rec, price, b)
    meta = data.symbol_meta().get(sym) or {}
    has = {x: bool(rec["bases"][x]["years"] or rec["bases"][x]["quarters"]) for x in fin.BASES}
    return {
        "symbol": sym, "company": meta.get("company") or rec.get("name"), "industry": meta.get("industry") or rec.get("industry"),
        "bank": bool(rec.get("bank")), "basis": b, "bases": has, "checked": rec.get("checked"), "price": price,
        "snapshot": {k: (_v(v, "cr") if k in ("market_cap", "sales_ttm", "profit_ttm") else
                         _v(v, "x") if k in ("pe", "pb", "de") else round(v, 2) if isinstance(v, float) else v)
                     for k, v in snap.items() if k not in ("shares",)},
        "years": _table(years, BANK_LINES if rec.get("bank") else YEAR_LINES, sym),
        "balance_sheet": _table(years[years["equity"].notna() | years["total_assets"].notna()]
                                if not years.empty else years, BS_LINES, sym),
        "cash_flow": _table(years[years["cfo"].notna()] if not years.empty else years, CF_LINES, sym),
        "ratios": _table(years, RATIO_LINES, sym),
        "quarters": _table(quarters, Q_LINES, sym),
        "segments": [{**s, "segments": [{"name": x["name"], "revenue_cr": _v(x.get("revenue"), "cr"),
                                         "result_cr": _v(x.get("result"), "cr")} for x in s["segments"]]}
                     for s in fin.segments(rec, b)],
        "peers": peers(sym),
        "score": {**(scores().get(sym) or {}), "ranked": len(scores())},
        "note": note or ("From NSE's filings: results back to 2005 (NSE's own line items before 2019, XBRL after), "
                         "balance sheets from FY2019, cash flows from FY2020. Consolidated and standalone are never "
                         "mixed. Numbers are as filed - open a year's filing to check one; EPS is not adjusted for later bonuses or "
                         "splits, and NSE's own lists have gaps (missing years stay blank)."),
    }
