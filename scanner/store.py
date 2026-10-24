"""Consolidated price store: one wide parquet file per field (rows = dates, columns = symbols).

Where the data comes from
  Deep history (first run, new symbols) : Yahoo Finance bulk download - fast, split-adjusted.
  Every completed trading day           : NSE's official end-of-day files (nse.py) - exact OHLCV,
                                          delivery %, and the official previous close.
  Today's forming candle                : Fyers real-time quotes when logged in, else Yahoo (delayed).

Splits / bonus issues: NSE's corporate-action notices give the ratio (corporate.py). On the ex-date
the stock's whole earlier history is rescaled by that exact factor - so a 1:2 split never shows up
as a fake 50% crash. NSE's day file states the raw (unadjusted) previous close.
Only completed days are saved; the live candle is kept in memory only.
"""
from __future__ import annotations

import json
import os
import shutil
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

import numpy as np
import pandas as pd

from . import corporate, events, nse
from .fyers_limits import FyersRateLimited
from .providers import COLS, INDEX_SYMBOLS, FyersAuthError, YahooProvider
from .settings import HISTORY_DIR, SESSION_START, ist_now, ist_today

STORE_DIR = HISTORY_DIR / "store"
FIELDS = COLS + ["deliv_pct"]
FULL_SLACK_DAYS = 30
NSE_MAX_DAYS = 60           # beyond this gap, catch up with Yahoo first
CA_TOLERANCE = 0.015        # ignore adjustment factors within 1.5% of 1 (rounding / source noise)
RETRY_FAILED_AFTER_DAYS = 3
NSE_PUBLISH_HOUR = 18       # don't look for today's NSE file before ~6 PM IST
# 2: missing NSE sessions added, NSE fills converted to our price units, gaps compared like for like.
# A store repaired by an older version is downloaded again once (its history may hold wrong
# "data corrections" that can't be undone in place).
REPAIR_VERSION = 2


class PanelStore:
    def __init__(self):
        STORE_DIR.mkdir(parents=True, exist_ok=True)
        self.meta_path = STORE_DIR / "meta.json"
        self.meta: dict = {"symbols": {}, "failed": {}, "holidays": [], "corporate_actions": []}
        if self.meta_path.exists():
            try:
                self.meta.update(json.loads(self.meta_path.read_text(encoding="utf-8")))
            except Exception:
                pass

    # Each save writes a complete new generation folder, then atomically repoints CURRENT at it,
    # so readers always see one consistent set of files (never half old, half new).
    def _generations(self) -> list:
        return sorted((p for p in STORE_DIR.glob("gen_*") if p.is_dir()), reverse=True)

    def _read(self, folder) -> dict[str, pd.DataFrame]:
        if (folder / "dates.npy").exists():   # fast format: raw arrays sharing one date/symbol axis
            dates = pd.DatetimeIndex(np.load(folder / "dates.npy").astype("datetime64[ns]"), name="date")
            cols = pd.Index(json.loads((folder / "symbols.json").read_text(encoding="utf-8")))
            return {f: pd.DataFrame(np.load(folder / f"{f}.npy"), index=dates, columns=cols) for f in FIELDS}
        frames = {}
        for f in FIELDS:                     # older parquet generations
            p = folder / f"{f}.parquet"
            frames[f] = pd.read_parquet(p) if p.exists() else pd.DataFrame(index=pd.DatetimeIndex([], name="date"))
        return frames

    def load(self) -> dict[str, pd.DataFrame]:
        current = STORE_DIR / "CURRENT"
        candidates = []
        if current.exists():
            candidates.append(STORE_DIR / current.read_text(encoding="utf-8").strip())
        candidates += [g for g in self._generations() if g not in candidates]
        candidates.append(STORE_DIR)  # legacy layout (files directly in the store folder)
        for folder in candidates:
            try:
                if (folder / "dates.npy").exists() or (folder / "close.parquet").exists():
                    return self._read(folder)
            except Exception:
                continue  # damaged generation: fall back to the previous one
        return {f: pd.DataFrame(index=pd.DatetimeIndex([], name="date")) for f in FIELDS}

    def save(self, frames: dict[str, pd.DataFrame]) -> None:
        name = f"gen_{ist_now():%Y%m%d_%H%M%S}_{os.getpid()}"
        folder = STORE_DIR / name
        folder.mkdir(parents=True, exist_ok=True)
        dates = frames["close"].index
        cols = frames["close"].columns
        for f in FIELDS:
            dates, cols = dates.union(frames[f].index), cols.union(frames[f].columns)
        np.save(folder / "dates.npy", dates.values.astype("datetime64[ns]").astype("int64"))
        (folder / "symbols.json").write_text(json.dumps(list(cols)), encoding="utf-8")
        for f in FIELDS:
            np.save(folder / f"{f}.npy", frames[f].reindex(index=dates, columns=cols).to_numpy(dtype=float))
        tmp = STORE_DIR / f"CURRENT.{os.getpid()}.tmp"
        tmp.write_text(name, encoding="utf-8")
        _replace(tmp, STORE_DIR / "CURRENT")
        self.save_meta()
        for old in self._generations()[2:]:          # keep the newest two generations
            shutil.rmtree(old, ignore_errors=True)
        for legacy in STORE_DIR.glob("*.parquet"):     # files from the old single-folder layout
            legacy.unlink(missing_ok=True)

    def version(self) -> str:
        current = STORE_DIR / "CURRENT"
        return current.read_text(encoding="utf-8").strip() if current.exists() else ""

    def save_meta(self) -> None:
        tmp = STORE_DIR / f"meta.{os.getpid()}.tmp"
        tmp.write_text(json.dumps(self.meta, indent=0), encoding="utf-8")
        _replace(tmp, self.meta_path)


