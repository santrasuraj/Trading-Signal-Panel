"""Intraday (MIS) backtest engine on 5-minute bars.

Rules that every intraday strategy is held to (see docs/strategy_catalogue.md section 7):
  * Signals on a bar's close fill at the NEXT bar's open (+ slippage). Stop-entry orders fill at
    max(open, level) for longs / min(open, level) for shorts - a gap through the level fills at the open.
  * Inside one bar the order of high and low is unknown: if both the stop and the target are touched,
    the STOP is assumed to have been hit first.
  * Forced square-off: 15:00 for F&O stocks (FYERS auto-squares MIS at 15:05 since NSE's closing
    auction), 15:15 for other stocks/ETFs.
  * Costs: FYERS intraday brokerage (Rs 20 or 0.03% per order, lower), STT 0.025% on the sell side,
    NSE charge, SEBI fee, stamp 0.003% on buys, 18% GST, plus slippage per side.
  * Profits are speculative business income: taxed at the slab rate (configurable), not as capital gains.
  * Each day the first `max_trades_per_day` trades by entry time are taken (ties by priority), each
    sized on an equal share of leverage x equity - a rule that can be followed in real time.
    A strategy that ranks stocks against each other (gap fade, stocks in play) does that in its
    `prepare` hook from what is known at its decision time, so picks that never trigger stay empty slots.
  * Every trade also records its gross return (fill to fill, before slippage and charges), so the
    results show whether a strategy has no edge or whether costs eat it.
Not modelled yet: participation cap / impact slippage, the F&O list as of each date, ex-date exclusion,
the 3 Aug / 7 Sep 2026 sample split.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, fields
from typing import Callable

import numpy as np
import pandas as pd

BAR_MIN = 5
SLOTS = 75                         # 09:15 .. 15:25 bar starts


def slot_of(hh: int, mm: int) -> int:
    """Bar index of the 5-minute bar starting at hh:mm (09:15 -> 0)."""
    return (hh * 60 + mm - 555) // BAR_MIN


FLAT_FNO = slot_of(15, 0)          # 69: exit at the open of the 15:00 bar
FLAT_OTHER = slot_of(15, 15)       # 72


@dataclass(frozen=True)
class IntradayCosts:
    brokerage_pct: float = 0.03
    brokerage_max: float = 20.0
    stt_sell_pct: float = 0.025
    exchange_pct: float = 0.00307
    sebi_pct: float = 0.0001
    stamp_buy_pct: float = 0.003
    gst_pct: float = 18.0
    slippage_large_pct: float = 0.03      # Nifty 50 stocks, per side
    slippage_other_pct: float = 0.07      # other F&O stocks, per side
    stop_entry_extra_pct: float = 0.05    # extra slippage when a stop order triggers
    tax_pct: float = 31.2                 # speculative income at slab rate incl. cess (set yours)

    @classmethod
    def from_config(cls, cfg: dict | None) -> "IntradayCosts":
        known = {f.name for f in fields(cls)}
        return cls(**{k: float(v) for k, v in (cfg or {}).items() if k in known})

    def charges(self, buy_value: float, sell_value: float) -> float:
        """Rupees of charges for one round trip (long or short)."""
        brk = min(self.brokerage_max, buy_value * self.brokerage_pct / 100) + \
            min(self.brokerage_max, sell_value * self.brokerage_pct / 100)
        exch = (buy_value + sell_value) * self.exchange_pct / 100
        sebi = (buy_value + sell_value) * self.sebi_pct / 100
        gst = (brk + exch + sebi) * self.gst_pct / 100
        return brk + exch + sebi + gst + sell_value * self.stt_sell_pct / 100 + buy_value * self.stamp_buy_pct / 100


@dataclass
class Day:
    """One symbol's session as numpy arrays indexed by 5-minute slot (NaN where Yahoo/Fyers had no bar)."""
    symbol: str
    date: pd.Timestamp
    o: np.ndarray
    h: np.ndarray
    l: np.ndarray
    c: np.ndarray
    v: np.ndarray
    prev_close: float
    prev_high: float
    prev_low: float
    atr_d: float                 # daily ATR(14) up to the previous day
    is_fno: bool
    large: bool                  # Nifty 50 member (lower slippage)
    results_day: bool = False    # results announced today or after yesterday's close
    ctx: dict = field(default_factory=dict)   # per-strategy extras (rolling stats from earlier days)

    @property
    def flat_slot(self) -> int:
        return FLAT_FNO if self.is_fno else FLAT_OTHER

    def vwap(self) -> np.ndarray:
        tp = (self.h + self.l + self.c) / 3
        v = np.nan_to_num(self.v)
        # one VWAP for every source: from 09:20, seeded by the 09:15 typical price (Yahoo history has no 09:15 volume)
        v[0] = 0.0
        pv = np.nancumsum(np.nan_to_num(tp) * v)
        cv = np.cumsum(v)
        with np.errstate(invalid="ignore", divide="ignore"):
            out = np.where(cv > 0, pv / cv, np.nan)
        return np.where(np.isnan(out), tp, out)   # no volume yet (the 09:15 bar): use its typical price


