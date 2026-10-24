"""FYERS-first intraday history: a resumable ~1-year backfill and a daily after-close archive.

FYERS keeps only a rolling ~1 year of intraday history on the Standard plan, so the archive should
run every trading day (setup_schedule.ps1 adds it). Every call goes through the shared rate limiter
(scanner/fyers_limits.py): calls are spaced under 45/minute and stop for the day before FYERS'
block threshold. Progress is saved after each batch, so an interrupted backfill resumes where it
stopped (data/intraday/fyers_sync.json records the range fetched per symbol).

Bookkeeping rules:
  * A symbol's coverage is one contiguous date range that only grows next to what is stored: the newer
    end is fetched oldest chunk first, the older end (and a new symbol) newest chunk first.
  * A chunk FYERS answers with an error is never recorded as covered. The symbol is retried the next day;
    after MAX_TRIES failing days the chunk is accepted as empty (e.g. older than FYERS' rolling year).
  * Weekends and NSE holidays (the cached NSE list) cost no calls.
  * One sync at a time across processes (data/intraday/.sync.lock): a scan that starts while the
    backfill or the archive runs skips its top-up instead of fetching the same symbols again.

Budget (Standard plan, 5-minute bars, <=100 days per request):
  backfill 1 year x 150 symbols = 150 x 4 = 600 calls  ~ 14 minutes, 13% of the daily limit
  daily archive               = 150 x 1 = 150 calls  ~ 4 minutes
"""
from __future__ import annotations

import functools
import json
import os
from datetime import date, datetime, timedelta

import pandas as pd

from ..fyers_limits import FyersRateLimited
from ..nse import NSE_DIR
from ..providers import FyersAuthError
from ..settings import ist_now
from . import data as idata

SYNC_FILE_NAME = "fyers_sync.json"
LOCK_FILE_NAME = ".sync.lock"
LOCK_WAIT_S = 5.0                 # a second sync waits this long for the first one, then skips
BATCH = 10                        # save to the store every N symbols (resumable progress)
MAX_TRIES = 3                     # failing days before a failing chunk is accepted as empty
MAX_FAILS_IN_A_ROW = 5            # this many symbols failing in a row = FYERS/network down: stop for now


def _state_path(root):
    return root / SYNC_FILE_NAME


def load_state(root) -> dict:
    """{'symbols': {sym: {'from', 'to'}}, 'failed': {sym: {'tries', 'day', 'message'}}}."""
    try:
        state = json.loads(_state_path(root).read_text(encoding="utf-8"))
    except Exception:
        state = {}
    if not isinstance(state, dict):
        state = {}
    for key in ("symbols", "failed"):
        if not isinstance(state.get(key), dict):
            state[key] = {}
    return state


def _save_state(root, state: dict) -> None:
    p = _state_path(root)
    tmp = p.with_name(f"{p.name}.{os.getpid()}.tmp")   # per process: a scan and a scheduled sync can overlap
    tmp.write_text(json.dumps(state, indent=0), encoding="utf-8")
    idata._replace(tmp, p)    # retries: on Windows os.replace fails while the web API is reading the file


@functools.lru_cache(maxsize=8)
def _holidays(year: int) -> frozenset:
    """NSE trading holidays of `year` from the cached list (scanner/events.py downloads and refreshes it).
    Read only - never a network call here; empty until that list has been downloaded once."""
    try:
        raw = json.loads((NSE_DIR / f"holidays_{year}.json").read_text(encoding="utf-8"))
        rows = raw.get("CM", [])
    except Exception:
        return frozenset()
    out = set()
    for r in rows if isinstance(rows, list) else []:
        try:
            out.add(datetime.strptime(str(r.get("tradingDate", "")).strip().title(), "%d-%b-%Y").date().isoformat())
        except (AttributeError, TypeError, ValueError):
            continue
    return frozenset(out)


def is_trading_day(d: date) -> bool:
    """Monday-Friday and not an NSE holiday. (A rare weekend special session is still archived: the next
    weekday's range includes it.)"""
    return d.weekday() < 5 and d.isoformat() not in _holidays(d.year)


def _has_trading_day(a: date, b: date) -> bool:
    d = a
    while d <= b:
        if is_trading_day(d):
            return True
        d += timedelta(days=1)
    return False


