"""Live signal engine: today's intraday signals about a second after each 5-minute bar, inside the dashboard server.

The 5-minute scheduled task (`intraday_sync.py --signals`) starts a new Python each time and rebuilds everything: ~4 s
of imports, the daily store, ~45 days of 5-minute bars, the results calendar and every stock-day's context (~15 s),
then the strategies (~0.6 s) - and it fires on the clock, so a bar that closes just after it waits for the next run.
Measured on 13 Nov 2026 (151 stocks): ~20 s per run, plus up to 5 minutes of waiting.

This engine keeps all of that in memory for the day and works incrementally:
  * once a day (or when config.yaml changes): the daily store, the universe, the earlier sessions' bars, the results
    calendar, each stock's daily context (build_days' daily_cache) and each stock's running state at the end of
    yesterday (build_days' carry: the early-volume and 09:45-move history today's context is computed from);
  * on every new bar (the live feed's bus event, scanner/intraday/bus.py, or the bars file changing): only TODAY's
    bars - the FYERS live feed's, plus Yahoo's (~15 min delayed, refreshed every YAHOO_EVERY_S) for the stocks the feed
    does not stream - are turned into today's Day per stock, from the carried state, and the strategies run on them.
The signals come from the same run_intraday_signals as the scheduled task (one code path, so live and backtest stay
identical) and are written to the same data/results/intraday_signals.json.

It only runs while the FYERS live feed is fresh: without real-time bars there is nothing to be fast about, and the
scheduled task keeps covering that case.
"""
from __future__ import annotations

import json
import threading
import time
from datetime import timedelta

import pandas as pd

from ..events import results_history
from ..settings import ist_now, load_config
from ..store import load_store
from ..universe import get_universe
from . import data as idata
from . import live as live_feed
from .run import (INTRADAY_DIR, SIGNAL_HISTORY_DAYS, build_days, intraday_universe, run_intraday_signals)
from .strategies import build_intraday_strategies

YAHOO_EVERY_S = 300                 # Yahoo is ~15 min delayed: refreshing it more often than the old job gains nothing


