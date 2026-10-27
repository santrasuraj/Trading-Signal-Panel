"""Smart money: which stocks big investors (FIIs/FPIs, mutual funds, insurers, banks, pension/sovereign funds,
promoters, well-known investors) bought, sold or left, from NSE's official disclosures (docs/smart_money_spec.md).

  nsearchives.nseindia.com/content/equities/bulk.csv, block.csv   the latest day's bulk / block deals (no cookies)
  www.nseindia.com/api/historicalOR/bulk-block-short-deals         deal history, one calendar month per call
  www.nseindia.com/api/snapshot-capital-market-largedeal           today's deals, only when both files fail
  www.nseindia.com/api/corporates-pit                              insider trades (SEBI PIT Reg 7(2)); NSE stopped
                                                                   filling it in May 2026, so months it leaves (nearly)
                                                                   empty come from:
  www.nseindia.com/api/corporates-pit-gg                           the insider filings list (one month per call), whose
                                                                   XBRL files (nsearchives) hold the trades
  www.nseindia.com/api/fiidiiTradeReact                            FII/DII cash-market net, market-wide (Rs crore)
  www.nseindia.com/api/corporate-share-holdings-master             quarterly shareholding filings, whose XBRL files
                                                                   (nsearchives) give category % and 1%+ holders
Everything is cached under data/smart_money/ (parquet tables, state.json, raw XBRL gzipped in xbrl/). Network
failures never raise: refresh() records them and the loaders return whatever is cached. Every request goes through
_fetch (the tests replace it). This is disclosed data: not live, not a prediction, and big buyers also lose money.
"""
from __future__ import annotations

import functools
import gzip
import io
import json
import math
import re
import threading
import time
import xml.etree.ElementTree as ET
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable, NamedTuple

import numpy as np
import pandas as pd
import requests

from . import nse
from .events import HEADERS as API_HEADERS
from .lock import _try_lock, _unlock
from .settings import DATA_DIR, IST, ist_now, ist_today, load_config

SM_DIR = DATA_DIR / "smart_money"           # NOT created at import; refresh() creates it
API = "https://www.nseindia.com/api/"
HOME = "https://www.nseindia.com/"
BULK_CSV_URL = "https://nsearchives.nseindia.com/content/equities/bulk.csv"
BLOCK_CSV_URL = "https://nsearchives.nseindia.com/content/equities/block.csv"
PAGES = {
    "deals": "https://www.nseindia.com/report-detail/display-bulk-and-block-deals",
    "large": "https://www.nseindia.com/market-data/large-deals",
    "pit": "https://www.nseindia.com/companies-listing/corporate-filings-insider-trading",
    "fiidii": "https://www.nseindia.com/reports/fii-dii",
    "shp": "https://www.nseindia.com/companies-listing/corporate-filings-shareholding-pattern",
}
API_GAP_S = 0.4              # at least this long between two NSE API requests
SESSION_MAX_AGE_S = 420      # re-warm the NSE cookies after 7 minutes
ROUND_TRIP_RATIO = 0.8       # min(buy, sell) / max(buy, sell) at or above this = intraday round trip
HOLDER_MIN_CHANGE_PTS = 0.25 # named-holder stake change that counts as added / cut
CATEGORY_MIN_CHANGE_PTS = 1.0  # category (FII, MF, ...) change that counts as up / down
SHP_LISTING_DAYS = 200       # how far back the shareholding filings list is read
SHP_EVENT_DAYS = 120         # shareholding changes stay "news" this long after the filing
SHP_MAX_GAP_DAYS = 200       # two periods further apart than this are not compared
MAX_SYMBOL_LOOKUPS = 80      # per-symbol shareholding lookups per refresh
RECHECK_DAYS = 7             # failed XBRL / per-symbol lookups are retried after this many days
PAST_MONTH_GRACE_DAYS = 7    # a month whose last day is older than this is final (never re-fetched)
XBRL_WORKERS = 4
MAX_PIT_XBRL = 600            # insider-filing XBRL files read per refresh (~3 min); the rest next time
HOLDERS_PARSER = 2            # bump when parse_shp_xbrl's holders change: cached files are parsed again
XBRL_MAX_FAILURES = 10       # consecutive download failures that stop the XBRL step for this refresh
LOCK_GRACE_S = 2.0           # refresh_running() probes hold the lock for an instant: don't mistake one for a refresh
QUARTER_ENDS = {(3, 31), (6, 30), (9, 30), (12, 31)}

CATEGORIES = ("fii", "mf", "insurance", "bank", "pension", "aif", "promoter", "famous", "broker", "other")
CATEGORY_LABELS = {"fii": "FII/FPI", "mf": "Mutual fund", "insurance": "Insurance", "bank": "Bank/NBFC",
                   "pension": "Pension/sovereign", "aif": "AIF/PE/VC fund", "promoter": "Promoter",
                   "famous": "Well-known investor", "broker": "Broker/prop", "other": "Other"}
INSTITUTIONS = frozenset({"fii", "mf", "insurance", "bank", "pension"})
BIG_MONEY = INSTITUTIONS | {"aif", "promoter", "famous"}
ODI_LABEL = "ODI/arbitrage desk - often hedging clients, weak signal"
LIKELY_PROMOTER = "Likely promoter (name match)"
INSIDER_LABEL = "Company insider (director/KMP)"

SOURCE_NAMES = ("deals", "insider", "flows", "holdings")
EXIT_KINDS = ("full_exit", "below_1pct", "category_exit")   # exit_kind values that mean "left" (not "sold part")

# ------------------------------------------------------------------ stored and derived tables (column -> dtype)
DEAL_COLS: dict[str, str] = {
    "date": "object", "kind": "object", "symbol": "object", "security": "object", "client": "object",
    "client_key": "object", "side": "object", "qty": "float64", "price": "float64", "value": "float64",
    "remarks": "object", "source": "object"}
INSIDER_COLS: dict[str, str] = {
    "symbol": "object", "company": "object", "person": "object", "person_key": "object",
    "person_category": "object", "sec_type": "object", "txn": "object", "side": "object", "mode": "object",
    "mode_kind": "object", "qty": "float64", "value": "float64", "before_shares": "float64",
    "before_pct": "float64", "after_shares": "float64", "after_pct": "float64", "trade_from": "object",
    "trade_to": "object", "intimated": "object", "disclosed": "object", "disclosed_at": "object",
    "exchange": "object", "xbrl": "object"}
INSIDER_EXTRA_COLS: dict[str, str] = {
    "id": "object", "role": "object", "category": "object", "sub_label": "object", "investor": "object",
    "avg_price": "float64", "change_pts": "float64", "is_market": "bool", "fully_exited": "bool",
    "delay_days": "float64"}
PIT_FILING_COLS: dict[str, str] = {   # corporates-pit-gg: one insider filing, its XBRL file and whether it is read
    "app_id": "object", "symbol": "object", "company": "object", "broadcast": "object", "submission": "object",
    "prev_app_id": "object", "xml": "object", "status": "object", "tries": "int64", "last_try": "object"}
FLOW_COLS: dict[str, str] = {
    "date": "object", "fii_buy_cr": "float64", "fii_sell_cr": "float64", "fii_net_cr": "float64",
    "dii_buy_cr": "float64", "dii_sell_cr": "float64", "dii_net_cr": "float64"}
FILING_COLS: dict[str, str] = {
    "symbol": "object", "company": "object", "period": "object", "record_id": "int64", "xbrl": "object",
    "broadcast": "object", "submission": "object", "revised": "bool", "promoter_pct": "float64",
    "public_pct": "float64"}
HOLDING_COLS: dict[str, str] = {
    "symbol": "object", "company": "object", "period": "object", "record_id": "int64", "broadcast": "object",
    "source": "object", "total_shares": "float64", "promoter_pct": "float64", "public_pct": "float64",
    "fii_pct": "float64", "dii_pct": "float64", "mf_pct": "float64", "insurance_pct": "float64",
    "banks_pct": "float64", "pension_pct": "float64", "aif_pct": "float64"}
HOLDER_COLS: dict[str, str] = {
    "symbol": "object", "period": "object", "record_id": "int64", "holder": "object", "holder_key": "object",
    "group": "object", "xbrl_member": "object", "shares": "float64", "pct": "float64"}
HOLDER_EXTRA_COLS: dict[str, str] = {"category": "object", "sub_label": "object", "investor": "object"}
NET_DEAL_COLS: dict[str, str] = {
    "id": "object", "date": "object", "symbol": "object", "client_key": "object", "security": "object",
    "client": "object", "kind": "object", "buy_qty": "float64", "sell_qty": "float64", "net_qty": "float64",
    "buy_value": "float64", "sell_value": "float64", "net_value": "float64", "side": "object",
    "avg_price": "float64", "round_trip": "bool", "category": "object", "sub_label": "object",
    "investor": "object", "pct_equity": "float64", "counterparties": "object"}
HOLDER_CHANGE_COLS: dict[str, str] = {
    "symbol": "object", "period": "object", "prev_period": "object", "holder": "object", "holder_key": "object",
    "group": "object", "category": "object", "sub_label": "object", "investor": "object", "pct": "float64",
    "prev_pct": "float64", "change_pts": "float64", "shares": "float64", "status": "object"}
EVENT_COLS: dict[str, str] = {
    "id": "object", "date": "object", "symbol": "object", "company": "object", "event": "object",
    "direction": "object", "source": "object", "who": "object", "who_key": "object", "investor": "object",
    "category": "object", "sub_label": "object", "value": "float64", "qty": "float64", "pct_before": "float64",
    "pct_after": "float64", "change_pts": "float64", "pct_equity": "float64", "period": "object",
    "prev_period": "object", "exit_kind": "object", "text": "object", "weight": "int64"}
SIGNAL_COLS: dict[str, str] = {
    "symbol": "object", "company": "object", "direction": "object", "up_events": "int64", "down_events": "int64",
    "up_score": "int64", "down_score": "int64", "deal_buy_value": "float64", "deal_sell_value": "float64",
    "deal_net_value": "float64", "inst_buyers": "int64", "inst_sellers": "int64", "famous_buyers": "object",
    "famous_sellers": "object", "insider_buy_value": "float64", "insider_sell_value": "float64",
    "promoter_buying": "bool", "promoter_selling": "bool", "pledge_invoked": "bool", "exits": "int64",
    "fii_chg_pts": "float64", "dii_chg_pts": "float64", "mf_chg_pts": "float64", "promoter_chg_pts": "float64",
    "period": "object", "last_date": "object", "reasons": "object"}

EVENT_WEIGHTS = {"deal_buy": 2, "deal_sell": 2, "insider_buy": 1, "insider_sell": 1, "insider_exit": 2,
                 "pledge_invoked": 2, "new_holder": 2, "holder_added": 1, "holder_cut": 1, "holder_dropped": 2,
                 "category_up": 1, "category_down": 1, "category_exit": 2}
# holdings column -> category slug, for the quarter-on-quarter category events
CATEGORY_FIELDS = (("fii_pct", "fii"), ("mf_pct", "mf"), ("insurance_pct", "insurance"), ("banks_pct", "bank"),
                   ("pension_pct", "pension"), ("promoter_pct", "promoter"))


# ------------------------------------------------------------------ paths and atomic writes
def files(folder: Path | None = None) -> dict[str, Path]:
    """Every file of the cache, built at call time (tests pass their own folder)."""
    f = Path(folder or SM_DIR)
    return {"deals": f / "deals.parquet", "insider": f / "insider.parquet", "flows": f / "flows.parquet",
            "holdings": f / "holdings.parquet", "holders": f / "holders.parquet",
            "filings": f / "shp_filings.parquet", "pit_filings": f / "pit_filings.parquet", "state": f / "state.json",
            "unmatched": f / "unmatched_names.json"}


def _replace(tmp: Path, path: Path) -> None:
    for attempt in range(6):
        try:
            tmp.replace(path)
            return
        except PermissionError:   # Windows: a reader has the file open for a moment
            if attempt == 5:
                raise
            time.sleep(0.2)


def _save_parquet(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    df.reset_index(drop=True).to_parquet(tmp, index=False)
    _replace(tmp, path)


def _save_json(obj, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    _replace(tmp, path)


def _save_bytes(data: bytes, path: Path) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    _replace(tmp, path)


# ------------------------------------------------------------------ network seam
_api_session: requests.Session | None = None
_api_warm_at = float("-inf")   # time.monotonic() of the last cookie warm-up (-inf: never)
_api_last = float("-inf")      # time.monotonic() of the last API request
_api_blocked = False
_api_fail_streak = 0
_api_lock = threading.Lock()


def _reset_api() -> None:
    global _api_blocked, _api_fail_streak
    _api_blocked = False
    _api_fail_streak = 0


def _fetch(url: str, params: dict | None = None, *, api: bool = False,
           referer: str | None = None) -> tuple[int, bytes]:
    """(HTTP status, body). Archive files (api=False) need no cookies; NSE API calls do. -1 = no answer,
    -2 = NSE API calls stopped for this refresh (blocked or failing). Never raises."""
    try:
        if not api:
            return nse._get_bytes(url)
        return _api_get(url, params, referer)
    except Exception:
        return -1, b""


def _warm(s: requests.Session, *pages: str | None) -> None:
    for page in pages:
        if page:
            try:
                s.get(page, timeout=15)   # picks up NSE's Akamai cookies
            except requests.RequestException:
                pass


def _api_get(url: str, params: dict | None, referer: str | None) -> tuple[int, bytes]:
    global _api_session, _api_warm_at, _api_last, _api_blocked, _api_fail_streak
    with _api_lock:                        # one NSE API request at a time, politely spaced
        if _api_blocked:
            return -2, b""
        if _api_session is None:
            _api_session = requests.Session()
            _api_session.headers.update(API_HEADERS)
            _api_warm_at = float("-inf")
        s = _api_session
        if time.monotonic() - _api_warm_at > SESSION_MAX_AGE_S:   # new session, or cookies about to expire
            s.cookies.clear()
            _warm(s, HOME)
            _api_warm_at = time.monotonic()
        headers = {"Referer": referer} if referer else None
        last = None
        for attempt in range(3):
            wait = API_GAP_S - (time.monotonic() - _api_last)
            if wait > 0:
                time.sleep(wait)
            try:
                r = s.get(url, params=params, headers=headers, timeout=25)
            except requests.RequestException:
                r = None
            _api_last = time.monotonic()
            if r is None:
                time.sleep(1.5 * (attempt + 1))
                continue
            code = r.status_code
            last = code
            if code in (401, 403) and attempt == 0:
                s.cookies.clear()
                _warm(s, HOME, referer)
                _api_warm_at = time.monotonic()
                continue
            if code == 200:
                _api_fail_streak = 0
                return 200, r.content
            if code in (401, 403, 429):
                _api_blocked = True        # never hammer: no more NSE API calls in this refresh
                return code, b""
            if code == 404:
                return 404, b""
            time.sleep(1.5 * (attempt + 1))
        _api_fail_streak += 1
        if _api_fail_streak >= 3:
            _api_blocked = True
        return (last or -1), b""


# ------------------------------------------------------------------ small helpers
_BOM = chr(0xFEFF)   # UTF-8 byte-order mark NSE's CSV files may start with
_NA_TEXT = {"", "-", "nil", "na", "n.a.", "none", "null"}
_DATE_FMTS = ("%d-%b-%Y", "%d-%B-%Y", "%d-%m-%Y", "%Y-%m-%d", "%d/%m/%Y")
_DT_FMTS = ("%d-%b-%Y %H:%M:%S", "%d-%b-%Y %H:%M", "%d-%m-%Y %H:%M:%S", "%d-%m-%Y %H:%M", "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M:%S")


def _now() -> str:
    return ist_now().isoformat(timespec="seconds")


def _missing(x) -> bool:
    if x is None or x is pd.NA or x is pd.NaT:
        return True
    return isinstance(x, (float, np.floating)) and math.isnan(x)


def _finite(x) -> bool:
    return (isinstance(x, (int, float, np.integer, np.floating)) and not isinstance(x, bool)
            and math.isfinite(x))


def _sv(x) -> str | None:
    """A cell as str, None when missing (NaN is truthy, so never test cells with `or`)."""
    return None if _missing(x) else str(x)


def _to_num(x) -> float:
    if _missing(x):
        return np.nan
    if isinstance(x, (int, float, np.integer, np.floating)) and not isinstance(x, bool):
        v = float(x)
        return v if math.isfinite(v) else np.nan
    s = str(x).replace(",", "").strip()
    if s.lower() in _NA_TEXT:
        return np.nan
    try:
        v = float(s)
    except ValueError:
        return np.nan
    return v if math.isfinite(v) else np.nan


def _text(x) -> str | None:
    if _missing(x):
        return None
    s = " ".join(str(x).split())
    return None if s in ("", "-") else s


def _parse_date(s: str) -> date | None:
    for fmt in _DATE_FMTS + _DT_FMTS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return None


def _iso(x) -> str | None:
    """'23-OCT-2026' / '23-10-2026' / '2026-10-23' / '23-Oct-2026 18:45' -> '2026-10-23' (None if unreadable)."""
    if isinstance(x, datetime):
        return x.date().isoformat()
    if isinstance(x, date):
        return x.isoformat()
    t = _text(x)
    return None if t is None else _iso_text(t)


@functools.lru_cache(maxsize=65536)   # a year of filings repeats the same few hundred dates
def _iso_text(t: str) -> str | None:
    d = _parse_date(t)
    if d is None:
        head = re.split(r"[ T]", t, maxsplit=1)[0]
        if head != t:
            d = _parse_date(head)
    return d.isoformat() if d else None


def _iso_dt(x) -> str | None:
    """'15-OCT-2026 10:10:10' -> '2026-10-15T10:10:10+05:30'; a date alone -> that day at midnight IST."""
    t = _text(x)
    return None if t is None else _iso_dt_text(t)


@functools.lru_cache(maxsize=65536)
def _iso_dt_text(t: str) -> str | None:
    for fmt in _DT_FMTS + _DATE_FMTS:
        try:
            return datetime.strptime(t, fmt).replace(tzinfo=IST).isoformat(timespec="seconds")
        except ValueError:
            pass
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        return None
    dt = dt.astimezone(IST) if dt.tzinfo else dt.replace(tzinfo=IST)
    return dt.isoformat(timespec="seconds")


def _records(payload) -> list[dict]:
    """Rows of an NSE reply: JSON list, JSON {"data": [...]}, or CSV (a BOM and a header-only file are fine)."""
    if payload is None:
        return []
    if isinstance(payload, (bytes, bytearray)):
        payload = bytes(payload).decode("utf-8-sig", errors="replace")
    if isinstance(payload, str):
        text = payload.lstrip(_BOM).strip()
        if not text:
            return []
        if text[0] in "{[":
            try:
                payload = json.loads(text)
            except ValueError:
                return []
        else:
            try:
                return pd.read_csv(io.StringIO(text), dtype=str, keep_default_na=False).to_dict("records")
            except (pd.errors.EmptyDataError, pd.errors.ParserError, ValueError):
                return []
    if isinstance(payload, dict):
        data = payload.get("data")
        return [r for r in data if isinstance(r, dict)] if isinstance(data, list) else []
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)]
    return []


