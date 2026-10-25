"""Intraday bars for NSE equities: fetch (FYERS history / Yahoo), clean, store, load, and bars built
from FYERS WebSocket ticks.

Used by fyers_sync.py (FYERS backfill + daily archive), live.py (WebSocket bars) and run.py (the
intraday pipeline). Self-contained (pandas + numpy + pyarrow). FYERS calls go through
FyersProvider._call, i.e. the shared rate limiter in scanner/fyers_limits.py - never the raw SDK.
Research helpers not used by the pipeline (measurements in docs/intraday_data.md):
`fyers_backfill_budget`, `validate_against_daily`, `adjust_to_store`, `resample_bars`,
`IntradayStore.load_grid`, `completed_only` (the first two take scanner.store.load_store()'s dict).

Conventions
  * Timestamps are IST *naive* bar-START times (09:15 = the 09:15:00-09:19:59 bar for 5m).
  * Regular session 09:15-15:30. Slot grid is anchored at 09:15 (5m -> 75 slots, 15m -> 25,
    1m -> 375, 60m -> 7 with the last slot 15:15-15:30 only 15 minutes long).
  * Prices are stored AS TRADED (unadjusted). `adjust_to_store` derives per-(symbol, day)
    factors from the corporate-action-adjusted daily store when multi-day continuity matters.
  * Storage: <root>/<interval>/<YYYY-MM>.parquet, long format
        ts datetime64[ns], symbol category, open/high/low/close float64, volume float64,
        flags uint8, source category
    plus <root>/<interval>/manifest.json. Writes are atomic (tmp file + os.replace) and one process
    at a time (<root>/<interval>/.save.lock), so two writers never drop each other's bars.

Measured Yahoo quirks this module handles (Nifty 100, Jul-Oct 2026; see out_quality.json):
  * The 09:15 bar of 1m/5m/1h has volume 0 (opening minutes' volume is dropped) -> FLAG_VOL0_OPEN.
  * The last ~15 minutes are mostly missing and replaced by one flat O=H=L=C bar at the official
    closing price (15:28/15:29 for 1m, 15:25 or 15:15 for 5m, 15:15 for 15m/1h) -> FLAG_SYNTH_CLOSE.
  * The session open is the first continuous-trade price, not NSE's pre-open auction price.
"""
from __future__ import annotations

import json
import os
import time
import warnings
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

IST = timezone(timedelta(hours=5, minutes=30))
SESSION_OPEN = "09:15"
SESSION_CLOSE = "15:30"
SESSION_MINUTES = 375
COLS = ["open", "high", "low", "close", "volume"]

# flag bits (uint8)
FLAG_VOL0_OPEN = 1        # first bar of the day with zero volume (Yahoo drops opening volume)
FLAG_SYNTH_CLOSE = 2      # flat closing-price print replacing the real last minutes (Yahoo)
FLAG_OHLC_FIXED = 4       # high/low were widened to contain open/close
FLAG_JUMP = 8             # >10% move vs previous bar inside the session (check before trusting)
FLAG_FORMING = 16         # bar not yet complete when fetched (live) - never saved

INTERVAL_MIN = {"1m": 1, "2m": 2, "3m": 3, "5m": 5, "10m": 10, "15m": 15, "30m": 30, "60m": 60, "1h": 60}
# Yahoo: `period=Nd` counts TRADING sessions; start/end must lie within the last N CALENDAR days.
YAHOO_MAX_PERIOD = {"1m": "8d", "2m": "60d", "5m": "60d", "15m": "60d", "30m": "60d", "60m": "730d", "1h": "730d"}
YAHOO_MAX_CAL_DAYS = {"1m": 30, "2m": 60, "5m": 60, "15m": 60, "30m": 60, "60m": 730, "1h": 730}
FYERS_RES = {"1m": "1", "2m": "2", "3m": "3", "5m": "5", "10m": "10", "15m": "15", "30m": "30", "60m": "60", "1h": "60"}
FYERS_MAX_DAYS_PER_CALL = 100


def norm_interval(interval: str) -> str:
    iv = interval.lower().strip()
    iv = {"1": "1m", "5": "5m", "15": "15m", "60": "60m", "1h": "60m"}.get(iv, iv)
    if iv not in INTERVAL_MIN:
        raise ValueError(f"unsupported interval {interval!r}")
    return iv


