"""Ten-plus years of company financials from NSE's official filings - the profit & loss, balance sheet, cash flow,
segments and ratios that Screener.in, Tijori or Trendlyne show, built from the same public filings they start from.
(Their own pages may not be copied or used as a database: their terms forbid it. NSE's filings are the source.)

Sources, all NSE, all public, one company at a time:
  api/corporates-financial-results?period=Annual|Quarterly   every result filed since 2005, consolidated and
                                                            standalone, with an XBRL link from 2019
  api/corporates-financial-results-data                      a pre-XBRL result's line items (P&L, paid-up capital,
                                                            reserves; rupees in lakh)
  nsearchives .../corporate/xbrl/*.xml                       XBRL results: P&L, balance sheet, cash flow, segments
  api/integrated-filing-results                              the quarterly "integrated filing" since 2025 (XBRL; its
                                                            March filing also carries the full year)
What the filings hold decides what is shown: the P&L goes back to 2005, balance sheets to FY2019 (the results'
statement of assets and liabilities), cash flows to FY2020. Pre-XBRL years have equity (paid-up capital + reserves)
but no borrowings, so ROE goes back further than ROCE. Banks file a different layout (interest earned / expended,
deposits, advances, NPAs) and get their own ratios; ROCE does not apply to them.

Stored per company in data/financials/{SYMBOL}.json, both bases kept apart (never mixed in one series). Each
period keeps the day it was filed, so a backtest only sees what was public then (point in time). Fetching is
incremental: a period is downloaded again only when NSE lists a different filing for it (a revision).
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

DIR = DATA_DIR / "financials"
LAKH = 1e5
YEARS = 12                                  # fiscal years kept per basis
QUARTERS = 12
BASES = ("consolidated", "standalone")
ARCHIVE = ("https://nsearchives.nseindia.com/", "https://nsearchives.nseindia.in/")

# XBRL tags, first one present wins. P&L and cash flow: the period's duration context; balance sheet: its instant.
PL = {
    "revenue": ("RevenueFromOperations", "TotalRevenueFromOperations", "InterestEarned"),
    "other_income": ("OtherIncome",),
    "total_income": ("Income", "TotalIncome"),
    "expenses": ("Expenses", "TotalExpenses"),
    "materials": ("CostOfMaterialsConsumed",),
    "employee": ("EmployeeBenefitExpense",),
    "depreciation": ("DepreciationDepletionAndAmortisationExpense", "DepreciationAndAmortisationExpense"),
    "finance_costs": ("FinanceCosts", "InterestExpended"),
    "bank_opex": ("OperatingExpenses",),
    "provisions": ("ProvisionsOtherThanTaxAndContingencies",),
    "exceptional": ("ExceptionalItemsBeforeTax", "ExceptionalItems"),
    "pbt": ("ProfitBeforeTax", "ProfitLossBeforeTax", "ProfitLossFromOrdinaryActivitiesBeforeTax"),
    "tax": ("TaxExpense", "TotalTaxExpense"),
    "current_tax": ("CurrentTax",),
    "deferred_tax": ("DeferredTax",),
    "profit": ("ProfitLossForPeriod", "ProfitLossForThePeriod", "NetProfitLossForThePeriod"),
    "profit_owners": ("ProfitOrLossAttributableToOwnersOfParent", "ProfitLossAttributableToOwnersOfParent"),
    "eps": ("BasicEarningsLossPerShareFromContinuingOperations",
            "BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations", "BasicEarningsLossPerShare",
            "BasicEarningsPerShareAfterExtraordinaryItems"),
    "paid_up": ("PaidUpValueOfEquityShareCapital",),
    "face_value": ("FaceValueOfEquityShareCapital",),
    "cfo": ("CashFlowsFromUsedInOperatingActivities",),
    "cfi": ("CashFlowsFromUsedInInvestingActivities",),
    "cff": ("CashFlowsFromUsedInFinancingActivities",),
    "capex_ppe": ("PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities",),
    "capex_intangible": ("PurchaseOfIntangibleAssetsClassifiedAsInvestingActivities",),
    "dividends_paid": ("DividendsPaidClassifiedAsFinancingActivities",),
    "gross_npa_pct": ("PercentageOfGrossNpa",),
    "net_npa_pct": ("PercentageOfNpa",),
}
BS = {
    "equity_owners": ("EquityAttributableToOwnersOfParent",),
    "equity": ("Equity",),
    "share_capital": ("EquityShareCapital", "Capital"),
    "other_equity": ("OtherEquity", "ReservesAndSurplus", "Reserves"),
    "borrowings_nc": ("BorrowingsNoncurrent",),
    "borrowings_c": ("BorrowingsCurrent",),
    "borrowings": ("Borrowings",),
    "total_assets": ("Assets",),
    "cash": ("CashAndCashEquivalents", "CashAndBalancesWithReserveBankOfIndia"),
    "bank_balances": ("BankBalanceOtherThanCashAndCashEquivalents",),
    "current_investments": ("CurrentInvestments",),
    "receivables": ("TradeReceivablesCurrent",),
    "inventories": ("Inventories",),
    "ppe": ("PropertyPlantAndEquipment", "FixedAssets"),
    "cwip": ("CapitalWorkInProgress",),
    "deposits": ("Deposits",),
    "advances": ("Advances",),
    "current_liabilities": ("CurrentLiabilities",),
    "current_assets": ("CurrentAssets",),
}
# Pre-XBRL line items (rupees in lakh; banks have their own fields)
OLD = {
    "revenue": ("re_net_sale", "re_int_earned"), "other_income": ("re_oth_inc_new", "re_oth_inc"),
    "total_income": ("re_total_inc", "re_tot_inc", "re_gro_inc"), "depreciation": ("re_depr_und_exp",),
    "finance_costs": ("re_int_new", "re_int", "re_int_expd"), "materials": ("re_rawmat_consump",),
    "employee": ("re_staff_cost", "re_prov_emp_pay"), "exceptional": ("re_excepn_items_new",),
    "pbt": ("re_pro_loss_bef_tax",), "tax": ("re_tax",), "profit": ("re_con_pro_loss", "re_net_profit", "re_proloss_ord_act"),
    "eps": ("re_bsc_eps_bfr_exi", "re_basic_eps_for_cont_dic_opr", "re_basic_eps"), "paid_up": ("re_pdup",),
    "reserves": ("re_res_reval",), "bank_opex": ("re_oper_exp",), "provisions": ("re_oth_pro_cont",),
    "total_expenses": ("re_oth_tot_exp", "re_tot_exp_exc_pro_cont"),
}
OLD_RAW = {"face_value": ("re_face_val",), "gross_npa_pct": ("re_grs_npa_per",), "roa_pct": ("re_ret_asset",)}


def folder():
    return DIR


def _file(sym: str):
    return folder() / f"{sym.upper()}.json"


def _blank(sym: str) -> dict:
    return {"symbol": sym.upper(), "checked": None, "bank": False, "primary": None, "name": None, "industry": None,
            "bases": {b: {"years": {}, "quarters": {}} for b in BASES}}


def load(sym: str) -> dict:
    try:
        rec = json.loads(_file(sym).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return _blank(sym)
    for b in BASES:
        rec.setdefault("bases", {}).setdefault(b, {"years": {}, "quarters": {}})
    return rec


def _save(sym: str, rec: dict) -> None:
    folder().mkdir(parents=True, exist_ok=True)
    tmp = _file(sym).with_suffix(".tmp")
    tmp.write_text(json.dumps(rec, separators=(",", ":")), encoding="utf-8")
    tmp.replace(_file(sym))


def _d(s) -> date | None:
    for fmt in ("%d-%b-%Y %H:%M:%S", "%d-%b-%Y %H:%M", "%d-%b-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(str(s).strip().title(), fmt).date()
        except ValueError:
            pass
    return None


def _num(v) -> float | None:
    try:
        f = float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


# ------------------------------------------------------------------ which filings exist
def result_list(sym: str, period: str, get=None) -> list[dict]:
    """NSE's list of results ('Annual' or 'Quarterly'), one row per filing, oldest format first in NSE's order."""
    get = get or events._get_json
    rows = get("corporates-financial-results", {"index": "equities", "symbol": sym.upper(), "period": period})
    out = []
    for x in rows if isinstance(rows, list) else []:
        end, start = _d(x.get("toDate")), _d(x.get("fromDate"))
        if not end:
            continue
        xbrl = str(x.get("xbrl") or "")
        out.append({"end": end.isoformat(), "start": start.isoformat() if start else None,
                    "basis": "standalone" if "non" in str(x.get("consolidated")).lower() else "consolidated",
                    "filed": (_d(x.get("filingDate")) or _d(x.get("broadCastDate")) or end).isoformat(),
                    "xbrl": xbrl if xbrl.startswith(ARCHIVE) and xbrl.lower().endswith(".xml") else None,
                    "id": str(x.get("seqNumber") or xbrl), "bank": str(x.get("bank") or "N").upper() not in ("N", ""),
                    "old": {k: x.get(k) for k in ("params", "seqNumber", "industry", "oldNewFlag", "reInd", "format")},
                    "name": x.get("companyName"), "industry": x.get("industry")})
    out.sort(key=lambda r: (r["end"], r["filed"]))
    return out


def integrated_list(sym: str, get=None) -> list[dict]:
    """The integrated filings (financials) since 2025: one row per quarter and basis, with its XBRL."""
    get = get or events._get_json
    out, page = [], 1
    while page <= 4:
        r = get("integrated-filing-results", {"index": "equities", "symbol": sym.upper()} if page == 1 else
                {"index": "equities", "symbol": sym.upper(), "page": page, "size": 20})
        rows = (r or {}).get("data") or [] if isinstance(r, dict) else []
        for x in rows:
            xbrl = str(x.get("xbrl") or "")
            if "Financial" not in str(x.get("type")) or not xbrl.startswith(ARCHIVE):
                continue
            qe, filed = _d(x.get("qe_Date")), _d(x.get("broadcast_Date") or x.get("creation_Date"))
            if qe:
                out.append({"end": qe.isoformat(), "basis": "consolidated" if str(x.get("consolidated")).lower()
                            .startswith("consol") else "standalone", "filed": (filed or qe).isoformat(), "xbrl": xbrl,
                            "id": xbrl, "integrated": True})
        if not isinstance(r, dict) or int(r.get("totalCount") or 0) <= len(rows) * page or not rows:
            break
        page += 1
    return out


# ------------------------------------------------------------------ parsing
_CTX = re.compile(r"<xbrli:context id=\"([^\"]+)\">(.*?)</xbrli:context>", re.S)
_NUM = re.compile(r"<[\w-]+:(\w+)\s[^>]*contextRef=\"([^\"]+)\"[^>]*>\s*([-\d.Ee+]+)\s*</")
_TXT = re.compile(r"<[\w-]+:(DescriptionOfReportableSegment|DescriptionOfSegment)\s[^>]*contextRef=\"([^\"]+)\"[^>]*>([^<]*)</")
_REP_START = re.compile(r"<[\w-]+:DateOfStartOfReportingPeriod\s[^>]*contextRef=\"([^\"]+)\"[^>]*>\s*([\d-]{10})")
_REP_END = re.compile(r"<[\w-]+:DateOfEndOfReportingPeriod\s[^>]*contextRef=\"([^\"]+)\"[^>]*>\s*([\d-]{10})")
_WORD = re.compile(r"[A-Z][a-z]+")
_USED = re.compile(r"contextRef=\"([^\"]+)\"")
_FY_START = re.compile(r"DateOfStartOfFinancialYear\s[^>]*>\s*([\d-]{10})")
_MEMBER = re.compile(r"explicitMember[^>]*dimension=\"[^\"]*?(\w+)\"[^>]*>[^<:]*:?(\w+)</")


def _contexts(text: str) -> dict:
    """context id -> {'start','end'} (duration) or {'instant'}, and its dimension members [(axis, member)]."""
    out = {}
    for cid, body in _CTX.findall(text):
        m = re.search(r"<xbrli:startDate>([^<]+)</xbrli:startDate>\s*<xbrli:endDate>([^<]+)</xbrli:endDate>", body)
        i = re.search(r"<xbrli:instant>([^<]+)</xbrli:instant>", body)
        c = {"members": _MEMBER.findall(body), "typed": "typedMember" in body}
        if m:
            c.update(start=m.group(1)[:10], end=m.group(2)[:10])
        elif i:
            c.update(instant=i.group(1)[:10])
        out[cid] = c
    # The 2019-2024 XBRL dates every column with the last quarter's period; the real one is in each column's
    # DateOfStart/EndOfReportingPeriod facts ('OneD' = the quarter, 'FourD' = the year to date), and the columns'
    # other contexts share their id's first word ('OneOperatingExpenses01D').
    starts = dict(_REP_START.findall(text))
    ends = dict(_REP_END.findall(text))
    fixed = {}
    for cid, st in starts.items():
        c = out.get(cid)
        if c and "start" in c:
            fixed[cid] = ((c["start"], c["end"]), (st[:10], ends.get(cid, c["end"])[:10]))
    # FY2019-23 files often use the results' column contexts ('OneD' = this quarter, 'FourD' = the year to date,
    # 'OneI' / 'FourI' = the balance sheet date) without defining them: rebuild them from the reporting-date facts,
    # else from the SEBI results layout itself
    fy_start = _FY_START.search(text)
    any_end = next(iter(ends.values()), None)
    for cid in set(_USED.findall(text)) - set(out):
        w = _WORD.match(cid)
        if not w or cid not in (w.group(0) + "D", w.group(0) + "I"):
            continue
        end = (ends.get(cid) or ends.get(w.group(0) + "D") or any_end or "")[:10]
        if not end:
            continue
        if cid.endswith("I"):
            out[cid] = {"members": [], "typed": False, "instant": end}
            continue
        st = starts.get(cid)
        if not st and w.group(0) == "One":
            st = (pd.Timestamp(end) - pd.DateOffset(months=3) + pd.Timedelta(days=1)).date().isoformat()
        elif not st and w.group(0) == "Four":
            st = fy_start.group(1) if fy_start else                 (pd.Timestamp(end) - pd.DateOffset(months=12) + pd.Timedelta(days=1)).date().isoformat()
        if st:
            out[cid] = {"members": [], "typed": False, "start": st[:10], "end": end}
    by_word = {}
    for cid, (orig, real) in fixed.items():
        w = _WORD.match(cid)
        if w:
            by_word[w.group(0)] = (orig, real)
    for cid, c in out.items():
        if "start" not in c:
            continue
        if cid in fixed:
            c["start"], c["end"] = fixed[cid][1]
            continue
        w = _WORD.match(cid)
        hit = by_word.get(w.group(0)) if w else None
        if hit and (c["start"], c["end"]) == hit[0]:
            c["start"], c["end"] = hit[1]
    return out


def _months(start: str, end: str) -> int:
    days = (date.fromisoformat(end) - date.fromisoformat(start)).days
    return 12 if 350 <= days <= 380 else 3 if 80 <= days <= 100 else 6 if 170 <= days <= 190 else 0


def parse_xbrl(text: str, end: str, months: int) -> dict:
    """One period of an XBRL result: the P&L and cash flow of the `months` (3 or 12) ending `end`, the balance sheet at
    `end`, and the reportable segments' revenue and result for that duration. Rupees. Missing items stay absent."""
    ctxs = _contexts(text)
    plain = {cid for cid, c in ctxs.items() if not c["members"] and not c["typed"]}
    dur = {cid for cid in plain if ctxs[cid].get("end") == end and _months(ctxs[cid]["start"], end) == months}
    inst = {cid for cid in plain if ctxs[cid].get("instant") == end}
    facts_d, facts_i, seg_num = {}, {}, {}
    for name, cid, val in _NUM.findall(text):
        v = _num(val)
        if v is None:
            continue
        if cid in dur:
            facts_d.setdefault(name, v)
        elif cid in inst:
            facts_i.setdefault(name, v)
        else:
            c = ctxs.get(cid)
            if c and c["members"] and c.get("end") == end and _months(c["start"], end) == months and \
                    name in ("SegmentRevenue", "SegmentProfitLossBeforeTaxAndFinanceCosts", "SegmentProfitBeforeTax"):
                member = next((mem for axis, mem in c["members"] if "Segment" in axis), None)
                if member:
                    seg_num.setdefault(member, {}).setdefault(name, v)
    out: dict = {}
    for k, names in PL.items():
        v = next((facts_d[n] for n in names if n in facts_d), None)
        if v is not None:
            out[k] = v
    for k, names in BS.items():
        v = next((facts_i[n] for n in names if n in facts_i), None)
        if v is not None:
            out[k] = v
    # normalise
    if "profit_owners" in out:
        out["profit"] = out.pop("profit_owners")             # the group's profit that belongs to shareholders
    if "tax" not in out and ("current_tax" in out or "deferred_tax" in out):
        out["tax"] = out.get("current_tax", 0.0) + out.get("deferred_tax", 0.0)
    out.pop("current_tax", None)
    out.pop("deferred_tax", None)
    eq = out.pop("equity_owners", None)
    if eq is not None:
        out["equity"] = eq
    elif "equity" not in out and "share_capital" in out and "other_equity" in out:
        out["equity"] = out["share_capital"] + out["other_equity"]
    if "borrowings" not in out and ("borrowings_nc" in out or "borrowings_c" in out):
        out["borrowings"] = out.get("borrowings_nc", 0.0) + out.get("borrowings_c", 0.0)
    out.pop("borrowings_nc", None)
    out.pop("borrowings_c", None)
    if "capex_ppe" in out or "capex_intangible" in out:
        out["capex"] = abs(out.pop("capex_ppe", 0.0)) + abs(out.pop("capex_intangible", 0.0))
    if "dividends_paid" in out:
        out["dividends_paid"] = abs(out["dividends_paid"])
    if "expenses" in out:                                      # Ind AS total expenses include depreciation and interest
        out["opex"] = out["expenses"] - out.get("depreciation", 0.0) - out.get("finance_costs", 0.0)
    elif "bank_opex" in out:
        out["opex"] = out["bank_opex"]
    # segments: names from the text facts (any duration), numbers for this duration
    names = {}
    for _n, cid, txt in _TXT.findall(text):
        c = ctxs.get(cid)
        member = next((mem for axis, mem in (c or {}).get("members", []) if "Segment" in axis), None)
        if member and txt.strip():
            names.setdefault(member, txt.strip())
    segs = []
    for member, vals in seg_num.items():
        if "SegmentRevenue" not in vals:
            continue
        segs.append({"name": names.get(member, member), "revenue": vals["SegmentRevenue"],
                     "result": vals.get("SegmentProfitLossBeforeTaxAndFinanceCosts", vals.get("SegmentProfitBeforeTax"))})
    if segs:
        out["segments"] = sorted(segs, key=lambda s: -(s["revenue"] or 0))
    return out


