"""Official NSE end-of-day files (free, public archives).

sec_bhavdata_full_DDMMYYYY.csv : every stock's official OHLC, volume, previous close and delivery %
                                 (NSE's archive has it from 30 Sep 2019)
cmDDMONYYYYbhav.csv.zip        : the older bhavcopy (same prices, no delivery %), used for days
                                 before that, and to complete a few full files that lack stocks
                                 (the archive ends in July 2024)
ind_close_all_DDMMYYYY.csv     : every NSE index (Nifty 50, India VIX, sector indices) OHLC

Files appear ~6-7 PM IST on trading days. Parsed days are cached under data/nse/ so each file is
downloaded only once. On holidays NSE serves the previous day's stock file, so the date inside the
file is always checked. PREV_CLOSE is the raw previous close: on a split/bonus ex-date it is NOT
adjusted (corporate.py supplies the factor).
"""
from __future__ import annotations

import io
import threading
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import numpy as np
import pandas as pd
import requests

from .settings import DATA_DIR

NSE_DIR = DATA_DIR / "nse"
NSE_DIR.mkdir(parents=True, exist_ok=True)
BHAV_URL = "https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{d}.csv"
CM_URL = "https://nsearchives.nseindia.com/content/historical/EQUITIES/{y}/{mon}/cm{dd}{mon}{y}bhav.csv.zip"
FULL_FROM = date(2019, 9, 30)   # first sec_bhavdata_full file in NSE's archive
CM_UNTIL = date(2024, 7, 8)     # the older bhavcopy archive ends here
INDEX_URL = "https://nsearchives.nseindia.com/content/indices/ind_close_all_{d}.csv"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/124.0 Safari/537.36",
    "Accept": "text/csv,*/*", "Referer": "https://www.nseindia.com/",
}
SERIES_PRIORITY = ("EQ", "BE", "BZ", "RR", "IV")  # equity, trade-to-trade, REITs, InvITs - best first
INDEX_NAMES = {"NIFTY 50": "NIFTY50", "INDIA VIX": "INDIAVIX", "NIFTY 500": "NIFTY500"}

_local = threading.local()


def _session() -> requests.Session:
    if not hasattr(_local, "s"):
        _local.s = requests.Session()
        _local.s.headers.update(HEADERS)
    return _local.s


def _get(url: str) -> tuple[int, str]:
    code, body = _get_bytes(url)
    return code, body.decode("utf-8", errors="replace") if body else ""


def _get_bytes(url: str) -> tuple[int, bytes]:
    for attempt in range(3):
        try:
            r = _session().get(url, timeout=20)
            return r.status_code, r.content if r.ok else b""
        except requests.RequestException:
            if attempt == 2:
                return -1, b""
    return -1, b""


def _num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s.astype(str).str.strip().replace({"-": None, "": None}), errors="coerce")


MIN_STOCK_ROWS = 1000   # a complete EQ bhavcopy has ~2,500+ rows; fewer means a truncated/blocked response


class DayFile:
    """Result of fetching one day.
    status: 'ok'      - official data for that day
            'holiday' - NSE served another day's file: no trading that day
            'missing' - not published (yet): 404
            'error'   - blocked / server error / unparsable: retry later, never treat as holiday"""

    def __init__(self, day: date, status: str, stocks: pd.DataFrame | None = None, indices: pd.DataFrame | None = None):
        self.day, self.status, self.stocks, self.indices = day, status, stocks, indices


class _OtherDay(Exception):
    pass


def _parse_stocks(text: str, day: date) -> pd.DataFrame:
    df = pd.read_csv(io.StringIO(text))
    df.columns = [c.strip() for c in df.columns]
    for c in ("SYMBOL", "SERIES", "DATE1"):
        df[c] = df[c].astype(str).str.strip()
    if pd.to_datetime(df["DATE1"].iloc[0], format="%d-%b-%Y").date() != day:
        raise _OtherDay()  # holiday: NSE served another day's file
    return _stock_rows(df, {"open": "OPEN_PRICE", "high": "HIGH_PRICE", "low": "LOW_PRICE", "close": "CLOSE_PRICE",
                            "volume": "TTL_TRD_QNTY", "prev_close": "PREV_CLOSE", "deliv_pct": "DELIV_PER"})


def _parse_cm(content: bytes, day: date) -> pd.DataFrame:
    """The older bhavcopy (cmDDMONYYYYbhav.csv inside a zip): same prices, no delivery %."""
    z = zipfile.ZipFile(io.BytesIO(content))
    df = pd.read_csv(z.open(z.namelist()[0]))
    df.columns = [c.strip() for c in df.columns]
    for c in ("SYMBOL", "SERIES", "TIMESTAMP"):
        df[c] = df[c].astype(str).str.strip()
    if pd.to_datetime(df["TIMESTAMP"].iloc[0], format="%d-%b-%Y").date() != day:
        raise _OtherDay()
    df["DELIV_PER"] = np.nan
    return _stock_rows(df, {"open": "OPEN", "high": "HIGH", "low": "LOW", "close": "CLOSE",
                            "volume": "TOTTRDQTY", "prev_close": "PREVCLOSE", "deliv_pct": "DELIV_PER"})


