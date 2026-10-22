"""Official NSE end-of-day files (free, public archives).

sec_bhavdata_full_DDMMYYYY.csv : every stock's official OHLC, volume, previous close and delivery %
ind_close_all_DDMMYYYY.csv     : every NSE index (Nifty 50, India VIX, sector indices) OHLC

Files appear ~6-7 PM IST on trading days. Parsed days are cached under data/nse/ so each file is
downloaded only once. On holidays NSE serves the previous day's stock file, so the date inside the
file is always checked.
"""
from __future__ import annotations

import io
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import pandas as pd
import requests

from .settings import DATA_DIR

NSE_DIR = DATA_DIR / "nse"
NSE_DIR.mkdir(parents=True, exist_ok=True)
BHAV_URL = "https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{d}.csv"
INDEX_URL = "https://nsearchives.nseindia.com/content/indices/ind_close_all_{d}.csv"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/124.0 Safari/537.36",
    "Accept": "text/csv,*/*", "Referer": "https://www.nseindia.com/",
}
SERIES_PRIORITY = ("EQ", "BE", "BZ", "RR", "IV")  # equity, trade-to-trade, REITs, InvITs - best first
INDEX_NAMES = {"NIFTY 50": "NIFTY50", "INDIA VIX": "INDIAVIX"}

_local = threading.local()


def _session() -> requests.Session:
    if not hasattr(_local, "s"):
        _local.s = requests.Session()
        _local.s.headers.update(HEADERS)
    return _local.s


def _get(url: str) -> tuple[int, str]:
    for attempt in range(3):
        try:
            r = _session().get(url, timeout=20)
            return r.status_code, r.text if r.ok else ""
        except requests.RequestException:
            if attempt == 2:
                return -1, ""
    return -1, ""


def _num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s.astype(str).str.strip().replace({"-": None, "": None}), errors="coerce")


class DayFile:
    """Result of fetching one trading day. status: 'ok' | 'missing' (404 / other day's file) | 'error'."""

    def __init__(self, day: date, status: str, stocks: pd.DataFrame | None = None, indices: pd.DataFrame | None = None):
        self.day, self.status, self.stocks, self.indices = day, status, stocks, indices


def _parse_stocks(text: str, day: date) -> pd.DataFrame | None:
    df = pd.read_csv(io.StringIO(text))
    df.columns = [c.strip() for c in df.columns]
    for c in ("SYMBOL", "SERIES", "DATE1"):
        df[c] = df[c].astype(str).str.strip()
    if pd.to_datetime(df["DATE1"].iloc[0], format="%d-%b-%Y").date() != day:
        return None  # holiday: NSE served another day's file
    df = df[df["SERIES"].isin(SERIES_PRIORITY)].copy()
    df["_rank"] = df["SERIES"].map({s: i for i, s in enumerate(SERIES_PRIORITY)})
    df = df.sort_values("_rank").drop_duplicates("SYMBOL")
    out = pd.DataFrame({
        "open": _num(df["OPEN_PRICE"]), "high": _num(df["HIGH_PRICE"]), "low": _num(df["LOW_PRICE"]),
        "close": _num(df["CLOSE_PRICE"]), "volume": _num(df["TTL_TRD_QNTY"]),
        "prev_close": _num(df["PREV_CLOSE"]), "deliv_pct": _num(df["DELIV_PER"]),
    })
    out.index = pd.Index(df["SYMBOL"].values, name="symbol")
    return out[out["close"] > 0]


def _parse_indices(text: str, day: date) -> pd.DataFrame | None:
    df = pd.read_csv(io.StringIO(text))
    df.columns = [c.strip() for c in df.columns]
    df["Index Name"] = df["Index Name"].astype(str).str.strip()
    if pd.to_datetime(df["Index Date"].astype(str).iloc[0], format="%d-%m-%Y").date() != day:
        return None
    out = pd.DataFrame({
        "open": _num(df["Open Index Value"]), "high": _num(df["High Index Value"]),
        "low": _num(df["Low Index Value"]), "close": _num(df["Closing Index Value"]),
        "volume": _num(df["Volume"]).fillna(0),
    })
    out.index = pd.Index(df["Index Name"].values, name="index_name")
    return out[out["close"] > 0]


def fetch_day(day: date, use_cache: bool = True) -> DayFile:
    tag = day.strftime("%Y%m%d")
    sp, ip = NSE_DIR / f"stocks_{tag}.parquet", NSE_DIR / f"indices_{tag}.parquet"
    if use_cache and sp.exists() and ip.exists():
        return DayFile(day, "ok", pd.read_parquet(sp), pd.read_parquet(ip))
    d = day.strftime("%d%m%Y")
    st_code, st_text = _get(BHAV_URL.format(d=d))
    ix_code, ix_text = _get(INDEX_URL.format(d=d))
    if st_code == -1 or ix_code == -1 or st_code >= 500 or ix_code >= 500:
        return DayFile(day, "error")
    stocks = _parse_stocks(st_text, day) if st_code == 200 else None
    indices = _parse_indices(ix_text, day) if ix_code == 200 else None
    if stocks is None or indices is None or stocks.empty:
        return DayFile(day, "missing")
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