def parse_old(d: dict) -> dict:
    """A pre-XBRL result (corporates-financial-results-data): its line items, lakh converted to rupees."""
    rd = (d or {}).get("resultsData2") or (d or {}).get("resultsData") or {}
    out = {}
    for k, names in OLD.items():
        v = next((_num(rd.get(n)) for n in names if _num(rd.get(n)) not in (None,)), None)
        if v is not None:
            out[k] = v * LAKH if k != "eps" else v
    for k, names in OLD_RAW.items():
        v = next((_num(rd.get(n)) for n in names if _num(rd.get(n)) is not None), None)
        if v is not None:
            out[k] = v
    if "paid_up" in out and out.get("reserves", 0) > 0:
        out["equity"] = out["paid_up"] + out["reserves"]
    te = out.pop("total_expenses", None)
    if te is not None and "bank_opex" not in out:
        out["opex"] = te - out.get("depreciation", 0.0)          # old layout: total expenses exclude interest only
    elif "bank_opex" in out:
        out["opex"] = out["bank_opex"]
    out.pop("reserves", None)
    if out.get("eps") == 0:
        out.pop("eps")
    return out


# ------------------------------------------------------------------ fetching
def _fetch_old(row: dict, get) -> dict:
    o = row["old"]
    d = get("corporates-financial-results-data", {"index": "equities", "params": o.get("params"), "seq_id": o.get("seqNumber"),
                                                 "industry": o.get("industry") or "-", "frOldNewFlag": o.get("oldNewFlag"),
                                                 "ind": o.get("reInd"), "format": o.get("format")})
    return parse_old(d if isinstance(d, dict) else {})


