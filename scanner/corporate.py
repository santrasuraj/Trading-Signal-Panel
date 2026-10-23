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


_bc_memo: dict[date, pd.DataFrame | None] = {}


def fetch_bc(day: date) -> pd.DataFrame | None:
    """Corporate-action notices published in the PR archive for `day` (None if no file that day)."""
    if day in _bc_memo:
        return _bc_memo[day]
    cache = NSE_DIR / f"bc_{day:%Y%m%d}.parquet"
    miss = NSE_DIR / f"bc_{day:%Y%m%d}.none"
    if cache.exists():
        _bc_memo[day] = pd.read_parquet(cache)
        return _bc_memo[day]
    if miss.exists():
        _bc_memo[day] = None
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


NON_EQUITY_BONUS = re.compile(r"NCRPS|DEBT|PREF")       # bonus preference shares / debentures
BONUS_RATIO = re.compile(r"BON(?:US)?\W*(\d+(?:\.\d+)?)\s*:\s*(\d+(?:\.\d+)?)")
SPLIT_WORDS = re.compile(r"SPLT|SPLIT|SUB-DIV|CONSOLIDAT")
SPLIT_RATIO = re.compile(r"(\d+(?:\.\d+)?)\D{0,25}?TO\D{0,8}?(\d+(?:\.\d+)?)")   # face value x ... TO ... y


def purpose_factor(purposes: list[str]) -> float | None:
    """Price adjustment factor implied by the purpose text, or None if it must be read from the
    market (demergers, bonus preference shares etc.). BONUS a:b -> b/(a+b); split/consolidation
    of face value x TO y -> y/x. NSE writes these many ways: "BONUS- 1:2", "BON 2:1/FVSPLIT RS2TORE1",
    "FV SPLT FRM RS 10 TO 1", "FVSPLTFRM10TO1", "CONSOLIDATION-RE1 TO RS10"."""
    factor, known = 1.0, False
    for p in purposes:
        if "DEMERGER" in p or "ARRANGEMENT" in p or "CAPITAL REDUCTION" in p or NON_EQUITY_BONUS.search(p):
            return None
        rest = p
        m = BONUS_RATIO.search(p)
        if m:
            a, b = float(m.group(1)), float(m.group(2))
            if a > 0 and b > 0:
                factor *= b / (a + b)
                known = True
            rest = p[m.end():]                    # a split may follow in the same text
        m = SPLIT_RATIO.search(rest) if SPLIT_WORDS.search(rest) else None
        if m:
            x, y = float(m.group(1)), float(m.group(2))
            if x > 0 and y > 0:
                factor *= y / x
                known = True
    return factor if known else None


def actions_on(symbol: str, ex_day: date, prior_days: list[date]) -> list[str]:
    """Purposes of price-affecting actions for `symbol` with ex-date `ex_day`, looked up in the
    notices of the given days, in order (the trading days just before it, and optionally the ex-date
    itself: many notices first appear in the ex-date's own file)."""
    for d in prior_days:
        hit = _notice_index(d).get((symbol, ex_day.isoformat()))
        if hit:
            return hit
    return []


RESCHEDULE_DAYS = 15     # the same action listed with ex-dates this close together = one action


def listed_on(ex_day: date, days: list[date]) -> dict[str, list[str]]:
    """Symbols with a price-affecting action listed for ex-date `ex_day` in the notice files of
    `days` -> its purposes. NSE sometimes moves an ex-date (HAL 2023: 29 -> 28 Sep; Inox Wind 2024:
    17 -> 24 May): the newest of these files that lists the same action decides its date, so a moved
    action counts only on its new date."""
    latest: dict[tuple[str, str], tuple[date, str]] = {}   # (symbol, purpose) -> (file day, ex-date)
    for day in sorted(set(days)):
        for (sym, ex), purposes in _notice_index(day).items():
            ex_d = _parse_date(ex)
            if ex_d is None or abs((ex_d - ex_day).days) > RESCHEDULE_DAYS:
                continue
            for p in purposes:
                latest[(sym, p)] = max(latest.get((sym, p), (day, ex)), (day, ex))
    out: dict[str, list[str]] = {}
    for (sym, p), (_, ex) in latest.items():
        if ex == ex_day.isoformat():
            out.setdefault(sym, []).append(p)
    return {s: sorted(v) for s, v in out.items()}


_bc_index: dict[date, dict[tuple[str, str], list[str]]] = {}


def _notice_index(day: date) -> dict[tuple[str, str], list[str]]:
    """(symbol, ex-date) -> purposes for one day's notices (a dict lookup instead of filtering a
    DataFrame for every price jump). Only definite answers are kept; a failed download is retried."""
    if day in _bc_index:
        return _bc_index[day]
    bc = fetch_bc(day)
    idx: dict[tuple[str, str], set[str]] = {}
    if bc is not None:
        for sym, ex, purpose in zip(bc["symbol"], bc["ex_date"], bc["purpose"]):
            idx.setdefault((sym, ex), set()).add(purpose)
    out = {k: sorted(v) for k, v in idx.items()}
    if bc is not None or day in _bc_memo:
        _bc_index[day] = out
    return out


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