def _readable(body: bytes) -> bool:
    """A 200 reply that really is data (JSON, or CSV with a Symbol column) and not an HTML error page - only
    such a reply may mark a month as done."""
    try:
        text = body.decode("utf-8-sig", errors="replace").lstrip(_BOM).strip()
    except Exception:
        return False
    if not text:
        return False
    if text[0] in "{[":
        try:
            json.loads(text)
            return True
        except ValueError:
            return False
    return "symbol" in text.split("\n", 1)[0].lower()


def _key(name) -> str:
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


def _truthy(x) -> bool:
    if _missing(x):
        return False
    if isinstance(x, str):
        return x.strip().lower() in ("true", "1", "yes", "y")
    return bool(x)


def _empty(cols: dict[str, str]) -> pd.DataFrame:
    return pd.DataFrame({c: pd.Series(dtype=t) for c, t in cols.items()})


def _conform(df: pd.DataFrame, cols: dict[str, str]) -> pd.DataFrame:
    """Exactly `cols`, in that order and dtype (missing strings NaN); a column an older file lacks is added empty."""
    df = df.reset_index(drop=True)
    n = len(df)
    out = {}
    for c, t in cols.items():
        s = df[c] if c in df.columns else pd.Series([None] * n, dtype=object)
        if t == "float64":
            s = pd.to_numeric(s, errors="coerce").astype("float64")
        elif t == "int64":
            s = pd.to_numeric(s, errors="coerce").fillna(0).astype("int64")
        elif t == "bool":
            s = pd.Series([_truthy(x) for x in s], dtype=bool)
        else:
            s = s.astype(object)
            s = s.where(s.notna(), np.nan)
        out[c] = s.reset_index(drop=True)
    return pd.DataFrame(out, columns=list(cols))


def _frame(rows: list[dict], cols: dict[str, str]) -> pd.DataFrame:
    return _conform(pd.DataFrame(rows), cols) if rows else _empty(cols)


def _obj(values: list) -> np.ndarray:
    """A 1-D object array of lists (np.array would turn equal-length lists into a 2-D array)."""
    arr = np.empty(len(values), dtype=object)
    for i, v in enumerate(values):
        arr[i] = v
    return arr


def _on_or_after(s: pd.Series, since: str | None) -> pd.Series:
    """Rows whose ISO date is on or after `since` (every row when since is None; a missing date never)."""
    if since is None:
        return pd.Series(True, index=s.index, dtype=bool)
    return pd.Series([isinstance(x, str) and x >= since for x in s], index=s.index, dtype=bool)


def _unique(items) -> list[str]:
    seen, out = set(), []
    for x in items:
        if x and x not in seen:
            seen.add(x)
            out.append(x)
    return out


def _unique_ids(ids: list[str]) -> list[str]:
    """'a', 'a', 'b' -> 'a', 'a#2', 'b'."""
    seen: dict[str, int] = {}
    out = []
    for i in ids:
        n = seen.get(i, 0) + 1
        seen[i] = n
        out.append(i if n == 1 else f"{i}#{n}")
    return out


def _days_between(later, earlier) -> float:
    try:
        return float((date.fromisoformat(str(later)[:10]) - date.fromisoformat(str(earlier)[:10])).days)
    except (TypeError, ValueError):
        return np.nan


def _day_text(iso) -> str:
    """'2026-10-23' -> '23 Oct 2026'."""
    try:
        d = date.fromisoformat(str(iso)[:10])
    except ValueError:
        return str(iso)
    return f"{d.day} {d:%b %Y}"


def _month_text(iso) -> str:
    try:
        return f"{date.fromisoformat(str(iso)[:10]):%b %Y}"
    except ValueError:
        return str(iso)


def _period_text(iso) -> str:
    return "quarter to " + _month_text(iso) if isinstance(iso, str) and iso else "latest quarter"


def _qty_text(n) -> str:
    """Indian digit grouping: 600000 -> '6,00,000'."""
    if not _finite(n):
        return "?"
    s = str(int(round(abs(float(n)))))
    if len(s) > 3:
        head, parts = s[:-3], [s[-3:]]
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        parts.insert(0, head)
        s = ",".join(parts)
    return ("-" if float(n) < 0 else "") + s


def _inr_short(v) -> str:
    """Rupees: 247260000 -> '₹24.7 cr', 6250000 -> '₹62.5 lakh', 9500 -> '₹9,500'."""
    a = abs(float(v))
    sign = "−" if v < 0 else ""
    if a >= 1e7:
        return f"{sign}₹{a / 1e7:,.1f} cr"
    if a >= 1e5:
        return f"{sign}₹{a / 1e5:.1f} lakh"
    return f"{sign}₹{a:,.0f}"


def _money(v) -> str:
    return _inr_short(v) if _finite(v) and v > 0 else "value not given"


def _pts_text(x) -> str:
    """'+1.20 pts' / '−0.85 pts' (U+2212 minus)."""
    if not _finite(x):
        return "? pts"
    return f"{'+' if x >= 0 else '−'}{abs(x):.2f} pts"


def _p2(x) -> str:
    return f"{x:.2f}" if _finite(x) else "n/a"


def _signed0(v) -> str:
    """FII/DII crore: '+2,358' / '−1,888'."""
    if not _finite(v):
        return "n/a"
    return ("+" if v > 0 else "−" if v < 0 else "") + f"{abs(v):,.0f}"


def _months(start: date, end: date) -> list[tuple[date, date, str, bool]]:
    """Calendar months touching [start, end], newest first: (first, last, 'YYYY-MM', full) with first/last clipped
    to the range; full = the range covers the month from its 1st."""
    out = []
    m = date(end.year, end.month, 1)
    stop = date(start.year, start.month, 1)
    while m >= stop:
        nxt = date(m.year + (m.month == 12), m.month % 12 + 1, 1)
        first, last = max(m, start), min(nxt - timedelta(days=1), end)
        out.append((first, last, f"{m:%Y-%m}", first.day == 1))
        m = date(m.year - (m.month == 1), (m.month - 2) % 12 + 1, 1)
    return out


def _final(first: date, full: bool, today: date) -> bool:
    """A fully fetched month that ended more than PAST_MONTH_GRACE_DAYS ago never changes: never fetch it again."""
    nxt = date(first.year + (first.month == 12), first.month % 12 + 1, 1)
    return full and nxt - timedelta(days=1) < today - timedelta(days=PAST_MONTH_GRACE_DAYS)


# ------------------------------------------------------------------ classification
class Label(NamedTuple):
    category: str            # one of CATEGORIES
    sub_label: str | None    # e.g. ODI_LABEL, LIKELY_PROMOTER, INSIDER_LABEL, 'Individual'
    investor: str | None     # display name of the well-known investor (category 'famous'), else None


_PUNCT = re.compile(r"[.,()'\";:]")
_EDGE_DASH = re.compile(r"^(- )+|( -)+$")
_TOKEN_FIX = {"PVT": "PRIVATE", "LTD": "LIMITED", "CO": "COMPANY"}


def normalise_name(name: object) -> str:
    """Upper case, '&' -> AND, punctuation gone, '-' a token of its own, PVT/LTD/CO spelled out, no M/S prefix:
    'M/S ABC & Co. Pvt. Ltd.' -> 'ABC AND COMPANY PRIVATE LIMITED'."""
    if _missing(name):
        return ""
    return _norm(str(name))


@functools.lru_cache(maxsize=65536)
def _norm(s: str) -> str:
    s = _PUNCT.sub(" ", s.upper().replace("&", " AND ")).replace("-", " - ")
    s = _EDGE_DASH.sub("", " ".join(s.split())).strip()
    for prefix in ("M/S ", "MS "):
        if s.startswith(prefix):
            s = s[len(prefix):]
            break
    return " ".join(_TOKEN_FIX.get(t, t) for t in s.split())


def parent_key(name: object) -> str:
    """The fund house / entity behind a scheme account: 'SBI MUTUAL FUND A/C SBI SMALL CAP FUND' -> 'SBI MUTUAL
    FUND', 'SOCIETE GENERALE - ODI' -> 'SOCIETE GENERALE'."""
    s = normalise_name(name)
    return _parent(s) if s else ""


@functools.lru_cache(maxsize=65536)
def _parent(s: str) -> str:
    p = f" {s} "
    cuts = [i for i in (p.find(m) for m in (" A/C ", " ACCOUNT ", " SCHEME ", " - ")) if i > 0]
    return p[:min(cuts)].strip() if cuts else s


def _has(s: str, phrase: str) -> bool:
    """Whole-token match on a normalised name ('LIC' does not match 'PUBLIC' or 'CLICK')."""
    return f" {phrase} " in f" {s} "


def _any(s: str, phrases) -> bool:
    return any(_has(s, p) for p in phrases)


FAMOUS_INVESTORS: dict[str, list[str]] = {   # display name -> aliases (all alias tokens must be in the name)
    "Rekha Jhunjhunwala (RJ estate)": ["REKHA RAKESH JHUNJHUNWALA", "REKHA JHUNJHUNWALA",
                                       "RAKESH RADHEYSHYAM JHUNJHUNWALA", "RAKESH JHUNJHUNWALA", "RARE ENTERPRISES"],
    "Radhakishan Damani": ["RADHAKISHAN SHIVKISHAN DAMANI", "RADHAKISHAN DAMANI", "GOPIKISHAN SHIVKISHAN DAMANI",
                           "DERIVE TRADING AND RESORTS", "BRIGHT STAR INVESTMENTS"],
    "Ashish Kacholia": ["ASHISH RAMESHCHANDRA KACHOLIA", "ASHISH KACHOLIA", "BENGAL FINANCE AND INVESTMENT"],
    "Vijay Kedia": ["VIJAY KISHANLAL KEDIA", "VIJAY KEDIA", "KEDIA SECURITIES"],
    "Dolly Khanna": ["DOLLY KHANNA", "DOLLY RAJIV KHANNA", "RAJIV KHANNA"],
    "Mukul Agrawal": ["MUKUL MAHAVIR AGRAWAL", "MUKUL AGRAWAL", "PARAM CAPITAL"],
    "Sunil Singhania (Abakkus)": ["SUNIL SINGHANIA", "ABAKKUS"],
    "Ashish Dhawan": ["ASHISH DHAWAN"],
    "Porinju Veliyath": ["PORINJU VELIYATH", "EQUITY INTELLIGENCE INDIA"],
    "Anil Kumar Goel": ["ANIL KUMAR GOEL"],
    "Madhusudan Kela": ["MADHUSUDAN KELA", "MADHURI MADHUSUDAN KELA", "SINGULARITY"],
    "Nemish Shah": ["NEMISH S SHAH", "NEMISH SHAH"],
    "Akash Bhanshali": ["AKASH PRAKASH BHANSHALI", "AKASH BHANSHALI"],
    "Vallabh Bhanshali": ["VALLABH BHANSHALI"],
    "Ramesh Damani": ["RAMESH DAMANI"],
    "Raamdeo Agrawal": ["RAAMDEO AGRAWAL", "RAAMDEO RAMGOPAL AGRAWAL"],
    "Seetha Kumari": ["SEETHA KUMARI"],
    "Satpal Khattar": ["SATPAL KHATTAR", "KHATTAR HOLDINGS"],
    "Ajay Upadhyaya": ["AJAY UPADHYAYA"],
    "Hemendra Kothari": ["HEMENDRA KOTHARI"],
    "Mohnish Pabrai": ["MOHNISH PABRAI", "PABRAI INVESTMENT FUND", "DALAL STREET LLC"],
    "Shankar Sharma": ["SHANKAR SHARMA"],
    "Vikas Khemani (Carnelian)": ["CARNELIAN"],
}
BRAND_TOKENS = frozenset({"ABAKKUS", "CARNELIAN", "SINGULARITY"})   # the only single-token aliases allowed
# (alias token set, display), most tokens first; aliases go through normalise_name
_ALIASES = sorted(((frozenset(normalise_name(a).split()), d) for d, al in FAMOUS_INVESTORS.items() for a in al),
                  key=lambda x: -len(x[0]))

AMC_BRANDS = ("SBI", "HDFC", "ICICI PRUDENTIAL", "NIPPON INDIA", "NIPPON LIFE INDIA", "KOTAK MAHINDRA", "AXIS",
              "ADITYA BIRLA SUN LIFE", "UTI", "DSP", "MIRAE ASSET", "TATA", "MOTILAL OSWAL", "QUANT", "BANDHAN",
              "INVESCO INDIA", "FRANKLIN TEMPLETON", "PPFAS", "PARAG PARIKH", "WHITEOAK CAPITAL", "EDELWEISS",
              "BARODA BNP PARIBAS", "HSBC", "CANARA ROBECO", "SUNDARAM", "UNION", "LIC", "MAHINDRA MANULIFE",
              "PGIM INDIA", "360 ONE", "JM FINANCIAL", "ITI", "NAVI", "GROWW", "ZERODHA", "SAMCO", "HELIOS",
              "OLD BRIDGE", "BAJAJ FINSERV", "JIO BLACKROCK", "QUANTUM", "SHRIRAM", "TAURUS", "NJ",
              "BANK OF INDIA", "UNIFI", "ANGEL ONE")
FOREIGN_MARKERS = ("PLC", "LLC", "LP", "L P", "PTE", "SICAV", "UCITS", "OEIC", "FCP", "S A", "SA", "AG", "GMBH",
                   "NV", "BV", "N V", "B V", "S A R L", "SARL", "AKTIENGESELLSCHAFT", "KG", "INC", "MASTER FUND", "OFFSHORE", "MAURITIUS", "SINGAPORE", "CAYMAN", "LUXEMBOURG",
                   "IRELAND", "HONG KONG", "DIFC", "DUBAI", "EMERGING MARKETS", "FOREIGN PORTFOLIO")
INSURANCE_WORDS = ("INSURANCE", "ASSURANCE", "REINSURANCE")
INSURANCE_BRANDS = ("HDFC LIFE", "SBI LIFE", "ICICI PRUDENTIAL LIFE", "ICICI LOMBARD", "TATA AIA", "MAX LIFE",
                    "AXIS MAX LIFE", "BAJAJ ALLIANZ", "BAJAJ LIFE", "KOTAK MAHINDRA LIFE",
                    "ADITYA BIRLA SUN LIFE INSURANCE", "NEW INDIA ASSURANCE", "STAR HEALTH", "CANARA HSBC LIFE",
                    "PNB METLIFE")
