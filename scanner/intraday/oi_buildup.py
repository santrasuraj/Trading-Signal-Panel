"""F&O OI build-up: the live rule (shared with run.oi_buildup_signals) and its backtest on stored OI snapshots.

NSE publishes no intraday OI history, so the backtest runs only on the OI-spurts snapshots this app stored while it ran
(scanner/fno_intraday.append_history -> data/fno/oi_history/), with the 5-minute bars of the same days. Until it has
OI_MIN_DAYS sessions of snapshots the strategy stays 'untested'; then it gets a status by the same rules as every other
intraday strategy (run.strategy_status) and joins the strategies in intraday.json, where the options evidence rule and
the Signals page read it.

The backtest replays what the live signal would have seen, bar by bar:
  * At each 5-minute bar's close, the newest snapshot the app had FETCHED by then (no older than OI_MAX_AGE_MIN, like
    live) and the bars completed by then: the last close, VWAP, the day's low / high so far (oi_rule, the live rule).
  * Each bar close keeps the OI_MAX_SIGNALS biggest OI changes among the signals, like the live list.
  * One trade per stock and side a day, never two at once on a stock (the options side's repeat / stacking rules);
    no new entry from 14:30 (the options side's NO_NEW_INTRADAY).
  * Fill at the next bar's open, stop the day's low (high) so far, target twice the risk from the signal's price, square
    off at 15:00; costs, slippage and sizing as every intraday strategy (engine.run_intraday).
Not modelled: a snapshot NSE had not updated counts from its first fetch (a later fetch of it is not stored), so a
signal can start a few minutes later than it did live; the live list's forming-bar prices (Yahoo / tick bars).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .. import fno_intraday as fi
from .engine import SLOTS, Day, IntradayStrategy, Trade
from .strategies import S_1430, _trade

OI_KEY, OI_NAME = "oi_buildup", "F&O OI build-up (live)"
OI_MAX_SIGNALS = 10
OI_MAX_AGE_MIN = 20                  # a live OI snapshot older than this (the 5-minute job stopped) gives no signals
OI_MIN_MOVE_PCT = 0.2                # a build-up needs the price to have moved: a flat stock is neither long nor short
OI_RISK = (0.002, 0.03)              # the stop (day's low / high so far) 0.2% - 3% from the price
OI_RR = 2.0                          # target = twice the risk
OI_MIN_DAYS = 40                     # sessions of stored OI snapshots before the backtest is judged (as every strategy)
OI_DESCRIPTION = ("Live F&O positioning from NSE's OI-spurts feed: open interest of all a stock's futures and options "
                  f"up {fi.MIN_OI_PCT:g}%+ on the day while the price is up {OI_MIN_MOVE_PCT:g}%+ and above VWAP = long "
                  "build-up, a LONG; OI up while the price is down and below VWAP = short build-up, a SHORT. Stop the "
                  "day's low (high) so far, target twice the risk. Tested only on the OI snapshots this app stored "
                  "(NSE keeps no intraday OI history).")


def oi_rule(px, prev_close, vw, low, high, oi_chg_pct):
    """The live OI build-up rule on numbers or numpy arrays (the backtest runs it on every bar close at once).
    px: the last close; vw: VWAP at that bar; low / high: the day's low / high so far; oi_chg_pct: open interest change
    since yesterday (NaN / None = unknown). Returns (side, stop, price change %): side +1 a long build-up above VWAP, -1 a
    short build-up below VWAP, 0 none - the same as fno_intraday.classify plus the price-move, VWAP and stop checks."""
    px = np.asarray(px, dtype=float)
    vw = np.asarray(vw, dtype=float)
    oi = np.asarray(np.nan if oi_chg_pct is None else oi_chg_pct, dtype=float)
    with np.errstate(invalid="ignore", divide="ignore"):
        chg = (px / prev_close - 1) * 100
        side = np.where(chg > fi.MIN_PRICE_PCT, 1, -1)
        stop = np.where(side > 0, low, high).astype(float)
        risk = np.abs(px - stop) / px
        ok = ((np.abs(chg) >= OI_MIN_MOVE_PCT)                    # an unchanged price says nothing about direction
              & (np.abs(oi) >= fi.MIN_OI_PCT) & (oi > 0)          # a build-up: OI up MIN_OI_PCT+ (not covering/unwinding)
              & np.where(side > 0, px >= vw, px <= vw)             # price and positioning agree
              & (risk >= OI_RISK[0]) & (risk <= OI_RISK[1]))
    return np.where(ok, side, 0), stop, chg


def _so_far(d: Day) -> tuple[np.ndarray, ...]:
    """Per bar k, what the live signal sees at k's close: the last traded bar up to k (-1 = none yet), its close, VWAP,
    and the day's low / high up to it."""
    k = np.arange(SLOTS)
    last = np.maximum.accumulate(np.where(np.isnan(d.c), -1, k))
    at = np.maximum(last, 0)
    low = np.fmin.accumulate(np.where(np.isnan(d.l), np.inf, d.l))[at]
    high = np.fmax.accumulate(np.where(np.isnan(d.h), -np.inf, d.h))[at]
    return last, d.c[at], d.vwap()[at], low, high