def _replace(src, dst, tries: int = 10) -> None:
    """os.replace with retries: on Windows it fails while another process has the target open."""
    for i in range(tries):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if i == tries - 1:
                raise
            time.sleep(0.2 * (i + 1))


def _clean(df: pd.DataFrame) -> pd.DataFrame:
    """Positive closes, high/low consistent with open/close, no NaN volume."""
    df = df[df["close"] > 0].copy()
    df["volume"] = df["volume"].fillna(0)
    for c in ("open", "high", "low"):
        df[c] = df[c].where(df[c] > 0, df["close"])
    df["high"] = df[["open", "high", "low", "close"]].max(axis=1)
    df["low"] = df[["open", "high", "low", "close"]].min(axis=1)
    return df


def _merge(frames: dict, new: dict[str, pd.DataFrame], replace_cols: set[str] = frozenset()) -> None:
    """Merge wide frames `new` into `frames` in place; new values win, `replace_cols` are rebuilt."""
    # Plain numpy overwrite: much faster than DataFrame.combine_first on wide frames.
    for f in FIELDS:
        if f not in new or new[f].empty:
            continue
        base = frames[f].drop(columns=[c for c in replace_cols if c in frames[f].columns])
        idx = pd.DatetimeIndex(base.index.union(new[f].index), name="date")
        cols = base.columns.union(new[f].columns)
        arr = base.reindex(index=idx, columns=cols).to_numpy(dtype=float, copy=True)
        upd = new[f].reindex(index=idx, columns=cols).to_numpy(dtype=float)
        has = ~np.isnan(upd)
        arr[has] = upd[has]
        frames[f] = pd.DataFrame(arr, index=idx, columns=cols)


