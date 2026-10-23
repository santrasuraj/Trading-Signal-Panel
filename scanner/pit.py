"""Point-in-time ("survivorship-free") backtest universe.

Why: a backtest on *today's* Nifty 500 list only contains companies that survived and grew. The ones
that collapsed, were merged away or delisted are missing, so every result is flattered (the average
stock in today's list made ~27%/yr in 2019-2026 while the real Nifty 500 index made ~14%/yr).

What this module builds (cached under data/history/pit/):
  1. every NSE equity on every trading day since Aug 2018, from NSE's official day files (nse.py),
     including companies that were later delisted, merged or suspended;
  2. renamed companies stitched into one history under their latest symbol (corporate.renames);
  3. the universe: on each day, the UNIVERSE_SIZE stocks with the highest average daily traded value
     (close x volume) over the previous ~6 months, using only data up to that day;
  4. prices adjusted for splits, bonus issues and demergers with NSE's corporate-action notices and
     the same factor logic as the main store (store._event_factor).

Daily scans append new days from the NSE cache. First build: `python -m scanner.pit build`
(downloads ~2,000 NSE day files, ~20-30 minutes). `python -m scanner.pit compare` prints the
current-list vs point-in-time comparison table.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, timedelta

import io
import zipfile

import bottleneck as bn
import numpy as np
import pandas as pd

from . import corporate, nse, store
from .settings import HISTORY_DIR, ist_now

PIT_DIR = HISTORY_DIR / "pit"
RAW_FILE = PIT_DIR / "raw.parquet"         # every NSE equity, every day, as published (long format)
NOTICES_FILE = PIT_DIR / "notices.parquet" # all cached corporate-action notice files in one table
ETF_FILE = PIT_DIR / "etf_symbols.json"
ETF_LIST_URL = "https://nsearchives.nseindia.com/content/equities/eq_etfseclist.csv"
VERSION = 1
UNIVERSE_SIZE = 500
TURNOVER_DAYS = 126       # ~6 months of trading days
MIN_HISTORY_DAYS = 21     # needs ~1 month of trading in that window (NSE's index rules use 1 month)
STALE_DAYS = 5            # not traded in the last 5 days -> not in the universe that day
EQUITY_SERIES = ("EQ", "BE", "BZ")          # REITs (RR) and InvITs (IV) are units, not shares
RAW_FIELDS = ("open", "high", "low", "close", "volume", "prev_close", "deliv_pct")
OUT_FIELDS = store.FIELDS                    # open, high, low, close, volume, deliv_pct
DOWN_GAP = 0.05           # opened this much below the previous close: check for a bonus/split too
# A >20% move with no NSE notice is still adjusted when (in this order):
#   1. the main store's Yahoo-adjusted history moved normally (<15%) between the same two days;
#   2. the opening gap is within 4% of a clean split/bonus ratio and the close agrees (within 10%);
#   3. the stock opened 60%+ lower (a special dividend / capital distribution): market-implied factor.
REFERENCE_NORMAL_MOVE = 0.15
CLEAN_FACTORS = sorted({1 / k for k in (2, 3, 4, 5, 6, 8, 10, 20, 25, 50, 100)}
                       | {2 / 5, 3 / 10, 2 / 7, 3 / 7, 2.0, 4.0, 5.0, 10.0})
DISTRIBUTION_GAP = 0.40
GIVE_UP_DAYS = 10         # a day file still unavailable this long after the day is skipped for good


@dataclass
class PitData:
    frames: dict[str, pd.DataFrame]   # adjusted daily prices, rows = dates, columns = symbols
    universe: pd.DataFrame            # True where the stock was in the universe that day
    info: dict

    @property
    def members(self) -> list[str]:
        """Every stock that was in the universe on at least one day."""
        return list(self.universe.columns[self.universe.any(axis=0).to_numpy()])


# --------------------------------------------------------------------------- raw NSE panel
def _day_rows(day: date, df: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame({f: df[f].to_numpy(dtype=float) for f in RAW_FIELDS})
    out.insert(0, "symbol", df.index.astype(str))
    out.insert(0, "date", pd.Timestamp(day).as_unit("ns"))
    out["equity"] = df["series"].isin(EQUITY_SERIES).to_numpy() if "series" in df.columns else True
    return out


def _load_raw() -> pd.DataFrame:
    if RAW_FILE.exists():
        raw = pd.read_parquet(RAW_FILE)
        raw["symbol"] = raw["symbol"].astype("category")
        return raw
    return pd.DataFrame(columns=["date", "symbol", *RAW_FIELDS, "equity"])


def update_raw(days: list[date], download: bool = True, log=print) -> pd.DataFrame:
    """Raw long table (date, symbol, prices, equity) for `days`, adding days missing from the cache
    from NSE's day files (downloaded if needed). Reading thousands of small files is slow on Windows,
    so they are consolidated into one file once."""
    PIT_DIR.mkdir(parents=True, exist_ok=True)
    raw = _load_raw()
    meta = _read_json(PIT_DIR / "raw_meta.json", {"skip": []})
    have = set(pd.DatetimeIndex(np.unique(raw["date"].to_numpy())).date) if len(raw) else set()
    skip = set(meta["skip"])
    need = [d for d in days if d not in have and d.isoformat() not in skip]
    if not need:
        return raw
    missing = [d for d in need if not (nse.NSE_DIR / f"stocks_{d:%Y%m%d}.parquet").exists()]
    if missing and download:
        log(f"Downloading {len(missing)} NSE day files (4 at a time)...")
        t0 = time.perf_counter()
        for i in range(0, len(missing), 100):
            part = missing[i:i + 100]
            got = nse.fetch_days(part, workers=4)
            for d, fl in got.items():
                if fl.status in ("missing", "holiday") and (date.today() - d).days > GIVE_UP_DAYS:
                    skip.add(d.isoformat())
            log(f"  {i + len(part)}/{len(missing)} files ({time.perf_counter() - t0:.0f}s)")
    parts, t0 = [], time.perf_counter()
    for i, d in enumerate(need):
        path = nse.NSE_DIR / f"stocks_{d:%Y%m%d}.parquet"
        if path.exists():
            parts.append(_day_rows(d, pd.read_parquet(path)))
        if len(need) > 200 and (i + 1) % 250 == 0:
            log(f"  read {i + 1}/{len(need)} day files ({time.perf_counter() - t0:.0f}s)")
    if parts:
        if len(raw):
            raw["symbol"] = raw["symbol"].astype(object)
        raw = pd.concat([raw, *parts], ignore_index=True) if len(raw) else pd.concat(parts, ignore_index=True)
        raw["date"] = raw["date"].astype("datetime64[ns]")
        raw["symbol"] = raw["symbol"].astype("category")       # symbols as integer codes: much faster
        raw = raw.sort_values(["date", "symbol"], kind="stable").reset_index(drop=True)
        raw["equity"] = raw["equity"].astype(bool)
        tmp = RAW_FILE.with_suffix(f".{os.getpid()}.tmp")
        raw.to_parquet(tmp, index=False)
        store._replace(tmp, RAW_FILE)
    meta["skip"] = sorted(skip)
    _write_json(PIT_DIR / "raw_meta.json", meta)
    return raw


# --------------------------------------------------------------------------- ETFs
def _etf_day(day: date) -> set[str] | None:
    """Symbols in the ETF file of that day's notice archive (None if it could not be read)."""
    code, body = nse._get_bytes(corporate.PR_URL.format(d=day.strftime("%d%m%y")))
    if code == 404:
        return set()
    if code != 200:
        return None
    try:
        z = zipfile.ZipFile(io.BytesIO(body))
        name = next((n for n in z.namelist() if n.lower().startswith("etf")), None)
        if name is None:
            return set()
        df = pd.read_csv(z.open(name), dtype=str)
        return {x.strip() for x in df.iloc[:, 2].dropna()}
    except Exception:
        return None


