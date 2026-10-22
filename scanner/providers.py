"""Market data providers: Fyers (live, needs daily login) and Yahoo Finance (free, ~15 min delayed)."""
from __future__ import annotations

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


class FyersProvider:
    name = "fyers"
    label = "Fyers (live)"
    INDEX_MAP = {INDEX_NIFTY: "NSE:NIFTY50-INDEX", INDEX_VIX: "NSE:INDIAVIX-INDEX"}
    # Fyers allows 10 requests/sec and 200/min; stay just under the per-minute cap.
    MIN_INTERVAL = 0.32
    MAX_DAYS_PER_CALL = 365

    def __init__(self, client_id: str, access_token: str):
        from fyers_apiv3 import fyersModel

        self.api = fyersModel.FyersModel(client_id=client_id, token=access_token,
                                         is_async=False, log_path=str(LOG_DIR))
        self._last_call = 0.0
        self.errors: dict[str, str] = {}

    def ticker(self, sym: str) -> str:
        return self.INDEX_MAP.get(sym, f"NSE:{sym}-EQ")

    def _call(self, fn, payload=None) -> dict:
        resp: dict = {}
        for attempt in range(4):
            wait = self.MIN_INTERVAL - (time.monotonic() - self._last_call)
            if wait > 0:
                time.sleep(wait)
            self._last_call = time.monotonic()
            try:
                resp = fn(data=payload) if payload is not None else fn()
            except Exception as e:  # network errors etc.
                resp = {"s": "error", "message": str(e)}
            if not isinstance(resp, dict):
                resp = {"s": "error", "message": str(resp)}
            if resp.get("s") in ("ok", "no_data"):
                return resp
            msg = str(resp.get("message", "")).lower()
            if "limit" in msg or resp.get("code") == 429:
                time.sleep(5 * (attempt + 1))
                continue
            if "token" in msg or "auth" in msg:
                return resp
            time.sleep(1)
        return resp

    def check_login(self) -> tuple[bool, str]:
        r = self._call(self.api.get_profile)
        if r.get("s") == "ok":
            return True, (r.get("data") or {}).get("name", "")
        return False, str(r.get("message", "login check failed"))

    @staticmethod
    def _candles_to_frame(candles: list) -> pd.DataFrame:
        df = pd.DataFrame(candles, columns=["ts"] + COLS)
        # Daily candle timestamps are midnight IST.
        dates = (pd.to_datetime(df["ts"], unit="s") + pd.Timedelta(hours=5, minutes=30)).dt.normalize()
        df = df.drop(columns="ts").set_index(pd.DatetimeIndex(dates, name="date")).astype(float)
        return df

    def history(self, symbols, starts: dict, end: date, progress=None) -> dict[str, pd.DataFrame]:
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
            for item in r.get("d") or []:
                v = item.get("v") or {}
                sym = by_ticker.get(item.get("n") or v.get("symbol"))
                if not sym or item.get("s") != "ok" or not v.get("lp"):
                    continue
                tt = v.get("tt")
                d = datetime.fromtimestamp(int(tt), IST).date() if tt else None
                out[sym] = (d, {
                    "open": v.get("open_price"), "high": v.get("high_price"), "low": v.get("low_price"),
                    "close": v.get("lp"), "volume": v.get("volume") or 0,
                    "prev_close": v.get("prev_close_price"),
                })
        return out


class YahooProvider:
    name = "yahoo"
    label = "Yahoo Finance (~15 min delayed)"
    INDEX_MAP = {INDEX_NIFTY: "^NSEI", INDEX_VIX: "^INDIAVIX"}
    BATCH = 80

    def __init__(self):
        self.errors: dict[str, str] = {}

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
                try:
                    with warnings.catch_warnings():  # yfinance triggers pandas deprecation noise
                        warnings.simplefilter("ignore")
                        data = yf.download(tickers, start=start.isoformat(),
                                           end=(end + timedelta(days=1)).isoformat(), interval="1d",
                                           auto_adjust=False, group_by="ticker", progress=False, threads=True)
                except Exception as e:
                    data = None
                    for s in batch:
                        self.errors[s] = f"Yahoo download failed: {e}"
                for s, t in zip(batch, tickers):
                    out[s] = self._extract(data, t)
                    if out[s].empty:
                        self.errors.setdefault(s, "no data from Yahoo")
                done += len(batch)
                if progress:
                    progress(done, len(symbols), batch[-1])
        return out

    def live_rows(self, symbols) -> dict:
        # Yahoo's partial candle for today already arrives with history().
        return {}


def load_token() -> dict | None:
    if not TOKEN_FILE.exists():
        return None
    try:
        tok = json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
        return tok if tok.get("access_token") and tok.get("client_id") else None
    except Exception:
        return None


def get_provider(preference: str = "auto"):
    """Return (provider, note). Falls back to Yahoo when Fyers is not logged in."""
    preference = (preference or "auto").lower()
    if preference in ("auto", "fyers"):
        tok = load_token()
        if tok:
            p = FyersProvider(tok["client_id"], tok["access_token"])
            ok, msg = p.check_login()
            if ok:
                return p, f"Fyers live data (logged in as {msg})" if msg else "Fyers live data"
            note = f"Fyers login expired ({msg}). Run 1_login.bat. Using Yahoo delayed data instead."
        else:
            note = "Not logged in to Fyers (run 1_login.bat). Using Yahoo delayed data instead."
        return YahooProvider(), note
    return YahooProvider(), "Yahoo Finance delayed data (~15 min)"
