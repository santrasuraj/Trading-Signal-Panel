"""Market data providers.

Yahoo Finance : deep daily history (bulk, free). Used to build the store; NSE official files then
                take over for every completed day (store.py).
Fyers         : real-time quotes for today's live candle when the user is logged in (daily login).

Fyers Standard (free) plan data limits: 5 req/s, 50 req/min, 5,000 req/day; breaching the per-minute
limit more than 3 times in a day blocks the user for the rest of the day. The client therefore
throttles to the plan's limit, waits for the next minute window on a rate-limit error, and stops
immediately on an authentication error.
"""
from __future__ import annotations

import functools
import json
import time
import warnings
from collections import defaultdict
from datetime import date, datetime, timedelta

import pandas as pd

from .settings import IST, LOG_DIR, TOKEN_FILE

COLS = ["open", "high", "low", "close", "volume"]
INDEX_NIFTY = "NIFTY50"
INDEX_VIX = "INDIAVIX"
INDEX_SYMBOLS = (INDEX_NIFTY, INDEX_VIX)


def empty_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=COLS, index=pd.DatetimeIndex([], name="date"), dtype=float)


class FyersAuthError(RuntimeError):
    """The Fyers session is invalid or expired - the user must run the daily login again."""


class FyersProvider:
    name = "fyers"
    INDEX_MAP = {INDEX_NIFTY: "NSE:NIFTY50-INDEX", INDEX_VIX: "NSE:INDIAVIX-INDEX"}
    MIN_INTERVAL = {"standard": 1.25, "prime": 0.13}   # seconds between data calls (50/min, 500/min)
    MAX_DAYS_PER_CALL = 365
    AUTH_CODES = {-8, -15, -16, -17, 401}
    RATE_CODES = {-429, -360, 429}
    TIMEOUT = (5, 20)                                   # connect, read seconds

    def __init__(self, client_id: str, access_token: str, plan: str = "standard"):
        from fyers_apiv3 import fyersModel

        self.api = fyersModel.FyersModel(client_id=client_id, token=access_token,
                                         is_async=False, log_path=str(LOG_DIR))
        # The SDK sets no HTTP timeout: a dropped connection would hang forever.
        sess = self.api.service.session
        sess.request = functools.partial(sess.request, timeout=self.TIMEOUT)
        for lg in (getattr(self.api, "request_logger", None), getattr(self.api, "api_logger", None)):
            try:
                lg.setLevel("WARNING")  # SDK logs every request at DEBUG to an unrotated file
            except Exception:
                pass
        self.interval = self.MIN_INTERVAL.get(plan, self.MIN_INTERVAL["standard"])
        self._last_call = 0.0
        self.calls = 0
        self.errors: dict[str, str] = {}

    def ticker(self, sym: str) -> str:
        return self.INDEX_MAP.get(sym, f"NSE:{sym}-EQ")

    def _call(self, fn, payload=None) -> dict:
        resp: dict = {}
        for attempt in range(3):
            wait = self.interval - (time.monotonic() - self._last_call)
            if wait > 0:
                time.sleep(wait)
            self._last_call = time.monotonic()
            self.calls += 1
            try:
                resp = fn(data=payload) if payload is not None else fn()
            except Exception as e:  # network errors, timeouts
                resp = {"s": "error", "code": -99, "message": f"{type(e).__name__}"}
            if not isinstance(resp, dict):
                resp = {"s": "error", "message": str(resp)[:200]}
            if resp.get("s") in ("ok", "no_data"):
                return resp
            code = resp.get("code")
            msg = str(resp.get("message", "")).lower()
            if code in self.AUTH_CODES or "token" in msg or "authenticat" in msg:
                raise FyersAuthError(str(resp.get("message") or "Fyers session expired"))
            if code in self.RATE_CODES or "limit" in msg:
                # Wait for the next minute window instead of hammering (3 strikes = blocked for the day).
                time.sleep(61 - datetime.now().second)
                continue
            time.sleep(1 + attempt)
        return resp

    def check_login(self) -> tuple[bool, str]:
        try:
            r = self._call(self.api.get_profile)
        except FyersAuthError as e:
            return False, str(e)
        if r.get("s") == "ok":
            return True, (r.get("data") or {}).get("name", "")
        return False, str(r.get("message", "login check failed"))

    @staticmethod
    def _candles_to_frame(candles: list) -> pd.DataFrame:
        df = pd.DataFrame(candles, columns=["ts"] + COLS)
        # Daily candle stamps are 00:00 UTC or 00:00 IST depending on endpoint; +5:30 then
        # normalising gives the IST trading date in both cases.
        dates = (pd.to_datetime(df["ts"], unit="s") + pd.Timedelta(hours=5, minutes=30)).dt.normalize()
        return df.drop(columns="ts").set_index(pd.DatetimeIndex(dates, name="date")).astype(float)

    def history(self, symbols, starts: dict, end: date, progress=None) -> dict[str, pd.DataFrame]:
        """Daily candles per symbol (slow on the Standard plan: use for a handful of symbols only)."""
        out = {}
        for i, sym in enumerate(symbols, 1):
            frames, s = [], starts[sym]
            while s <= end:
                e = min(s + timedelta(days=self.MAX_DAYS_PER_CALL - 1), end)
                r = self._call(self.api.history, {
                    "symbol": self.ticker(sym), "resolution": "D", "date_format": "1",
                    "range_from": s.isoformat(), "range_to": e.isoformat(), "cont_flag": "1",
                })
                if r.get("s") == "ok":
                    if r.get("candles"):
                        frames.append(self._candles_to_frame(r["candles"]))
                elif r.get("s") != "no_data":
                    self.errors[sym] = str(r.get("message", "history request failed"))
                    break
                s = e + timedelta(days=1)
            df = pd.concat(frames) if frames else empty_frame()
            out[sym] = df[~df.index.duplicated(keep="last")].sort_index()
            if progress:
                progress(i, len(symbols), sym)
        return out

    def live_rows(self, symbols) -> dict[str, tuple[date | None, dict]]:
        """Today's running OHLCV from the quotes API (50 symbols per call)."""
        by_ticker = {self.ticker(s): s for s in symbols}
        tickers = list(by_ticker)
        out = {}
        for k in range(0, len(tickers), 50):
            r = self._call(self.api.quotes, {"symbols": ",".join(tickers[k:k + 50])})
            if r.get("s") != "ok":
                self.errors["quotes"] = str(r.get("message", "quotes request failed"))
                continue
            for item in r.get("d") or []:
                v = item.get("v") or {}
                sym = by_ticker.get(item.get("n") or v.get("symbol"))
                if not sym or item.get("s") != "ok" or not v.get("lp"):
                    continue
                tt = v.get("tt")
                try:
                    d = datetime.fromtimestamp(int(tt), IST).date() if tt else None
                except (TypeError, ValueError):
                    d = None
                out[sym] = (d, {
                    "open": v.get("open_price"), "high": v.get("high_price"), "low": v.get("low_price"),
                    "close": v.get("lp"), "volume": v.get("volume") or 0,
                    "prev_close": v.get("prev_close_price"),
                })
        return out

    def holdings(self) -> list[dict]:
        """The user's demat holdings (broker cost price is already corporate-action adjusted)."""
        r = self._call(self.api.holdings)
        return (r.get("holdings") or []) if r.get("s") == "ok" else []