def etf_symbols(dates: pd.DatetimeIndex, log=print) -> set[str]:
    """ETFs (gold, silver, liquid, index and bond funds) trade as series EQ in NSE's day files, and
    the busiest ones would rank among the most-traded "stocks" - but they are funds, not companies,
    so they are never in the universe. Sources: NSE's current ETF list, plus the ETF file of the
    notice archive on the first trading day of every month (catches ETFs that have since closed or
    matured, like Bharat Bond ETF April 2023). Cached; only new months are fetched."""
    cache = _read_json(ETF_FILE, {"days": [], "symbols": [], "list_day": None})
    syms, have = set(cache["symbols"]), set(cache["days"])
    months = pd.Series(dates, index=dates).groupby(dates.to_period("M")).first()
    todo = [d.date() for d in months if d.date().isoformat() not in have]
    if todo:
        log(f"Reading the ETF lists of {len(todo)} month(s)...")
        with ThreadPoolExecutor(max_workers=4) as ex:
            for d, got in zip(todo, ex.map(_etf_day, todo)):
                if got is not None:
                    syms |= got
                    have.add(d.isoformat())
    today = date.today().isoformat()
    if cache.get("list_day") != today:
        code, text = nse._get(ETF_LIST_URL)
        if code == 200 and text:
            try:
                syms |= set(pd.read_csv(io.StringIO(text), dtype=str).iloc[:, 0].dropna().str.strip())
                cache["list_day"] = today
            except Exception:
                pass
    PIT_DIR.mkdir(parents=True, exist_ok=True)
    _write_json(ETF_FILE, {**cache, "days": sorted(have), "symbols": sorted(syms)})
    return syms


# --------------------------------------------------------------------------- renames
def rename_list() -> list[tuple[str, str, date]]:
    """(old, new, effective date), oldest change first, so chains A -> B -> C resolve correctly."""
    out = [(old, new, eff) for new, olds in corporate.renames().items() for old, eff in olds if old != new]
    return sorted(out, key=lambda x: (x[2], x[0]))


def stitch(sym: np.ndarray, day: np.ndarray, renames: list[tuple[str, str, date]]) -> tuple[np.ndarray, np.ndarray]:
    """Map each (symbol, day) row to the symbol the company trades under today: rows of an old symbol
    *before* its change date move to the new symbol (a later, different company reusing the old
    symbol keeps it). Returns (canonical symbols, moved flag)."""
    codes, names = pd.factorize(np.asarray(sym, dtype=object))
    codes, names, moved = _stitch_codes(codes, list(names), day, renames)
    return np.asarray(names, dtype=object)[codes], moved


