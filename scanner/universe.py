"""Which stocks to scan: official NSE index constituent lists (cached for a week)."""
from __future__ import annotations

import io
import time

import pandas as pd
import requests

from .settings import DATA_DIR

INDEX_FILES = {
    "nifty50": "ind_nifty50list.csv",
    "nifty100": "ind_nifty100list.csv",
    "nifty200": "ind_nifty200list.csv",
    "nifty500": "ind_nifty500list.csv",
    "totalmarket": "ind_niftytotalmarket_list.csv",   # Nifty 500 + Microcap 250: industries for ~750 stocks
}
SOURCES = [
    "https://archives.nseindia.com/content/indices/{file}",
    "https://www.niftyindices.com/IndexConstituent/{file}",
]
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                         "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"}
CACHE_DAYS = 7
EXPECTED_SIZE = {"nifty50": 50, "nifty100": 100, "nifty200": 200, "nifty500": 500, "totalmarket": 750}

# Used only if the NSE list cannot be downloaded and nothing is cached.
FALLBACK_NIFTY50 = [
    "ADANIENT", "ADANIPORTS", "APOLLOHOSP", "ASIANPAINT", "AXISBANK", "BAJAJ-AUTO", "BAJFINANCE",
    "BAJAJFINSV", "BEL", "BHARTIARTL", "CIPLA", "COALINDIA", "DRREDDY", "EICHERMOT", "GRASIM",
    "HCLTECH", "HDFCBANK", "HDFCLIFE", "HINDALCO", "HINDUNILVR", "ICICIBANK", "INFY", "ITC",
    "JSWSTEEL", "KOTAKBANK", "LT", "M&M", "MARUTI", "NESTLEIND", "NTPC", "ONGC", "POWERGRID",
    "RELIANCE", "SBILIFE", "SBIN", "SUNPHARMA", "TATACONSUM", "TATASTEEL", "TCS", "TECHM",
    "TITAN", "TRENT", "ULTRACEMCO", "WIPRO",
]


def _normalise(raw: pd.DataFrame) -> pd.DataFrame:
    raw.columns = [c.strip() for c in raw.columns]
    df = pd.DataFrame({
        "symbol": raw["Symbol"].astype(str).str.strip().str.upper(),
        "company": raw.get("Company Name", raw["Symbol"]).astype(str).str.strip(),
        "industry": raw.get("Industry", pd.Series([""] * len(raw))).astype(str).str.strip(),
    })
    df = df[(df["symbol"] != "") & ~df["symbol"].str.startswith("DUMMY")]  # NSE placeholders for demergers
    return df.drop_duplicates("symbol").reset_index(drop=True)


def get_universe(name: str) -> tuple[pd.DataFrame, str]:
    """Return (DataFrame[symbol, company, industry], note)."""
    name = (name or "nifty500").lower()
    file = INDEX_FILES.get(name, INDEX_FILES["nifty500"])
    cache = DATA_DIR / f"universe_{name}.csv"

    if cache.exists() and time.time() - cache.stat().st_mtime < CACHE_DAYS * 86400:
        return pd.read_csv(cache, dtype=str).fillna(""), f"{name.upper()} ({'cached list'})"

    for url in SOURCES:
        try:
            r = requests.get(url.format(file=file), headers=HEADERS, timeout=20)
            r.raise_for_status()
            df = _normalise(pd.read_csv(io.StringIO(r.text)))
            if len(df) >= 0.9 * EXPECTED_SIZE.get(name, 50):  # reject truncated lists
                df.to_csv(cache, index=False)
                return df, f"{name.upper()} ({len(df)} stocks, fresh from NSE)"
        except Exception:
            continue

    if cache.exists():
        return pd.read_csv(cache, dtype=str).fillna(""), f"{name.upper()} (old cached list - NSE download failed)"
    df = pd.DataFrame({"symbol": FALLBACK_NIFTY50, "company": FALLBACK_NIFTY50, "industry": ""})
    return df, "Built-in NIFTY 50 list (NSE download failed)"


def industry_map() -> dict[str, str]:
    """symbol -> NSE industry for as many stocks as NSE's lists cover (Nifty Total Market: ~750). NSE
    publishes industries only for today's index members, so companies that have since dropped out of
    every index (or were delisted) have none - see the industry coverage note on sector rotation."""
    out: dict[str, str] = {}
    for name in ("totalmarket", "nifty500"):
        df, _ = get_universe(name)
        if name == "totalmarket" and len(df) < 0.9 * EXPECTED_SIZE["totalmarket"]:
            continue                                     # the NIFTY 50 fallback: no industries
        out.update({s: i for s, i in zip(df["symbol"], df["industry"]) if i})
    return out
