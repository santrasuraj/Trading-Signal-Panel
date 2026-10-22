"""Consolidated price store: one wide parquet file per field (rows = dates, columns = symbols).

Where the data comes from
  Deep history (first run, new symbols) : Yahoo Finance bulk download - fast, split-adjusted.
  Every completed trading day           : NSE's official end-of-day files (nse.py) - exact OHLCV,
                                          delivery %, and the official previous close.
  Today's forming candle                : Fyers real-time quotes when logged in, else Yahoo (delayed).

Splits / bonus issues: NSE's file states each stock's official *adjusted* previous close. If it
differs from the close we stored, a corporate action happened and the stock's whole history is
rescaled by that exact factor - so a 1:2 split never shows up as a fake 50% crash.
Only completed days are saved; the live candle is kept in memory only.
"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

import numpy as np
import pandas as pd

from . import corporate, nse
from .providers import COLS, INDEX_SYMBOLS, YahooProvider
from .settings import HISTORY_DIR, SESSION_START, ist_now, ist_today

STORE_DIR = HISTORY_DIR / "store"
FIELDS = COLS + ["deliv_pct"]
FULL_SLACK_DAYS = 30
NSE_MAX_DAYS = 60           # beyond this gap, catch up with Yahoo first
CA_TOLERANCE = 0.015        # ignore adjustment factors within 1.5% of 1 (rounding / source noise)
RETRY_FAILED_AFTER_DAYS = 3
NSE_PUBLISH_HOUR = 18       # don't look for today's NSE file before ~6 PM IST


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

    def load(self) -> dict[str, pd.DataFrame]:
        frames = {}
        for f in FIELDS:
            p = STORE_DIR / f"{f}.parquet"
            frames[f] = pd.read_parquet(p) if p.exists() else pd.DataFrame(index=pd.DatetimeIndex([], name="date"))
        return frames

    def save(self, frames: dict[str, pd.DataFrame]) -> None:
        for f in FIELDS:
            tmp = STORE_DIR / f"{f}.parquet.tmp"
            frames[f].to_parquet(tmp)
            tmp.replace(STORE_DIR / f"{f}.parquet")  # atomic: readers never see a half-written file
        self.save_meta()

    def save_meta(self) -> None:
        tmp = self.meta_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.meta, indent=0), encoding="utf-8")
        tmp.replace(self.meta_path)


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


def _weekdays(start: date, end: date) -> list[date]:
    out, d = [], start
    while d <= end:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def _apply_corporate_action(frames: dict, sym: str, before: pd.Timestamp, factor: float) -> None:
    mask = frames["close"].index < before
    for f in ("open", "high", "low", "close"):
        frames[f].loc[mask, sym] = frames[f].loc[mask, sym] * factor
    frames["volume"].loc[mask, sym] = frames["volume"].loc[mask, sym] / factor


GAP_SUSPECT = 0.20          # overnight move >20% => check NSE for a split/bonus/demerger


def _repair_history(frames: dict, syms: list[str], log=print) -> dict:
    """Fix known defects in downloaded (Yahoo) history using NSE's official day files:
      1. fake flat bars (O=H=L=C, zero volume) are removed;
      2. trading days missing for many stocks are filled from NSE;
      3. overnight gaps >20% are checked against NSE's adjusted previous close and, where a split /
         bonus / demerger explains them, the earlier history is rescaled by the exact factor."""
    eq = [s for s in syms if s in frames["close"].columns and s not in INDEX_SYMBOLS]
    report = {"flat_bars": 0, "filled_days": 0, "adjusted": []}
    if not eq:
        return report
    close, vol = frames["close"][eq], frames["volume"][eq]
    flat = (vol == 0) & (frames["high"][eq] == frames["low"][eq])
    report["flat_bars"] = int(flat.to_numpy().sum())
    if report["flat_bars"]:
        for f in COLS:
            frames[f][eq] = frames[f][eq].mask(flat)
        close = frames["close"][eq]

    present = close.notna()
    listed = present.cummax() & present.iloc[::-1].cummax().iloc[::-1]
    missing = (listed & ~present).sum(axis=1)
    fill_dates = list(missing[missing >= max(5, 0.02 * len(eq))].index)
    if fill_dates:
        files = nse.fetch_days([d.date() for d in fill_dates])
        upd = {f: [] for f in FIELDS}
        idx = []
        for d, fl in sorted(files.items()):
            if fl.status != "ok":
                continue
            st = fl.stocks.reindex(eq)
            idx.append(pd.Timestamp(d))
            for f in FIELDS:
                upd[f].append(st[f].to_numpy(dtype=float))
        if idx:
            new = {f: pd.DataFrame(np.vstack(upd[f]), index=pd.DatetimeIndex(idx, name="date"), columns=eq)
                   for f in FIELDS}
            for f in FIELDS:  # only fill holes, never overwrite existing values here
                base = frames[f].reindex(columns=frames[f].columns.union(eq))
                cur = base.reindex(index=new[f].index)[eq]
                new[f] = new[f].where(cur.isna())
            _merge(frames, new)
            report["filled_days"] = len(idx)
        close = frames["close"][eq]

    prev = close.ffill().shift(1)
    gaps = (((frames["open"][eq] / prev - 1).abs() > GAP_SUSPECT)
            | ((close / prev - 1).abs() > GAP_SUSPECT)) & close.notna()
    events = sorted((close.index[i], eq[j]) for i, j in zip(*np.nonzero(gaps.to_numpy())))
    if events:
        files = nse.fetch_days(sorted({d.date() for d, _ in events}))
        prior_day = {d: _prior_days(frames, d) for d, _ in events}
        with ThreadPoolExecutor(max_workers=4) as ex:   # warm the corporate-action notice cache
            list(ex.map(corporate.fetch_bc, sorted({p[0] for p in prior_day.values() if p})))
        # Oldest first, so each factor is computed in the units of the not-yet-adjusted history.
        for d, s in events:
            adj = _event_factor(frames, s, d, files.get(d.date()), prior_day[d])
            if adj:
                _apply_corporate_action(frames, s, d, adj["factor"])
                report["adjusted"].append(adj)
    return report


def _prior_days(frames: dict, ts: pd.Timestamp, n: int = 3) -> list[date]:
    idx = frames["close"].index
    return [x.date() for x in idx[idx < ts][-n:][::-1]]


def _event_factor(frames: dict, s: str, d: pd.Timestamp, fl, prior: list[date]) -> dict | None:
    """Factor to rescale `s`'s history before day `d` so that its move on `d` matches NSE's
    official move net of any corporate action. Works whether or not our source already adjusted:
        factor = our_move * ca_factor / official_move
      our_move      = our close(d) / our previous close
      official_move = NSE close(d) / NSE previous close (raw)
      ca_factor     = from the NSE notice (bonus a:b -> b/(a+b), split Rs x->y -> y/x), or for a
                      demerger the special-session price: NSE open(d) / NSE previous close; 1 if none.
    A genuine crash (no corporate action, our data = NSE) gives factor 1 and is left untouched."""
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
    purposes = corporate.actions_on(s_then, d.date(), prior)
    ca = 1.0
    if purposes:
        pf = corporate.purpose_factor(purposes)
        ca = pf if pf is not None else (float(row["open"]) / float(row["prev_close"]) if row["open"] > 0 else 1.0)
    our_move = float(our_now) / float(ours.iloc[-1])
    official_move = float(row["close"]) / float(row["prev_close"])
    factor = our_move * ca / official_move
    if not (np.isfinite(factor) and factor > 0 and abs(factor - 1) > CA_TOLERANCE):
        return None
    return {"symbol": s, "date": d.date().isoformat(), "factor": round(factor, 6),
            "reason": " + ".join(purposes) if purposes else "data correction (matched to NSE)"}


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

    # 1) Deep history from Yahoo for new symbols, and catch-up for very stale ones.
    starts: dict[str, date] = {}
    for s in all_syms:
        if recently_failed(s):
            continue
        m, last = meta["symbols"].get(s), last_date(s)
        if not m or last is None or date.fromisoformat(m["full_from"]) > start_full + timedelta(days=FULL_SLACK_DAYS):
            starts[s] = start_full
        elif (today - last).days > NSE_MAX_DAYS:
            starts[s] = last - timedelta(days=7)
    if starts:
        n_full = sum(1 for d in starts.values() if d == start_full)
        log(f"Downloading history for {len(starts)} symbols"
            f"{f' ({n_full} new - first run takes ~2-4 min)' if n_full > 20 else ''}...")
        fetched = yahoo.history(list(starts), starts, today, progress=progress)
        good, replace = {}, set()
        for s, df in fetched.items():
            df = df[df.index < pd.Timestamp(today)]  # today's row comes from NSE / live quotes
            if df.empty:
                fl = meta["failed"].get(s, {})
                meta["failed"][s] = {"count": fl.get("count", 0) + 1, "last_try": today.isoformat()}
                errors[s] = yahoo.errors.get(s, "no data from Yahoo")
                continue
            meta["failed"].pop(s, None)
            good[s] = _clean(df)
            if starts[s] == start_full:
                replace.add(s)
                meta["symbols"][s] = {"full_from": start_full.isoformat()}
        _merge(frames, _wide(good), replace)
        changed = bool(good)
        touched = list(good)
    else:
        touched = []

    # 1b) Repair downloaded history (fake bars, missing days, unadjusted splits) with NSE data.
    to_repair = touched if meta.get("repaired_v1") else all_syms
    if to_repair and len(frames["close"]):
        rep = _repair_history(frames, to_repair, log)
        meta["repaired_v1"] = True
        if rep["flat_bars"] or rep["filled_days"] or rep["adjusted"]:
            log(f"History repaired: {rep['flat_bars']} fake bars removed, {rep['filled_days']} days filled "
                f"from NSE, {len(rep['adjusted'])} splits/bonuses/demergers adjusted")
            corp_actions.extend(rep["adjusted"])
            changed = True

    # 2) Official NSE files for every completed trading day we're missing: days after the store's
    #    last date, plus any recent days that freshly downloaded symbols lack.
    lasts = [d for d in (last_date(s) for s in touched) if d and (today - d).days <= NSE_MAX_DAYS]
    if len(frames["close"]):
        lasts.append(frames["close"].index[-1].date())
    nse_status = "up to date"
    if lasts:
        from_day = min(lasts) + timedelta(days=1)
        last_try_day = today if now.hour >= NSE_PUBLISH_HOUR else today - timedelta(days=1)
        days = [d for d in _weekdays(from_day, last_try_day) if d.isoformat() not in holidays]
        if days:
            files = nse.fetch_days(days)
            ok_days = sorted(d for d, fl in files.items() if fl.status == "ok")
            for d, fl in files.items():
                if fl.status == "missing" and (today - d).days >= 2:
                    holidays.add(d.isoformat())  # no file two days later => market holiday
                elif fl.status == "error":
                    nse_status = "NSE archive unreachable for some days - will retry next scan"
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
                # Corporate actions with ex-date d (split, bonus, demerger) for our symbols.
                prior = _prior_days(frames, ts)
                notices = corporate.fetch_bc(prior[0]) if prior else None
                if notices is not None:
                    todays = notices[notices["ex_date"] == d.isoformat()]
                    for s in sorted(set(todays["symbol"]) & set(frames["close"].columns)):
                        adj = _event_factor(frames, s, ts, fl, prior)
                        if adj:
                            _apply_corporate_action(frames, s, ts, adj["factor"])
                            corp_actions.append(adj)
            if ok_days:
                nse_status = f"NSE official data to {ok_days[-1].isoformat()}"

    meta["holidays"] = sorted(holidays)[-400:]
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
    trading_today = today.weekday() < 5 and today.isoformat() not in holidays
    live_rows: dict[str, dict] = {}
    live_source = None
    if trading_today and session_started and complete_upto and today > complete_upto:
        if fyers is not None:
            for s, (qdate, row) in fyers.live_rows(all_syms).items():
                if (qdate is None or qdate == today) and row.get("close"):
                    live_rows[s] = {c: float(row.get(c) or 0) for c in COLS}
            live_source = "Fyers (real-time)" if live_rows else None
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