def _stitch_codes(codes: np.ndarray, names: list[str], day: np.ndarray,
                  renames: list[tuple[str, str, date]]) -> tuple[np.ndarray, list[str], np.ndarray]:
    """stitch() on integer symbol codes; new symbols are appended to `names`."""
    codes = np.asarray(codes, dtype=np.int64).copy()
    names = list(names)
    pos = {n: i for i, n in enumerate(names)}
    moved = np.zeros(len(codes), dtype=bool)
    order = np.argsort(codes, kind="stable")
    bounds = np.searchsorted(codes[order], np.arange(len(names) + 1))
    rows_of = {i: order[bounds[i]:bounds[i + 1]] for i in range(len(names))}
    for old, new, eff in renames:
        oc = pos.get(old)
        rows = rows_of.get(oc) if oc is not None else None
        if rows is None or not len(rows):
            continue
        early = day[rows] < np.datetime64(eff)
        before = rows[early]
        if not len(before):
            continue
        nc = pos.setdefault(new, len(names))
        if nc == len(names):
            names.append(new)
        codes[before] = nc
        moved[before] = True
        rows_of[oc] = rows[~early]
        rows_of[nc] = np.sort(np.concatenate([rows_of.get(nc, np.array([], dtype=np.int64)), before]))
    return codes, names, moved


# --------------------------------------------------------------------------- universe
def membership(close: np.ndarray, volume: np.ndarray, equity: np.ndarray, size: int = UNIVERSE_SIZE,
               window: int = TURNOVER_DAYS, min_days: int = MIN_HISTORY_DAYS,
               stale_days: int = STALE_DAYS) -> tuple[np.ndarray, np.ndarray]:
    """Top-`size` stocks on each day by average daily traded value over the last `window` trading
    days (days without trades count as zero). Every input to row t comes from rows <= t, so the
    universe on a day never depends on later prices. Returns (member bool, average traded value)."""
    traded = ~np.isnan(close)
    value = np.where(traded, close * np.nan_to_num(volume), 0.0)
    T = len(close)
    avg = bn.move_sum(value, min(window, T), min_count=1, axis=0) / window
    n_obs = bn.move_sum(traded.astype(float), min(window, T), min_count=1, axis=0)
    recent = bn.move_max(traded.astype(float), min(stale_days, T), min_count=1, axis=0) > 0
    last_equity = bn.push(np.where(traded, equity.astype(float), np.nan), axis=0) == 1
    score = np.where((n_obs >= min_days) & recent & last_equity & (avg > 0), avg, -np.inf)
    member = np.zeros(score.shape, dtype=bool)
    k = min(size, score.shape[1])
    top = (np.argpartition(-score, k - 1, axis=1)[:, :k] if k < score.shape[1]
           else np.broadcast_to(np.arange(score.shape[1]), score.shape))
    rows = np.arange(score.shape[0])[:, None]
    member[rows, top] = np.isfinite(score[rows, top])
    return member, avg


# --------------------------------------------------------------------------- build
def _wide(raw: pd.DataFrame, dates: pd.DatetimeIndex, symbols: list[str], fields) -> dict[str, np.ndarray]:
    cat = raw["symbol"].astype("category")
    col = pd.Index(symbols).get_indexer(cat.cat.categories)[cat.cat.codes.to_numpy()]
    col[cat.cat.codes.to_numpy() < 0] = -1
    row = dates.get_indexer(pd.DatetimeIndex(raw["date"]))
    ok = (col >= 0) & (row >= 0)
    out = {}
    for f in fields:
        a = np.full((len(dates), len(symbols)), np.nan if f != "equity" else False,
                    dtype=bool if f == "equity" else float)
        a[row[ok], col[ok]] = raw[f].to_numpy()[ok]
        out[f] = a
    return out


def _canonical(raw: pd.DataFrame) -> pd.DataFrame:
    """Raw rows under today's symbols, one row per (date, symbol); symbol is categorical."""
    cat = raw["symbol"].astype("category")
    day = raw["date"].to_numpy(dtype="datetime64[ns]")
    codes, names, moved = _stitch_codes(cat.cat.codes.to_numpy(), list(cat.cat.categories), day, rename_list())
    # Clashes can only involve symbols that received rows: a row that was always under the symbol
    # wins over one moved in from an old symbol.
    sub = np.flatnonzero(np.isin(codes, np.unique(codes[moved])))
    keys = pd.DataFrame({"d": day[sub], "c": codes[sub], "m": moved[sub]}, index=sub)
    keys = keys.sort_values(["d", "c", "m"], kind="stable")
    keep = np.ones(len(codes), dtype=bool)
    keep[keys.index[keys.duplicated(["d", "c"])].to_numpy()] = False
    out = raw.loc[keep].reset_index(drop=True)
    out["symbol"] = pd.Categorical.from_codes(codes[keep], categories=names)
    return out


def _events(fr: dict[str, pd.DataFrame], prev_close: pd.DataFrame,
            after_missing: set) -> list[tuple[pd.Timestamp, str, bool]]:
    """(day, symbol, big) for moves worth checking for a corporate action, oldest first:
    a >20% overnight move (big), an opening gap down of 5%+ (bonus/split candidates), or NSE's
    previous close disagreeing with ours (e.g. a rename that came with a share swap) - except right
    after a day whose NSE file is missing, where NSE's previous close is legitimately different."""
    c, o = fr["close"], fr["open"]
    prev = c.ffill().shift(1)
    big = ((o / prev - 1).abs() > store.GAP_SUSPECT) | ((c / prev - 1).abs() > store.GAP_SUSPECT)
    down = (o / prev - 1) <= -DOWN_GAP
    after_gap = c.index.isin(sorted(after_missing))
    mismatch = ((prev_close / prev - 1).abs() > store.CA_TOLERANCE) & ~after_gap[:, None]
    hit = (big | down | mismatch) & c.notna()
    big = big.to_numpy()
    rows, cols = np.nonzero(hit.to_numpy())
    return sorted((c.index[i], c.columns[j], bool(big[i, j])) for i, j in zip(rows, cols))


