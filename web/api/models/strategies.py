"""3. strategies and 4. orders (Order lives here because strategy detail and overview embed it)."""
from __future__ import annotations

from typing import Any, Literal

from .common import (AssetUniverse, AsOf, Evidence, Horizon, ISODate, Lifecycle, Model, Side, StrategyKind,
                     StrategyMetrics, StrategyStatus, TimeSeries, Tone, TradeStats, PerfStats)
from .paper import PaperSummary


class Edges(Model):
    primary: Literal["ew", "nifty"]             # 'nifty' when universe === 'etfs'
    vs_ew_cagr_pct: float | None = None
    vs_n500_cagr_pct: float | None = None
    vs_nifty_cagr_pct: float | None = None
    vs_factor_cagr_pct: float | None = None
    r12m_vs_n500_pct: float | None = None       # window return_pct differences (not CAGR)
    r6m_vs_n500_pct: float | None = None


class TimingRange(Model):
    base_cagr_pct: float | None = None
    low: float | None = None
    high: float | None = None
    consistent: bool                            # low <= base <= high
    method: Literal["rebalance_offsets", "start_offsets"]


class Headline(Model):
    cagr_pct: float | None = None
    after_tax_cagr_pct: float | None = None
    max_dd_pct: float | None = None
    sharpe: float | None = None
    vol_pct: float | None = None
    win_rate: float | None = None
    trades: int = 0
    exposure_pct: float | None = None
    avg_days: float | None = None
    ret_12m_pct: float | None = None
    ret_6m_pct: float | None = None
    ret_3m_pct: float | None = None
    n500_12m_pct: float | None = None


class PaperPulse(Model):
    return_pct: float | None = None
    days: int
    level: Tone


class StrategySummary(Model):
    key: str
    name: str
    description: str
    kind: StrategyKind
    horizon: Horizon
    evidence: Evidence
    universe: AssetUniverse
    lifecycle: Lifecycle
    status: StrategyStatus
    status_reason: str
    rejected_reason: str | None = None
    comparison_only: bool                       # status === 'not-working' || lifecycle !== 'active'
    headline: Headline
    edges: Edges
    timing: TimingRange | None = None
    factor_benchmark_name: str | None = None
    max_positions: int
    per_position: float
    positions: int
    orders_buy: int
    orders_sell: int
    rebalance: str | None = None
    next_rebalance: ISODate | None = None
    uses_regime_filter: bool
    blocked_by_regime: bool
    spark: list[float]                          # <= 120 evenly sampled points of curves.parquet[key]
    paper: PaperPulse | None = None


class RejectedEntry(Model):
    key: str
    name: str
    horizon: Horizon
    evidence: Evidence
    result_text: str
    source: Literal["catalogue"] = "catalogue"


class Period(Model):
    start: ISODate
    end: ISODate


class BenchmarkStrip(Model):
    nifty50: PerfStats | None = None
    nifty500: PerfStats | None = None
    average_stock: PerfStats | None = None
    survivorship_gap_pct: float | None = None


class StrategyListResponse(Model):
    as_of: AsOf
    period: Period
    benchmarks: BenchmarkStrip
    counts: dict[Horizon, int]
    strategies: list[StrategySummary]
    rejected: list[StrategySummary]
    rejected_catalogue: list[RejectedEntry]


class YearlyRow(Model):
    year: int
    partial: bool
    strategy: float | None = None
    nifty500: float | None = None
    average_stock: float | None = None
    nifty50: float | None = None


class MonthlyRow(Model):
    year: int
    months: list[float | None]                  # months[0] = Jan; 12 entries
    total: float | None = None


class StrategyRules(Model):
    kind: StrategyKind
    rebalance: str | None = None
    top_n: int | None = None
    keep_rank: int | None = None
    max_positions: int
    stop_pct: float | None = None
    stop_atr: float | None = None
    target_pct: float | None = None
    trail_pct: float | None = None
    max_hold: int | None = None
    sizing: Literal["equal", "risk"]
    risk_pct: float | None = None
    use_regime: bool
    regime_action: Literal["hold", "cash"] | None = None
    params: dict[str, Any]
    plain_rules: list[str]
    source: Literal["scan", "config"]


class EvidenceSource(Model):
    title: str
    url: str | None = None


class EvidenceCard(Model):
    grade: Evidence
    catalogue_id: str | None = None
    summary: str
    what_to_expect: str
    sources: list[EvidenceSource]
    failure_modes: list[str]
    validation: None = None                     # B8 (P2): typed when it exists, not before


class ModelPosition(Model):
    symbol: str
    company: str | None = None
    industry: str | None = None
    entry_date: ISODate
    entry_price: float
    last_price: float | None = None
    ret_pct: float | None = None
    stop: float | None = None
    days: int
    weight_pct: float | None = None             # the backtest compounds: its share count is never exposed
    results_on: ISODate | None = None
    results_in_days: int | None = None


class RankingRow(Model):
    rank: int
    symbol: str
    company: str | None = None
    industry: str | None = None
    score: float | None = None
    price: float | None = None
    ret_6m_pct: float | None = None
    ret_12m_pct: float | None = None
    rs: float | None = None
    in_portfolio: bool
    results_on: ISODate | None = None
    results_in_days: int | None = None


class TradeRow(Model):
    symbol: str
    entry_date: ISODate
    exit_date: ISODate
    entry_price: float | None = None
    exit_price: float | None = None
    ret_pct: float | None = None
    days: int
    reason: str


class Order(Model):
    strategy_key: str
    strategy_name: str
    strategy_status: StrategyStatus
    horizon: Horizon
    comparison_only: bool
    action: Side
    symbol: str
    company: str | None = None
    industry: str | None = None
    reason: str
    price: float | None = None
    qty: int | None = None
    qty_basis: Literal["sized", "your_holding", "model_weight"]
    amount: float | None = None
    stop: float | None = None
    stop_distance_pct: float | None = None
    risk_amount: float | None = None
    results_on: ISODate | None = None
    results_in_days: int | None = None
    results_warning: bool
    provisional: bool
    below_min_position: bool
    you_hold_qty: float | None = None


class StrategyDetail(Model):
    as_of: AsOf
    strategy: StrategySummary
    metrics: StrategyMetrics
    yearly: list[YearlyRow]
    monthly: list[MonthlyRow]
    rules: StrategyRules
    evidence: EvidenceCard
    positions: list[ModelPosition]
    orders: list[Order]
    ranking: list[RankingRow]
    recent_trades: list[TradeRow]
    trades_available: bool
    regime_note: str | None = None
    paper: PaperSummary | None = None


class CurveResponse(Model):
    as_of: AsOf
    key: str
    range: Literal["1y", "3y", "all"]
    curve: TimeSeries
    drawdown: TimeSeries
    capital: float


class HistBin(Model):
    bin_lo: float
    bin_hi: float
    count: int


class ReasonRow(Model):
    reason: str
    count: int
    avg_ret_pct: float | None = None


class TradesPage(Model):
    as_of: AsOf
    key: str
    source: Literal["artifact", "recent_only"]
    total: int
    page: int
    page_size: int
    rows: list[TradeRow]
    stats: TradeStats
    histogram: list[HistBin]
    reasons: list[ReasonRow]