def _fetch(row: dict, months: int, get, get_bytes) -> dict | None:
    if row.get("xbrl"):
        code, body = get_bytes(row["xbrl"])
        if code != 200:
            return None
        nums = parse_xbrl(body.decode("utf-8", "replace"), row["end"], months)
        if months == 12 and not nums.get("revenue") and not nums.get("profit"):
            return None                                     # an integrated filing without the full-year columns
        if months == 12 and "equity" not in nums and not row.get("integrated") and row.get("old", {}).get("params"):
            try:                                            # FY2019-22 XBRL has no balance sheet: NSE's own line items
                for k, v in _fetch_old(row, get).items():   # give equity, paid-up capital and face value
                    nums.setdefault(k, v)
            except Exception:
                pass
        return nums
    if row.get("integrated"):
        return None
    return _fetch_old(row, get) or None


def _latest(rows: list[dict]) -> dict[tuple, dict]:
    """(basis, end) -> the newest filing for it (a revision wins)."""
    out: dict[tuple, dict] = {}
    for r in sorted(rows, key=lambda r: (r["filed"], r.get("xbrl") is not None)):
        out[(r["basis"], r["end"])] = r
    return out


def update(sym: str, get=None, get_bytes=None, pause: float = 0.35, years: int = YEARS, quarters: int = QUARTERS,
           log=lambda m: None) -> dict:
    """Fetch what is missing or revised for one company (both bases for years, the primary basis for quarters).
    Network errors on single periods are skipped (the next run tries again); the record is saved as it goes."""
    get = get or events._get_json
    raw_bytes = get_bytes or nse._get_bytes
    downloaded: dict[str, tuple] = {}

    def get_bytes(url):                                     # the March filing serves the year and the quarter
        if url not in downloaded:
            downloaded[url] = raw_bytes(url)
        return downloaded[url]
    sym = sym.upper()
    rec = load(sym)
    annual = result_list(sym, "Annual", get)
    quarterly = result_list(sym, "Quarterly", get)
    integ = integrated_list(sym, get)
    meta = next((r for r in reversed(annual + quarterly) if r.get("name")), None)
    if meta:
        rec["name"] = meta["name"]
        if meta.get("industry") not in (None, "-", ""):
            rec["industry"] = meta["industry"]
    rec["bank"] = any(r["bank"] for r in annual[-4:] + quarterly[-4:])
    recent = sorted(annual + quarterly + integ, key=lambda r: r["end"])[-8:]
    rec["primary"] = "consolidated" if any(r["basis"] == "consolidated" for r in recent) else "standalone"
    # years: the old annual list, plus each integrated March-quarter filing (it carries the full year)
    fy_month = int(annual[-1]["end"][5:7]) if annual else 3
    year_rows = _latest(annual + [r for r in integ if int(r["end"][5:7]) == fy_month])
    q_rows = _latest(quarterly + integ)
    todo = []
    for basis in BASES:
        ends = sorted({e for (b, e) in year_rows if b == basis})[-years:]
        todo += [("years", basis, e, year_rows[(basis, e)], 12) for e in ends]
    ends = sorted({e for (b, e) in q_rows if b == rec["primary"]})[-quarters:]
    todo += [("quarters", rec["primary"], e, q_rows[(rec["primary"], e)], 3) for e in ends]
    fetched = 0
    for kind, basis, end, row, months in todo:
        have = rec["bases"][basis][kind].get(end)
        if have and have.get("id") == row["id"]:
            continue
        try:
            nums = _fetch(row, months, get, get_bytes)
        except Exception as e:                              # one bad filing never stops the rest
            log(f"{sym} {kind} {end} {basis}: {type(e).__name__}: {e}")
            nums = None
        if nums is None and kind == "years" and row.get("integrated"):
            continue
        if nums is not None:
            rec["bases"][basis][kind][end] = {**nums, "filed": row["filed"], "id": row["id"],
                                              "src": "xbrl" if row.get("xbrl") else "nse"}
            fetched += 1
            if fetched % 8 == 0:
                _save(sym, rec)
        time.sleep(pause)
    for basis in BASES:                                     # keep the newest only
        for kind, n in (("years", years), ("quarters", quarters)):
            keep = sorted(rec["bases"][basis][kind])[-n:]
            rec["bases"][basis][kind] = {k: rec["bases"][basis][kind][k] for k in keep}
    rec["checked"] = date.today().isoformat()
    _save(sym, rec)
    return rec