PENSION_WORDS = ("PENSION", "PROVIDENT FUND", "EMPLOYEES PROVIDENT", "NPS TRUST", "SUPERANNUATION",
                 "RETIREMENT SYSTEM", "PUBLIC EMPLOYEES", "TEACHERS", "INVESTMENT AUTHORITY", "MONETARY AUTHORITY",
                 "SOVEREIGN", "GOVERNMENT OF", "PRESIDENT OF INDIA", "GIC PRIVATE", "TEMASEK",
                 "PUBLIC INVESTMENT FUND", "NORGES BANK", "CANADA PENSION PLAN", "CPP INVESTMENT",
                 "CAISSE DE DEPOT", "ONTARIO TEACHERS", "RETIREMENT TRUST", "RETIREMENT FUND", "RETIREMENT PLAN",
                 "EMPLOYEES RETIREMENT", "ABU DHABI INVESTMENT")
PROP_FIRMS = ("GRAVITON RESEARCH CAPITAL", "HRTI", "QE SECURITIES", "JUNOMONETA FINSOL", "NK SECURITIES RESEARCH",
              "IRAGE BROKING", "ALPHAGREP", "TOWER RESEARCH", "SILVERLEAF CAPITAL", "MICROCURVES TRADING",
              "MATHISYS ADVISORS", "QUADEYE", "ESTEE ADVISORS", "SHARE INDIA SECURITIES", "PACE STOCK BROKING",
              "DOLAT CAPITAL", "RAJASTHAN GLOBAL SECURITIES", "JUMP TRADING", "CITADEL SECURITIES",
              "BNP PARIBAS ARBITRAGE")
BROKER_WORDS = ("ARBITRAGE", "STOCK BROKING", "BROKING", "SHARE BROKERS", "STOCK BROKERS", "COMMODITIES", "FINSOL",
                "RESEARCH LLP", "TRADING LLP", "CAPITAL MARKETS", "CAPITAL MARKET", "TRADETECH", "QUANTCAP",
                "INTERMEDIARIES", "MARKET MAKER", "STOCKS PRIVATE", "SECURITIES LLP")
ODI_PHRASES = ("ODI", "SOCIETE GENERALE", "BOFA SECURITIES EUROPE", "CITIGROUP GLOBAL MARKETS MAURITIUS",
               "MORGAN STANLEY ASIA SINGAPORE", "GOLDMAN SACHS SINGAPORE PTE", "MERRILL LYNCH MARKETS SINGAPORE",
               "NOMURA SINGAPORE")
BANK_WORDS = ("BANK", "HOUSING FINANCE", "FINANCE LIMITED", "FINANCIAL SERVICES LIMITED", "FINVEST", "FINCORP",
              "NBFC", "INVESTMENT AND FINANCE", "CREDIT CAPITAL")
FII_BRANDS = ("VANGUARD", "BLACKROCK", "ISHARES", "FIDELITY", "GOLDMAN SACHS", "MORGAN STANLEY", "CITIGROUP",
              "J P MORGAN", "JP MORGAN", "JPMORGAN", "NOMURA", "MERRILL LYNCH", "BOFA SECURITIES", "UBS", "CLSA",
              "MACQUARIE", "SOCIETE GENERALE", "BNP PARIBAS", "HSBC", "ABRDN", "ABERDEEN", "NORTHERN TRUST",
              "STATE STREET", "WISDOMTREE", "SCHRODER", "INVESCO", "T ROWE", "CAPITAL GROUP", "SMALLCAP WORLD",
              "GOVERNMENT PENSION", "NALANDA", "AMANSA", "ELARA INDIA OPPORTUNITIES", "COPTHALL MAURITIUS", "FPI",
              "INDIA FUND", "GQG PARTNERS", "COLLECTIVE INVESTMENT TRUST", "EQUITY CIT")
AIF_WORDS = ("AIF", "ALTERNATIVE INVESTMENT", "ALTERNATE INVESTMENT", "CATEGORY III", "OPPORTUNITIES FUND",
             "PORTFOLIO MANAGEMENT", "ABAKKUS", "CARNELIAN", "MARCELLUS", "SINGULARITY", "NEO", "3P INDIA", "ASK",
             # private equity / venture capital (SEBI AIF Cat I/II, or their offshore vehicles)
             "PRIVATE EQUITY", "VENTURE CAPITAL", "VENTURE FUND", "PEAK XV", "SEQUOIA CAPITAL", "ELEVATION CAPITAL",
             "SAIF PARTNERS", "ACCEL", "TIGER GLOBAL", "SOFTBANK", "WARBURG PINCUS", "KKR", "BLACKSTONE",
             "BAIN CAPITAL", "BC INVESTMENTS", "CARLYLE", "TPG", "ADVENT INTERNATIONAL", "CHRYSCAPITAL", "MULTIPLES",
             "KEDAARA", "PREMJI INVEST", "LIGHTSPEED", "NEXUS VENTURE", "INVESTCORP", "GENERAL ATLANTIC",
             "EVERSTONE", "TRUE NORTH", "A91", "STEADVIEW", "ICICI VENTURE", "SBI VENTURES", "KOTAK REAL ESTATE",
             "KOTAK ALTERNATE", "IIFL SPECIAL OPPORTUNITIES", "360 ONE SPECIAL OPPORTUNITIES")
COMPANY_WORDS = ("LIMITED", "LLP", "PRIVATE", "ENTERPRISES", "INDUSTRIES", "VENTURES", "HOLDINGS")
TRUST_WORDS = ("HUF", "TRUST", "FOUNDATION")
CORPORATE_TOKENS = frozenset(COMPANY_WORDS + TRUST_WORDS + (
    "COMPANY", "CORPORATION", "FUND", "FUNDS", "CAPITAL", "INVESTMENT", "INVESTMENTS", "SECURITIES", "ADVISORS",
    "ADVISERS", "MANAGEMENT", "PARTNERS", "GROUP", "ASSOCIATES", "FINANCE", "FINANCIAL", "TRADING", "EXPORTS"))
PROMOTER_HINTS = ("HOLDINGS", "INVESTMENTS", "FAMILY TRUST", "ENTERPRISES", "VENTURES")
NOT_PROMOTER_WORDS = ("ASSET MANAGEMENT", "MUTUAL", "FUND", "FUNDS", "INSURANCE", "ASSURANCE", "BANK", "SECURITIES",
                      "BROKING", "CAPITAL MARKETS", "TRUSTEE")
COMPANY_STOPWORDS = frozenset({"THE", "SHREE", "SHRI", "SRI", "NEW", "INDIA", "INDIAN", "NATIONAL", "GLOBAL",
                               "INTERNATIONAL", "UNITED", "GENERAL", "ASIAN", "BHARAT", "HINDUSTAN"})


def _company_word(company) -> str | None:
    """The company's distinctive first word ('Astec LifeSciences Ltd' -> 'ASTEC'), or None when it is too short."""
    for t in normalise_name(company).split():
        if t in COMPANY_STOPWORDS:
            continue
        return t if t.isalpha() and len(t) >= 4 else None
    return None


def classify(name: object, *, promoters: set[str] | None = None, company: str | None = None,
             round_trip: bool = False) -> Label:
    """Which kind of investor a filed name is (rules in docs/smart_money_spec.md 4.5.3, first match wins). A name
    that only looks like a famous investor can be someone else: always show the filed name next to the label."""
    s = normalise_name(name)
    if not s:
        return Label("other", "Unclassified", None)
    # 1) promoter of this stock (per-symbol set built by promoter_sets)
    if promoters and (s in promoters or parent_key(name) in promoters):
        return Label("promoter", None, None)
    word = _company_word(company)
    base = _classify_name(s, bool(round_trip))
    if word and _has(s, word) and not _any(s, NOT_PROMOTER_WORDS):
        corporate = (base.category == "other" and base.sub_label == "Company") or (
            base.category == "fii" and base.sub_label is None and not _any(s, FII_BRANDS))   # a foreign parent
        if _any(s, PROMOTER_HINTS) or corporate:
            return Label("promoter", LIKELY_PROMOTER, None)
    return base


@functools.lru_cache(maxsize=65536)
def _classify_name(s: str, round_trip: bool) -> Label:
    toks = set(s.split())
    for alias, display in _ALIASES:                                   # 2) well-known investor
        if alias <= toks:
            return Label("famous", None, display)
    insurance_like = _any(s, INSURANCE_WORDS)
    if not insurance_like:                                            # 3) mutual fund
        brand = _any(s, AMC_BRANDS)
        if (_has(s, "MUTUAL FUND") or ((_has(s, "MF") or _has(s, "ETF")) and brand)
                or (_has(s, "TRUSTEE") and _has(s, "A/C"))
                or (brand and _has(s, "FUND") and not _any(s, FOREIGN_MARKERS))):
            return Label("mf", None, None)
    if (insurance_like or (_has(s, "LIC") and not _has(s, "LIC HOUSING"))   # 4) insurance
            or _any(s, INSURANCE_BRANDS)):
        return Label("insurance", None, None)
    if _any(s, PENSION_WORDS):                                        # 5) pension / sovereign
        return Label("pension", None, None)
    if _any(s, PROP_FIRMS) or _any(s, BROKER_WORDS):                  # 6) broker / prop / arbitrage
        return Label("broker", None, None)
    if _any(s, ODI_PHRASES):                                          #    P-note issuers are FPIs
        return Label("fii", ODI_LABEL, None)
    if round_trip:                                                    #    intraday round trip, no rule matched
        return Label("broker", None, None)
    if _any(s, BANK_WORDS):                                           # 7) bank / NBFC
        return Label("bank", None, None)
    if _any(s, FOREIGN_MARKERS) or _any(s, FII_BRANDS):               # 8) foreign investor
        return Label("fii", None, None)
    if _any(s, AIF_WORDS):                                            # 9) AIF / PMS / PE / VC fund
        return Label("aif", None, None)
    if _any(s, COMPANY_WORDS):
        return Label("other", "Company", None)
    if _any(s, TRUST_WORDS):
        return Label("other", "HUF/Trust", None)
    if 2 <= len(toks) <= 5 and not (toks & CORPORATE_TOKENS) and all(t.isalpha() for t in toks):
        return Label("other", "Individual", None)
    return Label("other", "Unclassified", None)


def _holder_label(holder, group, member) -> Label:
    """A shareholding-pattern holder: the XBRL category it is filed under first, then the name rules."""
    if group == "promoter":
        return Label("promoter", None, None)
    m = "" if _missing(member) else str(member).lower()
    if "mutualfund" in m:
        return Label("mf", None, None)
    if "insurance" in m:
        return Label("insurance", None, None)
    if "foreignportfolio" in m or "institutionsforeign" in m or "foreigninstitution" in m:
        return Label("fii", None, None)
    if "sovereign" in m or "providentfund" in m or "pensionfund" in m:
        return Label("pension", None, None)
    if "alternativeinvestment" in m:
        return Label("aif", None, None)
    if "bank" in m:
        return Label("bank", None, None)
    return classify(holder)   # finds well-known investors listed under "Individuals" or "Bodies corporate"


def _role(person_category) -> str:
    pc = "" if _missing(person_category) else str(person_category).lower()
    if "promoter" in pc:
        return "promoter"
    if any(w in pc for w in ("director", "key managerial", "kmp", "designated", "employee", "immediate relative",
                             "insider")):
        return "insider"
    return "other"


def promoter_sets(holders: pd.DataFrame | None, insider: pd.DataFrame | None) -> dict[str, set[str]]:
    """symbol -> normalised names (and parent keys) of its promoters: the shareholding pattern's promoter holders
    (every period) and the insider filers whose category is promoter / promoter group."""
    out: dict[str, set[str]] = defaultdict(set)

    def add(sym, name):
        if isinstance(sym, str) and not _missing(name):
            out[sym].update(k for k in (normalise_name(name), parent_key(name)) if k)

    if holders is not None and len(holders) and "group" in holders.columns:
        h = holders[holders["group"] == "promoter"]
        for sym, name in zip(h["symbol"], h["holder"]):
            add(sym, name)
    if insider is not None and len(insider):
        roles = insider["role"] if "role" in insider.columns else insider["person_category"].map(_role)
        i = insider[roles == "promoter"]
        for sym, name in zip(i["symbol"], i["person"]):
            add(sym, name)
    return dict(out)


# ------------------------------------------------------------------ parsers (pure)
DEAL_KEYS = {"date": "date", "bddtdate": "date", "symbol": "symbol", "bdsymbol": "symbol",
             "securityname": "security", "bdscripname": "security", "name": "security",
             "clientname": "client", "bdclientname": "client", "buysell": "side", "bdbuysell": "side",
             "quantitytraded": "qty", "bdqtytrd": "qty", "qty": "qty",
             "tradepricewghtavgprice": "price", "bdtpwatp": "price", "watp": "price",
             "remarks": "remarks", "bdremarks": "remarks"}


def _deal_side(x) -> str | None:
    t = "" if _missing(x) else str(x).strip().upper()
    if t in ("BUY", "B", "PURCHASE"):
        return "BUY"
    if t in ("SELL", "S", "SALE"):
        return "SELL"
    return None   # never default an unknown side to BUY


def parse_deals(payload, kind: str, source: str) -> pd.DataFrame:
    """bulk.csv / block.csv / historicalOR (CSV or JSON) / large-deal rows -> DEAL_COLS, one row per deal line."""
    rows = []
    for rec in _records(payload):
        r: dict = {}
        for k, v in rec.items():
            field = DEAL_KEYS.get(_key(k))
            if field and field not in r:
                r[field] = v
        side, day = _deal_side(r.get("side")), _iso(r.get("date"))
        sym, client, qty = _text(r.get("symbol")), _text(r.get("client")), _to_num(r.get("qty"))
        if side is None or day is None or not sym or not client or not qty > 0:
            continue
        price = _to_num(r.get("price"))
        price = price if price > 0 else np.nan
        rows.append({"date": day, "kind": kind, "symbol": sym.upper(), "security": _text(r.get("security")),
                     "client": client, "client_key": parent_key(client), "side": side, "qty": qty, "price": price,
                     "value": qty * price, "remarks": _text(r.get("remarks")), "source": source})
    return _frame(rows, DEAL_COLS)


def parse_large_deals(payload) -> pd.DataFrame:
    """NSE's large-deals snapshot JSON (today's bulk + block deals) -> DEAL_COLS."""
    obj = payload
    if isinstance(obj, (bytes, bytearray, str)):
        text = obj.decode("utf-8-sig", errors="replace") if isinstance(obj, (bytes, bytearray)) else obj
        try:
            obj = json.loads(text.lstrip(_BOM).strip() or "{}")
        except ValueError:
            obj = {}
    if not isinstance(obj, dict):
        obj = {}
    parts = [parse_deals(obj.get("BULK_DEALS_DATA") or [], "bulk", "snapshot"),
             parse_deals(obj.get("BLOCK_DEALS_DATA") or [], "block", "snapshot")]
    return _conform(pd.concat(parts, ignore_index=True), DEAL_COLS)


def _dedupe_deals(df: pd.DataFrame) -> pd.DataFrame:
    """The same deal line from two files (or as both a block and a bulk deal) is kept once, as the block row;
    newest first."""
    df = _conform(df, DEAL_COLS)
    if df.empty:
        return df
    d = df.assign(_rank=np.where(df["kind"] == "block", 0, 1), _p=df["price"].round(2))
    d = d.sort_values("_rank", kind="stable").drop_duplicates(["date", "symbol", "client_key", "side", "qty", "_p"])
    d = d.sort_values(["date", "symbol", "client"], ascending=[False, True, True])
    return _conform(d.drop(columns=["_rank", "_p"]), DEAL_COLS)


def parse_fiidii(payload) -> pd.DataFrame:
    """fiidiiTradeReact -> FLOW_COLS (Rs crore, provisional, market-wide), one row per date."""
    by_day: dict[str, dict] = {}
    for r in _records(payload):
        cat = str(r.get("category") or "").strip().upper()
        if "FII" in cat or "FPI" in cat:
            p = "fii"
        elif "DII" in cat:
            p = "dii"
        else:
            continue
        day = _iso(r.get("date"))
        if day is None:
            continue
        row = by_day.setdefault(day, {"date": day})
        row[f"{p}_buy_cr"] = _to_num(r.get("buyValue"))
        row[f"{p}_sell_cr"] = _to_num(r.get("sellValue"))
        row[f"{p}_net_cr"] = _to_num(r.get("netValue"))
    return _frame([by_day[d] for d in sorted(by_day)], FLOW_COLS)


def _first(r: dict, *keys):
    """The first of `keys` with a real value (NSE spells some fields two ways: afterAcq* / aftAcq*)."""
    for k in keys:
        if _text(r.get(k)) is not None:
            return r.get(k)
    return None


