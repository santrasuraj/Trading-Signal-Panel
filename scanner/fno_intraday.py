"""Live F&O positioning during the session, from NSE's OI-spurts feed:

  www.nseindia.com/api/live-analysis-oi-spurts-underlyings    every F&O underlying (~224): today's open interest
                                                              of ALL its futures and options contracts, yesterday's,
                                                              the change, contracts traded, and the spot (in whole
                                                              rupees), stamped with NSE's own time

This is not the end-of-day futures table (fno.py, NSE's F&O bhavcopy after the close): live OI here counts options
too, so it moves far more than futures OI - an expiry week's option writing can add 30% to an index's OI in a day.
A build-up therefore needs a MIN_OI_PCT change. Prices come from the caller (FYERS real time when logged in, else
Yahoo ~15 min delayed); the feed's rounded spot only fills in for indices. Network only in fetch(); positioning,
not a signal.

NSE keeps no intraday OI history and live_oi.json is overwritten by each fetch, so every snapshot fetched in market
hours is also appended to data/fno/oi_history/<YYYY-MM>.parquet (append_history): what the OI build-up backtest
(scanner/intraday/oi_buildup.py) runs on.
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from . import fno
from . import smart_money as sm
from .settings import IST

URL = sm.API + "live-analysis-oi-spurts-underlyings"
PAGE = "https://www.nseindia.com/market-data/oi-spurts"
LIVE_NAME = "live_oi.json"
MIN_OI_PCT = 5.0             # live OI includes options (options.py uses 5% too); futures-only EOD uses 2%
MIN_PRICE_PCT = 0.0          # any move counts for the direction (the OI change is the filter)
HISTORY_NAME = "oi_history"  # data/fno/oi_history/<YYYY-MM>.parquet
SESSION = ((9, 15), (15, 30))                     # a snapshot is kept when fetched (and stamped by NSE) inside these
HISTORY_COLS = ["fetched", "ts", "symbol", "oi", "oi_chg", "price"]
HISTORY_LOCK_TIMEOUT_S = 60.0


def _time(s: str | None) -> str | None:
    try:
        return datetime.strptime(str(s).strip(), "%d-%b-%Y %H:%M:%S").replace(tzinfo=IST).isoformat(timespec="seconds")
    except (TypeError, ValueError):
        return None


def _day(s: str | None) -> str | None:
    try:
        return datetime.strptime(str(s).strip(), "%d-%b-%Y").date().isoformat()
    except (TypeError, ValueError):
        return None


def _f(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v and abs(v) != float("inf") else None


def parse(payload: dict) -> dict | None:
    rows = (payload or {}).get("data") if isinstance(payload, dict) else None
    if not isinstance(rows, list) or not rows:
        return None
    out = []
    for r in rows:
        sym = str(r.get("symbol") or "").strip().upper()
        oi, prev = _f(r.get("latestOI")), _f(r.get("prevOI"))
        if not sym or oi is None:
            continue
        chg = _f(r.get("changeInOI"))
        out.append({"symbol": sym, "oi": oi, "prev_oi": prev, "oi_chg": chg if chg is not None else (oi - prev if prev else None),
                    "oi_chg_pct": round((oi / prev - 1) * 100, 2) if prev else None,
                    "volume": _f(r.get("volume")), "spot_rounded": _f(r.get("underlyingValue"))})
    return {"nse_time": _time(payload.get("timestamp")), "trade_date": _day(payload.get("currTradingDate")),
            "prev_date": _day(payload.get("prevTradingDate")), "rows": out, "source": PAGE}


def classify(price_chg_pct: float | None, oi_chg_pct: float | None, min_oi_pct: float = MIN_OI_PCT) -> str | None:
    if price_chg_pct is None or oi_chg_pct is None or abs(oi_chg_pct) < min_oi_pct:
        return None
    up = price_chg_pct > MIN_PRICE_PCT
    if oi_chg_pct > 0:
        return "long_buildup" if up else "short_buildup"
    return "short_covering" if up else "long_unwinding"


def fetch() -> tuple[dict | None, str | None]:
    """(parsed feed, error). Never raises."""
    sm._reset_api()
    code, body = sm._fetch(URL, None, api=True, referer=PAGE)
    if code != 200 or not body:
        return None, f"NSE OI-spurts feed: HTTP {code}"
    try:
        d = parse(json.loads(body))
    except ValueError:
        return None, "NSE OI-spurts feed: not JSON (NSE may have changed it)"
    if not d or not d["rows"]:
        return None, "NSE OI-spurts feed: no rows"
    return d, None


def save(view: dict) -> None:
    fno.FNO_DIR.mkdir(parents=True, exist_ok=True)
    sm._save_json(view, fno.FNO_DIR / LIVE_NAME)


def load() -> dict | None:
    try:
        return json.loads((fno.FNO_DIR / LIVE_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


# ------------------------------------------------------------------------------------------- intraday OI history
def history_dir() -> Path:
    return fno.FNO_DIR / HISTORY_NAME


def _empty_history() -> pd.DataFrame:
    return pd.DataFrame({"fetched": pd.Series(dtype="datetime64[s]"), "ts": pd.Series(dtype="datetime64[s]"),
                         "symbol": pd.Series(dtype="category"), "oi": pd.Series(dtype="int64"),
                         "oi_chg": pd.Series(dtype="Int64"), "price": pd.Series(dtype="float32")})


def _ist_naive(s) -> pd.Timestamp | None:
    """An ISO time (with or without +05:30) as a naive IST time to the second, like the 5-minute bars' ts; None if bad."""
    try:
        t = pd.Timestamp(s)
    except (TypeError, ValueError):
        return None
    if t is pd.NaT or pd.isna(t):
        return None
    if t.tzinfo is not None:
        t = t.tz_convert(IST).tz_localize(None)
    return t.floor("s")