@dataclass
class Trade:
    strategy: str
    symbol: str
    date: str
    side: int                    # +1 long, -1 short
    entry_slot: int
    entry_px: float
    exit_slot: int
    exit_px: float
    stop: float | None
    reason: str
    stop_entry: bool = False
    priority: float = 0.0
    qty: int = 0
    pnl: float = 0.0             # rupees after charges and slippage
    ret_pct: float = 0.0         # % of notional
    gross_pct: float = 0.0       # % from entry_px to exit_px, before slippage and charges


def walk_exit(d: Day, side: int, entry_slot: int, stop: float | None, target: float | None,
              exit_slot: int | None = None, check_entry_bar: bool = True) -> tuple[int, float, str]:
    """Walk bars after entry until stop / target / time exit / forced flat. Returns (slot, price, reason).
    Stop wins when stop and target are both inside the same bar (conservative)."""
    last = min(exit_slot if exit_slot is not None else d.flat_slot, d.flat_slot)
    start = entry_slot if check_entry_bar else entry_slot + 1
    for i in range(start, last):
        if math.isnan(d.l[i]):
            continue
        o = d.o[i]
        if stop is not None:
            if side > 0 and d.l[i] <= stop:
                return i, (min(o, stop) if i > entry_slot else stop), "stop"
            if side < 0 and d.h[i] >= stop:
                return i, (max(o, stop) if i > entry_slot else stop), "stop"
        if target is not None and i > entry_slot:   # never take profit inside the entry bar
            if side > 0 and d.h[i] >= target:
                return i, max(o, target), "target"
            if side < 0 and d.l[i] <= target:
                return i, min(o, target), "target"
    reason = "time" if exit_slot is not None and exit_slot < d.flat_slot else "square-off"
    if last < SLOTS and not math.isnan(d.o[last]):
        return last, d.o[last], reason
    for j in range(last - 1, entry_slot - 1, -1):   # bar missing: latest earlier close
        if not math.isnan(d.c[j]):
            return j, d.c[j], reason
    return entry_slot, d.c[entry_slot], reason


def stop_entry(d: Day, side: int, level: float, start: int, end: int) -> tuple[int, float] | None:
    """First bar in [start, end) whose range crosses `level` (buy-stop above / sell-stop below)."""
    for i in range(start, min(end, d.flat_slot)):
        if math.isnan(d.h[i]):
            continue
        if side > 0 and d.h[i] >= level:
            return i, max(d.o[i], level)
        if side < 0 and d.l[i] <= level:
            return i, min(d.o[i], level)
    return None


@dataclass
class IntradayStrategy:
    key: str
    name: str
    description: str
    evidence: str
    day_trades: Callable[[Day, dict], list[Trade]]     # candidate trades for one symbol-day
    params: dict = field(default_factory=dict)
    universe: str = "liquid"            # liquid | top30 | etf
    max_trades_per_day: int = 5
    # optional hooks (None = the default behaviour above):
    # prepare(days, params) -> extra params for day_trades, e.g. the day's cross-sectional picks; it must use
    #   only what is known at the strategy's decision time
    prepare: Callable[[list[Day], dict], dict] | None = None
    notional_x: float | None = None     # size each trade at this multiple of equity instead of by risk
    slippage_pct: float | None = None   # per side, replaces the Nifty 50 / other tiers (e.g. NIFTYBEES)
    horizon: str = field(default="intraday", init=False)


@dataclass
class IntradayResult:
    key: str
    trades: list[Trade]
    daily: pd.Series                   # equity by day
    metrics: dict


