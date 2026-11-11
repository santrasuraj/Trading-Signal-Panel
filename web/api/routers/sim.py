"""Practice account on live prices (services/sim_svc.py) and market depth for the order ladder (depth_svc.py)."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Path
from pydantic import Field

from ..errors import SafeJSONResponse
from ..models import Model
from ..services import depth_svc, sim_svc

router = APIRouter(prefix="/api", tags=["sim"])


class SimOrder(Model):
    symbol: str = Field(..., max_length=25)
    side: Literal["BUY", "SELL"]
    qty: int = Field(..., ge=1, le=1_000_000)
    type: Literal["MARKET", "LIMIT"] = "LIMIT"
    product: Literal["CNC", "INTRADAY"] = "CNC"
    limit_price: float | None = None
    stop: float | None = None
    target: float | None = None


class Levels(Model):
    stop: float | None = None
    target: float | None = None


class Reset(Model):
    cash: float | None = Field(None, gt=0, le=1e9)


@router.get("/sim", response_model=None, response_class=SafeJSONResponse)
def account():
    """The practice account: cash, positions marked to the live price, orders, closed trades."""
    return sim_svc.view()


@router.post("/sim/order", response_model=None, response_class=SafeJSONResponse)
def order(body: SimOrder):
    """A practice order (never sent to FYERS)."""
    return sim_svc.place(body.model_dump())


@router.post("/sim/cancel/{order_id}", response_model=None, response_class=SafeJSONResponse)
def cancel(order_id: str = Path(..., pattern=r"^[0-9a-f]{10}$")):
    return sim_svc.cancel(order_id)


@router.post("/sim/close/{symbol}", response_model=None, response_class=SafeJSONResponse)
def close(symbol: str = Path(..., max_length=25)):
    return sim_svc.close(symbol)


@router.post("/sim/levels/{symbol}", response_model=None, response_class=SafeJSONResponse)
def levels(body: Levels, symbol: str = Path(..., max_length=25)):
    return sim_svc.set_levels(symbol, body.stop, body.target)


@router.post("/sim/reset", response_model=None, response_class=SafeJSONResponse)
def reset(body: Reset):
    return sim_svc.reset(body.cash)


@router.get("/depth/{symbol}", response_model=None, response_class=SafeJSONResponse)
def depth(symbol: str = Path(..., max_length=25)):
    """Five best bids and offers from FYERS (needs today's login)."""
    return depth_svc.depth(symbol)
