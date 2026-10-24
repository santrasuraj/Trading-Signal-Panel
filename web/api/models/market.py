"""9. market (movers, sectors, factor indices, results calendar, breadth)."""
from __future__ import annotations

from typing import Literal

from .common import AsOf, ISODate, Model


class Mover(Model):
    symbol: str
    company: str | None = None
    industry: str | None = None
    price: float | None = None
    change_pct: float | None = None
    vol_ratio: float | None = None


class MoversResponse(Model):
    as_of: AsOf
    gainers: list[Mover]
    losers: list[Mover]
    volume_spikes: list[Mover]


class IndexRow(Model):
    """latest.indices.* (returns are 1-dp, percent units)."""
    name: str
    last: float | None = None
    chg_1d: float | None = None
    ret_1m: float | None = None
    ret_3m: float | None = None
    ret_6m: float | None = None
    ret_1y: float | None = None
    cagr: float | None = None
    max_dd: float | None = None
    since: ISODate | None = None
    above_50dma: bool | None = None
    rank: int | None = None


class Leader(Model):
    symbol: str
    ret_3m_pct: float | None = None


class IndustryRow(Model):
    industry: str
    members: int
    advances: int
    declines: int
    breadth_50: float | None = None
    ret_1d_pct: float | None = None
    ret_1w_pct: float | None = None
    ret_1m_pct: float | None = None
    ret_3m_pct: float | None = None
    ret_6m_pct: float | None = None
    leaders: list[Leader]


class SectorsResponse(Model):
    as_of: AsOf
    nse_sectors: list[IndexRow]
    industries: list[IndustryRow]
    industries_source_date: ISODate


class FactorsResponse(Model):
    as_of: AsOf
    factors: list[IndexRow]
    note: str


class ResultsEvent(Model):
    symbol: str
    company: str | None = None
    industry: str | None = None
    date: ISODate
    days_until: int
    purpose: str
    you_hold: bool
    in_models: list[str]
    in_orders: list[str]
    momentum_rank: int | None = None
    relevance: Literal["held", "order", "model", "ranked"] | None = None   # why it is relevant (most first)
    strategy_rank: int | None = None       # best rank in a strategy's top 20, with that strategy's name
    ranked_by: str | None = None


class ResultsResponse(Model):
    cached_on: ISODate | None = None
    note: str
    events: list[ResultsEvent]


class BreadthResponse(Model):
    source_date: ISODate                         # last store bar (completed days only)
    t: list[ISODate]
    breadth_50: list[float | None]
    nifty: list[float | None]
    nifty_sma200: list[float | None]
    nifty500: list[float | None]
    vix: list[float | None]
    ad_line: list[float | None]