def _wide(per_symbol: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    return {f: pd.DataFrame({s: df[f] for s, df in per_symbol.items() if f in df.columns}) for f in COLS}


def _days(start: date, end: date) -> list[date]:
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


def _fill_from_yahoo(frames: dict, yahoo: YahooProvider, syms: list[str], days: list[date],
                     provisional: set[str], log=print) -> bool:
    """Temporarily fill trading days NSE hasn't published (or is blocking) from Yahoo. The days are
    remembered as provisional and replaced by NSE's official file as soon as it is available."""
    start, end = min(days), max(days)
    got = yahoo.history(syms, {s: start for s in syms}, end)
    wanted = pd.DatetimeIndex([pd.Timestamp(d) for d in days])
    rows = {s: _clean(df.loc[df.index.isin(wanted)]) for s, df in got.items() if len(df)}
    rows = {s: df for s, df in rows.items() if len(df)}
    if not rows:
        return False
    _merge(frames, _wide(rows))
    filled = sorted({d.date().isoformat() for df in rows.values() for d in df.index})
    provisional.update(filled)
    log(f"Filled {len(filled)} day(s) from Yahoo while NSE data is unavailable: {', '.join(filled)}")
    return True


def _apply_corporate_action(frames: dict, sym: str, before: pd.Timestamp, factor: float) -> None:
    mask = frames["close"].index < before
    for f in ("open", "high", "low", "close"):
        frames[f].loc[mask, sym] = frames[f].loc[mask, sym] * factor
    frames["volume"].loc[mask, sym] = frames["volume"].loc[mask, sym] / factor


GAP_SUSPECT = 0.20          # overnight move >20% => check NSE for a split/bonus/demerger
FILL_MAX_GAP = 0.05         # a stock that opened 5%+ away from its previous close is not filled from NSE:
                            # it may be a split/bonus ex-date, and a gap beats a price in the wrong units


def _repair_history(frames: dict, syms: list[str], log=print, holidays: set[str] | None = None) -> dict:
    """Fix known defects in downloaded (Yahoo) history using NSE's official day files:
      1. fake flat bars (O=H=L=C, zero volume) are removed, and dates without a single stock price
         (Yahoo lists 15 Jan 2026, an NSE holiday);
      2. NSE sessions our source lacks entirely (Budget-day, Saturday and Muhurat sessions, a few
         regular days) are added: every calendar day in the stored range that isn't known either way
         is checked against NSE once (needs `holidays`, which collects the definite non-trading days);
      3. days a stock traded on NSE but has no price here are filled from NSE's files, converted to
         our price units (see _fill_from_nse);
      4. overnight gaps >20% are checked against NSE and, where a split / bonus / demerger (or a wrong
         price in our source) explains them, the earlier history is rescaled by the exact factor."""
    eq = [s for s in syms if s in frames["close"].columns and s not in INDEX_SYMBOLS]
    report = {"flat_bars": 0, "empty_rows": 0, "sessions_added": [], "filled_days": 0, "filled_prices": 0,
              "adjusted": []}
    if not eq:
        return report
    flat = (frames["volume"][eq] == 0) & (frames["high"][eq] == frames["low"][eq])
    report["flat_bars"] = int(flat.to_numpy().sum())
    if report["flat_bars"]:
        for f in COLS:
            frames[f][eq] = frames[f][eq].mask(flat)
    report["empty_rows"] = _drop_empty_rows(frames)
    if holidays is not None:
        report["sessions_added"] = _add_missing_sessions(frames, holidays, log)
    report["filled_days"], report["filled_prices"] = _fill_from_nse(frames, eq)

    close = frames["close"][eq]
    prev = close.ffill().shift(1)
    gaps = (((frames["open"][eq] / prev - 1).abs() > GAP_SUSPECT)
            | ((close / prev - 1).abs() > GAP_SUSPECT)) & close.notna()
    events = sorted((close.index[i], eq[j]) for i, j in zip(*np.nonzero(gaps.to_numpy())))
    if events:
        files = nse.fetch_days(sorted({d.date() for d, _ in events}))
        look = {d: _notice_days(close.index, d) for d, _ in events}
        with ThreadPoolExecutor(max_workers=4) as ex:   # warm the corporate-action notice cache
            list(ex.map(corporate.fetch_bc, sorted({x for days in look.values() for x in days})))
        # Oldest first, so each factor is computed in the units of the not-yet-adjusted history.
        for d, s in events:
            adj = _event_factor(frames, s, d, files.get(d.date()), look[d])
            if adj:
                _apply_corporate_action(frames, s, d, adj["factor"])
                report["adjusted"].append(adj)
    return report


def _drop_empty_rows(frames: dict) -> int:
    """Remove dates without a single stock price (not a trading day, e.g. a holiday Yahoo lists)."""
    stocks = [c for c in frames["close"].columns if c not in INDEX_SYMBOLS]
    empty = frames["close"][stocks].isna().all(axis=1)
    if not empty.any():
        return 0
    for f in FIELDS:
        frames[f] = frames[f][~empty.reindex(frames[f].index, fill_value=False)]
    return int(empty.sum())


SESSION_CHECKS_PER_RUN = 150   # NSE blocks bursts of requests: unknown days are checked a batch per run


def _session_priority(d: date) -> tuple:
    """Likeliest missing sessions first: weekdays, Budget day (1 Feb), weekends in the Diwali
    (Muhurat) season; then other weekends, newest first."""
    likely = d.weekday() < 5 or (d.month, d.day) == (2, 1) or (10, 15) <= (d.month, d.day) <= (11, 20)
    return (not likely, -d.toordinal())


def _add_missing_sessions(frames: dict, holidays: set[str], log=print) -> list[str]:
    """Add NSE sessions inside the stored date range that our dates lack. Every calendar day not in
    the store and not a known non-trading day is checked against NSE's archive once (the answers are
    remembered in `holidays`): days whose NSE file is already cached (e.g. by the point-in-time
    build) at once, the others SESSION_CHECKS_PER_RUN per run. New sessions get NSE's index values
    and empty stock rows, which _fill_from_nse fills. Returns the added days."""
    idx = frames["close"].index
    if not len(idx):
        return []
    have = {d.date() for d in idx}
    todo = [d for d in _days(idx[0].date(), idx[-1].date()) if d not in have and d.isoformat() not in holidays]
    if not todo:
        return []
    cached = [d for d in todo if (nse.NSE_DIR / f"stocks_{d:%Y%m%d}.parquet").exists()]
    rest = sorted(set(todo) - set(cached), key=_session_priority)
    todo = cached + rest[:SESSION_CHECKS_PER_RUN]
    if len(rest) > 20:
        log(f"Checking {min(len(rest), SESSION_CHECKS_PER_RUN)} of {len(rest)} unchecked calendar days against "
            "NSE's archive for sessions missing from the price history...")
    files = nse.fetch_days(todo, workers=2)
    today, new = ist_today(), []
    for d, fl in sorted(files.items()):
        if fl.status == "ok":
            new.append(d)
        elif fl.status == "holiday" or (fl.status == "missing" and (today - d).days > 3):
            holidays.add(d.isoformat())       # NSE has no file for it: not a trading day
    if new:
        rows = pd.DatetimeIndex([pd.Timestamp(d) for d in new], name="date")
        add = {f: pd.DataFrame(np.nan, index=rows, columns=frames[f].columns) for f in FIELDS}
        for d, ts in zip(new, rows):
            for s in INDEX_SYMBOLS:
                r = nse.index_row(files[d], s)
                if r is not None:
                    for f in COLS:
                        if s in add[f].columns:
                            add[f].at[ts, s] = float(r[f])
        _merge(frames, add)
        log(f"Added {len(new)} NSE trading session(s) missing from the downloaded history: "
            f"{', '.join(d.isoformat() for d in new)}")
    return [d.isoformat() for d in new]


def _fill_from_nse(frames: dict, eq: list[str]) -> tuple[int, int]:
    """Fill days a stock traded on NSE but has no price here (a session our source lacks, a fake bar
    that was removed, a gap in one stock's download) from NSE's day files. NSE's prices are raw while
    ours are back-adjusted for later splits/bonuses, so each fill is converted to our units with the
    ratio of our previous price to NSE's close on that same day. A stretch of holes is filled oldest
    first and stops where a split/bonus may have changed the units: an opening gap of 5%+ (a possible
    ex-date) or a day without an NSE file. Returns (days with fills, prices filled)."""
    if not len(frames["close"]):
        return 0, 0
    close = frames["close"].reindex(columns=eq)
    idx = close.index
    present = close.notna().to_numpy()
    listed = np.logical_or.accumulate(present, axis=0) & np.logical_or.accumulate(present[::-1], axis=0)[::-1]
    holes = listed & ~present
    rows = np.flatnonzero(holes.any(axis=1))
    if not len(rows):
        return 0, 0
    pos = np.arange(len(idx), dtype=float)[:, None]
    prev_row = pd.DataFrame(np.where(present, pos, np.nan)).ffill().shift(1).to_numpy()  # last price before
    before = {int(x) for x in np.unique(prev_row[holes]) if x >= 0}
    files = nse.fetch_days(sorted({idx[i].date() for i in rows} | {idx[i].date() for i in before}))

    def nse_close(i: int, s: str) -> float | None:
        fl = files.get(idx[i].date())
        sym = corporate.symbol_on(s, idx[i].date())
        if fl is None or fl.status != "ok" or sym not in fl.stocks.index:
            return None
        c = float(fl.stocks.at[sym, "close"])
        return c if c > 0 else None

    arr = {f: frames[f].reindex(index=idx, columns=eq).to_numpy(dtype=float, copy=True) for f in FIELDS}
    out = {f: np.full(holes.shape, np.nan) for f in FIELDS}
    last_fill = np.full(len(eq), -1)
    blocked = np.full(len(eq), -1)       # last hole where the units may have changed
    n_days = n_prices = 0
    for i in rows:
        d = idx[i].date()
        js = np.flatnonzero(holes[i])
        fl = files.get(d)
        if fl is None or fl.status != "ok":
            blocked[js] = i
            continue
        got = 0
        for j in js:
            p = int(max(prev_row[i, j], last_fill[j]))
            if blocked[j] > p:
                continue
            sym = corporate.symbol_on(eq[j], d)
            if sym not in fl.stocks.index:
                continue                 # didn't trade on NSE that day
            r = fl.stocks.loc[sym]
            pc, o, c = float(r["prev_close"]), float(r["open"]), float(r["close"])
            if not (pc > 0 and c > 0) or (o > 0 and abs(o / pc - 1) > FILL_MAX_GAP) or abs(c / pc - 1) > GAP_SUSPECT:
                blocked[j] = i
                continue
            k = arr["close"][p, j] / (nse_close(p, eq[j]) or pc)
            for f in ("open", "high", "low", "close"):
                v = float(r[f])
                out[f][i, j] = arr[f][i, j] = (v if v > 0 else c) * k
            out["volume"][i, j] = arr["volume"][i, j] = float(r["volume"]) / k
            out["deliv_pct"][i, j] = float(r["deliv_pct"])
            last_fill[j] = i
            got += 1
        n_days += got > 0
        n_prices += got
    if n_prices:
        _merge(frames, {f: pd.DataFrame(v, index=idx, columns=eq) for f, v in out.items()})
    return n_days, n_prices


def _prior_days(frames: dict, ts: pd.Timestamp, n: int = 3) -> list[date]:
    idx = frames["close"].index
    return [x.date() for x in idx[idx < ts][-n:][::-1]]


def _notice_days(idx: pd.DatetimeIndex, ts: pd.Timestamp, before: int = 3, after: int = 2) -> list[date]:
    """NSE notice files to look in for actions with ex-date `ts`, most telling first (as pit._adjust
    does): the ex-date's own file, the trading day before, the day after, then further out. NSE lists
    most actions a few days ahead, some first on the ex-date itself or only the day after."""
    b = [x.date() for x in idx[idx < ts][-before:][::-1]]
    a = [x.date() for x in idx[idx > ts][:after]]
    return [ts.date(), *b[:1], *a[:1], *b[1:], *a[1:]]


def _nse_close(s: str, day: date) -> float | None:
    """NSE's official (raw) close of `s` on `day`, or None if unknown."""
    fl = nse.fetch_day(day)
    sym = corporate.symbol_on(s, day)
    if fl.status != "ok" or fl.stocks is None or sym not in fl.stocks.index:
        return None
    c = float(fl.stocks.at[sym, "close"])
    return c if c > 0 else None


CLEAN_RATIOS = sorted({1 / k for k in (2, 3, 4, 5, 6, 8, 10, 20, 25, 50, 100)}
                      | {2 / 5, 3 / 10, 2 / 7, 3 / 7, 2.0, 4.0, 5.0, 10.0})   # splits, bonuses, consolidations


def _rebased(ratio: float, open_gap: float) -> bool:
    """NSE re-based the price for a corporate action while the stock wasn't trading (CCAVENUE Oct
    2026: 13.83 -> base 138.30, a 10:1 consolidation with no notice): its previous close differs from
    the last close by a clean ratio (within 1%) and the stock opened near that base (within 20%).
    A base far from the opening price is a placeholder for price discovery after a long suspension
    (BCG 2025: base Rs 2, opened at Rs 21.80), not an adjustment."""
    near = min(CLEAN_RATIOS, key=lambda f: abs(ratio / f - 1))
    return abs(ratio / near - 1) <= 0.01 and abs(open_gap - 1) <= GAP_SUSPECT


def _event_factor(frames: dict, s: str, d: pd.Timestamp, fl, prior: list[date]) -> dict | None:
    """Factor to rescale `s`'s history before day `d` so that its move on `d` matches NSE's
    official move net of any corporate action. Works whether or not our source already adjusted:
        factor = our_move * ca_factor / official_move
      our_move      = our close(d) / our previous close
      official_move = NSE close(d) / NSE's close on the same previous day (raw)
      ca_factor     = from the NSE notice (bonus a:b -> b/(a+b), split Rs x->y -> y/x), or for a
                      demerger the special-session price: NSE open(d) / the same previous close; 1 if none.
    A genuine crash (no corporate action, our data = NSE) gives factor 1 and is left untouched.
    Both moves must span the same days. NSE's file gives the close of the stock's previous session,
    which may be later than our previous price (a session or a stretch our source lacks), so NSE's
    close on the day of our previous price is used. If that is unknown, only an action NSE lists is
    applied - a "data correction" is never made from moves over different periods (a real move on
    the missing day would look like a corporate action). Exceptions, where NSE's previous close is
    a base price it set for a corporate action: across a symbol change (it includes any share swap),
    and when it differs from the older close by a clean split/bonus ratio and the stock opened near
    it (see _rebased)."""
    if fl is None or fl.status != "ok":
        return None
    s_then = corporate.symbol_on(s, d.date())
    if s_then not in fl.stocks.index:
        return None
    row = fl.stocks.loc[s_then]
    ours = frames["close"][s].loc[:d].iloc[:-1].dropna()
    our_now = frames["close"].at[d, s]
    if ours.empty or not our_now > 0 or not row["close"] > 0 or not row["prev_close"] > 0:
        return None
    base = float(row["prev_close"])
    prev_day = ours.index[-1].date()
    if abs(float(ours.iloc[-1]) / base - 1) > 1e-3 and corporate.symbol_on(s, prev_day) == s_then:
        then = _nse_close(s, prev_day)    # our prices are not NSE's raw ones: check the same day
        if then is None or not _rebased(base / then, float(row["open"]) / base):
            base = then
    purposes = corporate.actions_on(s_then, d.date(), prior)
    if base is None:
        if not purposes:
            return None
        base = float(row["prev_close"])
    ca = 1.0
    if purposes:
        pf = corporate.purpose_factor(purposes)
        ca = pf if pf is not None else (float(row["open"]) / base if row["open"] > 0 else 1.0)
    our_move = float(our_now) / float(ours.iloc[-1])
    official_move = float(row["close"]) / base
    factor = our_move * ca / official_move
    if not (np.isfinite(factor) and factor > 0 and abs(factor - 1) > CA_TOLERANCE):
        return None
    return {"symbol": s, "date": d.date().isoformat(), "factor": round(factor, 6),
            "reason": " + ".join(purposes) if purposes else "data correction (matched to NSE)"}


def _check_listed_actions(frames: dict, d: date, fl, look: list[date] | None = None) -> list[dict]:
    """Adjust stored history for the splits / bonuses / demergers NSE lists with ex-date `d` (a day
    already in the store, `fl` its NSE file). Notices are looked up in several files around the
    ex-date (see _notice_days) and a moved ex-date counts only on its new date. Safe to repeat: an
    action that was already applied gives factor 1."""
    if fl is None or fl.status != "ok":
        return []
    ts = pd.Timestamp(d)
    look = look or _notice_days(frames["close"].index, ts)
    listed = corporate.listed_on(d, look)
    done = []
    for s in frames["close"].columns:
        if s in INDEX_SYMBOLS or corporate.symbol_on(s, d) not in listed or pd.isna(frames["close"].at[ts, s]):
            continue
        adj = _event_factor(frames, s, ts, fl, look)
        if adj:
            _apply_corporate_action(frames, s, ts, adj["factor"])
            done.append(adj)
    return done


def refresh_store(symbols: list[str], lookback_days: int, fyers=None, progress=None, log=print):
    """Bring the store up to date. Returns (frames incl. today's live row if any, info dict)."""
    yahoo = YahooProvider()
    store = PanelStore()
    meta = store.meta
    frames = store.load()
    today, now = ist_today(), ist_now()
    start_full = today - timedelta(days=lookback_days)
    all_syms = list(INDEX_SYMBOLS) + [s for s in dict.fromkeys(symbols) if s not in INDEX_SYMBOLS]
    holidays = set(meta.get("holidays", []))
    errors: dict[str, str] = {}
    corp_actions: list[dict] = []
    changed = False

    def recently_failed(s: str) -> bool:
        fl = meta["failed"].get(s)
        return bool(fl) and fl.get("count", 0) >= 2 and \
            (today - date.fromisoformat(fl["last_try"])).days < RETRY_FAILED_AFTER_DAYS

    def last_date(s: str) -> date | None:
        if s not in frames["close"].columns:
            return None
        i = frames["close"][s].last_valid_index()
        return i.date() if i is not None else None

    # 1) Deep history from Yahoo for new symbols, and catch-up for very stale ones. A store repaired
    #    by an older version is downloaded again once (see REPAIR_VERSION).
    old_repair = meta.get("repair_version", 0) < REPAIR_VERSION
    rebuild = old_repair and bool(len(frames["close"]))
    if rebuild:
        log("Rebuilding the price history once with the improved NSE repair (~3-6 min)...")
    starts: dict[str, date] = {}
    for s in all_syms:
        if recently_failed(s):
            continue
        m, last = meta["symbols"].get(s), last_date(s)
        if rebuild or not m or last is None or \
                date.fromisoformat(m["full_from"]) > start_full + timedelta(days=FULL_SLACK_DAYS):
            starts[s] = start_full
        elif (today - last).days > NSE_MAX_DAYS:
            starts[s] = last - timedelta(days=7)
    replace: set[str] = set()
    if starts:
        n_full = sum(1 for d in starts.values() if d == start_full)
        log(f"Downloading history for {len(starts)} symbols"
            f"{f' ({n_full} new - first run takes ~2-4 min)' if n_full > 20 and not rebuild else ''}...")
        fetched = yahoo.history(list(starts), starts, today, progress=progress)
        if yahoo.outage:
            log("Yahoo looks throttled/unavailable for part of the download - those symbols will be retried.")
        good = {}
        for s, df in fetched.items():
            df = df[df.index < pd.Timestamp(today)]  # today's row comes from NSE / live quotes
            if df.empty:
                errors[s] = yahoo.errors.get(s, "no data from Yahoo")
                if not yahoo.outage:  # don't blacklist symbols because of a provider outage
                    fl = meta["failed"].get(s, {})
                    meta["failed"][s] = {"count": fl.get("count", 0) + 1, "last_try": today.isoformat()}
                continue
            meta["failed"].pop(s, None)
            good[s] = _clean(df)
            if starts[s] == start_full:
                existing = frames["close"][s].count() if s in frames["close"].columns else 0
                if len(good[s]) >= 0.9 * existing:  # never swap a long history for a truncated one
                    replace.add(s)
                    meta["symbols"][s] = {"full_from": start_full.isoformat()}
        _merge(frames, _wide(good), replace)
        changed = bool(good)
        touched = list(good)
    else:
        touched = []

    # 1b) Repair downloaded history (fake bars, missing sessions and days, unadjusted splits) with NSE data.
    to_repair = all_syms if old_repair else touched
    if to_repair and len(frames["close"]):
        rep = _repair_history(frames, to_repair, log, holidays)
        if old_repair and not yahoo.outage:
            meta["repair_version"] = REPAIR_VERSION
            meta["repaired_v1"] = True        # read by older versions of this module
            # The old log described adjustments to the history that was just replaced.
            meta["corporate_actions"] = [c for c in meta.get("corporate_actions", []) if c["symbol"] not in replace]
        if rep["flat_bars"] or rep["empty_rows"] or rep["sessions_added"] or rep["filled_prices"] or rep["adjusted"]:
            log(f"History repaired: {rep['flat_bars']} fake bars removed, {rep['empty_rows']} empty dates dropped, "
                f"{len(rep['sessions_added'])} missing sessions added, {rep['filled_prices']} prices on "
                f"{rep['filled_days']} days filled from NSE, {len(rep['adjusted'])} splits/bonuses/demergers/"
                "data errors adjusted")
            corp_actions.extend(rep["adjusted"])
            changed = True

    # 2) Official NSE files for every completed trading day we're missing: days after the store's
    #    last date, plus any recent days that freshly downloaded symbols lack.
    lasts = [d for d in (last_date(s) for s in touched) if d and (today - d).days <= NSE_MAX_DAYS]
    if len(frames["close"]):
        lasts.append(frames["close"].index[-1].date())
    if rebuild:   # Yahoo's copy replaced the official prices of recent days: put NSE's back
        lasts.append(today - timedelta(days=NSE_MAX_DAYS))
    nse_status = "up to date"
    provisional = set(meta.get("provisional", []))   # days filled from Yahoo while NSE was unavailable
    if lasts:
        from_day = min(lasts) + timedelta(days=1)
        last_try_day = today if now.hour >= NSE_PUBLISH_HOUR else today - timedelta(days=1)
        # Every calendar day (weekends too: Diwali Muhurat / Budget-day sessions), minus known holidays,
        # plus provisional days so they get replaced by official data.
        days = sorted({d for d in _days(from_day, last_try_day) if d.isoformat() not in holidays}
                      | {date.fromisoformat(x) for x in provisional})
        if days:
            files = nse.fetch_days(days)
            ok_days = sorted(d for d, fl in files.items() if fl.status == "ok")
            unavailable = []
            for d, fl in files.items():
                if fl.status == "holiday" or (fl.status == "missing" and d.weekday() >= 5 and d < today):
                    holidays.add(d.isoformat())   # NSE served another day's file: no trading that day
                elif fl.status in ("missing", "error") and d.weekday() < 5 and (today - d).days >= 2:
                    unavailable.append(d)
            for d in ok_days:
                provisional.discard(d.isoformat())
            if unavailable:
                nse_status = (f"NSE file not available for {', '.join(x.isoformat() for x in unavailable)} - "
                              "using Yahoo for those days until it is")
                changed |= _fill_from_yahoo(frames, yahoo, all_syms, unavailable, provisional, log)
            for d in ok_days:
                fl = files[d]
                ts = pd.Timestamp(d)
                stocks = fl.stocks.reindex([s for s in all_syms if s not in INDEX_SYMBOLS])
                rows = {f: stocks[f] for f in FIELDS}
                for s in INDEX_SYMBOLS:
                    r = nse.index_row(fl, s)
                    if r is not None:
                        for f in COLS:
                            rows[f].loc[s] = r[f]
                day_frame = {f: pd.DataFrame([rows[f].astype(float)], index=pd.DatetimeIndex([ts], name="date"))
                             for f in FIELDS}
                _merge(frames, {f: v.dropna(axis=1, how="all") for f, v in day_frame.items()})
                changed = True
            # Corporate actions (split, bonus, demerger) with these ex-dates. NSE lists most a few days
            # ahead, some only on the ex-date or the day after, so the stored day before the first new
            # one is checked again now that a later notice file exists (a no-op if already adjusted).
            if ok_days:
                idx = frames["close"].index
                before = idx[idx < pd.Timestamp(ok_days[0])]
                recheck = [before[-1].date()] if len(before) and (ok_days[0] - before[-1].date()).days <= 7 else []
                for d in recheck + ok_days:
                    found = _check_listed_actions(frames, d, files[d] if d in files else nse.fetch_day(d))
                    corp_actions.extend(found)
                    changed |= bool(found)
            if ok_days and not unavailable:
                nse_status = f"NSE official data to {ok_days[-1].isoformat()}"

    # Non-trading days are remembered for the whole lookback, so the missing-session check in
    # _repair_history doesn't ask NSE about them again.
    meta["holidays"] = sorted(h for h in holidays if h >= (start_full - timedelta(days=7)).isoformat())
    meta["provisional"] = sorted(provisional)
    if corp_actions:
        log("Price history adjusted: " + ", ".join(f"{c['symbol']} {c['date']} x{c['factor']:.4g} ({c['reason']})" for c in corp_actions))
        meta["corporate_actions"] = (meta.get("corporate_actions", []) + corp_actions)[-300:]
    if changed:
        store.save(frames)
    else:
        store.save_meta()

    # 3) Today's live candle (memory only).
    complete_upto = frames["close"].index[-1].date() if len(frames["close"]) else None
    session_started = (now.hour, now.minute) >= SESSION_START
    trading_today = (today.weekday() < 5 and today.isoformat() not in holidays
                     and today.isoformat() not in events.trading_holidays(today.year))
    live_rows: dict[str, dict] = {}
    live_source = None
    if trading_today and session_started and complete_upto and today > complete_upto:
        if fyers is not None:
            try:
                for s, (qdate, row) in fyers.live_rows(all_syms).items():
                    if (qdate is None or qdate == today) and row.get("close"):
                        live_rows[s] = {c: float(row.get(c) or 0) for c in COLS}
                live_source = "Fyers (real-time)" if live_rows else None
            except FyersAuthError as e:
                log(f"Fyers session expired ({e}) - using Yahoo for live prices. Run 1_login.bat.")
                errors["fyers"] = "session expired - run 1_login.bat"
            except FyersRateLimited as e:
                log(f"{e} - using Yahoo for live prices.")
                errors["fyers"] = str(e)
        if not live_rows:
            recent = yahoo.history(all_syms, {s: today - timedelta(days=5) for s in all_syms}, today)
            for s, df in recent.items():
                if len(df) and df.index[-1].date() == today and df["close"].iloc[-1] > 0:
                    live_rows[s] = {c: float(df[c].iloc[-1]) for c in COLS}
            live_source = "Yahoo (~15 min delayed)" if live_rows else None
    out = frames
    if live_rows:
        ts = pd.Timestamp(today)
        out = {}
        for f in FIELDS:
            row = pd.DataFrame({s: [v.get(f, np.nan)] for s, v in live_rows.items()},
                               index=pd.DatetimeIndex([ts], name="date"))
            out[f] = pd.concat([frames[f], row]).sort_index()
            out[f].index.name = "date"

    info = {
        "complete_upto": complete_upto.isoformat() if complete_upto else None,
        "live_day": today.isoformat() if live_rows else None,
        "live_source": live_source,
        "live_count": len(live_rows),
        "nse_status": nse_status,
        "errors": errors,
        "corporate_actions": corp_actions,
        "skipped_failed": [s for s in all_syms if recently_failed(s)],
    }
    return out, info


def load_store() -> dict[str, pd.DataFrame]:
    return PanelStore().load()