# ------------------------------------------------------------------ statements and ratios
def _f(x) -> float | None:
    return None if x is None or (isinstance(x, float) and not math.isfinite(x)) else float(x)


def _div(a, b) -> float | None:
    a, b = _f(a), _f(b)
    return a / b if a is not None and b not in (None, 0.0) else None


def _cagr(new, old, n: int) -> float | None:
    new, old = _f(new), _f(old)
    if new is None or old is None or old <= 0 or new <= 0 or n <= 0:
        return None
    return ((new / old) ** (1 / n) - 1) * 100


def basis_for(rec: dict, basis: str | None = None) -> str:
    if basis in BASES and rec["bases"][basis]["years"]:
        return basis
    p = rec.get("primary") or "consolidated"
    return p if rec["bases"][p]["years"] or rec["bases"][p]["quarters"] else ("standalone" if p == "consolidated" else
                                                                              "consolidated")


def years_table(rec: dict, basis: str) -> pd.DataFrame:
    """Fiscal years, oldest first, with the derived lines and ratios (rupees; percentages as %)."""
    ys = rec["bases"][basis]["years"]
    if not ys:
        return pd.DataFrame()
    df = pd.DataFrame([{"end": k, **{kk: vv for kk, vv in v.items() if kk != "segments"}} for k, v in ys.items()])
    df = df.sort_values("end").reset_index(drop=True)
    for c in ("revenue", "opex", "other_income", "depreciation", "finance_costs", "pbt", "tax", "profit", "eps", "equity",
              "borrowings", "total_assets", "cash", "cfo", "capex", "dividends_paid", "paid_up", "face_value", "cfi", "cff",
              "current_investments", "bank_balances", "deposits", "advances", "gross_npa_pct", "net_npa_pct", "roa_pct"):
        if c not in df:
            df[c] = np.nan
        df[c] = pd.to_numeric(df[c], errors="coerce")
    bank = bool(rec.get("bank"))
    ends = pd.to_datetime(df["end"])
    prev_ok = ((ends - ends.shift(1)).dt.days.between(330, 400)).to_numpy()   # the row before is the year before
    df["ebitda"] = np.nan if bank else df["revenue"] - df["opex"]
    df["opm"] = df["ebitda"] / df["revenue"].where(df["revenue"] > 0) * 100
    df["npm"] = df["profit"] / df["revenue"].where(df["revenue"] > 0) * 100
    df["ebit"] = df["pbt"] + df["finance_costs"].fillna(0)
    df["tax_rate"] = df["tax"] / df["pbt"].where(df["pbt"] > 0) * 100
    avg_eq = ((df["equity"] + df["equity"].shift(1)) / 2).where(prev_ok)
    avg_eq = avg_eq.fillna(df["equity"])
    df["roe"] = df["profit"] / avg_eq.where(avg_eq > 0) * 100
    ce = df["equity"] + df["borrowings"]
    avg_ce = ((ce + ce.shift(1)) / 2).where(prev_ok).fillna(ce)
    df["roce"] = np.nan if bank else df["ebit"] / avg_ce.where(avg_ce > 0) * 100
    df["de"] = df["borrowings"] / df["equity"].where(df["equity"] > 0)
    df["fcf"] = df["cfo"] - df["capex"]
    df["cash_conversion"] = np.nan if bank else df["cfo"] / df["profit"].where(df["profit"] > 0) * 100
    df["roa"] = (df["profit"] / df["total_assets"].where(df["total_assets"] > 0) * 100).fillna(df["roa_pct"])
    df["payout"] = df["dividends_paid"] / df["profit"].where(df["profit"] > 0) * 100
    df["sales_growth"] = (df["revenue"].pct_change(fill_method=None) * 100).where(prev_ok)
    df["profit_growth"] = ((df["profit"] / df["profit"].shift(1).where(df["profit"].shift(1) > 0) - 1) * 100).where(prev_ok)
    df["shares"] = df["paid_up"] / df["face_value"].where(df["face_value"] > 0)
    if bank:                                                # net interest income and the cost-to-income ratio
        df["nii"] = df["revenue"] - df["finance_costs"]
        df["cost_to_income"] = df["opex"] / (df["nii"] + df["other_income"].fillna(0)).where(lambda x: x > 0) * 100
    return df


