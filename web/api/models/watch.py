"""Watchlists, price alerts and many action cards at once (scanner/watch.py, services/action_svc.py)."""
from __future__ import annotations

from typing import Literal

from pydantic import Field

from .action import ActionCard
from .common import Model

AlertKind = Literal["above", "below", "change_above", "change_below"]


class Watchlist(Model):
    name: str = Field(..., max_length=40)
    symbols: list[str] = Field(..., max_length=200)


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


class FiredAlert(PriceAlert):
    text: str


class AlertsResponse(Model):
    alerts: list[PriceAlert]
    fired: list[FiredAlert]                       # most recent first
    note: str


class AlertBody(Model):
    symbol: str = Field(..., max_length=25)
    kind: AlertKind
    value: float
    note: str = Field("", max_length=120)


class AlertPatch(Model):
    active: bool


class ActionsResponse(Model):
    cards: list[ActionCard]


__all__ = ["AlertKind", "Watchlist", "WatchlistsBody", "WatchlistsResponse", "PriceAlert", "FiredAlert",
           "AlertsResponse", "AlertBody", "AlertPatch", "ActionsResponse"]
