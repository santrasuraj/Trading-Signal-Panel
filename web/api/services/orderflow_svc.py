"""Order flow for the intraday chart (GET /api/orderflow/{symbol}): per bar the buyer- and seller-initiated volume, the
delta (buy - sell) and the session's cumulative delta, and the session's volume profile (volume at each price level,
split buy / sell, with the point of control and the 70% value area). Built by the live service from the normal FYERS
feed (scanner/intraday/orderflow.py): today only, for the stocks it streamed; an estimate of who was the aggressor.
"""
from __future__ import annotations

import pandas as pd

from scanner.intraday.live import live_dir
from scanner.intraday.orderflow import file_name

from ..errors import ApiException
from ..paths import P
from ..util import today_ist

TFS = {"1m": "1min", "5m": "5min", "15m": "15min"}
NOTE = ("Estimated from the FYERS feed: each tick's new volume counted as bought at or above the ask, sold at or below "
        "the bid (in between, by the price move). Today only, for the stocks the live service streams. Exact "
        "tick-by-tick order flow needs FYERS Prime.")


def _load(sym: str, day) -> pd.DataFrame:
    p = live_dir(P.data / "intraday") / file_name(day)
    if not p.exists():
        return pd.DataFrame()
    try:
        df = pd.read_parquet(p, filters=[("symbol", "==", sym)])
    except Exception:
        return pd.DataFrame()                  # mid-write: the next refresh reads it
    return df


def flow(symbol: str, tf: str = "5m") -> dict:
    if tf not in TFS:
        raise ApiException("VALIDATION", "tf must be 1m, 5m or 15m.")
    sym = symbol.upper()
    day = today_ist()
    df = _load(sym, day)
    if df.empty:
        raise ApiException("FEATURE_UNAVAILABLE", f"No order flow for {sym} today.",
                           "It is recorded by the live service (market hours, after the FYERS login) for the stocks it "
                           "streams: open the stock's chart or add it to a watchlist.", {"feature": "orderflow"})
    df["ts"] = pd.to_datetime(df["ts"])
    bars = df.groupby(pd.Grouper(key="ts", freq=TFS[tf]))[["buy", "sell"]].sum()
    bars = bars[(bars["buy"] + bars["sell"]) > 0]
    delta = bars["buy"] - bars["sell"]
    epoch = ((bars.index - pd.Timestamp("1970-01-01")) // pd.Timedelta(seconds=1)).astype("int64").tolist()
    prof = df.groupby("price")[["buy", "sell"]].sum().sort_index()
    tot = prof["buy"] + prof["sell"]
    poc = float(tot.idxmax()) if len(tot) else None
    # value area: the levels around the point of control holding 70% of the volume
    va = set()
    if len(tot):
        order = tot.sort_values(ascending=False)
        acc, need = 0.0, 0.7 * float(tot.sum())
        for lvl, v in order.items():
            va.add(lvl)
            acc += float(v)
            if acc >= need:
                break
    return {"symbol": sym, "tf": tf, "date": day.isoformat(),
            "bars": {"t": epoch, "buy": bars["buy"].round(0).tolist(), "sell": bars["sell"].round(0).tolist(),
                     "delta": delta.round(0).tolist(), "cum_delta": delta.cumsum().round(0).tolist()},
            "profile": [{"price": float(p), "buy": float(r.buy), "sell": float(r.sell)} for p, r in prof.iterrows()],
            "poc": poc, "value_area": [min(va), max(va)] if va else None,
            "totals": {"buy": float(prof["buy"].sum()), "sell": float(prof["sell"].sum())}, "note": NOTE}
