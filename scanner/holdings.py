"""The user's own holdings (holdings.csv) and corporate-action-aware P&L.

If a stock had a split / bonus / demerger after you bought it, your buy price is not comparable
with today's price (a 1:1 bonus halves the price). Given the buy date, we read NSE's official close
for that day and compare it with our adjusted history: the ratio is the exact adjustment factor, so
the buy price (and quantity) are restated in today's terms and no false stop-loss fires.
"""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from . import corporate, nse
from .settings import HOLDINGS_FILE

HOLDING_COLS = ["symbol", "qty", "buy_price", "buy_date", "stop_loss_pct", "target_pct"]


def load_holdings() -> pd.DataFrame:
    if not HOLDINGS_FILE.exists():
        return pd.DataFrame({c: pd.Series(dtype="float64" if c not in ("symbol", "buy_date") else "object")
                             for c in HOLDING_COLS})
    df = pd.read_csv(HOLDINGS_FILE, dtype={"symbol": str, "buy_date": str})
    for c in HOLDING_COLS:
        if c not in df.columns:
            df[c] = np.nan
    df["symbol"] = df["symbol"].fillna("").astype(str).str.strip().str.upper()
    df = df[df["symbol"] != ""]
    for c in ("qty", "buy_price", "stop_loss_pct", "target_pct"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["buy_date"] = pd.to_datetime(df["buy_date"], errors="coerce").dt.date
    return df[HOLDING_COLS].reset_index(drop=True)


def save_holdings(df: pd.DataFrame) -> None:
    out = df.copy()
    out["symbol"] = out["symbol"].astype(str).str.strip().str.upper()
    out = out[~out["symbol"].isin(["", "NAN", "NONE"])]
    out["buy_date"] = pd.to_datetime(out["buy_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    tmp = HOLDINGS_FILE.with_suffix(".tmp")
    out[HOLDING_COLS].to_csv(tmp, index=False)
    tmp.replace(HOLDINGS_FILE)


def current_symbol(sym: str, known: set[str]) -> tuple[str, str | None]:
    """Follow NSE renames forward (e.g. TATAMOTORS -> TMPV). Returns (symbol, note)."""
    if sym in known:
        return sym, None
    for new, olds in corporate.renames().items():
        if any(old == sym for old, _ in olds) and new in known:
            return new, f"{sym} is now traded as {new}"
    return sym, None


def adjustment_factor(sym_now: str, buy_day: date, adjusted_close: pd.Series) -> float | None:
    """Our adjusted close on the buy date / NSE's actual close that day (1.0 = no corporate action since)."""
    if buy_day is None or pd.isna(buy_day):
        return None
    ts = pd.Timestamp(buy_day)
    ours = adjusted_close.loc[:ts].dropna()
    if ours.empty or (ts - ours.index[-1]).days > 7:
        return None
    day = ours.index[-1].date()
    fl = nse.fetch_day(day)
    if fl.status != "ok":
        return None
    raw_sym = corporate.symbol_on(sym_now, day)
    if raw_sym not in fl.stocks.index:
        return None
    raw = float(fl.stocks.at[raw_sym, "close"])
    if not raw > 0:
        return None
    f = float(ours.iloc[-1]) / raw
    return 1.0 if abs(f - 1) < 0.015 else f
