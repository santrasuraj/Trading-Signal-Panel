"""Implied-volatility history and IV rank / IV percentile for every F&O underlying (indices and ~220 stocks), from
NSE's daily F&O bhavcopy - what Sensibull or Opstra show next to an option chain.

Each trading day, per underlying: the expiry closest to TARGET_DTE days out with at least MIN_DTE days left, the strike
nearest the underlying, and the Black-76 implied volatility of its call and put closing prices (settlement price when
there was no trade) on the forward F = underlying x e^(rT); the day's IV is their average (one side alone when the other
can't be solved). Then, over the past year (LOOKBACK days):
  IV rank       = (IV today - lowest) / (highest - lowest)            0 = at the year's low, 100 = at its high
  IV percentile = share of the year's days with a lower IV            "IV is higher than on 80% of days"
Option sellers prefer a high rank (rich premiums), buyers a low one; neither says where the price goes.

Stored in data/fno/iv_hist.parquet (date, symbol, expiry, dte, spot, strike, iv): one row per underlying and day. The
nightly F&O refresh (fno.py) adds each new day from the file it already downloads; `backfill` fetches past days (about
1.3 MB each from nsearchives, one a second: a year is ~5 minutes)."""
from __future__ import annotations

import io
import math
import time
import zipfile
from datetime import date, timedelta

import numpy as np
import pandas as pd

from . import fno, nse
from .options import implied_vol

FILE = "iv_hist.parquet"
TARGET_DTE = 30
MIN_DTE = 7
LOOKBACK = 252
RISK_FREE = 0.065
COLS = ["date", "symbol", "expiry", "dte", "spot", "strike", "iv"]


def path():
    return fno.folder() / FILE


def day_iv(content: bytes, day: date, r: float = RISK_FREE) -> pd.DataFrame:
    """One day's at-the-money IV per underlying from an F&O bhavcopy (zip). IV as a percentage (15.2 = 15.2%)."""
    with zipfile.ZipFile(io.BytesIO(content)) as z:
        raw = z.read(z.namelist()[0])
    df = pd.read_csv(io.BytesIO(raw), usecols=["FinInstrmTp", "TckrSymb", "XpryDt", "StrkPric", "OptnTp", "ClsPric",
                                                "SttlmPric", "TtlTradgVol", "UndrlygPric"])
    df = df[df["FinInstrmTp"].isin(["IDO", "STO"])]
    if df.empty:
        return pd.DataFrame(columns=COLS)
    df = df.assign(expiry=pd.to_datetime(df["XpryDt"]).dt.normalize(), strike=df["StrkPric"].astype(float),
                   und=df["UndrlygPric"].astype(float), symbol=df["TckrSymb"].astype(str))
    df["dte"] = (df["expiry"] - pd.Timestamp(day)).dt.days
    df = df[(df["dte"] >= MIN_DTE) & (df["und"] > 0)]
    if df.empty:
        return pd.DataFrame(columns=COLS)
    traded = pd.to_numeric(df["TtlTradgVol"], errors="coerce").fillna(0) > 0
    close = pd.to_numeric(df["ClsPric"], errors="coerce")
    df["price"] = close.where(traded & (close > 0), pd.to_numeric(df["SttlmPric"], errors="coerce"))
    # per underlying: the expiry nearest TARGET_DTE (ties: the nearer one), then the strike nearest the underlying
    u = df[["symbol", "dte"]].drop_duplicates()
    u = u.assign(gap=(u["dte"] - TARGET_DTE).abs()).sort_values(["symbol", "gap", "dte"]).drop_duplicates("symbol")
    df = df.merge(u[["symbol", "dte"]], on=["symbol", "dte"])
    df = df.assign(gap=(df["strike"] - df["und"]).abs())
    atm = df.sort_values(["symbol", "gap", "strike"]).drop_duplicates("symbol")[["symbol", "strike"]]
    df = df.merge(atm, on=["symbol", "strike"]).reset_index(drop=True)
    df["side"] = df["OptnTp"].astype(object)
    w = df.pivot_table(index="symbol", columns="side", values="price", aggfunc="first")
    for c in ("CE", "PE"):
        if c not in w:
            w[c] = np.nan
    df = df.join(w[["CE", "PE"]], on="symbol")
    T_all = df["dte"].to_numpy(float) / 365.0
    # the forward from put-call parity at the ATM strike (as vol_svc does; it carries the futures basis), else spot x e^rT
    parity = df["strike"] + (df["CE"] - df["PE"]) * np.exp(r * T_all)
    df["F"] = parity.where((df["CE"] > 0) & (df["PE"] > 0), df["und"] * np.exp(r * T_all))
    iv = np.full(len(df), np.nan)
    for dte, idx in df.groupby("dte").groups.items():        # one vectorised solve per expiry (a handful a day)
        x = df.loc[idx]
        T = float(dte) / 365.0
        call = (x["side"].to_numpy() == "CE").astype(float)
        iv[np.asarray(idx)] = implied_vol(x["price"].to_numpy(float), x["F"].to_numpy(float), x["strike"].to_numpy(float),
                                          T, r, call)
    df["iv"] = iv * 100
    g = df.groupby("symbol", as_index=False).agg(expiry=("expiry", "first"), dte=("dte", "first"), spot=("und", "first"),
                                                 strike=("strike", "first"), iv=("iv", "mean"))
    g = g[g["iv"].notna()]
    g["iv"] = g["iv"].round(2)
    g.insert(0, "date", pd.Timestamp(day))
    return g[COLS].reset_index(drop=True)