def _pit_side(txn: str | None, mode: str | None) -> str | None:
    t = (txn or "").lower()
    if "buy" in t or "acqui" in t or "purchase" in t:
        return "BUY"
    if "sell" in t or "sale" in t or "dispos" in t:
        return "SELL"
    m = (mode or "").lower()
    if "purchase" in m:
        return "BUY"
    if "sale" in m:
        return "SELL"
    return None


def _mode_kind(mode: str | None) -> str:
    """Only 'market' is a real buy/sell decision; pledges, ESOPs, gifts and transfers are not."""
    m = (mode or "").lower()
    if "invocation" in m or "invoke" in m:
        return "pledge_invoked"     # a lender sold the pledged shares: a forced sale
    if "pledge" in m or "revok" in m or "encumb" in m:
        return "pledge"
    if "off market" in m or "off-market" in m:
        return "off_market"
    if "market" in m:
        return "market"
    if "esop" in m or "esos" in m or "employee stock" in m:
        return "esop"
    if "gift" in m:
        return "gift"
    if "inter" in m and "se" in m:
        return "inter_se"
    if any(w in m for w in ("preferential", "allot", "rights", "bonus", "conversion")):
        return "preferential"
    return "other"


def parse_pit(payload) -> pd.DataFrame:
    """corporates-pit (SEBI PIT Reg 7(2) disclosures) -> INSIDER_COLS. Derivative rows (no share quantity) are
    dropped; revised filings keep only their latest version."""
    rows = []
    for r in _records(payload):
        sym, person, qty = _text(r.get("symbol")), _text(r.get("acqName")), _to_num(r.get("secAcq"))
        if not sym or not person or not qty > 0:
            continue
        txn, mode = _text(r.get("tdpTransactionType")), _text(r.get("acqMode"))
        disclosed_at, intimated = _iso_dt(r.get("date")), _iso(r.get("intimDt"))
        rows.append({
            "symbol": sym.upper(), "company": _text(r.get("company")), "person": person,
            "person_key": normalise_name(person), "person_category": _text(r.get("personCategory")),
            "sec_type": _text(r.get("secType")), "txn": txn, "side": _pit_side(txn, mode), "mode": mode,
            "mode_kind": _mode_kind(mode), "qty": qty, "value": _to_num(r.get("secVal")),
            "before_shares": _to_num(r.get("befAcqSharesNo")), "before_pct": _to_num(r.get("befAcqSharesPer")),
            "after_shares": _to_num(_first(r, "afterAcqSharesNo", "aftAcqSharesNo")),
            "after_pct": _to_num(_first(r, "afterAcqSharesPer", "aftAcqSharesPer")),
            "trade_from": _iso(r.get("acqfromDt")), "trade_to": _iso(r.get("acqtoDt")), "intimated": intimated,
            "disclosed": disclosed_at[:10] if disclosed_at else intimated, "disclosed_at": disclosed_at,
            "exchange": _text(r.get("exchange")), "xbrl": _text(r.get("xbrl"))})
    return _dedupe_insider(_frame(rows, INSIDER_COLS))


def parse_pit_listing(payload) -> pd.DataFrame:
    """corporates-pit-gg -> PIT_FILING_COLS (status 'pending'): the filings only, the trades are in each XBRL."""
    rows = []
    for r in _records(payload):
        app, sym, xml = _text(r.get("appId")), _text(r.get("symbol")), _text(r.get("xmlFileName"))
        if not app or not sym or not xml:
            continue
        rows.append({"app_id": app, "symbol": sym.upper(), "company": _text(r.get("companyName")),
                     "broadcast": _iso_dt(r.get("broadcastDateTime")), "submission": _text(r.get("typeOfSubmission")),
                     "prev_app_id": _text(r.get("prevAppId")), "xml": xml, "status": "pending", "tries": 0,
                     "last_try": None})
    return _frame(rows, PIT_FILING_COLS)


def parse_pit_xbrl(data: bytes, filing: dict) -> pd.DataFrame:
    """One insider filing's XBRL (in-bse-co, one context per disclosure) -> INSIDER_COLS rows. Percentages are
    fractions in the file (0.1394 = 13.94%). Raises ValueError when the file is not an insider filing."""
    root = ET.fromstring(data)
    facts: dict[str, dict[str, str]] = {}
    for el in root.iter():
        if isinstance(el.tag, str) and el.get("contextRef"):
            facts.setdefault(el.get("contextRef"), {}).setdefault(_local(el.tag), (el.text or "").strip())
    main = next((f for f in facts.values() if "Symbol" in f or "NameOfTheCompany" in f), {})
    if not main and not any("NameOfThePerson" in f for f in facts.values()):
        raise ValueError("not an insider-trading filing")

    def pct(f: dict, key: str) -> float:
        v = _to_num(f.get(key))
        return round(v * 100, 4) if _finite(v) else np.nan
    broadcast = _text(filing.get("broadcast"))
    rows = []
    for f in facts.values():
        person, qty = _text(f.get("NameOfThePerson")), _to_num(f.get("SecuritiesAcquiredOrDisposedNumberOfSecurity"))
        if not person or not qty > 0:
            continue                                   # derivatives carry no share quantity
        txn, mode = _text(f.get("SecuritiesAcquiredOrDisposedTransactionType")), _text(f.get("ModeOfAcquisitionOrDisposal"))
        intimated = _iso(f.get("DateOfIntimationToCompany"))
        rows.append({
            "symbol": str(filing.get("symbol") or main.get("Symbol") or "").upper(),
            "company": _text(filing.get("company")) or _text(main.get("NameOfTheCompany")), "person": person,
            "person_key": normalise_name(person), "person_category": _text(f.get("CategoryOfPerson")),
            "sec_type": _text(f.get("TypeOfInstrument")), "txn": txn, "side": _pit_side(txn, mode), "mode": mode,
            "mode_kind": _mode_kind(mode), "qty": qty, "value": _to_num(f.get("SecuritiesAcquiredOrDisposedValueOfSecurity")),
            "before_shares": _to_num(f.get("SecuritiesHeldPriorToAcquisitionOrDisposalNumberOfSecurity")),
            "before_pct": pct(f, "SecuritiesHeldPriorToAcquisitionOrDisposalPercentageOfShareholding"),
            "after_shares": _to_num(f.get("SecuritiesHeldPostAcquistionOrDisposalNumberOfSecurity")),
            "after_pct": pct(f, "SecuritiesHeldPostAcquistionOrDisposalPercentageOfShareholding"),
            "trade_from": _iso(f.get("DateOfAllotmentAdviceOrAcquisitionOfSharesOrSaleOfSharesSpecifyFromDate")),
            "trade_to": _iso(f.get("DateOfAllotmentAdviceOrAcquisitionOfSharesOrSaleOfSharesSpecifyToDate")),
            "intimated": intimated, "disclosed": broadcast[:10] if broadcast else intimated, "disclosed_at": broadcast,
            "exchange": _text(f.get("ExchangeOnWhichTheTradeWasExecuted")), "xbrl": _text(filing.get("xml"))})
    return _frame(rows, INSIDER_COLS)


def _dedupe_insider(df: pd.DataFrame) -> pd.DataFrame:
    df = _conform(df, INSIDER_COLS)
    if df.empty:
        return df
    txn = ["" if _missing(t) else str(t).lower() for t in df["txn"]]
    d = df.assign(_t=txn).sort_values("disclosed_at", ascending=False, na_position="last", kind="stable")
    d = d.drop_duplicates(["symbol", "person_key", "trade_from", "qty", "_t"], keep="first")
    d = d.sort_values(["disclosed", "disclosed_at"], ascending=[False, False], na_position="last")
    return _conform(d.drop(columns="_t"), INSIDER_COLS)


def _enrich_insider(df: pd.DataFrame) -> pd.DataFrame:
    """INSIDER_COLS -> + INSIDER_EXTRA_COLS (role, investor type, open-market flag, full exit, delay, id)."""
    df = _conform(df, INSIDER_COLS)
    if df.empty:
        return _empty({**INSIDER_COLS, **INSIDER_EXTRA_COLS})
    roles, labels = [], []
    for pc, person in zip(df["person_category"], df["person"]):
        role = _role(pc)
        roles.append(role)
        labels.append(Label("promoter", None, None) if role == "promoter"
                      else Label("other", INSIDER_LABEL, None) if role == "insider" else classify(person))
    side, qty, value = df["side"], df["qty"], df["value"]
    after_sh, after_pct = df["after_shares"], df["after_pct"]
    fully = ((side == "SELL") & ((after_sh == 0) | (after_sh.isna() & (after_pct == 0)))
             & ((df["before_shares"] > 0) | (df["before_pct"] > 0)))
    ids = [f"{s}|{k}|{_sv(tf) or ''}|{q:.0f}|{_sv(sd) or _sv(mk) or ''}"
           for s, k, tf, q, sd, mk in zip(df["symbol"], df["person_key"], df["trade_from"], qty, side,
                                          df["mode_kind"])]
    out = df.assign(
        id=_unique_ids(ids), role=roles, category=[lb.category for lb in labels],
        sub_label=[lb.sub_label for lb in labels], investor=[lb.investor for lb in labels],
        avg_price=value.where(value > 0) / qty.where(qty > 0), change_pts=after_pct - df["before_pct"],
        is_market=(df["mode_kind"] == "market") & side.notna(), fully_exited=fully,
        delay_days=[_days_between(a, b) if isinstance(a, str) and isinstance(b, str) else np.nan
                    for a, b in zip(df["disclosed"], df["trade_to"])])
    return _conform(out, {**INSIDER_COLS, **INSIDER_EXTRA_COLS})


def parse_shp_master(payload) -> pd.DataFrame:
    """corporate-share-holdings-master -> FILING_COLS (quarter-end filings only: allotment-day patterns are not
    quarterly data)."""
    rows = []
    for r in _records(payload):
        sym, period, rid = _text(r.get("symbol")), _iso(r.get("date")), _to_num(r.get("recordId"))
        if not sym or not period or not _finite(rid):
            continue
        d = date.fromisoformat(period)
        if (d.month, d.day) not in QUARTER_ENDS:
            continue
        rows.append({"symbol": sym.upper(), "company": _text(r.get("name")), "period": period,
                     "record_id": int(rid), "xbrl": _text(r.get("xbrl")), "broadcast": _iso_dt(r.get("broadcastDate")),
                     "submission": _iso(r.get("submissionDate")),
                     "revised": str(r.get("revisedData")).strip().upper() in ("Y", "YES", "TRUE"),
                     "promoter_pct": _to_num(r.get("pr_and_prgrp")), "public_pct": _to_num(r.get("public_val"))})
    df = _frame(rows, FILING_COLS)
    return df.drop_duplicates("record_id", keep="last").reset_index(drop=True)


PCT = "ShareholdingAsAPercentageOfTotalNumberOfShares"
SHP_TARGETS = {"promoter_pct": ("PromoterAndPromoterGroup",), "public_pct": ("PublicShareholding", "PublicShareholder"),
               "dii_pct": ("InstitutionsDomestic",), "fii_pct": ("InstitutionsForeign",), "mf_pct": ("MutualFund",),
               "insurance_pct": ("InsuranceCompan",), "banks_pct": ("Banks",),
               "pension_pct": ("ProvidentFund", "PensionFund"),
               "aif_pct": ("AlternateInvestmentFund", "AlternativeInvestmentFund")}
SHP_LABEL_NAMES = {"CLEARING MEMBERS", "CLEARING MEMBER", "BODIES CORPORATE", "BODY CORPORATE", "HUF",
                   "HINDU UNDIVIDED FAMILY", "TRUSTS", "TRUST", "NON RESIDENT INDIANS", "NRI", "IEPF",
                   "INVESTOR EDUCATION AND PROTECTION FUND", "OTHERS", "ANY OTHER", "FOREIGN NATIONALS", "LLP",
                   "FOREIGN COMPANIES", "OVERSEAS CORPORATE BODIES", "EMPLOYEES", "KEY MANAGERIAL PERSONNEL",
                   "DIRECTORS AND THEIR RELATIVES", "ESOP TRUST", "FIRMS", "PARTNERSHIP FIRMS",
                   "QUALIFIED INSTITUTIONAL BUYER", "SUSPENSE ACCOUNT", "EMPLOYEE TRUSTS"}
_SKIP_HOLDER_PARTS = ("personsactinginconcert", "personsinconcert", "significantbeneficial", "unclaimed")
_NOT_PROMOTER_PARTS = ("nonpromoter", "relativesofpromoters", "governmentispromoter")
PROMOTER_HOLDER_AXES = frozenset(a.lower() for a in (   # the shareholding pattern's Table II (lower case)
    "DetailsSharesHeldByIndividualsOrHUFAxis", "DetailsOfSharesHeldByCentralGovernmentOrStateGovernmentsAxis",
    "DetailsOfSharesHeldByIndianFinancialInstitutionsOrBanksAxis", "DetailsOfSharesHeldByOthersIndianShareholdersAxis",
    "DetailsOfSharesHeldByNonResidentIndividualsOrForeignIndividualsAxis",
    "DetailsOfSharesHeldByOtherForeignShareholdersAxis", "DetailsOfSharesHeldByForeignInstitutionsAxis",
    "DetailsOfSharesHeldByForeignGovernmentAxis", "DetailsOfSharesHeldByForeignPortfolioInvestorPromoterAxis"))
_INSTITUTION_FIELDS = ("dii_pct", "fii_pct", "mf_pct", "insurance_pct", "banks_pct", "pension_pct", "aif_pct")


def _local(tag: str) -> str:
    tag = str(tag)
    return tag.rsplit("}", 1)[1] if "}" in tag else tag.rsplit(":", 1)[-1]


def _qlocal(text) -> str:
    return str(text or "").strip().rsplit(":", 1)[-1]


def _pct_of(f: dict[str, str]) -> float:
    if PCT in f:
        return _to_num(f[PCT])
    k = next((k for k in f if k.startswith(PCT)), None)
    return _to_num(f[k]) if k else np.nan


def _shares_of(f: dict[str, str]) -> float:
    if "NumberOfShares" in f:
        return _to_num(f["NumberOfShares"])
    k = next((k for k in f if k.startswith("NumberOfShares") and not k.startswith("NumberOfShareholders")), None)
    return _to_num(f[k]) if k else np.nan


def _name_of(f: dict[str, str]) -> str | None:
    if "NameOfTheShareholder" in f:
        return _text(f["NameOfTheShareholder"])
    k = next((k for k in f if "NameOfTheShareholder" in k or "NameOfShareholder" in k), None)
    return _text(f[k]) if k else None