def _fallback(s: str, d: pd.Timestamp, o: float, c: float, prev_nse: float, prev_day: pd.Timestamp | None,
              reference: pd.DataFrame | None) -> dict | None:
    """Factor for a >20% move that no NSE notice explains (see the rules at the top)."""
    if not (prev_nse > 0 and c > 0 and o > 0):
        return None
    move, gap = c / prev_nse, o / prev_nse
    factor, reason = None, None
    if reference is not None and s in reference.columns and prev_day is not None:
        ref = reference[s]
        r0, r1 = ref.get(prev_day), ref.get(d)
        if r0 is not None and r1 is not None and r0 > 0 and r1 > 0:
            ref_move = r1 / r0
            if abs(ref_move - 1) < REFERENCE_NORMAL_MOVE and abs(move / ref_move - 1) > REFERENCE_NORMAL_MOVE:
                factor, reason = move / ref_move, "no NSE notice: matched to the Yahoo-adjusted history"
    if factor is None:
        near = min(CLEAN_FACTORS, key=lambda f: abs(gap / f - 1))
        if abs(gap / near - 1) <= 0.04 and abs(move / near - 1) <= 0.10:
            factor, reason = near, f"no NSE notice: price jump matches a split/bonus (x{near:.4g})"
        elif gap <= DISTRIBUTION_GAP:
            factor, reason = gap, "no NSE notice: special dividend / capital distribution (opening price)"
    if factor is None or not np.isfinite(factor) or abs(factor - 1) <= store.CA_TOLERANCE:
        return None
    return {"symbol": s, "date": d.date().isoformat(), "factor": round(float(factor), 6), "reason": reason}


def _adjust(fr: dict[str, pd.DataFrame], prev_close: pd.DataFrame, after_missing: set, log=print,
            reference: pd.DataFrame | None = None, reuse: PitData | None = None) -> list[dict]:
    """Rescale history before each corporate action (oldest first, as store._repair_history does).
    `reference`: the main store's (Yahoo-adjusted, repaired) closes, used to check unexplained jumps.
    `reuse`: a previous build whose verdicts are kept for the days and stocks it already checked
    (daily updates then only check new days and stocks new to the universe)."""
    events = _events(fr, prev_close, after_missing)
    done: list[dict] = []
    checked = lambda d, s: False                                  # noqa: E731
    if reuse is not None:
        last, before = pd.Timestamp(reuse.info["last_day"]), set(reuse.universe.columns)
        cols = set(fr["close"].columns)
        done = [a for a in reuse.info["adjustments"]
                if pd.Timestamp(a["date"]) <= last and a["symbol"] in before and a["symbol"] in cols]
        checked = lambda d, s: d <= last and s in before          # noqa: E731
        events = [e for e in events if not checked(e[0], e[1])]
    # Notices: the ex-date's own file (many first appear there), the trading day before it, the next
    # one (a few are listed only after the ex-date); big jumps also look two more days each way.
    idx = fr["close"].index

    def around(d: pd.Timestamp) -> list[date]:
        before, after = store._prior_days(fr, d), [x.date() for x in idx[idx > d][:2]]
        return [d.date(), *before[:1], *after[:1], *before[1:], *after[1:]]

    look = {d: around(d) for d in {d for d, _, _ in events}}
    need = sorted({x for d, _, big in events for x in (look[d] if big else look[d][:3])})
    known = load_notices(set(need))

    def cached(d: date) -> bool:
        return (d in known or (nse.NSE_DIR / f"bc_{d:%Y%m%d}.parquet").exists()
                or (nse.NSE_DIR / f"bc_{d:%Y%m%d}.none").exists())

    todo = [d for d in need if not cached(d)]
    log(f"Checking {len(events)} price jumps against NSE corporate-action notices "
        f"({len(need)} notice files, {len(todo)} to download)...")
    t0 = time.perf_counter()
    for attempt, workers in enumerate((4, 2, 1)):      # NSE sometimes refuses bursts: retry slower
        with ThreadPoolExecutor(max_workers=workers) as ex:
            for i in range(0, len(todo), 100):
                list(ex.map(corporate.fetch_bc, todo[i:i + 100]))
                if attempt == 0:
                    log(f"  {min(i + 100, len(todo))}/{len(todo)} notice files ({time.perf_counter() - t0:.0f}s)")
        todo = [d for d in todo if not cached(d)]
        if not todo:
            break
    if todo:   # don't ask NSE again for each price jump in this build; the next build retries them
        corporate._bc_memo.update({d: None for d in todo})
        log(f"  could not load the notices of {len(todo)} day(s): {', '.join(d.isoformat() for d in todo[:10])}"
            f"{' ...' if len(todo) > 10 else ''} - price jumps on those days are checked with the fallbacks only")
    save_notices([d for d in need if d not in known and d not in todo])
    # Every split / bonus NSE lists for these stocks is checked too, however small the price move (a
    # 1:10 bonus on a rising day can open only 4% lower), looking in the files that list it. Without a
    # price jump only a ratio stated in the notice is used: for a demerger / scheme the opening price
    # would be mostly ordinary overnight noise.
    listed = _listed_actions(fr["close"], idx)
    have = {(d, s) for d, s, _ in events}
    extra = sorted((d, s, False) for d, s in listed if (d, s) not in have and not checked(d, s))
    if extra:
        log(f"  + {len(extra)} listed corporate actions with smaller price moves")
    extra_set = set(extra)
    events = sorted(events) + extra       # notice-only checks last: they can see the jumps already found
    load_notices({x for days in listed.values() for x in days})
    o, c = fr["open"], fr["close"]
    for d, s, big in events:
        i, j = c.index.get_loc(d), c.columns.get_loc(s)
        day = nse.DayFile(d.date(), "ok", pd.DataFrame(
            {"open": [o.iat[i, j]], "close": [c.iat[i, j]], "prev_close": [prev_close.iat[i, j]]},
            index=pd.Index([corporate.symbol_on(s, d.date())], name="symbol")))
        days = (look[d] if big else look[d][:3]) if d in look else []
        days = days + [x for x in listed.get((d, s), []) if x not in days]
        if (d, s, big) in extra_set and (
                corporate.purpose_factor(corporate.actions_on(corporate.symbol_on(s, d.date()), d.date(), days)) is None
                or any(a["symbol"] == s and abs((pd.Timestamp(a["date"]) - d).days) <= 7 for a in done)):
            continue          # no stated ratio, or the action was already found at a nearby price jump
        adj = store._event_factor(fr, s, d, day, days)
        if adj is None and big and not corporate.actions_on(corporate.symbol_on(s, d.date()), d.date(), days):
            before = c[s].iloc[:i].dropna()
            adj = _fallback(s, d, o.iat[i, j], c.iat[i, j], prev_close.iat[i, j],
                            before.index[-1] if len(before) else None, reference)
        if adj:
            done.append(adj)
    done.sort(key=lambda a: (a["date"], a["symbol"]))
    apply_adjustments(fr, done)
    return done