def load(symbol: str | None = None) -> pd.DataFrame:
    p = path()
    if not p.exists():
        return pd.DataFrame(columns=COLS)
    df = pd.read_parquet(p, filters=[("symbol", "==", symbol)] if symbol else None)
    df["date"] = pd.to_datetime(df["date"])
    return df


def days_stored() -> list[date]:
    p = path()
    if not p.exists():
        return []
    return sorted(set(pd.to_datetime(pd.read_parquet(p, columns=["date"])["date"]).dt.date))


def add_day(content: bytes, day: date) -> int:
    """Store one day's IVs from an F&O bhavcopy already downloaded (replaces that day if stored)."""
    new = day_iv(content, day)
    if new.empty:
        return 0
    with fno._write_lock():
        p = path()
        old = pd.read_parquet(p) if p.exists() else None
        if old is not None:
            old = old[pd.to_datetime(old["date"]).dt.date != day]
        out = new if old is None or old.empty else pd.concat([old, new], ignore_index=True)
        cutoff = pd.Timestamp(day) - pd.Timedelta(days=int(LOOKBACK * 1.6))      # ~a year and a half kept
        out = out[pd.to_datetime(out["date"]) >= cutoff]
        fno._write_parquet(out.sort_values(["date", "symbol"]).reset_index(drop=True), p)
    return len(new)


def backfill(days: int = LOOKBACK, log=print, today: date | None = None, get=None, pause: float = 1.0,
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
            log(f"  IV history: {i + 1} of {len(todo)} days")
        time.sleep(pause)
    return rep


def _rank(s: pd.Series) -> dict:
    """IV now, its rank and percentile within the last LOOKBACK stored days."""
    s = s.dropna().tail(LOOKBACK)
    if s.empty:
        return {}
    now, lo, hi = float(s.iloc[-1]), float(s.min()), float(s.max())
    past = s.iloc[:-1]
    return {"iv": round(now, 2), "low": round(lo, 2), "high": round(hi, 2), "days": int(len(s)),
            "rank": round((now - lo) / (hi - lo) * 100, 1) if hi > lo else None,
            "percentile": round(float((past < now).mean() * 100), 1) if len(past) else None,
            "median": round(float(s.median()), 2)}


def ranks() -> pd.DataFrame:
    """Every underlying's latest IV, rank and percentile (one row each); empty without history."""
    df = load()
    if df.empty:
        return pd.DataFrame()
    last = df["date"].max()
    out = []
    for sym, x in df.sort_values("date").groupby("symbol"):
        if x["date"].iloc[-1] != last:
            continue                                   # no options on the latest day (left the F&O list)
        r = _rank(x.set_index("date")["iv"])
        if not r:
            continue
        chg = x["iv"].iloc[-1] - x["iv"].iloc[-6] if len(x) >= 6 else np.nan
        out.append({"symbol": sym, **r, "change_5d": round(float(chg), 2) if chg == chg else None,
                    "expiry": x["expiry"].iloc[-1].date().isoformat(), "dte": int(x["dte"].iloc[-1]),
                    "spot": float(x["spot"].iloc[-1]), "date": last.date().isoformat()})
    return pd.DataFrame(out)


def one(symbol: str) -> dict:
    df = load(symbol.upper())
    if df.empty:
        return {"symbol": symbol.upper(), "history": []}
    df = df.sort_values("date")
    r = _rank(df.set_index("date")["iv"])
    hist = df.tail(LOOKBACK)
    return {"symbol": symbol.upper(), **r, "date": df["date"].iloc[-1].date().isoformat(),
            "expiry": df["expiry"].iloc[-1].date().isoformat() if hasattr(df["expiry"].iloc[-1], "date") else str(df["expiry"].iloc[-1]),
            "dte": int(df["dte"].iloc[-1]),
            "history": [{"date": d.date().isoformat(), "iv": float(v)} for d, v in zip(hist["date"], hist["iv"])]}