def session_slots(interval: str) -> pd.Index:
    """Bar start times ('HH:MM') of a full regular session for `interval`."""
    step = INTERVAL_MIN[norm_interval(interval)]
    mins = np.arange(0, SESSION_MINUTES, step)
    return pd.Index([f"{(555 + m) // 60:02d}:{(555 + m) % 60:02d}" for m in mins])


def empty_bars() -> pd.DataFrame:
    return pd.DataFrame({"ts": pd.Series([], dtype="datetime64[ns]"), "symbol": pd.Series([], dtype="object"),
                         **{c: pd.Series([], dtype=float) for c in COLS},
                         "flags": pd.Series([], dtype="uint8"), "source": pd.Series([], dtype="object")})


# ---------------------------------------------------------------------------------------------
# Yahoo
# ---------------------------------------------------------------------------------------------
def _yahoo_long(data: pd.DataFrame | None, tickers: list[str]) -> pd.DataFrame:
    if data is None or data.empty:
        return empty_bars()
    parts = []
    for t in tickers:
        if isinstance(data.columns, pd.MultiIndex):
            if t not in data.columns.get_level_values(0):
                continue
            sub = data[t]
        else:
            sub = data
        sub = sub.rename(columns=lambda c: str(c).lower())
        if not set(COLS).issubset(sub.columns):
            continue
        sub = sub[COLS].dropna(subset=["close"])
        if sub.empty:
            continue
        idx = pd.DatetimeIndex(sub.index)
        idx = idx.tz_convert("Asia/Kolkata").tz_localize(None) if idx.tz is not None else idx
        parts.append(pd.DataFrame({"ts": idx.values, "symbol": t.removesuffix(".NS"),
                                   **{c: sub[c].to_numpy(float) for c in COLS}}))
    if not parts:
        return empty_bars()
    df = pd.concat(parts, ignore_index=True)
    df["flags"] = np.uint8(0)
    df["source"] = "yahoo"
    return df


def _yf_download(tickers, **kw) -> pd.DataFrame | None:
    import yfinance as yf
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            return yf.download(tickers, group_by="ticker", auto_adjust=False, progress=False,
                               threads=True, prepost=False, timeout=30, **kw)
        except Exception:
            return None


def fetch_yahoo_intraday(symbols: list[str], interval: str = "5m", days: int | None = None,
                         batch: int = 100, log=print) -> pd.DataFrame:
    """Raw Yahoo intraday bars (long format, IST naive) for NSE symbols ('RELIANCE', not 'RELIANCE.NS').

    days = number of TRADING sessions wanted (default: the maximum Yahoo serves for `interval`:
    1m 8, 5m/15m 60, 60m ~727). 1m deeper than 8 sessions is fetched in 7-calendar-day windows
    within the last 30 calendar days (~20 sessions). Symbols with too little history for the
    `period` form (recent listings, e.g. HYUNDAI on 1h/730d) are retried with start/end.
    Output is NOT cleaned - pass it to clean_bars().
    """
    iv = norm_interval(interval)
    yiv = "60m" if iv == "60m" else iv
    maxp = int(YAHOO_MAX_PERIOD[yiv].rstrip("d"))
    tickers = [f"{s}.NS" for s in symbols]
    out = []
    if iv == "1m" and days and days > maxp:
        end = datetime.now(IST).date() + timedelta(days=1)
        start_lim = end - timedelta(days=YAHOO_MAX_CAL_DAYS["1m"] - 1)
        s = start_lim
        while s < end:
            e = min(s + timedelta(days=7), end)
            for k in range(0, len(tickers), batch):
                out.append(_yahoo_long(_yf_download(tickers[k:k + batch], start=s.isoformat(), end=e.isoformat(),
                                                    interval="1m"), tickers[k:k + batch]))
            s = e
    else:
        n = min(days or maxp, maxp)
        for k in range(0, len(tickers), batch):
            chunk = tickers[k:k + batch]
            got = _yahoo_long(_yf_download(chunk, period=f"{n}d", interval=yiv), chunk)
            out.append(got)
            have = set(got["symbol"].unique())          # once, not per ticker (Arrow strings iterate slowly)
            missing = [t for t in chunk if t.removesuffix(".NS") not in have]
            if missing:   # young listings: period form fails, start/end within the calendar limit works
                start = datetime.now(IST).date() - timedelta(days=YAHOO_MAX_CAL_DAYS[yiv] - 1)
                again = _yahoo_long(_yf_download(missing, start=start.isoformat(), interval=yiv), missing)
                out.append(again)
                still = sorted(set(m.removesuffix(".NS") for m in missing) - set(again["symbol"].unique()))
                if still and log:
                    log(f"yahoo {iv}: no data for {len(still)} symbols: {still[:10]}")
    df = pd.concat(out, ignore_index=True) if out else empty_bars()
    if not df.empty and days:
        keep = np.sort(df["ts"].dt.normalize().unique())[-days:]
        df = df[df["ts"].dt.normalize().isin(keep)]
    return df.reset_index(drop=True)