def parse_shp_xbrl(data: bytes) -> tuple[dict, list[dict]]:
    """One shareholding-pattern XBRL file -> (category percentages, named holders). Percent units always (the file
    may use fractions); a missing institution subtotal means none. Raises ValueError when the file has no
    shareholding categories at all."""
    root = ET.fromstring(data)
    contexts: dict[str, tuple[list[tuple[str, str]], list[tuple[str, str]]]] = {}
    facts: dict[str, dict[str, str]] = {}
    for el in root.iter():
        if not isinstance(el.tag, str):
            continue
        name = _local(el.tag)
        if name == "context" and el.get("id"):
            explicit, typed = [], []
            for sub in el.iter():
                if not isinstance(sub.tag, str):
                    continue
                sub_name = _local(sub.tag)
                if sub_name == "explicitMember":
                    explicit.append((_qlocal(sub.get("dimension")), _qlocal(sub.text)))
                elif sub_name == "typedMember":
                    typed.append((_qlocal(sub.get("dimension")), "".join(sub.itertext()).strip()))
            contexts[el.get("id")] = (explicit, typed)
        ref = el.get("contextRef")
        if ref:
            facts.setdefault(ref, {}).setdefault(name, (el.text or "").strip())
    # A named holder is split over two contexts with the same typed member: 'D_<id>' (a duration: name, PAN) and
    # '<id>' (an instant: shares, %). Join them, or every holder loses either its name or its stake.
    for cid in [c for c in contexts if c.startswith("D_") and c[2:] in contexts]:
        facts[cid[2:]] = {**facts.get(cid, {}), **facts.get(cid[2:], {})}
        contexts.pop(cid)

    cat_pct: dict[str, float] = {}
    cat_shares: dict[str, float] = {}
    for cid, (explicit, typed) in contexts.items():
        if typed or len(explicit) != 1 or "CategoryOfShareholders" not in explicit[0][0]:
            continue
        member, f = explicit[0][1], facts.get(cid, {})
        p, sh = _pct_of(f), _shares_of(f)
        if not math.isnan(p):
            cat_pct.setdefault(member, p)
        if not math.isnan(sh):
            cat_shares.setdefault(member, sh)

    grand = min((m for m in (cat_pct.keys() | cat_shares.keys()) if "ShareholdingPattern" in m),
                key=lambda m: (len(m), m), default=None)
    grand_pct = cat_pct.get(grand, np.nan) if grand else np.nan
    if not math.isnan(grand_pct):
        scale = 100.0 if grand_pct <= 1.5 else 1.0
    elif cat_pct:
        scale = 100.0 if max(cat_pct.values()) <= 1.0 else 1.0
    else:
        raise ValueError("no shareholding categories")

    cats: dict[str, float] = {"total_shares": cat_shares.get(grand, np.nan) if grand else np.nan}
    for field, needles in SHP_TARGETS.items():
        hits = [(m, p) for m, p in cat_pct.items() if any(n.lower() in m.lower() for n in needles)]
        if hits:
            _, p = min(hits, key=lambda x: (len(x[0]), -x[1]))   # the shortest member name is the subtotal
            cats[field] = round(p * scale, 4)
        else:
            cats[field] = np.nan
    if math.isnan(cats["promoter_pct"]) and not math.isnan(cats["public_pct"]):
        cats["promoter_pct"] = round(100.0 - cats["public_pct"], 4)
    elif math.isnan(cats["public_pct"]) and not math.isnan(cats["promoter_pct"]):
        cats["public_pct"] = round(100.0 - cats["promoter_pct"], 4)
    if not math.isnan(cats["dii_pct"]) or not math.isnan(cats["fii_pct"]):
        for field in _INSTITUTION_FIELDS:   # the institutions layout: a missing subtotal means none
            if math.isnan(cats[field]):
                cats[field] = 0.0
    cats = {k: cats[k] for k in ("total_shares", "promoter_pct", "public_pct", "fii_pct", "dii_pct", "mf_pct",
                                 "insurance_pct", "banks_pct", "pension_pct", "aif_pct")}

    best: dict[tuple[str, str], dict] = {}
    for cid, (explicit, typed) in contexts.items():
        if not typed:
            continue
        f = facts.get(cid, {})
        holder = _name_of(f)
        if not holder:
            continue
        parts = [a.lower() for a, _ in explicit] + [m.lower() for _, m in explicit] + [a.lower() for a, _ in typed]
        if any(bad in p for p in parts for bad in _SKIP_HOLDER_PARTS):
            continue   # persons acting in concert / beneficial owners / unclaimed shares repeat other holders
        # Table II (promoter and promoter group) has its own holder axes, none of them named "promoter"; public axes
        # like "relatives of promoters other than the promoter group" are not the promoter group. Checked against
        # each file's own promoter total (285 of 287 files with a promoter match to 1 point).
        # An explicit promoter-group member (older layouts) counts too; "NonPromoterNonPublic" (employee trusts, DR
        # custodians) and "relatives of promoters" / "government is promoter" do not.
        explicit_promoter = any("promoter" in x and not any(n in x for n in _NOT_PROMOTER_PARTS)
                                for d, m in explicit for x in (d.lower(), m.lower()))
        group = ("promoter" if explicit_promoter or any(a.lower() in PROMOTER_HOLDER_AXES for a, _ in typed)
                 else "public")
        member = explicit[0][1] if explicit else typed[0][0]
        pct = _pct_of(f)
        pct = round(pct * scale, 4) if not math.isnan(pct) else np.nan
        key = normalise_name(holder)
        if key in SHP_LABEL_NAMES:
            continue   # a category total that looks like a name ('CLEARING MEMBERS')
        if group == "public" and (math.isnan(pct) or pct < 1.0):
            continue   # public holders are named only at 1% or more
        old = best.get((key, group))
        if old is None or (not math.isnan(pct) and (math.isnan(old["pct"]) or pct > old["pct"])):
            best[(key, group)] = {"holder": holder, "group": group, "xbrl_member": member,
                                  "shares": _shares_of(f), "pct": pct}
    return cats, list(best.values())


def _enrich_holders(h: pd.DataFrame) -> pd.DataFrame:
    h = _conform(h, HOLDER_COLS)
    labels = [_holder_label(n, g, m) for n, g, m in zip(h["holder"], h["group"], h["xbrl_member"])]
    out = h.assign(category=[lb.category for lb in labels], sub_label=[lb.sub_label for lb in labels],
                   investor=[lb.investor for lb in labels])
    return _conform(out, {**HOLDER_COLS, **HOLDER_EXTRA_COLS})


# ------------------------------------------------------------------ loaders (never raise)
def _read(path: Path, cols: dict[str, str]) -> pd.DataFrame:
    try:
        if path.exists():
            return _conform(pd.read_parquet(path), cols)
    except Exception:
        pass
    return _empty(cols)


def load_deals(folder: Path | None = None) -> pd.DataFrame:
    """Every stored bulk/block deal line (DEAL_COLS), newest first."""
    return _read(files(folder)["deals"], DEAL_COLS)


def load_insider(folder: Path | None = None) -> pd.DataFrame:
    """Stored insider trades with their enrichment (INSIDER_COLS + INSIDER_EXTRA_COLS), newest disclosure first."""
    try:
        return _enrich_insider(_read(files(folder)["insider"], INSIDER_COLS))
    except Exception:
        return _empty({**INSIDER_COLS, **INSIDER_EXTRA_COLS})


def load_flows(folder: Path | None = None) -> pd.DataFrame:
    """FII/DII daily net (FLOW_COLS, Rs crore), oldest first."""
    df = _read(files(folder)["flows"], FLOW_COLS)
    if df.empty:
        return df
    df = df.sort_values("date", kind="stable").drop_duplicates("date", keep="last")
    return df.reset_index(drop=True)


def _pick_holdings(df: pd.DataFrame) -> pd.DataFrame:
    """One row per (symbol, period): parsed XBRL over the list's two numbers, then the latest revision."""
    if df.empty:
        return df
    d = df.assign(_x=(df["source"] == "xbrl").astype("int64"), _b=[_sv(b) or "" for b in df["broadcast"]])
    d = d.sort_values(["symbol", "period", "_x", "_b", "record_id"], ascending=[True, False, False, False, False])
    d = d.drop_duplicates(["symbol", "period"], keep="first")
    return _conform(d.drop(columns=["_x", "_b"]), HOLDING_COLS)


def load_holdings(folder: Path | None = None) -> pd.DataFrame:
    """Quarterly shareholding (HOLDING_COLS), one row per (symbol, period), by symbol then newest period."""
    try:
        return _pick_holdings(_read(files(folder)["holdings"], HOLDING_COLS))
    except Exception:
        return _empty(HOLDING_COLS)


def load_holders(folder: Path | None = None) -> pd.DataFrame:
    """Named 1%+ holders (HOLDER_COLS + category, sub_label, investor) of the filings load_holdings chose."""
    try:
        chosen = load_holdings(folder)
        keep = chosen.loc[chosen["source"] == "xbrl", "record_id"].tolist()
        h = _read(files(folder)["holders"], HOLDER_COLS)
        return _enrich_holders(h[h["record_id"].isin(keep)])
    except Exception:
        return _empty({**HOLDER_COLS, **HOLDER_EXTRA_COLS})


def _default_state() -> dict:
    return {"version": 1, "last_run": {}, "sources": {}, "errors": [], "deals_months_done": {"bulk": [], "block": []},
            "insider_months_done": [], "pit_gg_months_done": [], "shp_months_done": [], "shp_failed": {},
            "shp_symbol_checked": {}}


def load_state(folder: Path | None = None) -> dict:
    """state.json (section 4.3), every documented key present (empty when never refreshed)."""
    state = _default_state()
    try:
        raw = json.loads(files(folder)["state"].read_text(encoding="utf-8"))
    except Exception:
        return state
    if not isinstance(raw, dict):
        return state
    for k, v in raw.items():
        if k in state and not isinstance(v, type(state[k])):
            continue   # a damaged value keeps its default
        state[k] = v
    for kind in ("bulk", "block"):
        if not isinstance(state["deals_months_done"].get(kind), list):
            state["deals_months_done"][kind] = []
    return state


# ------------------------------------------------------------------ refresh
def _source(status: str, message: str, rows_added: int = 0, last_ok_at: str | None = None,
            latest_date: str | None = None) -> dict:
    return {"status": status, "message": message, "rows_added": rows_added, "last_ok_at": last_ok_at,
            "latest_date": latest_date}


def _report(started: str, t0: float, sources: dict, errors: list[str]) -> dict:
    return {"ok": all(s["status"] in ("ok", "partial") for s in sources.values()), "started_at": started,
            "finished_at": _now(), "elapsed_s": round(time.monotonic() - t0, 1), "sources": sources,
            "errors": errors}


def _safe_log(log: Callable[[str], None]) -> Callable[[str], None]:
    def say(msg: str) -> None:
        try:
            log(msg)
        except Exception:
            pass
    return say


def refresh(days: int = 365, log: Callable[[str], None] = print, symbols: list[str] | None = None, *,
            holdings_quarters: int = 2, max_xbrl: int = 300, max_pit_xbrl: int = MAX_PIT_XBRL,
            folder: Path | None = None, today: date | None = None) -> dict:
    """Download what is new from NSE into the cache: deals and insider trades of the last `days` (past months
    once), today's FII/DII figures, and the newest `holdings_quarters` shareholding filings of `symbols` (default:
    the cached scan universe + your holdings; at most `max_xbrl` files per run, the rest next time; insider filings
    from corporates-pit-gg: at most `max_pit_xbrl` XBRL files per run). Never raises
    for network or data problems: returns {"ok", "started_at", "finished_at", "elapsed_s", "sources", "errors"}."""
    t0, started, say = time.monotonic(), _now(), _safe_log(log)
    folder = Path(folder or SM_DIR)
    today = today or ist_today()
    try:
        days = max(1, min(int(days), 730))
    except (TypeError, ValueError):
        days = 365
    try:
        folder.mkdir(parents=True, exist_ok=True)
        fh = open(folder / ".refresh.lock", "a+")
    except OSError as e:
        msg = f"Cannot use the folder {folder}: {e}"[:300]
        return _report(started, t0, {n: _source("failed", msg) for n in SOURCE_NAMES}, [msg])
    deadline = time.monotonic() + LOCK_GRACE_S
    locked = _try_lock(fh)
    while not locked and time.monotonic() < deadline:   # maybe only a refresh_running() probe (the dashboard)
        time.sleep(0.1)
        locked = _try_lock(fh)
    if not locked:
        fh.close()
        busy = {n: _source("skipped", "Another refresh is running") for n in SOURCE_NAMES}
        return _report(started, t0, busy, ["Another smart-money refresh is already running."])
    try:
        (folder / "xbrl").mkdir(exist_ok=True)
        return _run(folder, days, say, symbols, holdings_quarters, max_xbrl, today, started, t0, max_pit_xbrl)
    except Exception as e:   # outside the per-step guards (disk trouble): still a report, never a crash
        msg = f"{type(e).__name__}: {e}"[:300]
        return _report(started, t0, {n: _source("failed", msg) for n in SOURCE_NAMES}, [msg])
    finally:
        _unlock(fh)
        fh.close()


def _run(folder: Path, days: int, say, symbols, holdings_quarters: int, max_xbrl: int, today: date,
         started: str, t0: float, max_pit_xbrl: int = MAX_PIT_XBRL) -> dict:
    _reset_api()
    state = load_state(folder)
    path = files(folder)["state"]
    steps = {
        "deals": lambda: _refresh_deals(folder, state, today, days, say),
        "insider": lambda: _refresh_insider(folder, state, today, days, say, max_pit_xbrl),
        "flows": lambda: _refresh_flows(folder, say),
        "holdings": lambda: _refresh_holdings(folder, state, today, symbols, holdings_quarters, max_xbrl, say),
    }
    sources: dict[str, dict] = {}
    problems: list[str] = []
    for name, step in steps.items():
        prev = state["sources"].get(name)
        prev = prev if isinstance(prev, dict) else {}
        try:
            res = step()
        except Exception as e:   # a bug or bad data in one step must not stop the others
            res = {"status": "failed", "message": f"{type(e).__name__}: {e}"[:300], "rows_added": 0,
                   "latest_date": prev.get("latest_date")}
        good = res.get("status") in ("ok", "partial")
        src = _source(res.get("status") or "failed", str(res.get("message") or "")[:300],
                      int(res.get("rows_added") or 0), _now() if good else prev.get("last_ok_at"),
                      res.get("latest_date", prev.get("latest_date")))
        sources[name] = src
        state["sources"][name] = src
        try:
            _save_json(state, path)   # progress survives a crash
        except OSError as e:
            problems.append(f"state.json could not be saved: {e}"[:300])
    errors = [f"{n}: {s['message']}" for n, s in sources.items() if s["status"] in ("partial", "failed", "skipped")]
    errors = (errors + _unique(problems))[:20]
    report = _report(started, t0, sources, errors)
    state["last_run"] = {"started_at": started, "finished_at": report["finished_at"],
                         "elapsed_s": report["elapsed_s"], "ok": report["ok"], "days": days}
    state["errors"] = errors
    try:
        _save_json(state, path)
    except OSError:
        pass
    return report


def _unmatched(deals: pd.DataFrame) -> dict:
    """Deal client names no rule could place, most frequent first (to grow the word lists)."""
    counts = deals["client"].value_counts() if len(deals) else pd.Series(dtype="int64")
    names = [{"name": str(n), "count": int(c)} for n, c in counts.items()
             if classify(n).sub_label == "Unclassified"]
    names.sort(key=lambda x: (-x["count"], x["name"]))
    return {"updated": _now(), "names": names[:300]}


def _refresh_deals(folder: Path, state: dict, today: date, days: int, log) -> dict:
    log("Smart money: bulk and block deals...")
    new: list[pd.DataFrame] = []
    fails: list[str] = []
    good = 0
    for kind, url in (("bulk", BULK_CSV_URL), ("block", BLOCK_CSV_URL)):
        code, body = _fetch(url)
        if code == 200 and _readable(body):
            new.append(parse_deals(body, kind, "archive"))
            good += 1
        else:
            fails.append(f"{kind}.csv " + (f"HTTP {code}" if code != 200 else "unreadable"))
    if not good:   # both archive files failed: NSE's large-deals snapshot has the same rows
        code, body = _fetch(API + "snapshot-capital-market-largedeal", api=True, referer=PAGES["large"])
        if code == 200 and _readable(body):
            new.append(parse_large_deals(body))
            good += 1
        else:
            fails.append(f"large-deals snapshot HTTP {code}")

    raw_done = state.get("deals_months_done") or {}
    done = {k: set(raw_done.get(k) or []) for k in ("bulk", "block")}
    hist_failed, blocked = 0, False
    months = _months(today - timedelta(days=days - 1), today)
    for kind, option in (("bulk", "bulk_deals"), ("block", "block_deals")):
        for first, last, key, full in months:
            if blocked:
                break
            if key in done[kind]:
                continue
            code, body = _fetch(API + "historicalOR/bulk-block-short-deals",
                                {"optionType": option, "from": first.strftime("%d-%m-%Y"),
                                 "to": last.strftime("%d-%m-%Y"), "csv": "true"},
                                api=True, referer=PAGES["deals"])
            if code == 200 and _readable(body):
                new.append(parse_deals(body, kind, "history"))
                good += 1
                if _final(first, full, today):
                    done[kind].add(key)
            elif code == -2:
                blocked = True
            else:
                hist_failed += 1

    f = files(folder)
    old = load_deals(folder)
    merged = _dedupe_deals(pd.concat([old, *new], ignore_index=True)) if any(len(d) for d in new) else old
    if not merged.equals(old):
        _save_parquet(merged, f["deals"])
    state["deals_months_done"] = {k: sorted(v, reverse=True) for k, v in done.items()}   # only after the save
    try:
        _save_json(_unmatched(merged), f["unmatched"])
    except OSError:
        pass

    newest = latest(merged, "date")
    issues = list(fails)
    if hist_failed:
        issues.append(f"{hist_failed} history month{'s' if hist_failed != 1 else ''} failed")
    if blocked:
        issues.append("NSE blocked requests - the rest of the history comes with the next refresh")
    msg = f"{len(merged):,} deal rows up to {_day_text(newest)}" if newest else "No deal rows stored yet"
    status = "failed" if not good else "partial" if issues else "ok"
    return {"status": status, "message": "; ".join([msg, *issues]), "rows_added": len(merged) - len(old),
            "latest_date": newest}