class LiveEngine:
    """One per server. refresh() is serialised by a lock; prepare() is run_intraday_signals' `warm` hook."""

    def __init__(self, log=print, frames_fn=None, cfg_fn=None):
        self.log = log
        self.frames_fn = frames_fn or load_store      # the server passes its cached store (shared, not loaded twice)
        self.cfg_fn = cfg_fn or load_config
        self.lock = threading.Lock()
        self.day = None                 # the date the caches are for
        self.cfg_key = None
        self.frames = None
        self.symbols: list[str] = []
        self.info: dict = {}
        self.large: set[str] = set()
        self.results: dict = {}
        self.strategies: list = []
        self.daily_cache: dict = {}
        self.carry: dict = {}
        self._yahoo: tuple[float, pd.DataFrame] | None = None
        self.latest: dict | None = None  # the last signals it computed
        self.ready_at: float | None = None   # epoch seconds when they were ready
        self.stats = {"runs": 0, "day_builds": 0, "last_compute_s": None, "last_day_build_s": None, "last_error": None}

    # ---------------------------------------------------------------- once a day
    def _ensure_day(self, cfg: dict, now) -> None:
        key = json.dumps(cfg, sort_keys=True, default=str)
        if self.day == now.date() and self.cfg_key == key:
            return
        t0 = time.perf_counter()
        today = pd.Timestamp(now.date())
        frames = self.frames_fn()
        symbols, info = intraday_universe(cfg, frames)
        store = idata.IntradayStore(INTRADAY_DIR / "bars")
        start = today - pd.Timedelta(days=SIGNAL_HISTORY_DAYS)
        hist = store.load("5m", symbols, start=start, end=today - pd.Timedelta(days=1))
        hist = hist[hist["symbol"].isin(symbols) & (hist["ts"] >= start) & (hist["ts"] < today)]
        large = set(get_universe("nifty50")[0]["symbol"])
        first = hist["ts"].min().date() if len(hist) else today.date()
        results = results_history(first - timedelta(days=7), now.date(), log=self.log)
        daily_cache: dict = {}
        carry: dict = {}
        if len(hist):
            build_days(hist, frames, info, large, results, daily_cache=daily_cache, carry=carry)
        self.frames, self.symbols, self.info, self.large, self.results = frames, symbols, info, large, results
        self.daily_cache, self.carry = daily_cache, carry
        self.strategies = build_intraday_strategies(cfg)
        self.day, self.cfg_key, self._yahoo = now.date(), key, None
        self.stats["day_builds"] += 1
        self.stats["last_day_build_s"] = round(time.perf_counter() - t0, 2)
        self.log(f"Live signal engine: {len(symbols)} stocks, {hist['ts'].dt.normalize().nunique() if len(hist) else 0} "
                 f"earlier sessions ready in {self.stats['last_day_build_s']:.1f} s")

    # ---------------------------------------------------------------- every new bar
    def todays_bars(self, now) -> pd.DataFrame:
        """Today's 5-minute bars like update_bars(today_only=True) gives them, without its full reload: what the store
        already has for today (the scheduled task's Yahoo bars), Yahoo for the stocks the live feed doesn't cover (at
        most every YAHOO_EVERY_S) and the live feed's completed bars, the best source winning per bar."""
        today = pd.Timestamp(now.date())
        store = idata.IntradayStore(INTRADAY_DIR / "bars")
        stored = store.load("5m", self.symbols, start=today, end=today)
        live_today = idata.clean_bars(live_feed.load_live(INTRADAY_DIR), "5m")
        covered: set[str] = set()
        if len(live_today) and live_feed.feed_fresh(INTRADAY_DIR, now):
            first = live_today.groupby(live_today["symbol"].astype(str))["ts"].min()
            covered = set(first[first.dt.hour * 60 + first.dt.minute <= 9 * 60 + 20].index.astype(str))
        need = [s for s in self.symbols if s not in covered]
        yahoo = idata.empty_bars()
        if need:
            if self._yahoo is None or time.time() - self._yahoo[0] >= YAHOO_EVERY_S:
                try:
                    raw = idata.fetch_yahoo_intraday(need, "5m", days=1, log=self.log)
                    clean = idata.clean_bars(raw.assign(source="yahoo"), "5m", drop_synthetic_close=True,
                                             now=now.replace(tzinfo=None))
                    self._yahoo = (time.time(), clean[clean["ts"] >= today])
                except Exception as e:                       # Yahoo down: the live feed's stocks still work
                    self.log(f"Live signal engine: Yahoo bars failed ({type(e).__name__}: {e})")
                    self._yahoo = (time.time(), idata.empty_bars())
            yahoo = self._yahoo[1]
            yahoo = yahoo[yahoo["symbol"].isin(need)]
        bars = idata.merge_by_priority(stored, yahoo, live_today)
        return bars[bars["symbol"].isin(self.symbols) & (bars["ts"] >= today)]

    def prepare(self, cfg: dict, now, log=None) -> tuple[dict, pd.DataFrame, dict]:
        """run_intraday_signals' warm hook: (universe info, today's bars, today's Day per stock)."""
        self._ensure_day(cfg, now)
        todays = self.todays_bars(now)
        if todays.empty:
            return self.info, todays, {}
        carry = {k: (list(ev), list(r1), last) for k, (ev, r1, last) in self.carry.items()}   # today only, never kept
        days = build_days(todays, self.frames, self.info, self.large, self.results, daily_cache=self.daily_cache,
                          carry=carry)
        return self.info, todays, days

    def prebuild(self, now=None) -> bool:
        """Build the day's caches ahead of the first bar (the server calls it shortly before the open). True if built."""
        now = now or ist_now()
        with self.lock:
            if self.day == now.date():
                return False
            self._ensure_day(self.cfg_fn(), now)
            return True

    def refresh(self, cfg: dict | None = None, now=None, force: bool = False) -> dict | None:
        """Today's signals now, or None when there is nothing to do (market closed, before 09:20, the FYERS live feed not
        fresh - the scheduled task covers that). `force`: compute even without a fresh feed (tests)."""
        now = now or ist_now()
        with self.lock:
            if not force:
                if not live_feed.market_open_now() or (now.hour, now.minute) < (9, 20):
                    return None
                if not live_feed.feed_fresh(INTRADAY_DIR, now):
                    return None
            t0 = time.perf_counter()
            try:
                out = run_intraday_signals(cfg or self.cfg_fn(), log=self.log, now=now, warm=self)
            except Exception as e:
                self.stats["last_error"] = f"{type(e).__name__}: {e}"
                raise
            self.stats["runs"] += 1
            self.stats["last_compute_s"] = round(time.perf_counter() - t0, 3)
            self.stats["last_error"] = None
            self.latest, self.ready_at = out, time.time()
            return out
