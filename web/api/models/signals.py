"""4. signals and sizing."""
from __future__ import annotations

from typing import Literal

from .common import AsOf, ISODate, Model, StrategyStatus
from .strategies import Order, StrategySummary


class Allocation(Model):
    strategy_key: str
    pct: float
    capital: float


class GroupSizing(Model):
    capital: float
    per_position: float
    max_positions: int
    sizing: Literal["equal", "risk"]
    risk_pct: float | None = None


class SignalGroup(Model):
    strategy: StrategySummary
    sizing: GroupSizing
    orders: list[Order]
    empty_reason: str | None = None


class RegimeInfo(Model):
    regime_up: bool
    note: str | None = None


class SignalTotals(Model):
    buy_count: int
    sell_count: int
    buy_amount: float
    sell_amount: float | None = None
    risk_amount: float
    results_warnings: int


class SignalsResponse(Model):
    as_of: AsOf
    capital: float
    min_position: float
    allocations: list[Allocation]
    allocation_source: Literal["config", "query", "none"]
    allocation_warning: str | None = None
    sized_like_scan: bool                       # true when allocation_source == 'none' (rows equal latest.json)
    regime: RegimeInfo
    groups: list[SignalGroup]                   # non-comparison groups first
    totals: SignalTotals


# ------------------------------------------------------------------ signal track record
class TrackSignal(Model):
    """One BUY signal the scanner gave (journal), followed on real prices by the strategy's own rules."""
    strategy_key: str
    strategy_name: str
    signal_date: ISODate
    symbol: str
    reason: str
    signal_price: float | None = None
    status_then: StrategyStatus | None = None     # the strategy's status on the signal day (journaled since 27 Oct)
    state: Literal["pending", "not_filled", "open", "closed"]
    note: str | None = None
    qty: int | None = None
    entry_date: ISODate | None = None
    entry_price: float | None = None              # next open + slippage
    exit_date: ISODate | None = None
    exit_price: float | None = None
    exit_reason: str | None = None
    last_price: float | None = None               # exit price, or the last close while open
    stop: float | None = None
    days: int
    pnl: float                                    # rupees after all charges (open: if sold at the last close)
    ret_pct: float


class TrackStats(Model):
    signals: int
    closed: int
    open: int
    pending: int
    not_filled: int
    win_rate: float | None = None
    avg_win_pct: float | None = None
    avg_loss_pct: float | None = None
    expectancy_pct: float | None = None           # average closed signal after costs
    profit_factor: float | None = None
    avg_days: float | None = None
    realised_pnl: float
    open_pnl: float
    level: Literal["good", "bad", "unknown"]
    verdict: str


class BacktestTradeStats(Model):
    trades: int | None = None
    win_rate: float | None = None
    expectancy_pct: float | None = None
    profit_factor: float | None = None
    avg_days: float | None = None


class TrackStrategy(Model):
    key: str
    name: str
    status: StrategyStatus | None = None          # today's status (None: no longer in the scan)
    live: TrackStats
    backtest: BacktestTradeStats | None = None    # the same strategy's backtest trades, for comparison


class TrackRecordResponse(Model):
    as_of: ISODate | None = None                  # last stored trading day
    min_closed: int
    overall: TrackStats
    strategies: list[TrackStrategy]
    signals: list[TrackSignal]                    # newest first, after the filters
    total: int                                    # before the filters