def _refresh_insider(folder: Path, state: dict, today: date, days: int, log,
                     max_pit_xbrl: int = MAX_PIT_XBRL) -> dict:
    done = set(state.get("insider_months_done") or [])
    new: list[pd.DataFrame] = []
    failed_months: list[str] = []
    tried = good = 0
    blocked = False
    for first, last, key, full in _months(today - timedelta(days=days - 1), today):
        if key in done:
            continue
        log(f"Smart money: insider trades {first:%b %Y}...")
        tried += 1
        code, body = _fetch(API + "corporates-pit", {"index": "equities", "from_date": first.strftime("%d-%m-%Y"),
                                                     "to_date": last.strftime("%d-%m-%Y")},
                            api=True, referer=PAGES["pit"])
        if code == 200 and _readable(body):
            new.append(parse_pit(body))
            good += 1
            if _final(first, full, today):
                done.add(key)
        elif code == -2:
            blocked = True
            break
        else:
            failed_months.append(f"{first:%b %Y}")

    f = files(folder)
    old = _read(f["insider"], INSIDER_COLS)   # stored columns only (no enrichment)
    merged = _dedupe_insider(pd.concat([old, *new], ignore_index=True)) if any(len(d) for d in new) else old
    state["insider_months_done"] = sorted(done, reverse=True)
    gg_issues: list[str] = []
    if not blocked:   # since May 2026 the trades come from corporates-pit-gg (see the module docstring)
        gg_rows, gg_issues, gg_tried, gg_good = _refresh_insider_gg(folder, state, today, days, merged,
                                                                    max_pit_xbrl, log)
        tried, good = tried + gg_tried, good + gg_good
        if len(gg_rows):
            merged = _dedupe_insider(pd.concat([merged, gg_rows], ignore_index=True))
    if not merged.equals(old):
        _save_parquet(merged, f["insider"])

    newest = latest(merged, "disclosed")
    issues = []
    if failed_months:
        issues.append("failed: " + ", ".join(failed_months[:6]) + (" ..." if len(failed_months) > 6 else ""))
    if blocked:
        issues.append("NSE blocked requests - the rest comes with the next refresh")
    issues += gg_issues
    msg = f"{len(merged):,} insider filings up to {_day_text(newest)}" if newest else "No insider filings stored yet"
    status = "ok" if not tried else "failed" if not good else "partial" if issues else "ok"
    return {"status": status, "message": "; ".join([msg, *issues]), "rows_added": len(merged) - len(old),
            "latest_date": newest}