RESCHEDULE_DAYS = 15     # the same action listed with ex-dates this close together = one action


def _listed_actions(close: pd.DataFrame, idx: pd.DatetimeIndex) -> dict[tuple[pd.Timestamp, str], list[date]]:
    """(ex-date, today's symbol) -> notice-file days listing it, for every price-affecting action in the
    consolidated notice table on a stock and trading day we have prices for. NSE sometimes lists an
    action with one ex-date and later corrects it (HAL 2023: 29 -> 28 Sep; Inox Wind 2024: 17 -> 24
    May): the same action listed with ex-dates close together is one action, dated by the latest file."""
    if not NOTICES_FILE.exists():
        return {}
    tab = pd.read_parquet(NOTICES_FILE, columns=["day", "symbol", "ex_date", "purpose"])
    tab = tab[tab["symbol"].notna() & tab["ex_date"].notna() & (tab["ex_date"] != "None")].drop_duplicates()
    forward: dict[str, list[tuple[str, date]]] = {}
    for new, olds in corporate.renames().items():
        for old, eff in olds:
            forward.setdefault(old, []).append((new, eff))
    groups: dict[tuple[str, str], list[tuple[pd.Timestamp, pd.Timestamp]]] = {}
    for day, sym, ex, purpose in zip(tab["day"], tab["symbol"], tab["ex_date"], tab["purpose"]):
        ex_ts = pd.Timestamp(ex)
        groups.setdefault((_current_symbol(sym, ex_ts.date(), forward), purpose), []).append(
            (ex_ts, pd.Timestamp(day)))
    cols, out = set(close.columns), {}
    for (now, _), rows in groups.items():
        if now not in cols:
            continue
        rows.sort()
        clusters, cur = [], [rows[0]]
        for r in rows[1:]:
            if (r[0] - cur[-1][0]).days <= RESCHEDULE_DAYS:
                cur.append(r)
            else:
                clusters.append(cur)
                cur = [r]
        clusters.append(cur)
        for cl in clusters:
            ex_ts = max(cl, key=lambda r: (r[1], r[0]))[0]            # ex-date in the latest file
            if ex_ts in idx and pd.notna(close.at[ex_ts, now]):
                out.setdefault((ex_ts, now), set()).update(r[1].date() for r in cl if r[0] == ex_ts)
    return {k: sorted(v) for k, v in out.items()}


def _current_symbol(sym: str, day: date, forward: dict[str, list[tuple[str, date]]]) -> str:
    """The symbol a company that traded as `sym` on `day` trades under today (follows renames forward)."""
    seen = set()
    while sym not in seen:
        seen.add(sym)
        later = [(new, eff) for new, eff in forward.get(sym, []) if eff > day]
        if not later:
            break
        sym = min(later, key=lambda x: x[1])[0]
    return sym


def load_notices(days_wanted: set[date] | None = None) -> set[date]:
    """Load the consolidated notice table (all days, or `days_wanted`) into corporate's cache - one
    file instead of ~2,000 small ones, which are slow to open on Windows. Returns the days loaded."""
    if not NOTICES_FILE.exists() or days_wanted == set():
        return set()
    try:
        tab = pd.read_parquet(NOTICES_FILE)
    except Exception:
        return set()
    if days_wanted is not None:
        tab = tab[tab["day"].isin(pd.DatetimeIndex([pd.Timestamp(d) for d in days_wanted]).as_unit("ns"))]
    days = set()
    for day, rows in tab.groupby("day", sort=False):
        d = pd.Timestamp(day).date()
        rows = rows[rows["symbol"].notna()].drop(columns="day").reset_index(drop=True)
        corporate._bc_memo.setdefault(d, rows if len(rows) else None)
        days.add(d)
    return days


