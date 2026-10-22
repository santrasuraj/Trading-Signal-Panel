"""Corporate actions (splits, bonus issues, demergers) and symbol renames from NSE's public archives.

Used to back-adjust price history exactly, so a 1:1 bonus or a demerger never appears as a crash.

Sources (cached under data/nse/):
  PR{ddmmyy}.zip -> Bc{ddmmyyyy}.csv : upcoming record/ex-dates with their PURPOSE text
  symbolchange.csv                   : old symbol -> new symbol, effective date
"""
from __future__ import annotations

import io
import re
import time
import zipfile
from datetime import date, timedelta

import pandas as pd

from .nse import HEADERS, NSE_DIR, _get, _session

PR_URL = "https://nsearchives.nseindia.com/archives/equities/bhavcopy/pr/PR{d}.zip"
SYMBOL_CHANGE_URL = "https://nsearchives.nseindia.com/content/equities/symbolchange.csv"
EQUITY_SERIES = {"EQ", "BE", "BZ", "RR", "IV"}
PRICE_ACTIONS = re.compile(r"BONUS|SPLT|SPLIT|SUB-DIV|DEMERGER|CONSOLIDAT|CAPITAL REDUCTION|ARRANGEMENT")


def _parse_date(s) -> date | None:
    s = str(s).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%b-%Y", "%d-%m-%Y"):
        try:
            return pd.to_datetime(s, format=fmt).date()
        except (ValueError, TypeError):
            continue
    return None


def fetch_bc(day: date) -> pd.DataFrame | None:
    """Corporate-action notices published in the PR archive for `day` (None if no file that day)."""
    cache = NSE_DIR / f"bc_{day:%Y%m%d}.parquet"
    miss = NSE_DIR / f"bc_{day:%Y%m%d}.none"
    if cache.exists():
        return pd.read_parquet(cache)
    if miss.exists():
        return None
    try:
        r = _session().get(PR_URL.format(d=day.strftime("%d%m%y")), timeout=30)
    except Exception:
        return None
    if r.status_code == 404:
        if (date.today() - day).days > 3:
            miss.touch()
        return None
    if not r.ok:
        return None
    try:
        z = zipfile.ZipFile(io.BytesIO(r.content))
        name = next((n for n in z.namelist() if n.lower().startswith("bc")), None)
        if not name:
            miss.touch()
            return None
        df = pd.read_csv(z.open(name), dtype=str)
    except Exception:
        return None
    df.columns = [c.strip() for c in df.columns]
    out = pd.DataFrame({
        "series": df["SERIES"].str.strip(), "symbol": df["SYMBOL"].str.strip(),
        "ex_date": df["EX_DT"].map(_parse_date).astype(str), "purpose": df["PURPOSE"].astype(str).str.strip().str.upper(),
    })
    out = out[out["series"].isin(EQUITY_SERIES) & out["purpose"].str.contains(PRICE_ACTIONS)].drop_duplicates()
    out.to_parquet(cache)
    return out


def purpose_factor(purposes: list[str]) -> float | None:
    """Price adjustment factor implied by the purpose text, or None if it must be read from the
    market (demergers etc.). BONUS a:b -> b/(a+b); split/consolidation FROM Rs x TO Rs y -> y/x."""
    factor, known = 1.0, False
    for p in purposes:
        if "DEMERGER" in p or "ARRANGEMENT" in p or "CAPITAL REDUCTION" in p:
            return None
        m = re.search(r"BONUS\s*(\d+(?:\.\d+)?)\s*:\s*(\d+(?:\.\d+)?)", p)
        if m:
            a, b = float(m.group(1)), float(m.group(2))
            factor *= b / (a + b)
            known = True
            continue
        m = re.search(r"(?:FRM|FROM)\s*R[SE]\.?\s*([\d.]+)\D*?(?:TO)\s*R[SE]\.?\s*([\d.]+)", p)
        if m:
            x, y = float(m.group(1)), float(m.group(2))
            if x > 0 and y > 0:
                factor *= y / x
                known = True
    return factor if known else None


def actions_on(symbol: str, ex_day: date, prior_days: list[date]) -> list[str]:
    """Purposes of price-affecting actions for `symbol` with ex-date `ex_day`, looked up in the
    notices of the trading days just before it (notices are listed until the ex-date)."""
    for d in prior_days[:3]:
        bc = fetch_bc(d)
        if bc is None:
            continue
        rows = bc[(bc["symbol"] == symbol) & (bc["ex_date"] == ex_day.isoformat())]
        if len(rows):
            return sorted(set(rows["purpose"]))
    return []


_renames: dict[str, list[tuple[str, date]]] | None = None


def renames() -> dict[str, list[tuple[str, date]]]:
    """new_symbol -> [(old_symbol, effective_date)], refreshed weekly."""
    global _renames
    if _renames is not None:
        return _renames
    path = NSE_DIR / "symbolchange.csv"
    if not path.exists() or time.time() - path.stat().st_mtime > 7 * 86400:
        code, text = _get(SYMBOL_CHANGE_URL)
        if code == 200 and text:
            path.write_text(text, encoding="utf-8")
    out: dict[str, list[tuple[str, date]]] = {}
    if path.exists():
        df = pd.read_csv(path, header=None, skiprows=1, dtype=str, encoding="utf-8", on_bad_lines="skip")
        for _, r in df.iterrows():
            old, new, eff = str(r[1]).strip(), str(r[2]).strip(), _parse_date(r[3])
            if old and new and eff:
                out.setdefault(new, []).append((old, eff))
    _renames = out
    return out


def symbol_on(symbol: str, day: date) -> str:
    """The NSE symbol this stock traded under on `day` (follows renames backwards)."""
    seen = set()
    while symbol not in seen:
        seen.add(symbol)
        older = [(old, eff) for old, eff in renames().get(symbol, []) if eff > day]
        if not older:
            break
        symbol = min(older, key=lambda x: x[1])[0]
    return symbol