class YahooProvider:
    name = "yahoo"
    INDEX_MAP = {INDEX_NIFTY: "^NSEI", INDEX_VIX: "^INDIAVIX"}
    BATCH = 80
    OUTAGE_SHARE = 0.2   # if more than this share of a batch comes back empty, treat it as an outage

    def __init__(self):
        self.errors: dict[str, str] = {}
        self.outage = False

    def ticker(self, sym: str) -> str:
        return self.INDEX_MAP.get(sym, f"{sym}.NS")

    @staticmethod
    def _extract(data: pd.DataFrame | None, ticker: str) -> pd.DataFrame:
        if data is None or data.empty:
            return empty_frame()
        if isinstance(data.columns, pd.MultiIndex):
            if ticker not in data.columns.get_level_values(0):
                return empty_frame()
            sub = data[ticker]
        else:
            sub = data
        sub = sub.rename(columns=lambda c: str(c).lower())
        if not set(COLS).issubset(sub.columns):
            return empty_frame()
        sub = sub[COLS].dropna(subset=["close"]).astype(float)
        idx = pd.to_datetime(sub.index)
        if idx.tz is not None:
            idx = idx.tz_localize(None)
        sub.index = pd.DatetimeIndex(idx.normalize(), name="date")
        return sub[~sub.index.duplicated(keep="last")].sort_index()

    def history(self, symbols, starts: dict, end: date, progress=None) -> dict[str, pd.DataFrame]:
        import yfinance as yf

        groups = defaultdict(list)
        for s in symbols:
            groups[starts[s]].append(s)
        out, done = {}, 0
        for start, syms in groups.items():
            for k in range(0, len(syms), self.BATCH):
                batch = syms[k:k + self.BATCH]
                tickers = [self.ticker(s) for s in batch]
                data = None
                for attempt in range(2):
                    try:
                        with warnings.catch_warnings():  # yfinance triggers pandas deprecation noise
                            warnings.simplefilter("ignore")
                            data = yf.download(tickers, start=start.isoformat(),
                                               end=(end + timedelta(days=1)).isoformat(), interval="1d",
                                               auto_adjust=False, group_by="ticker", progress=False,
                                               threads=True, timeout=30)
                    except Exception as e:
                        data = None
                        for s in batch:
                            self.errors[s] = f"Yahoo download failed: {type(e).__name__}"
                    got = {s: self._extract(data, t) for s, t in zip(batch, tickers)}
                    empty = sum(df.empty for df in got.values())
                    if empty <= self.OUTAGE_SHARE * len(batch) or attempt == 1:
                        break
                    time.sleep(5)  # looks like throttling: back off once and retry
                if empty > self.OUTAGE_SHARE * len(batch) and len(batch) >= 10:
                    self.outage = True
                for s, df in got.items():
                    out[s] = df
                    if df.empty:
                        self.errors.setdefault(s, "no data from Yahoo")
                done += len(batch)
                if progress:
                    progress(done, len(symbols), batch[-1])
        return out