def save_notices(new_days: list[date]) -> None:
    """Add these days' notices (from corporate's cache / the per-day files) to the consolidated table."""
    if not new_days:
        return
    parts = [pd.read_parquet(NOTICES_FILE)] if NOTICES_FILE.exists() else []
    for d in new_days:
        bc = corporate.fetch_bc(d)
        if bc is None and d not in corporate._bc_memo:
            continue                                   # not definite (download failed): not stored
        rows = bc if bc is not None and len(bc) else pd.DataFrame({"symbol": [None]})
        parts.append(rows.assign(day=pd.Timestamp(d).as_unit("ns")))
    if not parts:
        return
    tab = pd.concat(parts, ignore_index=True)
    tab = tab.astype({c: "object" for c in ("series", "symbol", "ex_date", "purpose") if c in tab.columns})
    PIT_DIR.mkdir(parents=True, exist_ok=True)
    tmp = NOTICES_FILE.with_suffix(f".{os.getpid()}.tmp")
    tab.to_parquet(tmp, index=False)
    store._replace(tmp, NOTICES_FILE)


def apply_adjustments(fr: dict[str, pd.DataFrame], adjustments: list[dict]) -> None:
    """Rescale prices (and inversely volumes) before each action's date, like
    store._apply_corporate_action, in place."""
    idx, cols = fr["close"].index, fr["close"].columns
    pos = {sym: j for j, sym in enumerate(cols)}
    arrs = {f: fr[f].to_numpy(dtype=float, copy=True) for f in ("open", "high", "low", "close", "volume")}
    for a in adjustments:
        i, j = idx.searchsorted(pd.Timestamp(a["date"])), pos[a["symbol"]]
        for f in ("open", "high", "low", "close"):
            arrs[f][:i, j] *= a["factor"]
        arrs["volume"][:i, j] /= a["factor"]
    for f, arr in arrs.items():
        fr[f] = pd.DataFrame(arr, index=idx, columns=cols)


def build(days: list[date], keep_symbols: list[str] = (), download: bool = True, log=print,
          size: int = UNIVERSE_SIZE, reference: pd.DataFrame | None = None,
          reuse: PitData | None = None) -> PitData:
    """Build (or rebuild) the point-in-time universe and its adjusted prices from the first to the
    last of `days` (the main store's trading days). Every calendar day in between is checked, so
    NSE sessions the store lacks (Budget-day and Saturday special sessions, Muhurat trading) are
    included. `keep_symbols` (e.g. today's Nifty 500) are kept even if never a member, so the
    current list can be tested on the same NSE data. `reference`: the main store's closes (see
    _fallback). `reuse`: see _adjust."""
    t0 = time.perf_counter()
    days = sorted(set(days))
    calendar = [days[0] + timedelta(days=i) for i in range((days[-1] - days[0]).days + 1)]
    raw = update_raw(calendar, download=download, log=log)
    if raw.empty:
        raise RuntimeError("no NSE day files available")
    have = np.unique(raw["date"].to_numpy())
    cal = pd.DatetimeIndex([pd.Timestamp(d) for d in calendar], name="date").as_unit("ns")
    dates = cal[cal.isin(have)]
    store_days_ = pd.DatetimeIndex([pd.Timestamp(d) for d in days]).as_unit("ns")
    missing = store_days_[~store_days_.isin(have)]           # store says trading day, NSE has no file
    extra = dates[~dates.isin(store_days_)]                  # NSE sessions the store lacks
    after_missing = {dates[dates > m][0] for m in missing if (dates > m).any()}
    raw = _canonical(raw[pd.DatetimeIndex(raw["date"]).isin(dates)])
    cat = raw["symbol"].cat
    all_syms = sorted(cat.categories[np.unique(cat.codes.to_numpy())])
    w = _wide(raw, dates, all_syms, ("close", "volume", "equity"))
    etfs = etf_symbols(dates, log) & set(all_syms)
    w["equity"][:, pd.Index(all_syms).get_indexer(sorted(etfs))] = False   # funds, not companies
    member, _ = membership(w["close"], w["volume"], w["equity"], size=size)
    ever = member.any(axis=0)
    kept = sorted(set(np.asarray(all_syms)[ever]) | (set(keep_symbols) & set(all_syms)))
    del w
    log(f"Universe: {int(ever.sum())} different stocks were in the top {size} at some point "
        f"({len(all_syms)} NSE equities seen, {len(etfs)} ETFs left out, {len(missing)} days without an NSE file)")

    wk = _wide(raw, dates, kept, RAW_FIELDS)
    fr = {f: pd.DataFrame(wk[f], index=dates, columns=kept) for f in OUT_FIELDS}
    prev_close = pd.DataFrame(wk["prev_close"], index=dates, columns=kept)
    del wk
    adjustments = _adjust(fr, prev_close, after_missing, log, reference, reuse)
    col = pd.Index(all_syms).get_indexer(kept)
    uni = pd.DataFrame(member[:, col], index=dates, columns=kept)
    last_day = dates[-1]
    gone = [s for s in kept if uni[s].any() and pd.isna(fr["close"].at[last_day, s])]
    info = {
        "version": VERSION, "built_at": ist_now().isoformat(timespec="seconds"),
        "first_day": dates[0].date().isoformat(), "last_day": last_day.date().isoformat(), "days": len(dates),
        "days_without_file": [d.date().isoformat() for d in missing],
        "sessions_not_in_store": [d.date().isoformat() for d in extra],
        "rule": {"size": size, "turnover_days": TURNOVER_DAYS, "min_history_days": MIN_HISTORY_DAYS,
                 "stale_days": STALE_DAYS, "series": list(EQUITY_SERIES)},
        "nse_equities_seen": len(all_syms), "etfs_excluded": len(etfs), "ever_members": int(ever.sum()),
        "kept": len(kept),
        "members_no_longer_trading": len(gone), "no_longer_trading_sample": gone[:40],
        "adjustments": adjustments, "build_seconds": round(time.perf_counter() - t0, 1),
    }
    data = PitData(fr, uni, info)
    save(data)
    log(f"Point-in-time universe built in {info['build_seconds']}s: {len(dates)} days, {len(kept)} stocks, "
        f"{len(adjustments)} corporate-action adjustments, {len(gone)} former members no longer trading")
    return data