def _in_session(t: pd.Timestamp) -> bool:
    return SESSION[0] <= (t.hour, t.minute) <= SESSION[1]


def snapshot_frame(view: dict) -> pd.DataFrame:
    """One fetched feed (the dict save() writes: parse() + prices + fetched_at) as history rows: when the app fetched it,
    NSE's time, symbol, open interest, its change since yesterday and the price the app had then (the FYERS / Yahoo
    quote when it is from today, else NSE's rounded spot). Empty unless it was fetched in market hours on its own trading
    day (before NSE rolls the feed over, a 09:15 fetch still shows yesterday)."""
    v = view or {}
    ts, fetched = _ist_naive(v.get("nse_time")), _ist_naive(v.get("fetched_at") or v.get("nse_time"))
    day = str(v.get("trade_date") or "")[:10]
    if ts is None or fetched is None or not day or not v.get("rows") \
            or ts.date().isoformat() != day or fetched.date().isoformat() != day \
            or not (_in_session(ts) and _in_session(fetched)):
        return _empty_history()
    fetched = max(fetched, ts)                    # this PC's clock a few seconds behind NSE's: known from NSE's time
    prices = v.get("prices") or {}
    sym, oi, chg, px = [], [], [], []
    for r in v["rows"]:
        s, o = str(r.get("symbol") or "").strip().upper(), _f(r.get("oi"))
        if not s or o is None:
            continue
        q = prices.get(s) or {}
        p = (_f(q.get("price")) if str(q.get("time") or "")[:10] == day else None) or _f(r.get("spot_rounded"))
        c = _f(r.get("oi_chg"))
        sym.append(s)
        oi.append(int(round(o)))
        chg.append(np.nan if c is None else c)
        px.append(np.nan if p is None else p)
    if not sym:
        return _empty_history()
    n = len(sym)
    return pd.DataFrame({"fetched": np.full(n, fetched.to_datetime64()).astype("datetime64[s]"),
                         "ts": np.full(n, ts.to_datetime64()).astype("datetime64[s]"),
                         "symbol": pd.Categorical(sym), "oi": np.asarray(oi, dtype="int64"),
                         "oi_chg": pd.array(np.round(chg), dtype="Int64"), "price": np.asarray(px, dtype="float32")})


def _symbols(*frames: pd.DataFrame) -> list[pd.DataFrame]:
    """The frames with one shared, sorted symbol category (they then concatenate without turning symbols into text)."""
    cats = sorted(set().union(*(set(f["symbol"].astype("category").cat.categories.astype(str)) for f in frames)))
    return [f.assign(symbol=f["symbol"].astype("category").cat.set_categories(cats)) for f in frames]