def quarters_table(rec: dict, basis: str) -> pd.DataFrame:
    qs = rec["bases"][basis]["quarters"]
    if not qs:
        return pd.DataFrame()
    df = pd.DataFrame([{"end": k, **{kk: vv for kk, vv in v.items() if kk != "segments"}} for k, v in qs.items()])
    df = df.sort_values("end").reset_index(drop=True)
    for c in ("revenue", "opex", "other_income", "depreciation", "finance_costs", "pbt", "tax", "profit", "eps"):
        if c not in df:
            df[c] = np.nan
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["ebitda"] = df["revenue"] - df["opex"]
    df["opm"] = df["ebitda"] / df["revenue"].where(df["revenue"] > 0) * 100
    ends = pd.to_datetime(df["end"])
    by = dict(zip(ends, range(len(df))))
    yoy_r, yoy_p = [], []
    for i, e in enumerate(ends):
        j = by.get(e - pd.DateOffset(years=1)) if by.get(e - pd.DateOffset(years=1)) is not None else \
            by.get((e - pd.DateOffset(years=1)) + pd.offsets.MonthEnd(0))
        r0 = df["revenue"].iloc[j] if j is not None else np.nan
        p0 = df["profit"].iloc[j] if j is not None else np.nan
        yoy_r.append((df["revenue"].iloc[i] / r0 - 1) * 100 if r0 and r0 > 0 else np.nan)
        yoy_p.append((df["profit"].iloc[i] / p0 - 1) * 100 if p0 and p0 > 0 else np.nan)
    df["sales_growth"], df["profit_growth"] = yoy_r, yoy_p
    return df


