"""8. paper (thin wrapper over scanner.paper.paper_report())."""
from __future__ import annotations

from typing import Any

from .common import ISODate, Model, Side, StrategyKind, TimeSeries, Tone, TradeStats


class PaperSummary(Model):
    key: str                                    # injected from the dict key (summary has no key)
    name: str
    kind: StrategyKind | None = None
    start: ISODate
    days: int
    last_date: ISODate
    equity: float
    return_pct: float | None = None
    pnl: float
    nifty_pct: float | None = None
    n500_pct: float | None = None
    excess_pct: float | None = None
    expected_pct: float | None = None
    expected_range_pct: tuple[float | None, float | None] | None = None
    haircut_pct: float | None = None
    expected_excess_pct: float | None = None
    haircut_excess_pct: float | None = None
    noise_pct: float | None = None
    backtest_cagr_pct: float | None = None
    backtest_n500_cagr_pct: float | None = None
    max_dd_pct: float | None = None
    trades: int
    win_rate: float | None = None
    open: int
    pending: int
    fees: float
    slippage: float
    verdict: str
    comparison: str | None = None
    level: Tone


class JournalInfo(Model):
    days: int
    first: ISODate
    last: ISODate


class PaperListResponse(Model):
    available: bool
    journal: JournalInfo | None = None
    survivorship_haircut_pct: float
    min_days_to_judge: int
    strategies: list[PaperSummary]


class PaperPosition(Model):
    symbol: str
    entry_date: ISODate
    entry_price: float
    qty: int
    last_price: float
    value: float
    pnl: float
    ret_pct: float
    stop: float | None = None
    days: int
    via: str


class PaperTrade(Model):
    symbol: str
    entry_date: ISODate
    entry_price: float
    exit_date: ISODate
    exit_price: float
    qty: int
    pnl: float
    ret_pct: float
    days: int
    reason: str
    via: str


class PendingOrder(Model):
    action: Side
    symbol: str
    reason: str


class PaperDetail(Model):
    summary: PaperSummary
    capital: float
    cash: float
    equity: TimeSeries                         # ids 'paper', 'nifty50', 'nifty500' in rupees
    open: list[PaperPosition]
    trades: list[PaperTrade]
    pending: list[PendingOrder]
    trade_stats: TradeStats
    expect: dict[str, Any]
    journal_days: int
    last_journal: ISODate