# --------------------------------------------------------------------------- cache
def _read_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _write_json(path, obj) -> None:
    tmp = path.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(obj, indent=1, default=str), encoding="utf-8")
    store._replace(tmp, path)


def save(data: PitData) -> None:
    """New generation folder, then atomically repoint CURRENT (same scheme as the price store)."""
    name = f"gen_{ist_now():%Y%m%d_%H%M%S}_{os.getpid()}"
    folder = PIT_DIR / name
    folder.mkdir(parents=True, exist_ok=True)
    dates = data.universe.index
    np.save(folder / "dates.npy", dates.values.astype("datetime64[ns]").astype("int64"))
    (folder / "symbols.json").write_text(json.dumps(list(data.universe.columns)), encoding="utf-8")
    for f in OUT_FIELDS:
        np.save(folder / f"{f}.npy", data.frames[f].to_numpy(dtype=float))
    np.save(folder / "universe.npy", data.universe.to_numpy(dtype=bool))
    (folder / "info.json").write_text(json.dumps(data.info, indent=1, default=str), encoding="utf-8")
    tmp = PIT_DIR / f"CURRENT.{os.getpid()}.tmp"
    tmp.write_text(name, encoding="utf-8")
    store._replace(tmp, PIT_DIR / "CURRENT")
    for old in sorted((p for p in PIT_DIR.glob("gen_*") if p.is_dir()), reverse=True)[2:]:
        shutil.rmtree(old, ignore_errors=True)


def load() -> PitData | None:
    current = PIT_DIR / "CURRENT"
    if not current.exists():
        return None
    folder = PIT_DIR / current.read_text(encoding="utf-8").strip()
    try:
        dates = pd.DatetimeIndex(np.load(folder / "dates.npy").astype("datetime64[ns]"), name="date")
        cols = pd.Index(json.loads((folder / "symbols.json").read_text(encoding="utf-8")))
        frames = {f: pd.DataFrame(np.load(folder / f"{f}.npy"), index=dates, columns=cols) for f in OUT_FIELDS}
        uni = pd.DataFrame(np.load(folder / "universe.npy"), index=dates, columns=cols)
        info = json.loads((folder / "info.json").read_text(encoding="utf-8"))
    except Exception:
        return None
    return PitData(frames, uni, info) if info.get("version") == VERSION else None


def update(days: list[date], keep_symbols: list[str] = (), log=print,
           reference: pd.DataFrame | None = None) -> PitData | None:
    """Keep an existing point-in-time cache current: rebuild from the consolidated raw cache when
    NSE files for newer days are available. Returns None if it was never built (the first build
    downloads ~2,000 files, so it is not started from a scan)."""
    data = load()
    if data is None:
        return None
    last = date.fromisoformat(data.info["last_day"])
    newer = [d for d in days if d > last]
    if any((nse.NSE_DIR / f"stocks_{d:%Y%m%d}.parquet").exists() for d in newer):
        log("Updating the point-in-time universe with new NSE days...")
        data = build([d for d in days if d >= date.fromisoformat(data.info["first_day"])],
                     keep_symbols, download=False, log=log, size=data.info["rule"]["size"], reference=reference,
                     reuse=data)
    return data


def store_days(frames: dict[str, pd.DataFrame], upto: date | None = None) -> list[date]:
    """Trading days in the main price store (completed days only)."""
    idx = frames["close"].index
    return [d.date() for d in idx if upto is None or d.date() <= upto]