def last_complete_day() -> date:
    """Latest trading day whose session is fully over: today after 15:35 IST, otherwise the trading day
    before. Weekends and NSE holidays are stepped over, so an archive on such a day costs no calls."""
    now = ist_now()
    d = now.date() if (now.hour, now.minute) >= (15, 35) else now.date() - timedelta(days=1)
    for _ in range(10):                # NSE never closes 10 days in a row: a broken holiday list can't loop
        if is_trading_day(d):
            break
        d -= timedelta(days=1)
    return d


def _window(days: int) -> tuple[date, date]:
    end = last_complete_day()
    return end - timedelta(days=days), end


def _missing(have, start: date, end: date) -> list[tuple[date, date, bool]]:
    """The parts of [start, end] a symbol still needs, as (from, to, newest_first), newer end first.
    A stored range that no longer touches the window (the symbol left the universe for a while, or
    `days` was reduced) is ignored: the whole window is fetched and replaces it."""
    try:
        lo, hi = date.fromisoformat(have["from"]), date.fromisoformat(have["to"])
    except (KeyError, TypeError, ValueError):
        lo = hi = None
    if lo is None or lo > end or hi < start - timedelta(days=1):
        return [(start, end, True)]
    out = []
    if hi < end:
        out.append((hi + timedelta(days=1), end, False))     # daily archive: oldest chunk first
    if lo > start:
        out.append((start, lo - timedelta(days=1), True))    # backfill: newest chunk first
    return out


def _chunks(a: date, b: date, newest_first: bool) -> list[tuple[date, date]]:
    """[a, b] in pieces of <=100 days (one FYERS call each), in fetch order."""
    n = idata.FYERS_MAX_DAYS_PER_CALL
    out = []
    if newest_first:
        e = b
        while e >= a:
            s = max(a, e - timedelta(days=n - 1))
            out.append((s, e))
            e = s - timedelta(days=1)
    else:
        s = a
        while s <= b:
            e = min(b, s + timedelta(days=n - 1))
            out.append((s, e))
            s = e + timedelta(days=1)
    return out


def _failed_today(state: dict, sym: str, today: str) -> bool:
    f = state["failed"].get(sym)
    return isinstance(f, dict) and f.get("day") == today


def plan_calls(symbols: list[str], root, days: int = 365) -> dict:
    """How many FYERS calls a backfill/archive would need right now (for the UI before starting)."""
    state = load_state(root)
    start, end = _window(days)
    today = ist_now().date().isoformat()
    calls = 0
    for s in symbols:
        if _failed_today(state, s, today):
            continue                                        # failed earlier today: retried tomorrow
        for a, b, newest_first in _missing(state["symbols"].get(s), start, end):
            calls += sum(1 for ca, cb in _chunks(a, b, newest_first) if _has_trading_day(ca, cb))
    return {"calls": calls, "minutes": round(calls / 44, 1), "symbols": len(symbols), "from": start.isoformat(),
            "to": end.isoformat()}


def _fetch_chunk(provider, sym: str, a: date, b: date, resolution: str) -> tuple[pd.DataFrame, str | None]:
    """One FYERS history call: (bars, error message or None). Budget and login errors propagate."""
    errs: dict = {}
    try:
        bars = idata.fetch_fyers_intraday(provider, [sym], a, b, resolution=resolution, errors=errs)
    except (FyersRateLimited, FyersAuthError):
        raise
    except Exception as e:              # malformed answer and the like: fails this symbol, not the whole sync
        return idata.empty_bars(), f"{type(e).__name__}: {e}"
    return bars, (str(errs.get(sym) or "FYERS history request failed") if errs else None)


def sync(provider, symbols: list[str], root, days: int = 365, resolution: str = "5",
         progress=None, log=print) -> dict:
    """Fetch whatever part of the last `days` of intraday bars each symbol is missing (both the older
    end - backfill - and the newer end - daily archive). Stops cleanly when FYERS' budget for the day is
    used up or the login expires; run again later to continue. Returns at once, without fetching, when
    another process is already syncing."""
    start, end = _window(days)
    lock = idata.FileLock(root / LOCK_FILE_NAME)
    if not lock.acquire(timeout=LOCK_WAIT_S):
        msg = "Another FYERS intraday sync (backfill/archive) is running - skipped this one."
        log(msg)
        return {"symbols_done": 0, "symbols": len(symbols), "stopped": msg, "message": msg, "failed": {},
                "coverage_from": start.isoformat(), "coverage_to": end.isoformat()}
    try:
        return _sync(provider, symbols, root, days, start, end, resolution, progress, log)
    finally:
        lock.release()


