"""Local price-history cache and the daily refresh logic.

Only *completed* daily candles are saved to disk. Today's still-moving candle (during market
hours) is kept in memory and re-fetched on every scan, so the cache never holds a half-day.
"""
from __future__ import annotations

import json
import re
from datetime import date, timedelta

import pandas as pd

from .providers import INDEX_SYMBOLS, empty_frame
from .settings import CANDLE_FINAL_AFTER, HISTORY_DIR, ist_now, ist_today

FULL_HISTORY_SLACK_DAYS = 30


class HistoryStore:
    def __init__(self, provider_name: str):
        self.dir = HISTORY_DIR / provider_name
        self.dir.mkdir(parents=True, exist_ok=True)
        self.meta_path = self.dir / "_meta.json"
        self.meta = json.loads(self.meta_path.read_text()) if self.meta_path.exists() else {}

    def _path(self, sym: str):
        return self.dir / f"{re.sub(r'[^A-Za-z0-9_-]', '_', sym)}.parquet"

    def load(self, sym: str) -> pd.DataFrame:
        p = self._path(sym)
        if not p.exists():
            return empty_frame()
        try:
            return pd.read_parquet(p)
        except Exception:
            return empty_frame()

    def save(self, sym: str, df: pd.DataFrame) -> None:
        df.to_parquet(self._path(sym))

    def has_full_history(self, sym: str, start_full: date) -> bool:
        full_from = self.meta.get(sym)
        return bool(full_from) and date.fromisoformat(full_from) <= start_full + timedelta(days=FULL_HISTORY_SLACK_DAYS)

    def mark_full(self, sym: str, start_full: date) -> None:
        self.meta[sym] = start_full.isoformat()

    def save_meta(self) -> None:
        self.meta_path.write_text(json.dumps(self.meta, indent=0))


def _combine(old: pd.DataFrame, new: pd.DataFrame) -> pd.DataFrame:
    if old.empty:
        df = new
    elif new.empty:
        df = old
    else:
        df = pd.concat([old, new])
    df = df[~df.index.duplicated(keep="last")].sort_index()
    return df[(df["close"] > 0)].dropna(subset=["close"])


def _quote_date(hist: pd.DataFrame, quote_date: date | None, row: dict, today: date) -> date | None:
    """Work out which trading day a live quote belongs to."""
    if quote_date:
        return quote_date
    if hist.empty or not row.get("prev_close"):
        return None
    last_close = float(hist["close"].iloc[-1])
    # Quote's previous close equals our last saved close -> the quote is for the next session.
    if abs(float(row["prev_close"]) - last_close) / last_close < 0.003 and today > hist.index[-1].date():
        return today
    return None


def refresh(provider, symbols: list[str], lookback_days: int, progress=None, log=print):
    """Update the cache and return ({symbol: full history incl. today's live candle}, info)."""
    today = ist_today()
    now = ist_now()
    start_full = today - timedelta(days=lookback_days)
    store = HistoryStore(provider.name)

    # 1. Use the Nifty index to find the latest trading day and which candles are final.
    ref = provider.history([INDEX_SYMBOLS[0]], {INDEX_SYMBOLS[0]: today - timedelta(days=20)}, today)[INDEX_SYMBOLS[0]]
    if len(ref) < 2:
        raise RuntimeError("Could not download Nifty data. Check your internet connection / Fyers login.")
    latest = ref.index[-1].date()
    if latest == today and (now.hour, now.minute) < CANDLE_FINAL_AFTER:
        final_upto = ref.index[-2].date()  # today's candle is still forming
    else:
        final_upto = latest
    live_day = latest if latest > final_upto else None

    # 2. Decide what each symbol needs.
    all_syms = list(INDEX_SYMBOLS) + [s for s in symbols if s not in INDEX_SYMBOLS]
    cached = {s: store.load(s) for s in all_syms}
    starts = {}
    for s, df in cached.items():
        if df.empty or not store.has_full_history(s, start_full):
            starts[s] = start_full
        elif df.index[-1].date() < final_upto:
            starts[s] = df.index[-1].date() - timedelta(days=5)
        elif live_day and provider.name == "yahoo":
            starts[s] = final_upto - timedelta(days=3)  # just to pick up today's partial candle

    full = sum(1 for s in starts if starts[s] == start_full)
    if starts:
        log(f"Downloading prices: {len(starts)} symbols ({full} need full history"
            f"{' - first run takes several minutes' if full > 50 else ''})")
    fetched = provider.history(list(starts), starts, today, progress=progress) if starts else {}

    # 3. Merge, save completed candles, keep today's partial candle in memory.
    cutoff = pd.Timestamp(final_upto)
    live: dict[str, pd.DataFrame] = {}
    for s, new in fetched.items():
        merged = _combine(cached[s], new)
        complete = merged[merged.index <= cutoff]
        if not complete.empty:
            store.save(s, complete)
            if starts[s] == start_full and not new.empty:
                store.mark_full(s, start_full)
        cached[s] = complete
        if (merged.index > cutoff).any():
            live[s] = merged[merged.index > cutoff]
    store.save_meta()

    # 4. Live quotes (Fyers) for today's running candle.
    if live_day:
        for s, (qdate, row) in provider.live_rows(all_syms).items():
            d = _quote_date(cached[s], qdate, row, today)
            if d and d > final_upto and row.get("close"):
                vals = {k: float(row.get(k) or 0) for k in ("open", "high", "low", "close", "volume")}
                live[s] = pd.DataFrame([vals], index=pd.DatetimeIndex([pd.Timestamp(d)], name="date"))

    histories = {s: _combine(cached[s], live[s]) if s in live else cached[s] for s in all_syms}
    info = {
        "final_upto": final_upto.isoformat(),
        "live_day": live_day.isoformat() if live_day else None,
        "errors": dict(provider.errors),
    }
    return histories, info


def load_cached(provider_name: str, symbols: list[str]) -> dict[str, pd.DataFrame]:
    store = HistoryStore(provider_name)
    return {s: store.load(s) for s in symbols}
