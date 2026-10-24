"""5. screener, symbols, sparklines and 6. chart and stock."""
from __future__ import annotations

from typing import Literal

from .common import AsOf, ISODate, Model, StrategyStatus
from .holdings import HoldingRow

SymbolKind = Literal["stock", "etf", "index"]
IndicatorId = Literal["sma20", "sma50", "sma200", "ema21", "bb_upper", "bb_mid", "bb_lower",
                      "rsi14", "macd", "macd_signal", "macd_hist", "vol_avg20"]


class ScreenerRow(Model):
    symbol: str
    company: str | None = None
    industry: str | None = None
    price: float | None = None
    change_pct: float | None = None
    ret_1w_pct: float | None = None
    ret_1m_pct: float | None = None
    ret_3m_pct: float | None = None
    ret_6m_pct: float | None = None
    ret_12m_pct: float | None = None
    rs: float | None = None
    momentum_score: float | None = None
    momentum_rank: int | None = None
    vol_ann_pct: float | None = None
    pct_from_52w_high: float | None = None
    above_sma50: bool | None = None
    above_sma200: bool | None = None
    sma50_above_sma200: bool | None = None
    rsi14: float | None = None
    vol_ratio: float | None = None
    turnover_cr: float | None = None
    atr_pct: float | None = None
    deliv_pct: float | None = None
    results_on: ISODate | None = None
    in_models: list[str]
    you_hold: bool


class ScreenerResponse(Model):
    as_of: AsOf
    source_date: ISODate
    preset: str
    total: int
    rows: list[ScreenerRow]
    industries: list[str] = []             # every industry of the liquid list (for the filter menu)


class SymbolInfo(Model):
    symbol: str
    company: str | None = None
    industry: str | None = None
    kind: SymbolKind
    in_universe: bool


class SymbolsResponse(Model):
    as_of: AsOf | None = None
    symbols: list[SymbolInfo]


class SparklinesResponse(Model):
    source_date: ISODate
    days: int
    series: dict[str, list[float | None]]       # closes rounded to 2 dp, oldest first


class Bars(Model):
    t: list[ISODate]
    o: list[float]
    h: list[float]
    l: list[float]  # noqa: E741
    c: list[float]
    v: list[float]


class ChartMarker(Model):
    t: ISODate
    position: Literal["aboveBar", "belowBar", "inBar"]
    shape: Literal["arrowUp", "arrowDown", "circle", "square"]
    kind: Literal["entry", "exit", "open_entry", "pending_order", "corporate_action", "results"]
    tone: Literal["profit", "loss", "neutral", "warn"]
    text: str
    detail: str | None = None
    strategy_key: str | None = None


class PriceLine(Model):
    price: float
    label: str
    strategy_key: str | None = None
    kind: Literal["model_entry", "model_stop", "order_stop", "your_buy", "your_stop", "your_target",
                  "high_52w", "low_52w"]


class StrategyTradesCount(Model):
    key: str
    name: str
    trades: int


class ChartResponse(Model):
    symbol: str
    company: str | None = None
    industry: str | None = None
    kind: SymbolKind
    tf: Literal["1d", "1w"]
    range: str
    adjusted: Literal[True] = True
    source_date: ISODate
    bars: Bars
    indicators: dict[IndicatorId, list[float | None]]
    markers: list[ChartMarker]
    price_lines: list[PriceLine]
    strategies_available: list[StrategyTradesCount]
    results_on: ISODate | None = None
    past_results: list[ISODate]


class StockStrategyRole(Model):
    key: str
    name: str
    status: StrategyStatus
    role: Literal["holding", "order", "ranked"]
    detail: str


class CorporateAction(Model):
    date: ISODate
    factor: float
    reason: str


class StockSnapshot(Model):
    as_of: AsOf | None = None
    symbol: str
    company: str | None = None
    industry: str | None = None
    kind: SymbolKind
    price: float | None = None
    change_pct: float | None = None
    data_date: ISODate | None = None
    high_52w: float | None = None
    low_52w: float | None = None
    pct_from_52w_high: float | None = None
    ret_1m_pct: float | None = None
    ret_3m_pct: float | None = None
    ret_6m_pct: float | None = None
    ret_12m_pct: float | None = None
    rs: float | None = None
    momentum_rank: int | None = None
    sma50: float | None = None
    sma200: float | None = None
    vol_ratio: float | None = None
    turnover_cr: float | None = None
    deliv_pct: float | None = None
    results_on: ISODate | None = None
    strategies: list[StockStrategyRole]
    your_holding: HoldingRow | None = None
    corporate_actions: list[CorporateAction]
