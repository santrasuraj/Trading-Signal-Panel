"""2. overview."""
from __future__ import annotations

from typing import Literal

from .common import AsOf, Horizon, ISODate, Model, Tone
from .market import Mover, ResultsEvent
from .paper import PaperSummary
from .strategies import Order, StrategySummary

AlertSeverity = Literal["danger", "warn", "info", "good"]


class MarketSnapshot(Model):
    label: Literal["Bullish", "Mixed", "Bearish"]
    level: Tone
    advice: str
    regime_up: bool
    nifty: float | None = None
    nifty_change_pct: float | None = None
    nifty_sma200: float | None = None
    nifty_vs_sma200_pct: float | None = None
    nifty500: float | None = None
    nifty500_change_pct: float | None = None
    vix: float | None = None
    vix_change_pct: float | None = None
    high_vix: bool
    breadth_50: float | None = None
    advances: int
    declines: int


class IndexTile(Model):
    name: str
    last: float | None = None
    chg_1d_pct: float | None = None
    spark: list[float | None]                   # last 63 closes from data/nse/index_history.parquet
    href: str


class Alert(Model):
    id: str                                     # `${category}:${symbol ?? ''}:${rule}` (stable across scans)
    severity: AlertSeverity
    category: Literal["holding", "order", "results", "data", "login", "scan", "market", "paper", "bias"]
    title: str
    detail: str | None = None
    symbol: str | None = None
    strategy_key: str | None = None
    href: str | None = None


class Change(Model):
    kind: Literal["status", "regime", "new_order", "position_opened", "position_closed"]
    text: str
    strategy_key: str | None = None
    symbol: str | None = None


class Changes(Model):
    since_scan_id: str | None = None
    since_data_date: ISODate | None = None
    items: list[Change]


class MoversBlock(Model):
    gainers: list[Mover]
    losers: list[Mover]
    volume_spikes: list[Mover]


class OverviewResponse(Model):
    as_of: AsOf
    market: MarketSnapshot
    index_tiles: list[IndexTile]
    orders: list[Order]
    empty_reasons: dict[Horizon, str | None]
    alerts: list[Alert]
    changes: Changes
    strategy_pulse: list[StrategySummary]
    movers: MoversBlock
    results_soon: list[ResultsEvent]
    paper: list[PaperSummary]
