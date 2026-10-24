"""7. holdings (holdings.csv is per CHECKOUT: ROOT/holdings.csv)."""
from __future__ import annotations

from typing import Literal

from .common import AsOf, ISODate, Model

HoldingLevel = Literal["ok", "good", "watch", "danger", "unknown"]


class HoldingInput(Model):
    symbol: str
    qty: float | None = None
    buy_price: float | None = None
    buy_date: ISODate | None = None
    stop_loss_pct: float | None = None
    target_pct: float | None = None


class HoldingRow(Model):
    symbol: str
    company: str | None = None
    industry: str | None = None
    qty: float | None = None
    buy_price: float | None = None
    price: float | None = None
    change_pct: float | None = None
    pnl_pct: float | None = None
    pnl_amount: float | None = None
    stop_price: float | None = None
    target_price: float | None = None
    momentum_rank: int | None = None
    rs: float | None = None
    results_on: ISODate | None = None
    level: HoldingLevel
    alerts: list[str]
    value: float | None = None
    day_pnl: float | None = None
    weight_pct: float | None = None
    in_models: list[str]


class HoldingsTotals(Model):
    count: int
    invested: float | None = None
    value: float | None = None
    pnl: float | None = None
    pnl_pct: float | None = None
    day_pnl: float | None = None
    danger: int
    watch: int


class IndustryWeight(Model):
    industry: str
    weight_pct: float


class HoldingDefaults(Model):
    stop_loss_pct: float
    target_pct: float


class HoldingsResponse(Model):
    as_of: AsOf | None = None
    rows: list[HoldingRow]
    inputs: list[HoldingInput]
    health_stale: bool
    totals: HoldingsTotals
    by_industry: list[IndustryWeight]
    defaults: HoldingDefaults


class HoldingsPutRequest(Model):
    rows: list[HoldingInput]


class RejectedRow(Model):
    index: int
    symbol: str
    reason: str


class HoldingsPutResponse(Model):
    saved: int
    rejected: list[RejectedRow]
    unknown_symbols: list[str]


class FyersImportResponse(Model):
    rows: list[HoldingInput]
    count: int
    note: str