def growth(df: pd.DataFrame) -> dict:
    """Compounded growth of sales and profit over 3, 5 and 10 years (to the latest year), plus the average ROE / ROCE."""
    out = {}
    if df.empty:
        return out
    last = df.iloc[-1]
    ends = pd.to_datetime(df["end"])
    end = ends.iloc[-1]
    for n in (3, 5, 10):
        back = (end - ends).dt.days                         # the year n years back, by date (NSE's lists have gaps)
        hit = df[(back >= 365 * n - 40) & (back <= 365 * n + 40)]
        old = hit.iloc[0] if len(hit) else None
        out[f"sales_cagr_{n}y"] = _cagr(last["revenue"], old["revenue"], n) if old is not None else None
        out[f"profit_cagr_{n}y"] = _cagr(last["profit"], old["profit"], n) if old is not None else None
        window = df[ends > end - pd.DateOffset(years=n, days=40)]
        for k in ("roe", "roce"):
            v = window[k].dropna()
            out[f"{k}_{n}y"] = float(v.mean()) if len(window) == n and len(v) == n else None
    return out


def ttm(rec: dict, basis: str) -> dict:
    """The last four quarters added up (revenue, profit, EPS), when all four are there and consecutive."""
    q = quarters_table(rec, basis)
    if len(q) < 4:
        return {}
    last4 = q.tail(4)
    span = (pd.Timestamp(last4["end"].iloc[-1]) - pd.Timestamp(last4["end"].iloc[0])).days
    if not 260 <= span <= 290:
        return {}
    out = {"end": last4["end"].iloc[-1]}
    for c in ("revenue", "profit", "eps", "ebitda"):
        v = last4[c]
        out[c] = float(v.sum()) if v.notna().all() else None
    return out