# ---------------------------------------------------------------------------------------------
# Fyers history (fyers_apiv3 3.2.0 FyersModel.history, always through FyersProvider._call)
# ---------------------------------------------------------------------------------------------
def _as_provider(provider):
    """provider = scanner.providers.FyersProvider or a raw FyersModel. A raw model is wrapped, so every call
    goes through the shared cross-process limiter (scanner/fyers_limits.py) and FyersProvider's error rules:
    FyersAuthError on an expired login, strikes + FyersRateLimited on rate-limit errors, no own sleeps."""
    if hasattr(provider, "_call") and hasattr(provider, "api"):
        return provider
    from ..providers import FyersProvider     # lazy: the rest of this module needs no project imports
    return FyersProvider.from_model(provider)


def _fyers_call(provider, payload: dict) -> dict:
    return provider._call(provider.api.history, payload)


def fyers_candles_to_frame(candles: list, symbol: str) -> pd.DataFrame:
    """[[epoch_s, o, h, l, c, v], ...] -> long bars. Epochs are UTC seconds at bar start."""
    if not candles:
        return empty_bars()
    a = np.asarray(candles, dtype=float)
    ts = pd.to_datetime(a[:, 0].astype("int64"), unit="s") + pd.Timedelta(hours=5, minutes=30)
    df = pd.DataFrame({"ts": ts.values, "symbol": symbol, "open": a[:, 1], "high": a[:, 2], "low": a[:, 3],
                       "close": a[:, 4], "volume": a[:, 5]})
    df["flags"] = np.uint8(0)
    df["source"] = "fyers"
    return df


def fetch_fyers_intraday(provider, symbols: list[str], start: date, end: date, resolution: str = "5",
                         progress=None, throttle=None, now: datetime | None = None,
                         errors: dict | None = None) -> pd.DataFrame:
    """Fyers intraday candles for NSE equities, chunked to <=100 calendar days per call.

    resolution: '1','2','3','5','10','15','20','30','60','120','240' (or '5m' style).
    Standard plan: intraday history only for the last ~1 year (docs: "from 2025", rolling);
    5000 data calls/day, 50/min. Calls needed = symbols x ceil(days / 100).
    The forming candle is excluded by clamping range_to to (now - one bar) when `end` is today.
    errors: if given, symbols whose request failed are recorded here ({symbol: message}), so a caller
    never mistakes a failed range for one that simply had no data.
    throttle: ignored (kept for older callers) - the shared FYERS limiter spaces every call.
    """
    res = FYERS_RES.get(resolution, resolution)
    step = int(res)
    now = now or datetime.now(IST).replace(tzinfo=None)
    provider = _as_provider(provider)
    out = []
    for i, sym in enumerate(symbols, 1):
        ticker = sym if ":" in sym else f"NSE:{sym}-EQ"
        s = start
        while s <= end:
            e = min(s + timedelta(days=FYERS_MAX_DAYS_PER_CALL - 1), end)
            if e >= now.date():
                last_done = now - timedelta(minutes=step)
                rng_from = int((datetime.combine(s, datetime.min.time()) - timedelta(hours=5, minutes=30))
                               .replace(tzinfo=timezone.utc).timestamp())
                rng_to = int((last_done - timedelta(hours=5, minutes=30)).replace(tzinfo=timezone.utc).timestamp())
                payload = {"symbol": ticker, "resolution": res, "date_format": "0",
                           "range_from": str(rng_from), "range_to": str(rng_to), "cont_flag": "1"}
            else:
                payload = {"symbol": ticker, "resolution": res, "date_format": "1",
                           "range_from": s.isoformat(), "range_to": e.isoformat(), "cont_flag": "1"}
            r = _fyers_call(provider, payload)
            if r.get("s") == "ok" and r.get("candles"):
                out.append(fyers_candles_to_frame(r["candles"], sym.split(":")[-1].removesuffix("-EQ")))
            elif r.get("s") not in ("ok", "no_data"):
                if errors is not None:
                    errors[sym] = str(r.get("message") or "FYERS history request failed")
                if progress:
                    progress(i, len(symbols), f"{sym}: {r.get('message')}")
                break
            s = e + timedelta(days=1)
        if progress:
            progress(i, len(symbols), sym)
    return pd.concat(out, ignore_index=True) if out else empty_bars()


