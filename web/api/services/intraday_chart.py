"""Intraday candles for the Chart page (GET /api/chart/{symbol}/intraday): 1, 5 or 15 minutes, last N sessions.

1-minute bars come from the live FYERS feed only (data/intraday/live/1m_*.parquet today, the 1m store for the days
the live service ran): the symbols it streamed, from the day it started keeping them.

Bars come from the intraday store (data/intraday/bars/5m: FYERS history and the archived live feed, Yahoo for the
last 60 days before that), today's completed live bars (data/intraday/live/YYYYMMDD.parquet) and the bar still
forming (forming.json), newest source winning per bar. 15-minute bars are built from the 5-minute ones (09:15,
09:30, ...). VWAP restarts every session. Times are IST wall-clock seconds (the chart shows them as they are).
The store covers the ~150 most liquid F&O stocks and whatever the live feed streams; anything else has no bars.
"""
from __future__ import annotations

import json
from datetime import timedelta

import numpy as np
import pandas as pd

from scanner.intraday import data as idata
from scanner.intraday.live import FORMING_1M_NAME, FORMING_FILE_NAME, live_dir, live_file, live_file_1m
from scanner.intraday.quote_hub import to_ticker

from ..errors import ApiException
from ..paths import P
from ..util import today_ist

TFS = {"1m": "1min", "5m": "5min", "15m": "15min"}
MAX_DAYS = {"1m": 5, "5m": 20, "15m": 20}
NOTE = ("Intraday candles from the FYERS feed and history (Yahoo fills older days, about 15 minutes late while it "
        "was live). The last candle may still be forming. VWAP restarts each session.")


def _forming(symbol: str, one_minute: bool = False) -> pd.DataFrame:
    try:
        name = FORMING_1M_NAME if one_minute else FORMING_FILE_NAME
        info = json.loads((live_dir(P.data / "intraday") / name).read_text(encoding="utf-8"))
    except Exception:
        return idata.empty_bars()
    b = (info.get("bars") or {}).get(to_ticker(symbol))
    if not b:
        return idata.empty_bars()
    try:
        row = {"ts": pd.Timestamp(b["ts"]), "symbol": symbol, "open": float(b["open"]), "high": float(b["high"]),
               "low": float(b["low"]), "close": float(b["close"]), "volume": float(b.get("volume") or 0),
               "flags": idata.FLAG_FORMING, "source": "fyers_ws"}
    except (KeyError, TypeError, ValueError):
        return idata.empty_bars()
    if row["ts"].date() != today_ist():
        return idata.empty_bars()
    return pd.DataFrame([row])


def bars(symbol: str, days: int, one_minute: bool = False) -> pd.DataFrame:
    sym = symbol.upper()
    today = today_ist()
    stored = idata.IntradayStore(P.intraday_bars).load("1m" if one_minute else "5m", [sym],
                                                       start=today - timedelta(days=days * 2 + 10))
    parts = [stored]
    p = live_file_1m(P.data / "intraday") if one_minute else live_file(P.data / "intraday")
    if p.exists():
        try:
            live = pd.read_parquet(p)
            parts.append(live[live["symbol"].astype(str) == sym])
        except Exception:
            pass                                          # mid-write: the stored bars still answer
    parts.append(_forming(sym, one_minute))
    parts = [x for x in parts if len(x)]
    if not parts:
        return idata.empty_bars()
    df = pd.concat([x.astype({"symbol": str, "source": str}) for x in parts], ignore_index=True)
    df["ts"] = pd.to_datetime(df["ts"])
    df = df.sort_values("ts").drop_duplicates("ts", keep="last")       # live / forming win over stored
    sessions = sorted(df["ts"].dt.normalize().unique())[-days:]
    return df[df["ts"].dt.normalize().isin(sessions)].reset_index(drop=True)


def resample(df: pd.DataFrame, tf: str) -> pd.DataFrame:
    if tf in ("1m", "5m") or df.empty:
        return df
    g = df.set_index("ts").groupby(pd.Grouper(freq=TFS[tf]))
    out = pd.DataFrame({"open": g["open"].first(), "high": g["high"].max(), "low": g["low"].min(),
                        "close": g["close"].last(), "volume": g["volume"].sum(),
                        "flags": g["flags"].max()}).dropna(subset=["open"])
    return out.reset_index()


def vwap(df: pd.DataFrame) -> list[float | None]:
    if df.empty:
        return []
    tp = (df["high"] + df["low"] + df["close"]) / 3
    day = df["ts"].dt.normalize()
    pv = (tp * df["volume"]).groupby(day).cumsum()
    vol = df["volume"].groupby(day).cumsum()
    v = (pv / vol.replace(0, np.nan)).round(2)
    return [None if not np.isfinite(x) else float(x) for x in v.fillna(np.nan)]


def build(symbol: str, tf: str = "5m", days: int = 3) -> dict:
    if tf not in TFS:
        raise ApiException("VALIDATION", "tf must be 1m, 5m or 15m.")
    days = max(1, min(int(days), MAX_DAYS[tf]))
    raw = bars(symbol, days, one_minute=tf == "1m")
    if raw.empty and tf == "1m":
        raise ApiException("FEATURE_UNAVAILABLE", f"No 1-minute bars for {symbol.upper()} yet.",
                           "1-minute bars come from the live FYERS feed: they exist for the symbols it streams (the "
                           "screen's, your watchlists' and the most liquid F&O stocks) from the first session it "
                           "runs with this version, and are kept at each close. 5-minute bars go back further.",
                           {"feature": "intraday_chart"})
    if raw.empty:
        raise ApiException("FEATURE_UNAVAILABLE", f"No intraday bars for {symbol.upper()}.",
                           "Intraday candles cover the ~150 most liquid F&O stocks and the symbols the live feed streams "
                           "(add it to a watchlist: it is streamed from the next live session).",
                           {"feature": "intraday_chart"})
    df = resample(raw, tf)
    # IST wall-clock as epoch seconds: the chart library shows UTC, so 09:15 IST reads 09:15
    t = ((df["ts"] - pd.Timestamp("1970-01-01")) // pd.Timedelta(seconds=1)).astype("int64").tolist()
    r2 = lambda s: [round(float(x), 2) for x in s]  # noqa: E731
    src = sorted(set(raw["source"].astype(str)))
    return {"symbol": symbol.upper(), "tf": tf, "days": days,
            "sessions": sorted({d.date().isoformat() for d in df["ts"].dt.normalize()}),
            "bars": {"t": t, "o": r2(df["open"]), "h": r2(df["high"]), "l": r2(df["low"]), "c": r2(df["close"]),
                     "v": [float(x) for x in df["volume"]]},
            "vwap": vwap(df), "forming": bool(len(df) and int(df["flags"].iloc[-1]) & idata.FLAG_FORMING),
            "sources": src, "note": NOTE}