def snapshot(rec: dict, price: float | None, basis: str | None = None) -> dict:
    """The headline numbers: market cap, P/E, P/B, ROCE, ROE, D/E, growth, margins - from the latest filings."""
    b = basis_for(rec, basis)
    y = years_table(rec, b)
    t = ttm(rec, b)
    if y.empty and not t:
        return {"basis": b}
    last = y.iloc[-1] if len(y) else pd.Series(dtype=float)
    shares = None
    for _, r in (y.iloc[::-1].iterrows() if len(y) else []):
        if _f(r.get("shares")):
            shares = float(r["shares"])
            break
    mcap = price * shares if price and shares else None
    profit_ttm = t.get("profit") if t else None
    profit = profit_ttm if profit_ttm is not None else _f(last.get("profit"))
    g = growth(y)
    eq_latest = next((float(v) for v in y["equity"][::-1] if _f(v)), None) if len(y) else None
    return {
        "basis": b, "bank": bool(rec.get("bank")), "year_end": last.get("end") if len(y) else None,
        "ttm_end": t.get("end") if t else None, "price": price, "shares": shares, "market_cap": mcap,
        "pe": _div(mcap, profit) if profit and profit > 0 else None,
        "pb": _div(mcap, eq_latest) if eq_latest and eq_latest > 0 else None,
        "sales_ttm": t.get("revenue") if t else None, "profit_ttm": profit_ttm,
        "roce": _f(last.get("roce")) if len(y) else None, "roe": _f(last.get("roe")) if len(y) else None,
        "de": _f(last.get("de")) if len(y) else None, "opm": _f(last.get("opm")) if len(y) else None,
        "npm": _f(last.get("npm")) if len(y) else None, "cash_conversion": _f(last.get("cash_conversion")) if len(y) else None,
        "roa": _f(last.get("roa")) if len(y) else None, "gross_npa_pct": _f(last.get("gross_npa_pct")) if len(y) else None,
        "net_npa_pct": _f(last.get("net_npa_pct")) if len(y) else None,
        "dividend_yield": _div((_f(last.get("dividends_paid")) or 0) * 100, mcap) if mcap and len(y) and _f(last.get("dividends_paid")) else None,
        "earnings_yield": _div((profit or 0) * 100, mcap) if mcap and profit else None,
        **{k: (round(v, 2) if v is not None else None) for k, v in g.items()},
    }


