"""Watchlists, price alerts and many action cards at once (scanner/watch.py, services/action_svc.py)."""
from __future__ import annotations

from typing import Literal

from pydantic import Field

from .action import ActionCard
from .common import Model

AlertKind = Literal["above", "below", "change_above", "change_below", "line_above", "line_below", "rsi_above",
                    "rsi_below", "sma_above", "sma_below", "scan_hit", "pattern"]


class LinePoint(Model):
    t: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    v: float = Field(..., gt=0)


class Watchlist(Model):
    name: str = Field(..., max_length=40)
    symbols: list[str] = Field(..., max_length=200)
    scan_id: str | None = Field(None, max_length=40)     # a smart list: filled by this saved scan after each scan


class WatchlistsBody(Model):
    lists: list[Watchlist] = Field(..., max_length=20)


class WatchlistsResponse(Model):
    lists: list[Watchlist]


class PriceAlert(Model):
    id: str
    symbol: str
    kind: AlertKind
    value: float
    note: str
    created: str
    active: bool
    fired_at: str | None = None
    fired_price: float | None = None
    source: str | None = None                     # the quote that fired it: live / fyers / yahoo (~15 min late)
    a: LinePoint | None = None                    # a trendline alert's two points
    b: LinePoint | None = None
    ref: str | None = None                        # a scan alert's saved scan id
    detail: str | None = None                     # what a rule alert saw when it fired (RSI 71.2, new: ABC, ...)


class FiredAlert(PriceAlert):
    text: str


class AlertsResponse(Model):
    alerts: list[PriceAlert]
    fired: list[FiredAlert]                       # most recent first
    note: str


class AlertBody(Model):
    symbol: str = Field(..., max_length=25)
    kind: AlertKind
    value: float = 0.0
    note: str = Field("", max_length=120)
    a: LinePoint | None = None
    b: LinePoint | None = None
    ref: str | None = Field(None, max_length=40)


class AlertPatch(Model):
    active: bool


class ActionsResponse(Model):
    cards: list[ActionCard]


__all__ = ["AlertKind", "LinePoint", "Watchlist", "WatchlistsBody", "WatchlistsResponse", "PriceAlert", "FiredAlert",
           "AlertsResponse", "AlertBody", "AlertPatch", "ActionsResponse"]