def _snapshot_index(snaps: pd.DataFrame) -> dict:
    """Per day (a datetime.date): the fetch times (minutes after midnight, ascending) and each symbol's OI change % per
    snapshot (NaN where a snapshot lacks the symbol)."""
    out = {}
    if snaps is None or snaps.empty:
        return out
    fetched = snaps["fetched"].to_numpy().astype("datetime64[s]")
    day_of = fetched.astype("datetime64[D]")
    sym_all, pct_all = snaps["symbol"].astype(str).to_numpy(), snaps["oi_chg_pct"].to_numpy(dtype=float)
    for day in np.unique(day_of):
        m = day_of == day
        times = np.unique(fetched[m])
        sid = np.searchsorted(times, fetched[m])
        mins = (times - day.astype("datetime64[s]")).astype(float) / 60
        per = {}
        for sym, h in pd.DataFrame({"s": sym_all[m], "i": sid, "p": pct_all[m]}).groupby("s"):
            a = np.full(len(times), np.nan)
            a[h["i"].to_numpy()] = h["p"].to_numpy()
            per[str(sym)] = a
        out[day.astype(object)] = (mins, per)
    return out


def _oi_at_bar_closes(mins: np.ndarray, per_symbol: np.ndarray) -> np.ndarray:
    """The OI change % the live signal used at each bar's close: from the newest snapshot fetched by then, if fresh."""
    close = 555 + 5 * (np.arange(SLOTS) + 1)                     # bar k closes at 09:20 + 5k
    i = np.searchsorted(mins, close, side="right") - 1
    fresh = (i >= 0) & (close - mins[np.maximum(i, 0)] <= OI_MAX_AGE_MIN)
    return np.where(fresh, per_symbol[np.maximum(i, 0)], np.nan)


def picks(days: list[Day], snaps: pd.DataFrame) -> dict[tuple[str, pd.Timestamp], list[Trade]]:
    """The trades the live OI build-up signals would have led to, per (symbol, day) (see the module's rules)."""
    index = _snapshot_index(snaps)
    by_date: dict = {}
    for d in days:
        if d.date.date() in index and d.prev_close > 0:
            by_date.setdefault(d.date.date(), []).append(d)
    out: dict[tuple[str, pd.Timestamp], list[Trade]] = {}
    for day, ds in by_date.items():
        mins, per = index[day]
        cands = []                                               # (bar k, -|OI %|, day idx, side, price, stop)
        for j, d in enumerate(ds):
            if d.symbol not in per:
                continue
            oi = _oi_at_bar_closes(mins, per[d.symbol])
            last, px, vw, low, high = _so_far(d)
            side, stop, _ = oi_rule(px, d.prev_close, vw, low, high, oi)
            last_k = min(S_1430, d.flat_slot) - 1                # the entry bar k + 1 must start before 14:30
            for k in np.flatnonzero((side != 0) & (last >= 0) & (np.arange(SLOTS) < last_k)):
                cands.append((int(k), -abs(float(oi[k])), j, int(side[k]), float(px[k]), float(stop[k])))
        listed: dict[int, list] = {}
        for c in sorted(cands):                                  # each bar close: the OI_MAX_SIGNALS biggest OI changes
            if len(listed.setdefault(c[0], [])) < OI_MAX_SIGNALS:
                listed[c[0]].append(c)
        taken: dict[int, list[Trade]] = {}
        for k in sorted(listed):
            for _, neg_oi, j, side, px, stop in listed[k]:
                d, done = ds[j], taken.setdefault(j, [])
                if any(t.side == side for t in done) or (done and done[-1].exit_slot >= k + 1):
                    continue                                     # a repeat, or a trade still open on the stock
                t = _trade(d, side, k + 1, float(d.o[k + 1]), stop, px + side * OI_RR * abs(px - stop),
                           priority=-neg_oi)
                if t is not None:
                    done.append(t)
        for j, ts in taken.items():
            if ts:
                out[(ds[j].symbol, ds[j].date)] = ts
    return out


def build_strategy(cfg: dict, snaps: pd.DataFrame) -> IntradayStrategy:
    """The OI build-up as an engine strategy (sizing, costs and square-off as every intraday strategy). Up to
    OI_MAX_SIGNALS trades a day (config.yaml intraday_strategies.oi_buildup.max_trades_per_day), each on an equal share
    of the leverage limit."""
    conf = (cfg.get("intraday_strategies") or {}).get(OI_KEY) or {}
    return IntradayStrategy(
        OI_KEY, OI_NAME, OI_DESCRIPTION, "EXPERIMENTAL",
        day_trades=lambda d, p: [t for t in p["picks"].get((d.symbol, d.date), [])],
        universe="liquid", max_trades_per_day=int(conf.get("max_trades_per_day", OI_MAX_SIGNALS)),
        prepare=lambda days, p: {"picks": picks(days, snaps)})


def history_days(snaps: pd.DataFrame, before) -> list:
    """The sessions (datetime.date) before `before` with stored OI snapshots."""
    if snaps is None or snaps.empty:
        return []
    days = np.unique(snaps["fetched"].to_numpy().astype("datetime64[D]"))
    return [x for x in days.astype(object) if x < pd.Timestamp(before).date()]