def _sync(provider, symbols, root, days, start, end, resolution, progress, log) -> dict:
    iv = resolution + "m"
    store = idata.IntradayStore(root / "bars")
    state = load_state(root)
    have_all, fails = state["symbols"], state["failed"]
    today = ist_now().date().isoformat()
    pending: list[tuple[str, date, date]] = []
    fetched_bars: list[pd.DataFrame] = []
    failed: dict[str, str] = {}
    done, skipped, in_a_row, stopped, error = 0, 0, 0, None, None
    estimate = plan_calls(symbols, root, days)
    log(f"FYERS intraday sync: {estimate['calls']} calls for {len(symbols)} symbols "
        f"(~{estimate['minutes']} min at the safe rate)")

    def flush():
        nonlocal fetched_bars
        if fetched_bars:
            raw = pd.concat(fetched_bars, ignore_index=True)
            store.save(idata.clean_bars(raw.assign(source="fyers"), iv), iv)
            fetched_bars = []
        for sym, lo, hi in pending:
            try:
                p_lo, p_hi = date.fromisoformat(have_all[sym]["from"]), date.fromisoformat(have_all[sym]["to"])
            except (KeyError, TypeError, ValueError):
                p_lo = p_hi = None
            # merge only with a range it touches; a stale range outside the window is replaced, so the gap
            # between the two is never marked as covered
            if p_lo is not None and lo <= p_hi + timedelta(days=1) and hi >= p_lo - timedelta(days=1):
                lo, hi = min(lo, p_lo), max(hi, p_hi)
            have_all[sym] = {"from": lo.isoformat(), "to": hi.isoformat()}
        pending.clear()
        _save_state(root, state)

    try:
        for i, sym in enumerate(symbols, 1):
            if _failed_today(state, sym, today):
                skipped += 1
            else:
                prior = fails.get(sym) if isinstance(fails.get(sym), dict) else {}
                tries = int(prior.get("tries") or 0) + 1           # counts only if this run fails too
                error, gave_up = None, []
                for a, b, newest_first in _missing(have_all.get(sym), start, end):
                    for ca, cb in _chunks(a, b, newest_first):
                        if _has_trading_day(ca, cb):
                            bars, error = _fetch_chunk(provider, sym, ca, cb, resolution)
                            if len(bars):
                                fetched_bars.append(bars)
                            if error and tries < MAX_TRIES:
                                break                   # not recorded as covered: fetched again tomorrow
                            if error:
                                gave_up.append(f"{ca}..{cb}")
                                error = None
                        pending.append((sym, ca, cb))   # fetched, holiday-only, or failed on MAX_TRIES days
                    if error:
                        break
                if error:
                    fails[sym] = {"tries": tries, "day": today, "message": error[:200]}
                    failed[sym] = error
                    in_a_row += 1
                else:
                    fails.pop(sym, None)
                    done += 1
                    in_a_row = 0
                    if gave_up:
                        log(f"{sym}: FYERS failed on {MAX_TRIES} days for {', '.join(gave_up)} - treated as no data")
            if progress:
                progress(i, len(symbols), sym)
            if i % BATCH == 0:
                flush()
            if in_a_row >= MAX_FAILS_IN_A_ROW:
                stopped = f"FYERS history failed for {in_a_row} symbols in a row ({error}) - try again later"
                break
    except FyersRateLimited as e:
        stopped = str(e)
    except FyersAuthError as e:
        stopped = f"FYERS login expired ({e}) - run 1_login.bat and sync again"
    finally:
        flush()     # also on Ctrl+C or an unexpected error: keep what was fetched (those calls are spent)
    used = provider.limiter.usage()["data"]
    msg = (f"Synced {done}/{len(symbols)} symbols"
           + (f" ({len(failed)} failed, retried tomorrow: {', '.join(sorted(failed)[:5])})" if failed else "")
           + (f" ({skipped} skipped: failed earlier today)" if skipped else "")
           + (f" - stopped: {stopped}" if stopped else "")
           + f". FYERS calls today: {used['calls_today']}/{used['daily_limit']}.")
    log(msg)
    return {"symbols_done": done, "symbols": len(symbols), "stopped": stopped, "message": msg,
            "failed": failed, "coverage_from": start.isoformat(), "coverage_to": end.isoformat()}


def coverage(root) -> dict:
    """Which symbols have FYERS intraday history and for what range (for the data-health page)."""
    syms = load_state(root)["symbols"]
    if not syms:
        return {"symbols": 0, "from": None, "to": None}
    return {"symbols": len(syms), "from": min(v["from"] for v in syms.values()),
            "to": max(v["to"] for v in syms.values())}