def run_intraday(strategy: IntradayStrategy, days: list[Day], costs: IntradayCosts, capital: float = 500000.0,
                 risk_pct: float = 0.5, leverage: float = 2.0) -> IntradayResult:
    """Collect candidate trades, keep the first `max_trades_per_day` each day by entry time (ties by
    priority), size them by risk (risk_pct of equity to the stop, each capped at leverage x equity /
    max_trades_per_day, so total notional <= leverage x equity), and apply costs."""
    by_day: dict[pd.Timestamp, list[Trade]] = {}
    params = strategy.params if strategy.prepare is None else {**strategy.params,
                                                               **strategy.prepare(days, strategy.params)}
    for d in days:
        for t in strategy.day_trades(d, params):
            t.strategy = strategy.key
            by_day.setdefault(d.date, []).append(t)
    large = {(d.symbol, d.date): d.large for d in days}
    all_days = sorted({d.date for d in days})
    equity = capital
    curve, kept = [], []
    for day in all_days:
        # first come, first served: a later, higher-priority trigger cannot displace a trade already taken
        cands = sorted(by_day.get(day, []), key=lambda t: (t.entry_slot, -t.priority))[:strategy.max_trades_per_day]
        day_pnl = 0.0
        cap_each = equity * leverage / max(strategy.max_trades_per_day, 1)
        for t in cands:
            slip = (strategy.slippage_pct if strategy.slippage_pct is not None else
                    costs.slippage_large_pct if large.get((t.symbol, day)) else costs.slippage_other_pct) / 100
            entry = t.entry_px * (1 + t.side * (slip + (costs.stop_entry_extra_pct / 100 if t.stop_entry else 0)))
            exitp = t.exit_px * (1 - t.side * slip * (2 if t.reason == "stop" else 1))
            if strategy.notional_x is not None:
                qty = int(min(equity * strategy.notional_x, cap_each) / entry)
            else:
                per_share_risk = abs(entry - t.stop) if t.stop else entry * 0.01
                qty = int(min(equity * risk_pct / 100 / max(per_share_risk, entry * 0.001), cap_each / entry))
            if qty < 1:
                continue
            buy_v, sell_v = (entry * qty, exitp * qty) if t.side > 0 else (exitp * qty, entry * qty)
            gross = (exitp - entry) * qty * t.side
            t.qty = qty
            t.pnl = gross - costs.charges(buy_v, sell_v)
            t.ret_pct = t.pnl / (entry * qty) * 100
            t.gross_pct = t.side * (t.exit_px / t.entry_px - 1) * 100
            day_pnl += t.pnl
            kept.append(t)
        equity += day_pnl
        curve.append((day, equity))
    daily = pd.Series({d: e for d, e in curve}, dtype=float)
    return IntradayResult(strategy.key, kept, daily, intraday_metrics(kept, daily, capital, costs))


def intraday_metrics(trades: list[Trade], daily: pd.Series, capital: float, costs: IntradayCosts) -> dict:
    if daily.empty:
        return {"days": 0, "trades": 0}
    eq = pd.concat([pd.Series([capital]), daily.reset_index(drop=True)])
    rets = eq.pct_change().dropna()
    n = len(rets)
    mean, sd = rets.mean(), rets.std()
    pnl = np.array([t.pnl for t in trades]) if trades else np.array([0.0])
    wins, losses = pnl[pnl > 0], pnl[pnl <= 0]
    total = daily.iloc[-1] / capital - 1
    gross_profit = max(daily.iloc[-1] - capital, 0)
    after_tax = (daily.iloc[-1] - gross_profit * costs.tax_pct / 100) / capital - 1
    t_stat = float(mean / (sd / math.sqrt(n))) if sd > 0 and n > 1 else None
    return {
        "days": int(n), "trades": len(trades),
        "trades_per_day": round(len(trades) / n, 2),
        "return_pct": round(total * 100, 2),
        "after_tax_return_pct": round(after_tax * 100, 2),
        "annualised_pct": round(((1 + total) ** (252 / n) - 1) * 100, 1) if n >= 20 and total > -1 else None,
        "sharpe": round(float(mean / sd * math.sqrt(252)), 2) if sd > 0 else None,
        "max_dd_pct": round(float((eq / eq.cummax() - 1).min() * 100), 2),
        "win_rate": round(float((pnl > 0).mean() * 100), 1) if trades else None,
        "avg_trade_pct": round(float(np.mean([t.ret_pct for t in trades])), 3) if trades else None,
        "avg_trade_gross_pct": round(float(np.mean([t.gross_pct for t in trades])), 3) if trades else None,
        "profit_factor": round(float(wins.sum() / -losses.sum()), 2) if losses.sum() < 0 else None,
        "avg_day_pct": round(float(mean * 100), 3),
        "ci95_day_pct": [round(float((mean - 1.96 * sd / math.sqrt(n)) * 100), 3),
                         round(float((mean + 1.96 * sd / math.sqrt(n)) * 100), 3)] if n > 1 else None,
        "t_stat": round(t_stat, 2) if t_stat is not None else None,
        "significant": bool(t_stat is not None and abs(t_stat) >= 2),
        "start": str(daily.index[0].date()), "end": str(daily.index[-1].date()),
    }
