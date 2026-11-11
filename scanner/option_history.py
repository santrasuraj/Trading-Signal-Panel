"""Daily index-option prices from NSE's F&O bhavcopy, for the options backtester (scanner/options_backtest.py).

One row per (day, underlying, expiry, strike, CE/PE): close, settlement price, open interest, volume, the
underlying's close and the lot size. Kept: NIFTY and BANKNIFTY, expiries within 70 days, strikes within 20% of the
underlying (what a strategy can trade); stored in data/fno/options_hist.parquet (a few MB a year).

The nightly F&O refresh (scanner/fno.py) adds each new day from the file it already downloads. `backfill` fetches
past days (about 1.2 MB each from nsearchives.nseindia.com, one a second): 500 trading days are ~2 years.
"""
from __future__ import annotations

import io
import time
import zipfile
from datetime import date, timedelta

import numpy as np
import pandas as pd

from . import fno, nse

UNDERLYINGS = ("NIFTY", "BANKNIFTY")
FILE = "options_hist.parquet"
MAX_DTE = 70
BAND = 0.20
COLS = ["date", "symbol", "expiry", "strike", "type", "close", "settle", "oi", "volume", "underlying", "lot"]


def path():
    return fno.folder() / FILE


def parse(content: bytes, day: date, unders=UNDERLYINGS) -> pd.DataFrame:
    with zipfile.ZipFile(io.BytesIO(content)) as z:
        raw = z.read(z.namelist()[0])
    df = pd.read_csv(io.BytesIO(raw), usecols=["TradDt", "FinInstrmTp", "TckrSymb", "XpryDt", "StrkPric", "OptnTp",
                                                "ClsPric", "SttlmPric", "OpnIntrst", "TtlTradgVol", "UndrlygPric",
                                                "NewBrdLotQty"])
    df = df[(df["FinInstrmTp"] == "IDO") & df["TckrSymb"].isin(unders)]
    if df.empty:
        return pd.DataFrame(columns=COLS)
    exp = pd.to_datetime(df["XpryDt"])
    dte = (exp - pd.Timestamp(day)).dt.days
    und = df["UndrlygPric"].astype(float)
    k = df["StrkPric"].astype(float)
    keep = (dte >= 0) & (dte <= MAX_DTE) & ((k / und - 1).abs() <= BAND)
    df, exp = df[keep], exp[keep]
    return pd.DataFrame({"date": pd.Timestamp(day), "symbol": df["TckrSymb"].astype(str).to_numpy(),
                         "expiry": exp.dt.normalize().to_numpy(), "strike": df["StrkPric"].astype(float).to_numpy(),
                         "type": df["OptnTp"].astype(str).to_numpy(), "close": df["ClsPric"].astype(float).to_numpy(),
                         "settle": df["SttlmPric"].astype(float).to_numpy(), "oi": df["OpnIntrst"].astype(float).to_numpy(),
                         "volume": df["TtlTradgVol"].astype(float).to_numpy(),
                         "underlying": df["UndrlygPric"].astype(float).to_numpy(),
                         "lot": df["NewBrdLotQty"].astype(float).to_numpy()})[COLS]


def load(symbol: str | None = None) -> pd.DataFrame:
    p = path()
    if not p.exists():
        return pd.DataFrame(columns=COLS)
    df = pd.read_parquet(p, filters=[("symbol", "==", symbol)] if symbol else None)
    df["date"] = pd.to_datetime(df["date"])
    df["expiry"] = pd.to_datetime(df["expiry"])
    return df


def days_stored() -> list[date]:
    p = path()
    if not p.exists():
        return []
    d = pd.read_parquet(p, columns=["date"])["date"]
    return sorted(set(pd.to_datetime(d).dt.date))


def add_day(content: bytes, day: date) -> int:
    """Store one day's rows from an F&O bhavcopy already downloaded (replaces that day if stored)."""
    new = parse(content, day)
    if new.empty:
        return 0
    with fno._write_lock():
        p = path()
        old = pd.read_parquet(p) if p.exists() else None
        if old is not None:
            old = old[pd.to_datetime(old["date"]).dt.date != day]
        out = new if old is None or old.empty else pd.concat([old, new], ignore_index=True)
        fno._write_parquet(out.sort_values(["date", "symbol", "expiry", "strike", "type"]).reset_index(drop=True), p)
    return len(new)


def backfill(days: int = 500, log=print, today: date | None = None, get=None, pause: float = 1.0,
             stop=lambda: False, progress=lambda done, total: None) -> dict:
    """Fetch the last `days` trading days not stored yet, newest first. Never raises for NSE problems."""
    get = get or nse._get_bytes
    today = today or date.today()
    have = set(days_stored())
    todo = [d for d in reversed(fno._trading_days(days, today - timedelta(days=1))) if d not in have]
    rep = {"wanted": len(todo), "added": 0, "missing": [], "errors": []}
    for i, d in enumerate(todo):
        if stop():
            break
        try:
            code, body = get(fno.FO_URL.format(d=d))
            if code != 200:
                rep["missing"].append(d.isoformat())
            else:
                rep["added"] += 1 if add_day(body, d) else 0
        except Exception as e:
            rep["errors"].append(f"{d}: {type(e).__name__}: {e}")
        progress(i + 1, len(todo))
        if i % 25 == 24:
            log(f"  option history: {i + 1} of {len(todo)} days")
        time.sleep(pause)
    return rep


def summary() -> dict:
    p = path()
    if not p.exists():
        return {"days": 0, "first": None, "last": None, "symbols": [], "mb": 0}
    d = pd.read_parquet(p, columns=["date", "symbol"])
    dd = pd.to_datetime(d["date"])
    return {"days": int(dd.dt.date.nunique()), "first": dd.min().date().isoformat(), "last": dd.max().date().isoformat(),
            "symbols": sorted(d["symbol"].unique().tolist()), "mb": round(p.stat().st_size / 1e6, 1)}


def nearest_strike(strikes: np.ndarray, target: float) -> float:
    return float(strikes[np.argmin(np.abs(strikes - target))])