def fyers_backfill_budget(n_symbols: int, cal_days: int, per_min: int = 50, per_day: int = 5000) -> dict:
    calls = n_symbols * int(np.ceil(cal_days / FYERS_MAX_DAYS_PER_CALL))
    return {"calls": calls, "minutes_at_limit": round(calls / (per_min - 2), 1),
            "share_of_daily_quota": round(calls / per_day, 3), "days_needed": int(np.ceil(calls / (per_day - 50)))}


# ---------------------------------------------------------------------------------------------
# Clean / validate
# ---------------------------------------------------------------------------------------------
def clean_bars(df: pd.DataFrame, interval: str, drop_synthetic_close: bool = False,
               now: datetime | None = None, special_sessions: bool = False) -> pd.DataFrame:
    """Normalise raw bars: grid-align, restrict to the session, dedupe, fix OHLC, set flags.

    * Bars are floored onto the 09:15-anchored grid of `interval` (Yahoo 30m/90m bars are
      clock-aligned at 09:00 - re-aligning is lossy, so build 30m by resampling 5m/15m instead).
    * Bars outside 09:15-15:29 are dropped unless special_sessions=True (Muhurat trading).
    * now=<IST naive datetime>: bars whose end is after `now` are flagged FLAG_FORMING.
    """
    iv = norm_interval(interval)
    step = INTERVAL_MIN[iv]
    if df.empty:
        return empty_bars()
    d = df.copy()
    d["ts"] = pd.to_datetime(d["ts"])
    if d["ts"].dt.tz is not None:
        d["ts"] = d["ts"].dt.tz_convert("Asia/Kolkata").dt.tz_localize(None)
    day = d["ts"].dt.normalize()
    mins = (d["ts"] - day).dt.total_seconds() // 60 - 555                 # minutes since 09:15
    d["ts"] = day + pd.to_timedelta(555 + (mins // step) * step, unit="m")
    mins = (mins // step) * step
    if not special_sessions:
        d = d[(mins >= 0) & (mins < SESSION_MINUTES)]
    for c in COLS:
        d[c] = pd.to_numeric(d[c], errors="coerce").astype(float)
    d = d.dropna(subset=["open", "high", "low", "close"])
    d = d[(d[["open", "high", "low", "close"]] > 0).all(axis=1)]
    d["volume"] = d["volume"].fillna(0).clip(lower=0)
    if "flags" not in d:
        d["flags"] = 0
    if "source" not in d:
        d["source"] = "unknown"
    d["flags"] = d["flags"].fillna(0).astype("uint8")
    d = d.sort_values(["symbol", "ts"]).drop_duplicates(["symbol", "ts"], keep="last")

    hi = d[["open", "high", "low", "close"]].max(axis=1)
    lo = d[["open", "high", "low", "close"]].min(axis=1)
    bad = (hi > d["high"] + 1e-9) | (lo < d["low"] - 1e-9)
    d.loc[bad, "flags"] |= FLAG_OHLC_FIXED
    d["high"], d["low"] = hi, lo

    day = d["ts"].dt.normalize()
    g = d.groupby(["symbol", day], sort=False)
    first = g.cumcount() == 0
    last = g.cumcount(ascending=False) == 0
    d.loc[first & (d["volume"] == 0), "flags"] |= FLAG_VOL0_OPEN
    flat = (d["open"] == d["high"]) & (d["high"] == d["low"]) & (d["low"] == d["close"])
    tmin = (d["ts"] - day).dt.total_seconds() / 60
    synth = last & flat & (tmin >= 15 * 60 + 15) & (d["source"] == "yahoo")
    d.loc[synth, "flags"] |= FLAG_SYNTH_CLOSE
    prev_c = g["close"].shift()
    jump = (d["close"] / prev_c - 1).abs() > 0.10
    d.loc[jump.fillna(False), "flags"] |= FLAG_JUMP
    if now is not None:
        forming = d["ts"] + pd.Timedelta(minutes=step) > pd.Timestamp(now)
        d.loc[forming, "flags"] |= FLAG_FORMING
    if drop_synthetic_close:
        d = d[(d["flags"] & FLAG_SYNTH_CLOSE) == 0]
    d["symbol"] = d["symbol"].astype(str)
    return d[["ts", "symbol"] + COLS + ["flags", "source"]].reset_index(drop=True)


def daily_from_bars(bars: pd.DataFrame) -> pd.DataFrame:
    """Session OHLCV per (symbol, date) from intraday bars."""
    b = bars.sort_values(["symbol", "ts"])
    b = b.assign(date=b["ts"].dt.normalize())
    return b.groupby(["symbol", "date"]).agg(open=("open", "first"), high=("high", "max"), low=("low", "min"),
                                             close=("close", "last"), volume=("volume", "sum"),
                                             bars=("ts", "size")).reset_index()


def validate_against_daily(bars: pd.DataFrame, store: dict, interval: str, tol: float = 0.005) -> dict:
    """Compare session OHLCV built from bars with the official NSE daily store (unadjusted days only).

    Days whose close differs by more than 1.5% are treated as corporate-action-adjusted in the
    store (or bad data) and reported separately rather than counted as mismatches.
    """
    agg = daily_from_bars(bars)
    rows = []
    for f in COLS:
        w = store[f]
        s = w.reindex(columns=sorted(set(agg["symbol"].unique()) & set(w.columns)))
        st = s.stack().rename(f + "_nse").reset_index()
        st.columns = ["date", "symbol", f + "_nse"]
        rows.append(st.set_index(["symbol", "date"]))
    nse = pd.concat(rows, axis=1).reset_index()
    m = agg.merge(nse, on=["symbol", "date"], how="inner")
    if m.empty:
        return {"n": 0}
    ratio = m["close_nse"] / m["close"]
    adj = (ratio - 1).abs() > 0.015
    ok = m[~adj]
    nexp = len(session_slots(interval))
    rep = {"n_symdays": int(len(m)), "excluded_ratio_gt_1.5pct": int(adj.sum()),
           "full_sessions_pct": round(float((m["bars"] >= nexp).mean() * 100), 2)}
    for f in ["open", "high", "low", "close"]:
        rel = (ok[f] / ok[f + "_nse"] - 1).abs()
        rep[f] = {"within_tol_pct": round(float((rel <= tol).mean() * 100), 2),
                  "exact_pct": round(float((rel <= 1e-4).mean() * 100), 2),
                  "median_bp": round(float(rel.median() * 1e4), 2)}
    vr = ok["volume"] / ok["volume_nse"]
    rep["volume_ratio"] = {"median": round(float(vr.median()), 4), "p5": round(float(vr.quantile(.05)), 4)}
    rep["worst"] = m.loc[(m["close"] / m["close_nse"] - 1).abs().nlargest(3).index,
                         ["symbol", "date", "close", "close_nse"]].astype(str).to_dict("records")
    return rep


def adjust_to_store(bars: pd.DataFrame, store: dict, snap: float = 0.015) -> pd.DataFrame:
    """Rescale as-traded bars onto the store's corporate-action-adjusted price scale.

    factor(symbol, day) = store_close / session_close, snapped to 1.0 when within `snap`,
    and otherwise to the median factor of that symbol's run of equal-ish days (CA factors are
    step functions in time). Volume is divided by the same factor.
    """
    if bars.empty:
        return bars
    agg = daily_from_bars(bars)[["symbol", "date", "close"]]
    sc = store["close"].stack().rename("close_nse").reset_index()
    sc.columns = ["date", "symbol", "close_nse"]
    f = agg.merge(sc, on=["symbol", "date"], how="left")
    f["factor"] = (f["close_nse"] / f["close"]).where(lambda x: (x - 1).abs() > snap, 1.0).fillna(1.0)
    # smooth noise: within a symbol, consecutive days with factors within 2% share their median
    f = f.sort_values(["symbol", "date"])
    brk = (f.groupby("symbol")["factor"].pct_change().abs() > 0.02).fillna(True)
    f["run"] = brk.cumsum()
    f["factor"] = f.groupby("run")["factor"].transform("median")
    out = bars.assign(date=bars["ts"].dt.normalize()).merge(f[["symbol", "date", "factor"]], on=["symbol", "date"], how="left")
    k = out["factor"].fillna(1.0)
    for c in ["open", "high", "low", "close"]:
        out[c] = out[c] * k
    out["volume"] = out["volume"] / k
    return out.drop(columns=["date", "factor"])


def resample_bars(bars: pd.DataFrame, interval: str) -> pd.DataFrame:
    """Aggregate finer bars to `interval` on the 09:15-anchored grid (e.g. 5m -> 15m/30m/60m)."""
    step = INTERVAL_MIN[norm_interval(interval)]
    b = bars.sort_values(["symbol", "ts"])
    day = b["ts"].dt.normalize()
    mins = (b["ts"] - day).dt.total_seconds() // 60 - 555
    key = day + pd.to_timedelta(555 + (mins // step) * step, unit="m")
    out = b.assign(ts=key).groupby(["symbol", "ts"], sort=True).agg(
        open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last"),
        volume=("volume", "sum"), flags=("flags", lambda x: np.bitwise_or.reduce(x.to_numpy())),
        source=("source", "first")).reset_index()
    out["flags"] = out["flags"].astype("uint8")
    return out[["ts", "symbol"] + COLS + ["flags", "source"]]


# ---------------------------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------------------------
SOURCE_PRIORITY = {"fyers": 3, "nse": 3, "fyers_ws": 2, "yahoo": 1, "unknown": 0}
SAVE_LOCK_TIMEOUT_S = 120.0


def _replace(src: Path, dst: Path, tries: int = 10):
    for i in range(tries):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if i == tries - 1:
                raise
            time.sleep(0.2 * (i + 1))


class FileLock:
    """Exclusive cross-process lock on byte 0 of `path` (same msvcrt/fcntl pattern as scanner/lock.py).
    acquire(timeout) -> bool; as a context manager it raises TimeoutError when the lock stays busy."""

    def __init__(self, path: str | Path, timeout: float = 60.0):
        self.path, self.timeout, self.fh = Path(path), timeout, None

    def acquire(self, timeout: float | None = None) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fh = open(self.path, "a+")
        deadline = time.monotonic() + (self.timeout if timeout is None else timeout)
        while True:
            try:
                if os.name == "nt":
                    import msvcrt
                    fh.seek(0)   # msvcrt locks from the current position ("a+" starts at the end): always byte 0
                    msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                self.fh = fh
                return True
            except OSError:
                if time.monotonic() >= deadline:
                    fh.close()
                    return False
                time.sleep(0.1)

    def release(self) -> None:
        fh, self.fh = self.fh, None
        if fh is None:
            return
        try:
            if os.name == "nt":
                import msvcrt
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        fh.close()

    def __enter__(self):
        if not self.acquire():
            raise TimeoutError(f"{self.path} is locked by another process")
        return self

    def __exit__(self, *exc) -> bool:
        self.release()
        return False


def merge_by_priority(*frames: pd.DataFrame) -> pd.DataFrame:
    """Concatenate bar frames; per (symbol, ts) the best source wins (fyers > fyers_ws > yahoo), and between
    equal sources the bar from the later frame. Tick-built bars therefore never replace FYERS' official ones."""
    parts = [f for f in frames if f is not None and len(f)]
    if not parts:
        return empty_bars()
    allb = pd.concat(parts, ignore_index=True)
    allb = allb.assign(_pri=allb["source"].astype(str).map(SOURCE_PRIORITY).fillna(0).to_numpy(),
                       _ord=np.arange(len(allb)))
    allb = allb.sort_values(["symbol", "ts", "_pri", "_ord"]).drop_duplicates(["symbol", "ts"], keep="last")
    return allb.drop(columns=["_pri", "_ord"]).reset_index(drop=True)


class IntradayStore:
    """<root>/<interval>/<YYYY-MM>.parquet + manifest.json. Merge-on-save, newest source wins
    per (symbol, ts) with priority fyers > fyers_ws > yahoo (Fyers has the complete last 15 minutes)."""

    PRIORITY = SOURCE_PRIORITY

    def __init__(self, root: str | Path):
        self.root = Path(root)

    def _dir(self, interval: str) -> Path:
        p = self.root / norm_interval(interval)
        p.mkdir(parents=True, exist_ok=True)
        return p

    def months(self, interval: str) -> list[str]:
        return sorted(p.stem for p in self._dir(interval).glob("????-??.parquet"))

    def manifest(self, interval: str) -> dict:
        p = self._dir(interval) / "manifest.json"
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return {"months": {}}

    def save(self, bars: pd.DataFrame, interval: str) -> dict:
        """Merge cleaned bars into monthly partitions. Forming bars are never stored. The read-merge-write
        runs under a lock: two processes saving the same month (live service, archive, a scan) would
        otherwise each write back only their own merge and drop the other's bars."""
        iv = norm_interval(interval)
        d = self._dir(iv)
        bars = bars[(bars["flags"] & FLAG_FORMING) == 0]
        if bars.empty:
            return {}
        written = {}
        with FileLock(d / ".save.lock", timeout=SAVE_LOCK_TIMEOUT_S):
            man = self.manifest(iv)
            for month, part in bars.groupby(bars["ts"].dt.strftime("%Y-%m")):
                path = d / f"{month}.parquet"
                old = pd.read_parquet(path) if path.exists() else empty_bars()
                allb = pd.concat([old.astype({"symbol": str, "source": str}),
                                  part.astype({"symbol": str, "source": str})], ignore_index=True)
                allb["_pri"] = allb["source"].map(self.PRIORITY).fillna(0)
                allb["_ord"] = np.arange(len(allb))
                allb = (allb.sort_values(["symbol", "ts", "_pri", "_ord"])
                            .drop_duplicates(["symbol", "ts"], keep="last").drop(columns=["_pri", "_ord"]))
                allb = allb.sort_values(["ts", "symbol"]).reset_index(drop=True)
                allb["symbol"] = allb["symbol"].astype("category")
                allb["source"] = allb["source"].astype("category")
                allb["flags"] = allb["flags"].astype("uint8")
                tmp = path.with_suffix(f".{os.getpid()}.tmp")
                allb.to_parquet(tmp, index=False, compression="zstd")
                _replace(tmp, path)
                man["months"][month] = {"rows": int(len(allb)), "symbols": int(allb["symbol"].nunique()),
                                        "days": int(allb["ts"].dt.normalize().nunique()),
                                        "first": str(allb["ts"].min()), "last": str(allb["ts"].max()),
                                        "sources": sorted(map(str, allb["source"].unique())),
                                        "updated": datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")}
                written[month] = len(allb)
            tmp = d / f"manifest.{os.getpid()}.tmp"
            tmp.write_text(json.dumps(man, indent=1), encoding="utf-8")
            _replace(tmp, d / "manifest.json")
        return written

    def load(self, interval: str, symbols: list[str] | None = None, start=None, end=None,
             drop_flags: int = 0) -> pd.DataFrame:
        """Long bars between start/end (inclusive dates). drop_flags: bitmask of flags to exclude
        (e.g. FLAG_SYNTH_CLOSE for intrabar-path backtests)."""
        iv = norm_interval(interval)
        s = pd.Timestamp(start) if start is not None else None
        e = pd.Timestamp(end) + pd.Timedelta(days=1) if end is not None else None
        parts = []
        for m in self.months(iv):
            mstart = pd.Timestamp(m + "-01")
            if (s is not None and mstart + pd.offsets.MonthEnd(1) + pd.Timedelta(days=1) <= s) or (e is not None and mstart >= e):
                continue
            filters = [("symbol", "in", list(symbols))] if symbols else None
            parts.append(pd.read_parquet(self._dir(iv) / f"{m}.parquet", filters=filters))
        if not parts:
            return empty_bars()
        df = pd.concat([p.astype({"symbol": str, "source": str}) for p in parts], ignore_index=True)
        if s is not None:
            df = df[df["ts"] >= s]
        if e is not None:
            df = df[df["ts"] < e]
        if drop_flags:
            df = df[(df["flags"] & drop_flags) == 0]
        return df.reset_index(drop=True)

    def load_grid(self, interval: str, symbols: list[str] | None = None, start=None, end=None,
                  drop_flags: int = 0, ffill_close: bool = False) -> dict:
        """Dense cube for vectorised strategies: {'dates', 'slots', 'symbols', 'open'.. 'volume'}
        with arrays shaped (n_days, n_slots, n_symbols); missing bars are NaN (volume 0)."""
        df = self.load(interval, symbols, start, end, drop_flags)
        slots = session_slots(interval)
        if df.empty:
            return {"dates": pd.DatetimeIndex([]), "slots": slots, "symbols": pd.Index([])}
        dates = pd.DatetimeIndex(np.sort(df["ts"].dt.normalize().unique()))
        syms = pd.Index(sorted(df["symbol"].unique()))
        di = dates.get_indexer(df["ts"].dt.normalize())
        si = slots.get_indexer(df["ts"].dt.strftime("%H:%M"))
        ki = syms.get_indexer(df["symbol"])
        ok = si >= 0
        out = {"dates": dates, "slots": slots, "symbols": syms}
        for c in COLS:
            a = np.full((len(dates), len(slots), len(syms)), 0.0 if c == "volume" else np.nan)
            a[di[ok], si[ok], ki[ok]] = df[c].to_numpy(float)[ok]
            out[c] = a
        if ffill_close:   # carry last close through missing slots (flat bar, zero volume)
            cl = out["close"]
            for t in range(1, len(slots)):
                m = np.isnan(cl[:, t, :])
                cl[:, t, :][m] = cl[:, t - 1, :][m]
                for f in ("open", "high", "low"):
                    out[f][:, t, :][m] = cl[:, t, :][m]
        return out


# ---------------------------------------------------------------------------------------------
# Live helpers
# ---------------------------------------------------------------------------------------------
def completed_only(bars: pd.DataFrame, interval: str, now: datetime | None = None, grace_s: int = 0) -> pd.DataFrame:
    """Drop the forming bar(s): keep bars whose end time <= now - grace."""
    step = INTERVAL_MIN[norm_interval(interval)]
    now = pd.Timestamp(now or datetime.now(IST).replace(tzinfo=None))
    return bars[bars["ts"] + pd.Timedelta(minutes=step) <= now - pd.Timedelta(seconds=grace_s)]


class TickBarBuilder:
    """Build 1m/5m bars from Fyers data-socket SymbolUpdate ticks (ltp, vol_traded_today,
    last_traded_time / exch_feed_time). Standard plan: max 100 symbols per user on the socket."""

    def __init__(self, interval: str = "5m"):
        self.step = INTERVAL_MIN[norm_interval(interval)]
        self.cur: dict[str, dict] = {}
        self.done: list[dict] = []
        self.last_cum: dict[str, float] = {}

    def on_tick(self, msg: dict):
        sym, ltp = msg.get("symbol"), msg.get("ltp")
        t = msg.get("last_traded_time") or msg.get("exch_feed_time")
        if not sym or ltp is None or not t or float(ltp) <= 0:
            return      # a zero / negative price is a bad tick, never a bar low
        ts = pd.Timestamp(int(t), unit="s") + pd.Timedelta(hours=5, minutes=30)
        if ts.date() != datetime.now(IST).date():
            return      # subscription snapshot of a stock not traded yet today: yesterday's last trade
        m = int((ts - ts.normalize()).total_seconds() // 60) - 555
        if m < 0 or m >= SESSION_MINUTES:
            return
        start = ts.normalize() + pd.Timedelta(minutes=555 + (m // self.step) * self.step)
        b = self.cur.get(sym)
        if b is not None and start < b["ts"]:
            return      # late / repeated older trade time: never reopen a bar that is already closed
        # both checks come before the volume bookkeeping, so stale ticks cannot distort the volume deltas
        cum = float(msg.get("vol_traded_today") or 0)
        prev = self.last_cum.get(sym, cum)
        dv = max(cum - prev, 0.0)
        self.last_cum[sym] = max(cum, prev)
        if b is None or b["ts"] != start:
            if b is not None:
                self.done.append(b)
            b = {"ts": start, "symbol": sym.split(":")[-1].removesuffix("-EQ"), "open": ltp, "high": ltp,
                 "low": ltp, "close": ltp, "volume": 0.0, "flags": 0, "source": "fyers_ws"}
            self.cur[sym] = b
        b["high"], b["low"], b["close"] = max(b["high"], ltp), min(b["low"], ltp), ltp
        b["volume"] += dv

    def flush(self) -> pd.DataFrame:
        out, self.done = self.done, []
        return pd.DataFrame(out) if out else empty_bars()