def backtest_frames(data: PitData, store_frames: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """Point-in-time stock prices plus the store's index columns (Nifty 50, VIX, Nifty 500)."""
    from .providers import INDEX_SYMBOLS
    out = {}
    for f in OUT_FIELDS:
        idx_cols = [c for c in INDEX_SYMBOLS if c in store_frames[f].columns]
        out[f] = pd.concat([data.frames[f], store_frames[f][idx_cols].reindex(data.frames[f].index)], axis=1)
    return out


# --------------------------------------------------------------------------- comparison
def compare(cfg: dict | None = None, keys=("momentum", "trend_breakout", "low_vol"), log=print) -> pd.DataFrame:
    """Each strategy on (a) today's list with the store's data - what the dashboard used to show,
    (b) today's list rebuilt from NSE files - checks the NSE rebuild, (c) the point-in-time universe."""
    from dataclasses import replace

    from .costs import CostModel, TaxModel
    from .engine import _curve_stats, equal_weight_index, evaluate, simulate
    from .panel import TRADING_DAYS, Factors, panel_from_wide
    from .providers import INDEX_N500
    from .settings import load_config
    from .strategies import build_strategies, tradable_mask
    from .universe import get_universe

    cfg = cfg or load_config()
    sfr = store.load_store()
    data = load()
    if data is None:
        raise RuntimeError("point-in-time universe not built yet: run  python -m scanner.pit build")
    current = list(get_universe(cfg.get("universe", "nifty500"))[0]["symbol"])
    nfr = backtest_frames(data, sfr)
    flt = cfg.get("filters") or {}
    costs, tax = CostModel.from_config(cfg.get("costs")), TaxModel.from_config(cfg.get("tax"))
    acct = cfg.get("account") or {}
    capital, min_pos = float(acct.get("capital", 500000)), float(acct.get("min_position", 0))
    strategies = {s.key: s for s in build_strategies(cfg) if s.key in keys}
    end = min(sfr["close"].index[-1], data.universe.index[-1])
    # Same test window for every setup: the NSE calendar has a few sessions the store lacks.
    start = max(sfr["close"].index[TRADING_DAYS], data.universe.index[TRADING_DAYS])
    setups = {
        "current list, store data": (sfr, current, None),
        "current list, NSE data": (nfr, [s for s in current if s in data.universe.columns], None),
        "point-in-time top 500": (nfr, data.members, data.universe),
    }
    rows = []
    for label, (frames, syms, uni) in setups.items():
        frames = {f: v.loc[:end] for f, v in frames.items()}
        p = panel_from_wide(frames, syms, universe=uni.loc[:end] if uni is not None else None)
        f = Factors(p)
        trad = tradable_mask(f, float(flt.get("min_price", 50)), float(flt.get("min_turnover_cr", 5)))
        ew = equal_weight_index(f, trad)
        n500 = frames["close"][INDEX_N500].reindex(p.dates) if INDEX_N500 in frames["close"].columns else None
        log(f"{label}: {len(syms)} stocks, {int(trad.sum(axis=1).median())} tradable on a typical day")
        w0 = int(p.dates.searchsorted(start))
        bench = None
        for key, s in strategies.items():
            res = simulate(s, f, costs, trad, capital=capital, min_position=min_pos, warmup=w0)
            m = evaluate(res, p.index_close, ew, tax=tax, n500_benchmark=n500)["full"]
            variants = ([replace(s, rebalance_offset=k) for k in (5, 10, 15)] if s.kind == "rank" else [s, s, s])
            spread = [m["cagr_pct"]]
            for i, v in enumerate(variants):
                alt = simulate(v, f, costs, trad, capital=capital, min_position=min_pos,
                               warmup=w0 if s.kind == "rank" else w0 + 21 * (i + 1))
                spread.append(_curve_stats(alt.equity)["cagr_pct"])
            spread = [x for x in spread if x is not None]
            rows.append({"universe": label, "strategy": s.name, "cagr_pct": m["cagr_pct"],
                         "max_dd_pct": m["max_dd_pct"], "sharpe": m["sharpe"],
                         "after_tax_cagr_pct": m.get("after_tax_cagr_pct"),
                         "cagr_low": min(spread), "cagr_high": max(spread), "trades": m["trades"],
                         "start": m["start"], "end": m["end"]})
            bench = m
        for name, key in (("Average stock (equal weight)", "ew_benchmark"), ("Nifty 500 index", "n500_benchmark")):
            b = bench[key]
            rows.append({"universe": label, "strategy": name, "cagr_pct": b.get("cagr_pct"),
                         "max_dd_pct": b.get("max_dd_pct"), "sharpe": b.get("sharpe"),
                         "after_tax_cagr_pct": b.get("after_tax_cagr_pct"), "start": bench["start"],
                         "end": bench["end"]})
    return pd.DataFrame(rows)


def markdown_table(df: pd.DataFrame) -> str:
    def pct(x, signed=True):
        return "-" if x is None or pd.isna(x) else (f"{x:+.1f}%" if signed else f"{x:.1f}%")
    lines = ["| Strategy | Universe | Yearly return | Timing range | Worst drop | Sharpe | After tax |",
             "|---|---|---|---|---|---|---|"]
    for r in df.to_dict("records"):
        rng = (f"{r['cagr_low']:.0f} to {r['cagr_high']:.0f}%" if pd.notna(r.get("cagr_low"))
               and r.get("cagr_low") is not None else "-")
        sharpe = "-" if r["sharpe"] is None or pd.isna(r["sharpe"]) else f"{r['sharpe']:.2f}"
        lines.append(f"| {r['strategy']} | {r['universe']} | {pct(r['cagr_pct'])} | {rng} | "
                     f"{pct(r['max_dd_pct'], signed=False)} | {sharpe} | {pct(r['after_tax_cagr_pct'])} |")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    from .settings import load_config
    from .universe import get_universe

    cmd = argv[0] if argv else "build"
    if cmd == "build":
        cfg = load_config()
        current = list(get_universe(cfg.get("universe", "nifty500"))[0]["symbol"])
        sfr = store.load_store()
        build(store_days(sfr), current, reference=sfr["close"])
    elif cmd == "compare":
        df = compare()
        out = PIT_DIR / "comparison.csv"
        df.to_csv(out, index=False)
        print(markdown_table(df))
        print(f"\nSaved to {out}")
    else:
        print("usage: python -m scanner.pit [build|compare]")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
