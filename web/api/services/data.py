"""Read-only loaders for every file the API serves from. No function here touches the network.

The NSE/universe caches are read directly (never through scanner.universe.get_universe,
scanner.events.upcoming_results / trading_holidays or scanner.nse.index_history, which fetch from NSE
when their cache is stale).
"""
from __future__ import annotations

import functools
import json
import re
import sqlite3
from contextlib import closing
import time
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from scanner.providers import INDEX_SYMBOLS

from ..caches import FileCache, KeyedCache, TTLCache, file_key, register
from ..paths import P


# ------------------------------------------------------------------ json / yaml
def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _read_latest(path: Path):
    r = _read_json(path)
    return r if isinstance(r, dict) and r.get("version") == 2 else None


_latest = register(FileCache(_read_latest))
_intraday = register(FileCache(_read_json))
_intraday_signals = register(FileCache(_read_json))
_config = register(FileCache(lambda p: yaml.safe_load(p.read_text(encoding="utf-8")) or {}, missing={}))
_meta = register(FileCache(_read_json, missing={}))


def latest() -> dict | None:
    """data/results/latest.json (version 2) or None."""
    return _latest.get(P.latest)


def intraday() -> dict | None:
    return _intraday.get(P.intraday)


def intraday_signals() -> dict | None:
    return _intraday_signals.get(P.intraday_signals)


def config() -> dict:
    return _config.get(P.config) or {}


def store_meta() -> dict:
    return _meta.get(P.store / "meta.json") or {}


def read_json_file(path: Path) -> dict | None:
    try:
        return _read_json(path)
    except Exception:
        return None


# ------------------------------------------------------------------ parquet artifacts
_curves = register(FileCache(lambda p: pd.read_parquet(p)))
_trades = register(FileCache(lambda p: pd.read_parquet(p)))
_screener = register(FileCache(lambda p: pd.read_parquet(p)))
_index_hist = register(FileCache(lambda p: pd.read_parquet(p)))


def curves() -> pd.DataFrame | None:
    """curves.parquet, unless it carries a scan_id (df.attrs) from another scan than latest.json. Files without
    the attr (older scans, test fixtures) are still accepted."""
    df = _curves.get(P.curves)
    if df is None:
        return None
    sid = df.attrs.get("scan_id")
    lt = latest() if sid is not None else None
    if sid is not None and lt is not None and str(sid) != str(lt.get("generated_at")):
        return None
    return df


def _artifact(cache: FileCache, path: Path) -> pd.DataFrame | None:
    """An artifact is used only if it was written by the same scan as latest.json (scan_id column);
    a scan from another checkout rewrites latest.json without it, and stale rows must never be mixed in."""
    df = cache.get(path)
    lt = latest()
    if df is None or lt is None or "scan_id" not in df.columns:
        return None
    ids = df["scan_id"].unique()
    if len(df) and (len(ids) != 1 or str(ids[0]) != str(lt.get("generated_at"))):
        return None
    return df


def trades() -> pd.DataFrame | None:
    return _artifact(_trades, P.trades)


def screener() -> pd.DataFrame | None:
    return _artifact(_screener, P.screener)


def index_history() -> pd.DataFrame | None:
    df = _index_hist.get(P.index_history)
    if df is not None and not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index)
    return df


# ------------------------------------------------------------------ universe
def _read_universe(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype=str).fillna("")


_universe = register(FileCache(_read_universe))


def universe_name() -> str:
    return str(config().get("universe") or "nifty500").lower()


def universe() -> pd.DataFrame:
    """The cached universe csv (symbol, company, industry), never downloaded here."""
    df = _universe.get(P.universe(universe_name()))
    if df is None:
        return pd.DataFrame(columns=["symbol", "company", "industry"])
    return df


def symbol_meta() -> dict[str, dict]:
    """symbol -> {company, industry} from the universe csv plus every name seen in latest.json."""
    return _meta_cache.get((file_key(P.universe(universe_name())), file_key(P.latest)), _build_meta)


