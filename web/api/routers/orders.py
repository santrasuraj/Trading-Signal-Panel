"""Orders on your own FYERS account (services/orders_svc.py): two steps (preview, then place with the preview id),
kill switch, cancel, stop-loss / target protection, and the Orders page. Every mutation needs the X-Quant-Desk header
(security.py), so another web page cannot place an order through this local server."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Path
from pydantic import Field

from ..errors import SafeJSONResponse
from ..models import Model
from ..services import orders_svc

router = APIRouter(prefix="/api/orders", tags=["orders"])


class Ticket(Model):
    symbol: str = Field(..., max_length=25)
    side: Literal["BUY", "SELL"]
    qty: int = Field(..., ge=1, le=1_000_000)
    type: Literal["LIMIT", "MARKET", "SL-M", "SL-L"] = "LIMIT"
    product: Literal["CNC", "INTRADAY"] = "CNC"
    limit_price: float | None = None
    trigger_price: float | None = None
    stop: float | None = None            # for the stop-loss / target protection after a buy fills, and the risk shown
    target: float | None = None
    ref_price: float | None = None       # the signal's reference price (slippage report)
    strategy_key: str | None = Field(None, max_length=40)
    source: str = Field("manual", max_length=20)


class PlaceBody(Model):
    preview_id: str = Field(..., pattern=r"^[0-9a-f]{16}$")
    confirm: bool


class Switch(Model):
    on: bool
    phrase: str = Field("", max_length=20)
    reason: str = Field("", max_length=120)


class ProtectBody(Model):
    symbol: str = Field(..., max_length=25)
    qty: int = Field(..., ge=1)
    stop: float
    target: float
    confirm: bool


@router.get("", response_model=None, response_class=SafeJSONResponse)
def orders_view():
    """Switches, limits, today's FYERS orders / positions / stop-loss-target orders, the audit log and slippage."""
    return orders_svc.view()


@router.post("/preview", response_model=None, response_class=SafeJSONResponse)
def preview(body: Ticket):
    """The exact order, every check and the charges. Sends nothing."""
    return orders_svc.preview(body.model_dump())


@router.post("/place", response_model=None, response_class=SafeJSONResponse)
def place(body: PlaceBody):
    """Sends a previewed order to FYERS (once; never retried)."""
    return orders_svc.place(body.preview_id, body.confirm)


@router.post("/cancel/{order_id}", response_model=None, response_class=SafeJSONResponse)
def cancel(order_id: str = Path(..., pattern=r"^[0-9A-Za-z-]{1,40}$")):
    return orders_svc.cancel(order_id)


@router.post("/kill", response_model=None, response_class=SafeJSONResponse)
def kill(body: Switch):
    """On: blocks every new order and cancels every pending order. Off: orders allowed again."""
    return orders_svc.set_kill(body.on, body.reason)


@router.post("/enable", response_model=None, response_class=SafeJSONResponse)
def enable(body: Switch):
    """Switch order placement on (type ENABLE) or off."""
    return orders_svc.set_enabled(body.on, body.phrase)


@router.post("/protect", response_model=None, response_class=SafeJSONResponse)
def protect(body: ProtectBody):
    """A FYERS GTT OCO sell on a delivery holding: the target above the price, the stop-loss below it."""
    return orders_svc.protect(body.symbol, body.qty, body.stop, body.target, body.confirm)