def _tidy(df: pd.DataFrame) -> pd.DataFrame:
    """One row per (symbol, NSE time) - the first fetch of it, when the app first knew it - sorted by symbol, then time."""
    (df,) = _symbols(df)
    code, ts = df["symbol"].cat.codes.to_numpy(), df["ts"].to_numpy()
    order = np.lexsort((df["fetched"].to_numpy(), ts, code))
    code, ts = code[order], ts[order]
    keep = np.r_[True, (code[1:] != code[:-1]) | (ts[1:] != ts[:-1])]
    return df.iloc[order[keep]].reset_index(drop=True).astype(
        {"oi": "int64", "oi_chg": "Int64", "price": "float32", "fetched": "datetime64[s]", "ts": "datetime64[s]"}
    )[HISTORY_COLS]


def _write_history(df: pd.DataFrame, path: Path) -> None:
    """Written to a temporary file and swapped in (a reader or a crash never sees half a file). Rows sorted by symbol
    then time, open interest and times delta-coded: each symbol's OI moves a little between snapshots, so a month of
    5-minute snapshots of ~220 underlyings stays at about 2 MB (the 5-minute bars take ~3.7 MB a month)."""
    import pyarrow as pa
    import pyarrow.parquet as pq
    from .intraday.data import _replace
    tmp = path.with_name(f"{path.stem}.{os.getpid()}.tmp")
    delta = "DELTA_BINARY_PACKED"
    pq.write_table(pa.Table.from_pandas(df, preserve_index=False), tmp, compression="zstd", use_dictionary=["symbol"],
                   column_encoding={"fetched": delta, "ts": delta, "oi": delta, "oi_chg": delta,
                                    "price": "BYTE_STREAM_SPLIT"})
    _replace(tmp, path)


def append_history(view: dict) -> int:
    """Append one fetched snapshot (see snapshot_frame) to data/fno/oi_history/<YYYY-MM>.parquet: read-merge-write under
    a lock (the web server and the 5-minute signals job both fetch), then an atomic swap (_write_history). A snapshot NSE
    has not updated since the last fetch adds nothing. Returns the rows added (0 outside market hours)."""
    from .intraday.data import FileLock
    rows = snapshot_frame(view)
    if rows.empty:
        return 0
    d = history_dir()
    d.mkdir(parents=True, exist_ok=True)
    ts = rows["ts"].iloc[0]
    path = d / f"{ts:%Y-%m}.parquet"
    with FileLock(d / ".save.lock", timeout=HISTORY_LOCK_TIMEOUT_S):
        old = pd.read_parquet(path) if path.exists() else _empty_history()
        seen = set(old.loc[old["ts"] == ts, "symbol"].astype(str))
        rows = rows[~rows["symbol"].astype(str).isin(seen)]
        if rows.empty:
            return 0
        _write_history(_tidy(pd.concat(_symbols(old, rows), ignore_index=True)), path)
    return int(len(rows))


def load_history(start=None, end=None) -> pd.DataFrame:
    """Stored snapshots with NSE's time between start and end (inclusive dates), sorted by fetch time; with oi_chg_pct
    computed as the live feed does (change / yesterday's OI, 2 decimals)."""
    d = history_dir()
    s = pd.Timestamp(start).normalize() if start is not None else None
    e = pd.Timestamp(end).normalize() + pd.Timedelta(days=1) if end is not None else None
    parts = []
    for p in sorted(d.glob("????-??.parquet")) if d.exists() else []:
        m0 = pd.Timestamp(p.stem + "-01")
        if (s is not None and m0 + pd.offsets.MonthBegin(1) <= s) or (e is not None and m0 >= e):
            continue
        try:
            parts.append(pd.read_parquet(p).astype({"symbol": str}))
        except Exception:        # a damaged month must not stop the others
            continue
    df = pd.concat(parts, ignore_index=True) if parts else _empty_history().astype({"symbol": str})
    if s is not None:
        df = df[df["ts"] >= s]
    if e is not None:
        df = df[df["ts"] < e]
    chg = df["oi_chg"].astype("float64")
    prev = df["oi"] - chg
    df = df.assign(oi_chg=chg, oi_chg_pct=((df["oi"] / prev.where(prev > 0) - 1) * 100).round(2))
    return df.sort_values(["fetched", "symbol"], kind="stable").reset_index(drop=True)