def _refresh_insider_gg(folder: Path, state: dict, today: date, days: int, have: pd.DataFrame, max_files: int,
                        log) -> tuple[pd.DataFrame, list[str], int, int]:
    """corporates-pit-gg: list each month's filings (past months once), then read the XBRL file of every filing the
    old corporates-pit API did not cover (no stored trade of that stock disclosed that day), newest first, at most
    `max_files` per refresh. Returns (new INSIDER_COLS rows, issues, list calls tried, list calls that worked)."""
    f = files(folder)
    done = set(state.get("pit_gg_months_done") or [])
    listed: list[pd.DataFrame] = []
    tried = good = 0
    issues: list[str] = []
    for first, last, key, full in _months(today - timedelta(days=days - 1), today):
        if key in done:
            continue
        tried += 1
        code, body = _fetch(API + "corporates-pit-gg", {"index": "equities", "from_date": first.strftime("%d-%m-%Y"),
                                                        "to_date": last.strftime("%d-%m-%Y")},
                            api=True, referer=PAGES["pit"])
        if code == 200 and _readable(body):
            listed.append(parse_pit_listing(body))
            good += 1
            if _final(first, full, today):
                done.add(key)
        elif code == -2:
            issues.append("NSE blocked the insider filings list - the rest comes with the next refresh")
            break
        else:
            issues.append(f"insider filings list {first:%b %Y} failed")
    state["pit_gg_months_done"] = sorted(done, reverse=True)

    old = _read(f["pit_filings"], PIT_FILING_COLS)
    filings = old.copy()
    if listed:   # new filings join as 'pending'; a filing already stored keeps its status
        new = pd.concat(listed, ignore_index=True)
        filings = _conform(pd.concat([old, new[~new["app_id"].isin(old["app_id"])]], ignore_index=True)
                           .drop_duplicates("app_id", keep="first"), PIT_FILING_COLS)
    # a filing the old API already gave us (a trade of that stock disclosed that day) is not read again
    covered = set(zip(have["symbol"], have["disclosed"].astype(str).str[:10]))
    day = filings["broadcast"].astype(str).str[:10]
    is_covered = pd.Series([(s, d) in covered for s, d in zip(filings["symbol"], day)], index=filings.index,
                           dtype=bool)
    filings.loc[(filings["status"] == "pending") & is_covered, "status"] = "covered"
    recheck = (today - timedelta(days=RECHECK_DAYS)).isoformat()
    due = filings[(filings["status"] == "pending")
                  | ((filings["status"] == "failed") & (filings["tries"] < 5)
                     & (filings["last_try"].fillna("").astype(str) < recheck))]
    due = due.sort_values("broadcast", ascending=False, na_position="last")
    todo = due.head(max(0, int(max_files))).to_dict("records")
    rows: list[pd.DataFrame] = []
    n_bad = streak = 0
    if todo:
        log(f"Smart money: insider filings 0/{len(todo)} files")

        def get(rec: dict) -> tuple[str, pd.DataFrame | None]:
            try:
                code, body = _fetch(rec["xml"])
                if code != 200 or not body:
                    return "download", None
                return "ok", parse_pit_xbrl(body, rec)
            except Exception:
                return "unreadable", None
        status_of: dict[str, str] = {}
        step = 2 * XBRL_WORKERS
        with ThreadPoolExecutor(XBRL_WORKERS) as ex:
            for i in range(0, len(todo), step):
                chunk = todo[i:i + step]
                for rec, (st, df) in zip(chunk, ex.map(get, chunk)):
                    status_of[rec["app_id"]] = "ok" if st == "ok" else "failed"
                    if st == "ok":
                        streak = 0
                        rows.append(df)
                    else:
                        n_bad += 1
                        streak = streak + 1 if st == "download" else 0
                if (i // step) % 13 == 12:
                    log(f"Smart money: insider filings {min(i + step, len(todo))}/{len(todo)} files")
                if streak >= XBRL_MAX_FAILURES:
                    issues.append("the NSE archive stopped answering - the rest of the insider files come next time")
                    break
        hit = filings["app_id"].isin(list(status_of))
        filings.loc[hit, "status"] = filings.loc[hit, "app_id"].map(status_of)
        filings.loc[hit, "last_try"] = today.isoformat()
        filings.loc[hit & (filings["status"] == "failed"), "tries"] += 1
    left = int((filings["status"] == "pending").sum())
    if left:
        issues.append(f"{left:,} insider filing{'s' if left != 1 else ''} left for the next refresh")
    if n_bad:
        issues.append(f"{n_bad} insider file{'s' if n_bad != 1 else ''} could not be read (will retry)")
    filings = _conform(filings, PIT_FILING_COLS)
    if not filings.equals(old):
        _save_parquet(filings, f["pit_filings"])
    out = _dedupe_insider(pd.concat(rows, ignore_index=True)) if rows else pd.DataFrame()
    return out, issues, tried, good


def _refresh_flows(folder: Path, log) -> dict:
    log("Smart money: FII/DII figures...")
    f = files(folder)
    old = load_flows(folder)
    code, body = _fetch(API + "fiidiiTradeReact", api=True, referer=PAGES["fiidii"])
    new = parse_fiidii(body) if code == 200 else _empty(FLOW_COLS)
    if new.empty:
        why = "NSE blocked requests" if code == -2 else f"HTTP {code}" if code != 200 else "no figures in the reply"
        return {"status": "failed", "message": f"FII/DII figures not available ({why})", "rows_added": 0,
                "latest_date": latest(old, "date")}
    if len(old):   # upsert by date: a NaN in the new row keeps the old value
        merged = new.set_index("date").combine_first(old.set_index("date"))
        merged.index.name = "date"
        merged = merged.reset_index()
    else:
        merged = new
    merged = _conform(merged, FLOW_COLS).sort_values("date", kind="stable").reset_index(drop=True)
    if not merged.equals(old):
        _save_parquet(merged, f["flows"])
    newest, first = latest(merged, "date"), merged["date"].iloc[0]
    return {"status": "ok", "message": f"FII/DII figures up to {_day_text(newest)} (history since "
                                       f"{_day_text(first)})", "rows_added": len(merged) - len(old),
            "latest_date": newest}


def _default_symbols() -> list[str]:
    """The cached scan universe + your holdings, minus ETFs (never downloads the universe)."""
    try:
        cfg = load_config() or {}
    except Exception:
        cfg = {}
    name = str(cfg.get("universe") or "nifty500").lower()
    out: list[str] = []
    try:
        path = DATA_DIR / f"universe_{name}.csv"
        if path.exists():
            out += [str(s) for s in pd.read_csv(path, dtype=str)["symbol"].dropna()]
    except Exception:
        pass
    try:
        from .holdings import load_holdings as load_my_holdings
        out += [str(s) for s in load_my_holdings()["symbol"].dropna()]
    except Exception:
        pass
    etfs = cfg.get("etfs")
    skip = {str(e).strip().upper() for e in etfs} if isinstance(etfs, (list, tuple)) else set()
    syms = [s.strip().upper() for s in out]
    return _unique(s for s in syms if s and s not in ("NAN", "NONE") and s not in skip)


def _merge_filings(old: pd.DataFrame, parts: list[pd.DataFrame]) -> pd.DataFrame:
    parts = [p for p in parts if len(p)]
    if not parts:
        return old
    m = pd.concat([old, *parts], ignore_index=True).drop_duplicates("record_id", keep="last")
    m = m.sort_values(["symbol", "period", "broadcast", "record_id"], ascending=[True, False, False, False],
                      na_position="last")
    return _conform(m, FILING_COLS)


def _reparse_cached_holders(folder: Path, hold: pd.DataFrame) -> int:
    """Named holders of every stored XBRL filing, parsed again from the cached files (no download). Returns the
    number of files read."""
    xdir, rows, n = folder / "xbrl", [], 0
    for r in hold[hold["source"] == "xbrl"].to_dict("records"):
        path = xdir / f"SHP_{int(r['record_id'])}.xml.gz"
        try:
            _, holders = parse_shp_xbrl(gzip.decompress(path.read_bytes()))
        except Exception:
            continue                                   # missing or damaged: its old holders stay
        n += 1
        rows += [{"symbol": r["symbol"], "period": r["period"], "record_id": int(r["record_id"]), "holder": h["holder"],
                  "holder_key": normalise_name(h["holder"]), "group": h["group"], "xbrl_member": h["xbrl_member"],
                  "shares": h["shares"], "pct": h["pct"]} for h in holders]
    if n:
        f = files(folder)
        old = _read(f["holders"], HOLDER_COLS)
        done = {int(r["record_id"]) for r in rows} | {int(x) for x in hold.loc[hold["source"] == "xbrl", "record_id"]
                                                    if (xdir / f"SHP_{int(x)}.xml.gz").exists()}
        keep = old[~old["record_id"].isin(list(done))]
        _save_parquet(_conform(pd.concat([keep, _frame(rows, HOLDER_COLS)], ignore_index=True), HOLDER_COLS),
                      f["holders"])
    return n


def _get_xbrl(rec: dict, xdir: Path) -> tuple[str, dict | None, list | None]:
    """('ok', cats, holders) / ('download', None, None) / ('unreadable', None, None) for one filing. The raw file
    is cached (gzip) once it parses, so each filing is downloaded only once."""
    try:
        path = xdir / f"SHP_{int(rec['record_id'])}.xml.gz"
        if path.exists():
            try:
                cats, holders = parse_shp_xbrl(gzip.decompress(path.read_bytes()))
                return "ok", cats, holders
            except Exception:
                try:
                    path.unlink()   # a damaged cache file: download it again
                except OSError:
                    pass
        url = _text(rec.get("xbrl"))
        if not url:
            return "unreadable", None, None
        code, body = _fetch(url)
        if code != 200 or not body:
            return "download", None, None
        try:
            cats, holders = parse_shp_xbrl(body)
        except Exception:
            return "unreadable", None, None
        try:
            _save_bytes(gzip.compress(body), path)
        except OSError:
            pass
        return "ok", cats, holders
    except Exception:
        return "download", None, None


def _refresh_holdings(folder: Path, state: dict, today: date, symbols, holdings_quarters: int, max_xbrl: int,
                      log) -> dict:
    f = files(folder)
    syms = (_unique(str(s).strip().upper() for s in symbols if not _missing(s)) if symbols is not None
            else _default_symbols())
    recheck = (today - timedelta(days=RECHECK_DAYS)).isoformat()

    # 1. the filings list, month by month (date-range mode lists every company that filed)
    log("Smart money: shareholding filings list...")
    done = set(state.get("shp_months_done") or [])
    listed: list[pd.DataFrame] = []
    list_tried = list_good = list_bad = 0
    blocked = False
    for first, last, key, full in _months(today - timedelta(days=SHP_LISTING_DAYS), today):
        if key in done:
            continue
        list_tried += 1
        code, body = _fetch(API + "corporate-share-holdings-master",
                            {"index": "equities", "from_date": first.strftime("%d-%m-%Y"),
                             "to_date": last.strftime("%d-%m-%Y")}, api=True, referer=PAGES["shp"])
        if code == 200 and _readable(body):
            listed.append(parse_shp_master(body))
            list_good += 1
            if _final(first, full, today):
                done.add(key)
        elif code == -2:
            blocked = True
            break
        else:
            list_bad += 1

    # 2. stocks the list did not cover: ask NSE per symbol (a few per refresh, never-checked first)
    old_filings = _read(f["filings"], FILING_COLS)
    filings = _merge_filings(old_filings, listed)
    cutoff = (today - timedelta(days=SHP_LISTING_DAYS)).isoformat()
    recent = set(filings.loc[_on_or_after(filings["period"], cutoff), "symbol"])
    checked = {str(k): str(v) for k, v in (state.get("shp_symbol_checked") or {}).items()}
    lookups = [s for s in syms if s not in recent and checked.get(s, "") < recheck]
    lookups = sorted(lookups, key=lambda s: checked.get(s, ""))[:MAX_SYMBOL_LOOKUPS]
    sym_good = sym_bad = 0
    if lookups and not blocked:
        log(f"Smart money: shareholding lookups for {len(lookups)} stocks...")
    for s in lookups:
        if blocked:
            break
        code, body = _fetch(API + "corporate-share-holdings-master", {"index": "equities", "symbol": s},
                            api=True, referer=PAGES["shp"])
        if code == -2:
            blocked = True
            break
        checked[s] = today.isoformat()
        if code == 200 and _readable(body):
            listed.append(parse_shp_master(body))
            sym_good += 1
        else:
            sym_bad += 1
    filings = _merge_filings(old_filings, listed)
    if not filings.equals(old_filings):
        _save_parquet(filings, f["filings"])
    state["shp_months_done"] = sorted(done, reverse=True)
    state["shp_symbol_checked"] = checked

    # 3. the XBRL files to read: the newest `holdings_quarters` periods of each stock (latest revision)
    old_hold = _read(f["holdings"], HOLDING_COLS)
    if int(state.get("holders_parser") or 1) < HOLDERS_PARSER:
        n = _reparse_cached_holders(folder, old_hold)
        log(f"Smart money: named holders re-read from {n} cached shareholding files")
        state["holders_parser"] = HOLDERS_PARSER
    have_xbrl = set(old_hold.loc[old_hold["source"] == "xbrl", "record_id"].tolist())
    have_any = set(old_hold["record_id"].tolist())
    failed = {str(k): str(v) for k, v in (state.get("shp_failed") or {}).items()}
    order = {s: i for i, s in enumerate(syms)}
    fl = filings[filings["symbol"].isin(list(order))]
    fl = fl.sort_values(["broadcast", "record_id"], ascending=[False, False], na_position="last")
    fl = fl.drop_duplicates(["symbol", "period"], keep="first")
    fl = fl.sort_values(["symbol", "period"], ascending=[True, False])
    fl = fl.groupby("symbol", sort=False).head(max(1, int(holdings_quarters)))
    recs = [r for r in fl.to_dict("records")
            if r["record_id"] not in have_xbrl and failed.get(str(r["record_id"]), "") < recheck]
    recs.sort(key=lambda r: order[r["symbol"]])
    recs.sort(key=lambda r: r["period"], reverse=True)   # stable: newest period first, then the symbols' order
    todo = recs[:max(0, int(max_xbrl))]
    left = len(recs) - len(todo)

    # 4. download (cached forever) and parse, a few files at a time
    xdir = folder / "xbrl"
    xdir.mkdir(parents=True, exist_ok=True)
    new_hold: list[dict] = []
    new_holders: list[dict] = []
    parsed: set[int] = set()
    n_ok = n_dl = n_bad = seen = streak = 0
    if todo:
        log(f"Smart money: shareholding 0/{len(todo)} files")
        step = 2 * XBRL_WORKERS
        with ThreadPoolExecutor(XBRL_WORKERS) as ex:
            for i in range(0, len(todo), step):
                chunk = todo[i:i + step]
                for rec, (status, cats, holders) in zip(chunk, ex.map(lambda r: _get_xbrl(r, xdir), chunk)):
                    seen += 1
                    rid = int(rec["record_id"])
                    base = {"symbol": rec["symbol"], "company": rec.get("company"), "period": rec["period"],
                            "record_id": rid, "broadcast": rec.get("broadcast")}
                    if status == "ok":
                        streak = 0
                        n_ok += 1
                        parsed.add(rid)
                        failed.pop(str(rid), None)
                        new_hold.append({**base, "source": "xbrl", **cats})
                        new_holders += [{"symbol": rec["symbol"], "period": rec["period"], "record_id": rid,
                                         "holder": h["holder"], "holder_key": normalise_name(h["holder"]),
                                         "group": h["group"], "xbrl_member": h["xbrl_member"],
                                         "shares": h["shares"], "pct": h["pct"]} for h in holders]
                    else:
                        if status == "download":
                            streak += 1
                            n_dl += 1
                        else:
                            streak = 0
                            n_bad += 1
                        failed[str(rid)] = today.isoformat()
                        if rid not in have_any:   # at least the list's promoter / public split
                            new_hold.append({**base, "source": "master", "promoter_pct": rec.get("promoter_pct"),
                                             "public_pct": rec.get("public_pct")})
                            have_any.add(rid)
                    if seen % 50 == 0:
                        log(f"Smart money: shareholding {seen}/{len(todo)} files")
                if streak >= XBRL_MAX_FAILURES:
                    left += len(todo) - seen   # the archive is refusing: try the rest next time
                    break

    # 5. merge and save: holders first, so a crash can never leave an xbrl holdings row without its holders
    if parsed:
        old_h = _read(f["holders"], HOLDER_COLS)
        keep = old_h[~old_h["record_id"].isin(list(parsed))]
        _save_parquet(_conform(pd.concat([keep, _frame(new_holders, HOLDER_COLS)], ignore_index=True),
                               HOLDER_COLS), f["holders"])
    hold = old_hold
    if new_hold:
        both = pd.concat([_frame(new_hold, HOLDING_COLS), old_hold], ignore_index=True)
        both = both.assign(_x=np.where(both["source"] == "xbrl", 0, 1)).sort_values("_x", kind="stable")
        hold = _conform(both.drop_duplicates("record_id", keep="first").drop(columns="_x"), HOLDING_COLS)
        hold = _conform(hold.sort_values(["symbol", "period", "record_id"], ascending=[True, False, False]),
                        HOLDING_COLS)
        _save_parquet(hold, f["holdings"])
    state["shp_failed"] = failed

    covered = int(hold.loc[hold["symbol"].isin(list(order)), "symbol"].nunique())
    newest = latest(hold, "period")
    issues = []
    if not syms:
        issues.append("no stock list found (the scan universe is not cached yet)")
    if list_bad:
        issues.append(f"{list_bad} filings-list month{'s' if list_bad != 1 else ''} failed")
    if sym_bad:
        issues.append(f"{sym_bad} per-stock lookup{'s' if sym_bad != 1 else ''} failed")
    if n_dl:
        issues.append(f"{n_dl} shareholding file{'s' if n_dl != 1 else ''} could not be downloaded (will retry)")
    if n_bad:
        issues.append(f"{n_bad} shareholding file{'s' if n_bad != 1 else ''} could not be read")
    if left:
        issues.append(f"{left} file{'s' if left != 1 else ''} left for the next refresh")
    if blocked:
        issues.append("NSE blocked requests")
    msg = f"Shareholding for {covered} of {len(syms)} stocks" + (f", newest quarter {_month_text(newest)}"
                                                                    if newest else "")
    attempted = list_tried + sym_good + sym_bad + len(todo)
    nothing_worked = attempted > 0 and list_good + sym_good + n_ok == 0
    status = "failed" if nothing_worked else "partial" if issues else "ok"
    return {"status": status, "message": "; ".join([msg, *issues]), "rows_added": len(hold) - len(old_hold),
            "latest_date": newest}


def refresh_running(folder: Path | None = None) -> bool:
    """True while another handle (this or another process) holds the refresh lock."""
    path = Path(folder or SM_DIR) / ".refresh.lock"
    if not path.exists():
        return False
    try:
        with open(path, "a+") as fh:
            if _try_lock(fh):
                _unlock(fh)
                return False
            return True
    except OSError:
        return False


# ------------------------------------------------------------------ derived tables (pure; the API calls these)
def latest(df: pd.DataFrame, col: str) -> str | None:
    """Newest value of an ISO date column, or None."""
    if df is None or col not in df.columns or len(df) == 0:
        return None
    vals = [x for x in df[col] if isinstance(x, str) and x]
    return max(vals) if vals else None


def window(as_of: str | None, days: int) -> str | None:
    """First day of a `days`-long window ending on `as_of` (inclusive): days=1 -> as_of itself."""
    if _missing(as_of) or not as_of:
        return None
    try:
        d = date.fromisoformat(str(as_of)[:10])
        n = max(int(days), 1)
    except (TypeError, ValueError):
        return None
    return (d - timedelta(days=n - 1)).isoformat()


def share_counts(holdings: pd.DataFrame) -> dict[str, float]:
    """symbol -> total shares from its newest parsed shareholding filing."""
    if holdings is None or len(holdings) == 0:
        return {}
    x = holdings[(holdings["source"] == "xbrl") & (holdings["total_shares"] > 0)]
    x = x.sort_values(["symbol", "period"], ascending=[True, False]).drop_duplicates("symbol")
    return {s: float(v) for s, v in zip(x["symbol"], x["total_shares"])}


def company_names(net: pd.DataFrame, insider: pd.DataFrame, holdings: pd.DataFrame) -> dict[str, str]:
    """symbol -> company name: shareholding filings first, then insider filings, then the deal files."""
    out: dict[str, str] = {}
    for df, col in ((holdings, "company"), (insider, "company"), (net, "security")):
        if df is None or col not in df.columns:
            continue
        for s, c in zip(df["symbol"], df[col]):
            if isinstance(s, str) and isinstance(c, str) and c.strip() and s not in out:
                out[s] = c.strip()
    return out


def category_mask(categories: pd.Series, flt: str) -> pd.Series:
    """'all' / 'big' (BIG_MONEY) / 'institutions' / one category slug -> boolean mask."""
    flt = (flt or "all").strip().lower()
    if flt == "all":
        return pd.Series(True, index=categories.index, dtype=bool)
    if flt == "big":
        return categories.isin(list(BIG_MONEY)).astype(bool)
    if flt == "institutions":
        return categories.isin(list(INSTITUTIONS)).astype(bool)
    return (categories == flt).astype(bool)


def net_deals(deals: pd.DataFrame, promoters: dict[str, set[str]] | None = None,
              shares: dict[str, float] | None = None) -> pd.DataFrame:
    """One row per (date, symbol, client): that client's bulk + block lines in the stock that day, netted and
    labelled (NET_DEAL_COLS). Newest first, then by size."""
    if deals is None or len(deals) == 0:
        return _empty(NET_DEAL_COLS)
    promoters, shares = promoters or {}, shares or {}
    d = _conform(deals, DEAL_COLS)
    d = d[d["side"].isin(["BUY", "SELL"]) & (d["qty"] > 0)].reset_index(drop=True)
    if d.empty:
        return _empty(NET_DEAL_COLS)
    d["client_key"] = [k if isinstance(k, str) and k else parent_key(c) for k, c in zip(d["client_key"], d["client"])]
    buy = d["side"] == "BUY"
    val = d["value"].fillna(0.0)
    keys = ["date", "symbol", "client_key"]
    d = d.assign(_bq=d["qty"].where(buy, 0.0), _sq=d["qty"].where(~buy, 0.0), _bv=val.where(buy, 0.0),
                 _sv=val.where(~buy, 0.0), _blk=(d["kind"] == "block").astype("int64"),
                 _rank=d["value"].fillna(-1.0))
    out = d.groupby(keys, sort=False).agg(
        security=("security", "first"), buy_qty=("_bq", "sum"), sell_qty=("_sq", "sum"),
        buy_value=("_bv", "sum"), sell_value=("_sv", "sum"), n=("_blk", "size"), n_block=("_blk", "sum"),
    ).reset_index()
    top = d.sort_values("_rank", ascending=False, kind="stable").drop_duplicates(keys)   # the biggest line's name
    out = out.merge(top[keys + ["client"]], on=keys, how="left")

    bq, sq = out["buy_qty"].to_numpy(float), out["sell_qty"].to_numpy(float)
    bv, sv = out["buy_value"].to_numpy(float), out["sell_value"].to_numpy(float)
    net_q, net_v = bq - sq, bv - sv
    is_buy, is_sell = net_q > 0, net_q < 0
    side = np.where(is_buy, "BUY", np.where(is_sell, "SELL", "FLAT")).astype(object)
    num = np.where(is_buy, bv, np.where(is_sell, sv, bv + sv))
    den = np.where(is_buy, bq, np.where(is_sell, sq, bq + sq))
    avg = np.divide(num, den, out=np.full(len(out), np.nan), where=(num > 0) & (den > 0))
    hi, lo = np.maximum(bq, sq), np.minimum(bq, sq)
    ratio = np.divide(lo, hi, out=np.zeros(len(out)), where=hi > 0)
    rt = (bq > 0) & (sq > 0) & (ratio >= ROUND_TRIP_RATIO)
    n, nb = out["n"].to_numpy(), out["n_block"].to_numpy()
    kind = np.where(nb == n, "block", np.where(nb == 0, "bulk", "both")).astype(object)

    labels = [classify(c, promoters=promoters.get(s), company=sec, round_trip=bool(r))
              for c, s, sec, r in zip(out["client"], out["symbol"], out["security"], rt)]
    pct = np.full(len(out), np.nan)
    for i, s in enumerate(out["symbol"]):
        sh = shares.get(s)
        if _finite(sh) and sh > 0:
            pct[i] = round((hi[i] if rt[i] else abs(net_q[i])) / sh * 100, 3)

    # block deals: who was on the other side of the same stock that day
    book: dict[tuple[str, str], list[tuple[str, str, str]]] = defaultdict(list)
    blk = d[d["kind"] == "block"]
    for day, s, sd, c, ck in zip(blk["date"], blk["symbol"], blk["side"], blk["client"], blk["client_key"]):
        book[(day, s)].append((sd, c, ck))
    cps = []
    for day, s, ck, k, sd in zip(out["date"], out["symbol"], out["client_key"], kind, side):
        if k == "bulk":
            cps.append([])
            continue
        want = {"BUY": ("SELL",), "SELL": ("BUY",)}.get(sd, ("BUY", "SELL"))
        cps.append(sorted({c for x, c, key in book.get((day, s), []) if x in want and key != ck}))

    res = pd.DataFrame({
        "id": [f"{a}|{b}|{c}" for a, b, c in zip(out["date"], out["symbol"], out["client_key"])],
        "date": out["date"], "symbol": out["symbol"], "client_key": out["client_key"], "security": out["security"],
        "client": out["client"], "kind": kind, "buy_qty": bq, "sell_qty": sq, "net_qty": net_q, "buy_value": bv,
        "sell_value": sv, "net_value": net_v, "side": side, "avg_price": avg, "round_trip": rt,
        "category": [lb.category for lb in labels], "sub_label": [lb.sub_label for lb in labels],
        "investor": [lb.investor for lb in labels], "pct_equity": pct, "counterparties": _obj(cps),
        "_sk": np.where(rt, bv, np.abs(net_v))})
    res = res.sort_values(["date", "_sk", "symbol", "client_key"], ascending=[False, False, True, True])
    return _conform(res.drop(columns="_sk"), NET_DEAL_COLS)


def _pq_rows(holdings: pd.DataFrame | None) -> dict[str, tuple[dict, dict | None]]:
    """symbol -> (newest parsed filing P, the one before it Q or None when missing / too far apart)."""
    if holdings is None or len(holdings) == 0:
        return {}
    x = _conform(holdings, HOLDING_COLS)
    x = x[x["source"] == "xbrl"]
    if x.empty:
        return {}
    x = x.assign(_b=[_sv(b) or "" for b in x["broadcast"]])
    x = x.sort_values(["symbol", "period", "_b", "record_id"], ascending=[True, False, False, False])
    x = x.drop_duplicates(["symbol", "period"]).drop(columns="_b")
    out: dict[str, tuple[dict, dict | None]] = {}
    count: dict[str, int] = {}
    for rec in x.to_dict("records"):
        sym = rec["symbol"]
        k = count.get(sym, 0)
        count[sym] = k + 1
        if k == 0:
            out[sym] = (rec, None)
        elif k == 1 and _days_between(out[sym][0]["period"], rec["period"]) <= SHP_MAX_GAP_DAYS:
            out[sym] = (out[sym][0], rec)
    return out


def _filing_day(rec: dict) -> str:
    b = rec.get("broadcast")
    return b[:10] if isinstance(b, str) and len(b) >= 10 else rec["period"]


def holder_changes(holders: pd.DataFrame, holdings: pd.DataFrame) -> pd.DataFrame:
    """Named holders of each stock's newest quarter P vs the one before Q (HOLDER_CHANGE_COLS): new / added / cut /
    same / dropped. 'dropped' only means "no longer shown at 1% or more", not always a full exit."""
    pq = _pq_rows(holdings)
    if not pq or holders is None or len(holders) == 0:
        return _empty(HOLDER_CHANGE_COLS)
    h = holders if "category" in holders.columns else _enrich_holders(holders)
    h = _conform(h, {**HOLDER_COLS, **HOLDER_EXTRA_COLS})
    # promoter-group members filed with no shares (0.00%) name the promoters (promoter_sets) but hold no stake:
    # they never make a new / cut / dropped holder
    h = h[pd.to_numeric(h["pct"], errors="coerce") >= 0.01]
    by_rid = {int(rid): g.to_dict("records") for rid, g in h.groupby("record_id", sort=False)}
    rows = []
    for sym, (rp, rq) in pq.items():
        now = by_rid.get(int(rp["record_id"]), [])
        before = by_rid.get(int(rq["record_id"]), []) if rq is not None else []
        prev_period = rq["period"] if rq is not None else None
        cur = {(r["holder_key"], r["group"]): r for r in now}
        old = {(r["holder_key"], r["group"]): r for r in before}
        for k, r in cur.items():
            o = old.get(k) if rq is not None else None
            row = {"symbol": sym, "period": rp["period"], "prev_period": prev_period, "holder": r["holder"],
                   "holder_key": r["holder_key"], "group": r["group"], "category": r["category"],
                   "sub_label": r["sub_label"], "investor": r["investor"], "pct": r["pct"], "prev_pct": np.nan,
                   "change_pts": np.nan, "shares": r["shares"], "status": "same"}
            if rq is not None and o is None:
                row["status"] = "new"
            elif o is not None:
                row["prev_pct"] = o["pct"]
                if _finite(r["pct"]) and _finite(o["pct"]):
                    ch = round(r["pct"] - o["pct"], 4)
                    row["change_pts"] = ch
                    row["status"] = ("added" if ch >= HOLDER_MIN_CHANGE_PTS - 1e-9
                                     else "cut" if ch <= -HOLDER_MIN_CHANGE_PTS + 1e-9 else "same")
            rows.append(row)
        if rq is not None:
            for k, o in old.items():
                if k not in cur:
                    rows.append({"symbol": sym, "period": rp["period"], "prev_period": prev_period,
                                 "holder": o["holder"], "holder_key": o["holder_key"], "group": o["group"],
                                 "category": o["category"], "sub_label": o["sub_label"], "investor": o["investor"],
                                 "pct": np.nan, "prev_pct": o["pct"], "change_pts": np.nan, "shares": np.nan,
                                 "status": "dropped"})
    df = _frame(rows, HOLDER_CHANGE_COLS)
    if df.empty:
        return df
    dropped = df["status"] == "dropped"
    df = df.assign(_d=dropped.astype("int64"), _p=df["pct"].where(~dropped, df["prev_pct"]))
    df = df.sort_values(["symbol", "_d", "_p"], ascending=[True, True, False], na_position="last")
    return _conform(df.drop(columns=["_d", "_p"]), HOLDER_CHANGE_COLS)


def _event_text(e: dict) -> str:
    who = _sv(e["investor"]) or _sv(e["who"]) or "?"
    money = _money(e["value"])
    pct = f", {e['pct_equity']:.2f}% of the company" if _finite(e["pct_equity"]) else ""
    kind_word = "block" if e["source"] == "block" else "bulk"
    role = "Promoter " if e["category"] == "promoter" else "Insider " if e["sub_label"] == INSIDER_LABEL else ""
    q = _period_text(e["period"])
    label = CATEGORY_LABELS.get(e["category"], e["category"])
    qty, before, after, pts = _qty_text(e["qty"]), _p2(e["pct_before"]), _p2(e["pct_after"]), _pts_text(e["change_pts"])
    return {
        "deal_buy": f"{who} bought {qty} shares ({money}{pct}) in a {kind_word} deal",
        "deal_sell": f"{who} sold {qty} shares ({money}{pct}) in a {kind_word} deal",
        "insider_buy": f"{role}{who} bought {qty} shares on the market ({money})",
        "insider_sell": f"{role}{who} sold {qty} shares on the market ({money})",
        "insider_exit": f"{role}{who} sold all their shares ({qty} shares, {money}) - fully exited",
        "pledge_invoked": f"Lender sold {qty} pledged shares of {role}{who} (pledge invoked - a warning sign)",
        "new_holder": f"{who} is a new 1%+ holder with {after}% ({q})",
        "holder_added": f"{who} raised their stake from {before}% to {after}% ({q})",
        "holder_cut": f"{who} cut their stake from {before}% to {after}% ({q})",
        "holder_dropped": f"{who} is no longer shown as a 1%+ holder (was {before}%) - sold some or all ({q})",
        "category_up": f"{label} holding rose {pts} to {after}% ({q})",
        "category_down": f"{label} holding fell {pts} to {after}% ({q})",
        "category_exit": f"{label} sold out completely (was {before}%) ({q})",
    }[e["event"]]


def _ev(event: str, direction: str, source: str, day: str, symbol: str, companies: dict, *, category: str,
        who=None, who_key=None, investor=None, sub_label=None, value=np.nan, qty=np.nan, pct_before=np.nan,
        pct_after=np.nan, change_pts=np.nan, pct_equity=np.nan, period=None, prev_period=None,
        exit_kind=None, extra_weight: int = 0) -> dict:
    e = {"date": day, "symbol": symbol, "company": companies.get(symbol), "event": event, "direction": direction,
         "source": source, "who": _sv(who), "who_key": _sv(who_key) or "", "investor": _sv(investor),
         "category": category, "sub_label": _sv(sub_label), "value": _to_num(value), "qty": _to_num(qty),
         "pct_before": _to_num(pct_before), "pct_after": _to_num(pct_after), "change_pts": _to_num(change_pts),
         "pct_equity": _to_num(pct_equity), "period": _sv(period), "prev_period": _sv(prev_period),
         "exit_kind": exit_kind, "weight": EVENT_WEIGHTS[event] + extra_weight}
    e["text"] = _event_text(e)
    return e


def events(net: pd.DataFrame, insider: pd.DataFrame, holdings: pd.DataFrame, holders: pd.DataFrame,
           since: str | None, shp_since: str | None = None, companies: dict[str, str] | None = None) -> pd.DataFrame:
    """Everything big investors did that the disclosures show, as plain-English events (EVENT_COLS). Deals and
    insider trades count from `since`, shareholding changes when the newest filing came out on or after
    `shp_since` (default `since`). exit_kind says what a sale proves: full_exit (holding after = 0), below_1pct
    (no longer a named 1%+ holder - some or all sold), category_exit, or sold_part."""
    shp_since = since if shp_since is None else shp_since
    companies = companies or {}
    rows: list[dict] = []

    if net is not None and len(net):     # bulk / block deals by big money (no intraday round trips)
        m = (_on_or_after(net["date"], since) & ~net["round_trip"].astype(bool)
             & net["category"].isin(list(BIG_MONEY)) & net["side"].isin(["BUY", "SELL"]))
        for r in net[m].to_dict("records"):
            buy = r["side"] == "BUY"
            v = abs(r["net_value"]) if _finite(r["net_value"]) and r["net_value"] != 0 else np.nan
            rows.append(_ev("deal_buy" if buy else "deal_sell", "up" if buy else "down",
                            "block" if r["kind"] in ("block", "both") else "bulk", r["date"], r["symbol"],
                            companies, category=r["category"], who=r["client"], who_key=r["client_key"],
                            investor=r["investor"], sub_label=r["sub_label"], value=v, qty=abs(r["net_qty"]),
                            pct_equity=r["pct_equity"], exit_kind=None if buy else "sold_part"))

    if insider is not None and len(insider):   # insider filings (promoters, directors, KMP)
        ins = insider if "is_market" in insider.columns else _enrich_insider(insider)
        for r in ins[_on_or_after(ins["disclosed"], since)].to_dict("records"):
            common = dict(category=r["category"], who=r["person"], who_key=r["person_key"], investor=r["investor"],
                          sub_label=r["sub_label"], value=r["value"], qty=r["qty"], pct_before=r["before_pct"],
                          pct_after=r["after_pct"], change_pts=r["change_pts"])
            promoter = 1 if r["category"] == "promoter" else 0
            if r["is_market"] and r["fully_exited"]:
                rows.append(_ev("insider_exit", "down", "insider", r["disclosed"], r["symbol"], companies,
                                exit_kind="full_exit", **common))
            elif r["is_market"]:
                buy = r["side"] == "BUY"
                rows.append(_ev("insider_buy" if buy else "insider_sell", "up" if buy else "down", "insider",
                                r["disclosed"], r["symbol"], companies, exit_kind=None if buy else "sold_part",
                                extra_weight=promoter, **common))
            elif r["mode_kind"] == "pledge_invoked":
                rows.append(_ev("pledge_invoked", "down", "insider", r["disclosed"], r["symbol"], companies,
                                **common))

    pq = _pq_rows(holdings)
    fresh = {s: _filing_day(rp) for s, (rp, _) in pq.items()
             if shp_since is None or _filing_day(rp) >= shp_since}
    if fresh:   # quarterly shareholding: named holders, then whole categories
        hc = holder_changes(holders, holdings)
        kinds = {"new": ("new_holder", "up", None), "added": ("holder_added", "up", None),
                 "cut": ("holder_cut", "down", "sold_part"), "dropped": ("holder_dropped", "down", "below_1pct")}
        for r in hc[hc["symbol"].isin(list(fresh)) & hc["status"].isin(list(kinds))].to_dict("records"):
            event, direction, exit_kind = kinds[r["status"]]
            rows.append(_ev(event, direction, "shareholding", fresh[r["symbol"]], r["symbol"], companies,
                            category=r["category"], who=r["holder"], who_key=r["holder_key"],
                            investor=r["investor"], sub_label=r["sub_label"], qty=r["shares"],
                            pct_before=r["prev_pct"], pct_after=r["pct"], change_pts=r["change_pts"],
                            period=r["period"], prev_period=r["prev_period"], exit_kind=exit_kind))
        for sym, day in fresh.items():
            rp, rq = pq[sym]
            if rq is None:
                continue
            for col, cat in CATEGORY_FIELDS:
                now, prev = rp[col], rq[col]
                if not (_finite(now) and _finite(prev)):
                    continue
                ch = round(now - prev, 4)
                if prev > 0 and now == 0:
                    event, direction, exit_kind = "category_exit", "down", "category_exit"
                elif ch >= CATEGORY_MIN_CHANGE_PTS - 1e-9:
                    event, direction, exit_kind = "category_up", "up", None
                elif ch <= -CATEGORY_MIN_CHANGE_PTS + 1e-9:
                    event, direction, exit_kind = "category_down", "down", "sold_part"
                else:
                    continue
                big = 1 if event != "category_exit" and abs(ch) >= 3 else 0
                rows.append(_ev(event, direction, "shareholding", day, sym, companies, category=cat, who_key=cat,
                                pct_before=prev, pct_after=now, change_pts=ch, period=rp["period"],
                                prev_period=rq["period"], exit_kind=exit_kind, extra_weight=big))

    if not rows:
        return _empty(EVENT_COLS)
    ids = _unique_ids([f"{e['event']}|{e['symbol']}|{e['date']}|{e['who_key']}" for e in rows])
    for e, i in zip(rows, ids):
        e["id"] = i
    df = _frame(rows, EVENT_COLS)
    df = df.sort_values(["date", "weight", "value", "id"], ascending=[False, False, False, True], na_position="last")
    return df.reset_index(drop=True)


def _reason_order(ev: pd.DataFrame) -> pd.DataFrame:
    """REASON_ORDER: weight desc, date desc, abs(change_pts) desc (NaN last), id asc."""
    if ev.empty:
        return ev
    d = ev.assign(_ac=ev["change_pts"].abs())
    d = d.sort_values(["weight", "date", "_ac", "id"], ascending=[False, False, False, True], na_position="last")
    return d.drop(columns="_ac")


def top_reasons(ev: pd.DataFrame, direction: str | None = None, n: int = 4) -> list[str]:
    """The `text` of the `n` most important events (of `direction` when given)."""
    if ev is None or len(ev) == 0:
        return []
    e = ev if direction is None else ev[ev["direction"] == direction]
    return [str(t) for t in _reason_order(e)["text"].head(n)]


def _big_deals(net: pd.DataFrame | None, since: str | None) -> pd.DataFrame:
    if net is None or len(net) == 0:
        return _empty(NET_DEAL_COLS)
    m = _on_or_after(net["date"], since) & ~net["round_trip"].astype(bool) & net["category"].isin(list(BIG_MONEY))
    return net[m]


def _chg(rp: dict | None, rq: dict | None, col: str) -> float:
    """Latest quarter minus the one before, in percentage points (NaN without both)."""
    if rp is None or rq is None or not (_finite(rp[col]) and _finite(rq[col])):
        return np.nan
    return round(rp[col] - rq[col], 2)


def stock_signals(ev: pd.DataFrame, net: pd.DataFrame, holdings: pd.DataFrame, since: str | None) -> pd.DataFrame:
    """One row per stock with at least one event: who is buying / selling / leaving it (SIGNAL_COLS), strongest
    first."""
    if ev is None or len(ev) == 0:
        return _empty(SIGNAL_COLS)
    nd = _big_deals(net, since)
    nd_by = {s: g for s, g in nd.groupby("symbol", sort=False)} if len(nd) else {}
    pq = _pq_rows(holdings)
    rows = []
    for sym, e in ev.groupby("symbol", sort=False):
        up, dn = e[e["direction"] == "up"], e[e["direction"] == "down"]
        up_score, down_score = int(up["weight"].sum()), int(dn["weight"].sum())
        d = nd_by.get(sym)
        buy_v = sell_v = 0.0
        inst_b = inst_s = 0
        fam_b: list[str] = []
        fam_s: list[str] = []
        if d is not None and len(d):
            nv = d["net_value"]
            buy_v, sell_v = float(nv[nv > 0].sum()), float(-nv[nv < 0].sum())
            inst = d[d["category"].isin(list(INSTITUTIONS))]
            inst_b = int(inst.loc[inst["side"] == "BUY", "client_key"].nunique())
            inst_s = int(inst.loc[inst["side"] == "SELL", "client_key"].nunique())
            fam = d[d["category"] == "famous"]
            fam_b = sorted({x for x in fam.loc[fam["side"] == "BUY", "investor"] if isinstance(x, str)})
            fam_s = sorted({x for x in fam.loc[fam["side"] == "SELL", "investor"] if isinstance(x, str)})
        prom = e[e["source"].isin(["bulk", "block", "insider"]) & (e["category"] == "promoter")]
        rp, rq = pq.get(sym, (None, None))
        pref, other = (up, dn) if up_score >= down_score else (dn, up)
        reasons = (list(_reason_order(pref)["text"]) + list(_reason_order(other)["text"]))[:4]
        names = [c for c in e["company"] if isinstance(c, str)]
        dates = [x for x in e["date"] if isinstance(x, str)]
        rows.append({
            "symbol": sym, "company": names[0] if names else None,
            "direction": "up" if dn.empty else "down" if up.empty else "mixed",
            "up_events": len(up), "down_events": len(dn), "up_score": up_score, "down_score": down_score,
            "deal_buy_value": buy_v, "deal_sell_value": sell_v, "deal_net_value": buy_v - sell_v,
            "inst_buyers": inst_b, "inst_sellers": inst_s, "famous_buyers": fam_b, "famous_sellers": fam_s,
            "insider_buy_value": float(e.loc[e["event"] == "insider_buy", "value"].fillna(0.0).sum()),
            "insider_sell_value": float(e.loc[e["event"].isin(["insider_sell", "insider_exit"]), "value"]
                                        .fillna(0.0).sum()),
            "promoter_buying": bool((prom["direction"] == "up").any()),
            "promoter_selling": bool((prom["direction"] == "down").any()),
            "pledge_invoked": bool((e["event"] == "pledge_invoked").any()),
            "exits": int(dn["exit_kind"].isin(list(EXIT_KINDS)).sum()),
            "fii_chg_pts": _chg(rp, rq, "fii_pct"), "dii_chg_pts": _chg(rp, rq, "dii_pct"),
            "mf_chg_pts": _chg(rp, rq, "mf_pct"), "promoter_chg_pts": _chg(rp, rq, "promoter_pct"),
            "period": rp["period"] if rp is not None else None,
            "last_date": max(dates) if dates else None, "reasons": reasons})
    df = pd.DataFrame(rows)
    for c in ("famous_buyers", "famous_sellers", "reasons"):
        df[c] = _obj(list(df[c]))
    df = df.assign(_mx=np.maximum(df["up_score"], df["down_score"]))
    df = df.sort_values(["_mx", "symbol"], ascending=[False, True])
    return _conform(df.drop(columns="_mx"), SIGNAL_COLS)


def accumulating(signals: pd.DataFrame) -> pd.DataFrame:
    """Stocks with buying / adding events, strongest first."""
    s = signals[signals["up_events"] > 0]
    return s.sort_values(["up_score", "deal_net_value", "symbol"], ascending=[False, False, True]).reset_index(drop=True)


def exiting(signals: pd.DataFrame) -> pd.DataFrame:
    """Stocks with selling / exit events, strongest first."""
    s = signals[signals["down_events"] > 0]
    return s.sort_values(["down_score", "deal_net_value", "symbol"], ascending=[False, True, True]).reset_index(drop=True)


# ------------------------------------------------------------------ Telegram summary
def summary_lines(folder: Path | None = None, limit: int = 5) -> list[str]:
    """A few plain-English lines for the daily message ([] when nothing is cached). Never raises."""
    try:
        return _summary(folder, limit)
    except Exception:
        return []


def _who(investor, name) -> str:
    return _sv(investor) or _sv(name) or "?"


def _summary(folder: Path | None, limit: int) -> list[str]:
    deals, insider, flows = load_deals(folder), load_insider(folder), load_flows(folder)
    holdings, holders = load_holdings(folder), load_holders(folder)
    if deals.empty and insider.empty and flows.empty and holdings.empty:
        return []
    net = net_deals(deals, promoter_sets(holders, insider), share_counts(holdings))
    d_asof, i_asof = latest(deals, "date"), latest(insider, "disclosed")
    lines = [f"Smart money - NSE disclosures (deals of {_day_text(d_asof)}):" if d_asof
             else "Smart money - NSE disclosures:"]
    if len(flows):
        r = flows.iloc[-1]
        if _finite(r["fii_net_cr"]) or _finite(r["dii_net_cr"]):
            lines.append(f"FII/FPI net {_signed0(r['fii_net_cr'])} cr, DII net {_signed0(r['dii_net_cr'])} cr on "
                         f"{_day_text(r['date'])} (provisional, market-wide)")
    if d_asof:
        day = net[(net["date"] == d_asof) & ~net["round_trip"] & net["category"].isin(list(BIG_MONEY))]
        for side, title in (("BUY", "Big buys"), ("SELL", "Big sells")):
            x = day[day["side"] == side]
            x = x.assign(_a=x["net_value"].abs()).sort_values("_a", ascending=False).head(limit)
            items = [f"{s} ({_who(inv, c)} {_money(abs(v))})"
                     for s, inv, c, v in zip(x["symbol"], x["investor"], x["client"], x["net_value"])]
            if items:
                lines.append(f"{title}: " + ", ".join(items))
    if i_asof:
        x = insider[insider["is_market"] & (insider["side"] == "BUY")
                    & _on_or_after(insider["disclosed"], window(i_asof, 3))]
        x = x.sort_values("value", ascending=False, na_position="last").head(limit)
        items = [f"{s} ({_who(inv, p)} {_money(v)})"
                 for s, inv, p, v in zip(x["symbol"], x["investor"], x["person"], x["value"])]
        if items:
            lines.append("Promoter/insider market buys: " + ", ".join(items))
    anchor = max([x for x in (d_asof, i_asof) if x], default=None)
    if anchor:
        ev = events(net, insider, holdings, holders, window(anchor, 3))
        items = []
        for r in ev[ev["exit_kind"].isin(list(EXIT_KINDS))].head(limit).to_dict("records"):
            who = _who(r["investor"], r["who"])
            if r["exit_kind"] == "full_exit":
                items.append(f"{r['symbol']} ({who} sold all shares)")
            elif r["exit_kind"] == "below_1pct":
                items.append(f"{r['symbol']} ({who} now below 1%)")
            else:
                items.append(f"{r['symbol']} ({CATEGORY_LABELS.get(r['category'], r['category'])} sold out)")
        if items:
            lines.append("Exits: " + ", ".join(items))
    lines.append("Disclosed data, not a tip: big investors also lose money.")
    return lines