def _build_meta() -> dict[str, dict]:
    out: dict[str, dict] = {}
    lt = latest() or {}
    rows = []
    for s in lt.get("strategies", []) + lt.get("rejected_strategies", []):
        rows += s.get("positions", []) + s.get("actions", []) + s.get("ranking", [])
    rows += lt.get("gainers", []) + lt.get("losers", []) + lt.get("volume_spikes", [])
    for r in rows:
        if r.get("symbol") and (r.get("company") or r.get("industry")):
            out.setdefault(r["symbol"], {"company": r.get("company") or None, "industry": r.get("industry") or None})
    for r in universe().itertuples(index=False):
        out[r.symbol] = {"company": r.company or None, "industry": r.industry or None}
    return out


_meta_cache = register(KeyedCache(2))


def etfs() -> list[str]:
    return [str(e).upper() for e in (config().get("etfs") or [])]


INDEX_NAMES = {"NIFTY50": "Nifty 50", "NIFTY500": "Nifty 500", "INDIAVIX": "India VIX"}


def symbol_kind(sym: str) -> str:
    if sym in INDEX_SYMBOLS:
        return "index"
    return "etf" if sym in set(etfs()) else "stock"


# ------------------------------------------------------------------ price store (read-only, no mmap)
_store_version = register(TTLCache(2.0))
_store = register(KeyedCache(1))


def store_version() -> str:
    def read():
        cur = P.store / "CURRENT"
        try:
            return cur.read_text(encoding="utf-8").strip() or "legacy"
        except OSError:
            return "none"
    return _store_version.get(read)


def store() -> dict[str, pd.DataFrame]:
    """The completed-day price store (one wide frame per field). ~50 MB, cached per store generation."""
    def load():
        from scanner.store import PanelStore
        return PanelStore().load()
    return _store.get(store_version(), load)


def store_close() -> pd.DataFrame:
    return store()["close"]


def store_size_mb() -> float:
    cur = P.store / "CURRENT"
    try:
        folder = P.store / cur.read_text(encoding="utf-8").strip()
        return round(sum(f.stat().st_size for f in folder.iterdir() if f.is_file()) / 1e6, 1)
    except OSError:
        return 0.0


# ------------------------------------------------------------------ NSE caches (read directly)
_MONTHS = {m: i for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov",
                                        "dec"), 1)}


@functools.lru_cache(maxsize=8192)
def _nse_date(text) -> date:
    """'23-Oct-2026' -> date. Hand-parsed and memoised: strptime/pd.to_datetime per row (tens of thousands of
    rows in the results calendar) cost seconds; NSE uses the same few hundred date strings."""
    try:
        d, m, y = str(text or "").strip().split("-")
        return date(int(y), _MONTHS[m[:3].lower()], int(d))
    except (KeyError, ValueError) as e:
        raise ValueError(f"bad NSE date {text!r}") from e


_listing = register(KeyedCache(4))


