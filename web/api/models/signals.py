"""4. signals and sizing."""
from __future__ import annotations

from typing import Literal

from .common import AsOf, Model
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