def load_token() -> dict | None:
    if not TOKEN_FILE.exists():
        return None
    try:
        tok = json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
        return tok if tok.get("access_token") and tok.get("client_id") else None
    except Exception:
        return None


_fyers_cache: dict = {}


def get_fyers(cfg: dict) -> tuple[FyersProvider | None, str]:
    """A logged-in Fyers client for live prices (one per process), or None with the reason."""
    if (cfg.get("data_source") or "auto").lower() == "yahoo":
        return None, "Live prices: Yahoo (~15 min delayed) - Fyers disabled in config.yaml"
    tok = load_token()
    if not tok:
        return None, "Not logged in to Fyers - live prices from Yahoo (~15 min delayed). Run 1_login.bat."
    key = (tok["client_id"], tok["access_token"])
    p = _fyers_cache.get(key)
    if p is None:
        p = FyersProvider(tok["client_id"], tok["access_token"], plan=str(cfg.get("fyers_plan", "standard")).lower())
        ok, msg = p.check_login()
        if not ok:
            return None, f"Fyers login expired ({msg}) - live prices from Yahoo. Run 1_login.bat."
        _fyers_cache.clear()
        _fyers_cache[key] = p
        p.user_name = msg
    return p, f"Fyers connected{' (' + p.user_name + ')' if getattr(p, 'user_name', '') else ''} - real-time prices"