def _stock_rows(df: pd.DataFrame, cols: dict[str, str]) -> pd.DataFrame:
    """One row per symbol (best series first), numeric fields plus the series traded."""
    df = df[df["SERIES"].isin(SERIES_PRIORITY)].copy()
    df["_rank"] = df["SERIES"].map({s: i for i, s in enumerate(SERIES_PRIORITY)})
    df = df.sort_values("_rank").drop_duplicates("SYMBOL")
    out = pd.DataFrame({k: _num(df[v]) for k, v in cols.items()})
    out["series"] = df["SERIES"].values
    out.index = pd.Index(df["SYMBOL"].values, name="symbol")
    return out[out["close"] > 0]


def _parse_indices(text: str, day: date) -> pd.DataFrame:
    df = pd.read_csv(io.StringIO(text))
    df.columns = [c.strip() for c in df.columns]
    df["Index Name"] = df["Index Name"].astype(str).str.strip()
    if pd.to_datetime(df["Index Date"].astype(str).iloc[0], format="%d-%m-%Y").date() != day:
        raise _OtherDay()
    out = pd.DataFrame({
        "open": _num(df["Open Index Value"]), "high": _num(df["High Index Value"]),
        "low": _num(df["Low Index Value"]), "close": _num(df["Closing Index Value"]),
        "volume": _num(df["Volume"]).fillna(0),
    })
    out.index = pd.Index(df["Index Name"].values, name="index_name")
    return out[out["close"] > 0]


def _add_cm_rows(stocks: pd.DataFrame, day: date) -> pd.DataFrame:
    """NSE's full file lacks ~10% of the stocks on a few days (13 Apr 2020, 28 Sep 2020, 7 Mar 2022);
    the older bhavcopy of the same day has them (without delivery %)."""
    mon = day.strftime("%b").upper()
    code, body = _get_bytes(CM_URL.format(y=day.year, mon=mon, dd=day.strftime("%d")))
    if code != 200:
        return stocks
    try:
        cm = _parse_cm(body, day)
    except Exception:
        return stocks
    extra = cm[~cm.index.isin(stocks.index)]
    return pd.concat([stocks, extra]) if len(extra) else stocks


def _old(day: date) -> bool:
    return (date.today() - day).days > 2


def fetch_day(day: date, use_cache: bool = True) -> DayFile:
    tag = day.strftime("%Y%m%d")
    sp, ip = NSE_DIR / f"stocks_{tag}.parquet", NSE_DIR / f"indices_{tag}.parquet"
    if use_cache and sp.exists() and (ip.exists() or _old(day)):
        return DayFile(day, "ok", pd.read_parquet(sp), pd.read_parquet(ip) if ip.exists() else None)
    d = day.strftime("%d%m%Y")
    sources = []
    if day >= FULL_FROM:
        sources.append((lambda: _get(BHAV_URL.format(d=d)), _parse_stocks))
    if day < CM_UNTIL:   # older days, or a full file that is missing / carries another date
        mon = day.strftime("%b").upper()
        sources.append((lambda: _get_bytes(CM_URL.format(y=day.year, mon=mon, dd=day.strftime("%d"))), _parse_cm))
    status, stocks = "missing", None
    for n, (get, parse) in enumerate(sources):
        code, body = get()
        if code == 404:
            continue
        try:
            if code != 200:
                raise ValueError(code)
            stocks = parse(body, day)
            if len(stocks) >= MIN_STOCK_ROWS:
                break
        except _OtherDay:
            status = "holiday"   # NSE served another day's file: no trading that day
        except Exception:
            pass
        stocks = None
        status = "error" if status == "missing" else status
    if stocks is None:
        return DayFile(day, status)
    if n == 0 and len(sources) > 1:
        stocks = _add_cm_rows(stocks, day)
    ix_code, ix_text = _get(INDEX_URL.format(d=d))
    try:
        indices = _parse_indices(ix_text, day) if ix_code == 200 else None
    except Exception:
        indices = None
    if indices is None:
        # The index file is sometimes published a little later: wait for it on recent days so the
        # Nifty series has no holes; older days are cached with the stock file alone.
        if not _old(day):
            return DayFile(day, "missing", stocks, None)
        stocks.to_parquet(sp)
        return DayFile(day, "ok", stocks, None)
    stocks.to_parquet(sp)
    indices.to_parquet(ip)
    return DayFile(day, "ok", stocks, indices)


def fetch_days(days: list[date], workers: int = 4) -> dict[date, DayFile]:
    """Fetch several days in parallel (politely: a few connections at a time)."""
    if not days:
        return {}
    with ThreadPoolExecutor(max_workers=min(workers, len(days))) as ex:
        return dict(zip(days, ex.map(fetch_day, days)))


def index_row(day_file: DayFile, symbol: str) -> pd.Series | None:
    """Row for NIFTY50 / INDIAVIX (or any index by its NSE name) from a day's index file."""
    if day_file.indices is None:
        return None
    names = {v: k for k, v in INDEX_NAMES.items()}
    name = names.get(symbol, symbol).upper()
    idx = day_file.indices
    match = idx[idx.index.str.upper() == name]
    return match.iloc[0] if len(match) else None