def _nse_files(pattern: str) -> list[Path]:
    """Sorted data/nse/<pattern> (data/nse holds thousands of files: listed at most every 2 minutes)."""
    bucket = int(time.monotonic() // 120)
    return _listing.get((str(P.nse), pattern, bucket), lambda: sorted(P.nse.glob(pattern)))


def holidays(year: int) -> dict[str, str] | None:
    """{ISO date: description} from data/nse/holidays_<year>.json ('CM' = equity segment), or None."""
    path = P.nse / f"holidays_{year}.json"
    key = file_key(path)
    if key[1] is None:
        return None
    try:
        return _holidays.get(key, lambda: _parse_holidays(path))
    except Exception:
        return None


def _parse_holidays(path: Path) -> dict[str, str]:
    raw = _read_json(path)
    out = {}
    for r in raw.get("CM", []) if isinstance(raw, dict) else []:
        try:
            d = _nse_date(r.get("tradingDate"))
        except (ValueError, TypeError):
            continue
        out[d.isoformat()] = str(r.get("description") or "Holiday")
    return out


_holidays = register(KeyedCache(8))


def events_file() -> Path | None:
    """The newest data/nse/events_YYYYMMDD.json (upcoming results/board meetings)."""
    files = _nse_files("events_*.json")
    return files[-1] if files else None


def _parse_events(path: Path) -> list[dict]:
    rows = _read_json(path)
    out = []
    for r in rows if isinstance(rows, list) else []:
        purpose = str(r.get("purpose") or "")
        if "result" not in purpose.lower():
            continue
        try:
            d = _nse_date(r.get("date"))
        except (ValueError, TypeError):
            continue
        out.append({"symbol": str(r.get("symbol", "")).strip(), "company": r.get("company"),
                    "purpose": purpose, "date": d.isoformat()})
    return out


_events = register(FileCache(_parse_events, missing=[]))


def results_events() -> tuple[list[dict], str | None]:
    f = events_file()
    if f is None:
        return [], None
    m = re.search(r"events_(\d{8})", f.name)
    cached_on = f"{m.group(1)[:4]}-{m.group(1)[4:6]}-{m.group(1)[6:]}" if m else None
    return _events.get(f) or [], cached_on


def past_results(symbol: str) -> list[str]:
    """Past results dates of `symbol` from the monthly data/nse/results_YYYYMM.json caches."""
    return _past_results_index().get(symbol, [])


def _past_results_index() -> dict[str, list[str]]:
    files = _nse_files("results_*.json")
    key = tuple(file_key(f) for f in files[-120:])
    return _past_cache.get(key, lambda: _build_past(files[-120:]))


def _build_past(files) -> dict[str, list[str]]:
    out: dict[str, set] = {}
    for f in files:
        try:
            rows = _read_json(f)
        except Exception:
            continue
        for r in rows if isinstance(rows, list) else []:
            if "result" not in str(r.get("purpose", "")).lower():
                continue
            try:
                d = _nse_date(r.get("date"))
            except (ValueError, TypeError):
                continue
            out.setdefault(str(r.get("symbol", "")).strip(), set()).add(d.isoformat())
    return {k: sorted(v) for k, v in out.items()}


_past_cache = register(KeyedCache(1))


# ------------------------------------------------------------------ holdings / journal / status
def _load_holdings(_path=None) -> pd.DataFrame:
    from scanner.holdings import load_holdings
    return load_holdings()


_holdings = register(FileCache(_load_holdings))


def holdings_df() -> pd.DataFrame:
    """holdings.csv as scanner.holdings.load_holdings() parses it (cached by file; do not mutate)."""
    df = _holdings.get(P.holdings)
    return df if df is not None else _load_holdings()


def holdings_qty() -> dict[str, float]:
    """symbol -> total quantity held. A symbol on several rows (lots bought at different prices) is summed; None
    when no row of it has a quantity."""
    df = holdings_df()
    out: dict[str, float | None] = {}
    for r in df.itertuples(index=False):
        q = r.qty
        q = float(q) if q is not None and not (isinstance(q, float) and np.isnan(q)) else None
        prev = out.get(r.symbol)
        out[r.symbol] = q if prev is None else (prev if q is None else prev + q)
    return out


def journal_info() -> dict | None:
    return _journal.get(P.journal)


def _read_journal(path: Path) -> dict | None:
    with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)) as con:
        try:
            n, first, last = con.execute("SELECT COUNT(DISTINCT date), MIN(date), MAX(date) FROM scans").fetchone()
        except sqlite3.DatabaseError:
            return None
    return {"days": int(n or 0), "first": first, "last": last} if n else None


_journal = register(FileCache(_read_journal))


def status_file() -> dict:
    return read_json_file(P.status) or {}