def segments(rec: dict, basis: str) -> list[dict]:
    """Segment revenue and result per fiscal year (and the latest quarter), newest first."""
    out = []
    for kind in ("years", "quarters"):
        items = rec["bases"][basis][kind]
        for end in sorted(items, reverse=True):
            s = items[end].get("segments")
            if s:
                out.append({"period": kind[:-1], "end": end, "segments": s})
                if kind == "quarters":
                    break
    return out[:6]


# ------------------------------------------------------------------ point-in-time frames for scans / backtests
FRAME_FIELDS = ("roce", "roe", "de", "opm", "sales_cagr_3y", "profit_cagr_3y", "sales_cagr_5y", "profit_cagr_5y",
                "cash_conversion", "profit", "equity", "shares", "bank")
_frames_cache: dict = {}


def frames(symbols: list[str], dates: pd.DatetimeIndex) -> dict[str, pd.DataFrame]:
    """Wide frames (dates x symbols) of the yearly ratios, profit, equity and share count, each from the day its
    year's results were filed (bank: 1 for banks). Cached until a company's file changes."""
    folder_ver = (folder().stat().st_mtime_ns if folder().exists() else None, len(symbols), len(dates),
                  dates[0] if len(dates) else None, dates[-1] if len(dates) else None, hash(tuple(symbols)))
    if _frames_cache.get("ver") == folder_ver:
        return _frames_cache["out"]
    out = {c: pd.DataFrame(np.nan, index=dates, columns=symbols) for c in FRAME_FIELDS}
    for s in symbols:
        if not _file(s).exists():
            continue
        rec = load(s)
        y = years_table(rec, basis_for(rec))
        if y.empty:
            continue
        rows = []
        for i in range(len(y)):
            g = growth(y.iloc[: i + 1])
            r = y.iloc[i]
            rows.append({"filed": r.get("filed"), **{k: _f(r.get(k)) for k in ("roce", "roe", "de", "opm", "cash_conversion",
                                                                                 "profit", "equity", "shares")},
                         **{k: g.get(k) for k in ("sales_cagr_3y", "profit_cagr_3y", "sales_cagr_5y", "profit_cagr_5y")},
                         "bank": 1.0 if rec.get("bank") else 0.0})
        t = pd.DataFrame(rows).dropna(subset=["filed"])
        if t.empty:
            continue
        t.index = pd.to_datetime(t["filed"])
        t = t[~t.index.duplicated(keep="last")].sort_index()
        if "shares" in t:                                   # a year without its share count: the last known one
            t["shares"] = pd.to_numeric(t["shares"], errors="coerce").ffill()
        for c in FRAME_FIELDS:
            out[c][s] = pd.to_numeric(t[c], errors="coerce").reindex(dates, method="ffill").to_numpy()
    _frames_cache.update(ver=folder_ver, out=out)
    return out


def refresh(symbols: list[str], log=print, progress=lambda d, t: None, stop=lambda: False, max_age_days: int = 25) -> dict:
    """Update every company not checked in `max_age_days` days. Never raises for NSE trouble."""
    today = date.today()

    def due(s):
        c = load(s).get("checked")
        return not c or (today - date.fromisoformat(c)).days >= max_age_days
    todo = [s for s in symbols if due(s)]
    rep = {"wanted": len(todo), "updated": 0, "errors": []}
    for i, s in enumerate(todo):
        if stop():
            break
        try:
            update(s)
            rep["updated"] += 1
        except Exception as e:
            rep["errors"].append(f"{s}: {type(e).__name__}: {e}")
        progress(i + 1, len(todo))
        if i % 25 == 24:
            log(f"  financials: {i + 1} of {len(todo)}")
    return rep
