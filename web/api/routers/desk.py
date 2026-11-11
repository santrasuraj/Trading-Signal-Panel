"""Market calendar, tax harvesting, options strategy builder, portfolio risk."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Query
from pydantic import Field

from ..errors import SafeJSONResponse
from ..models.common import Model
from ..services import calendar_svc, payoff_svc, risk_svc, tax_svc

router = APIRouter(prefix="/api", tags=["desk"])


@router.get("/calendar", response_model=None, response_class=SafeJSONResponse)
def calendar(days: int = Query(30, ge=1, le=calendar_svc.MAX_DAYS)):
    """Results, ex-dividend / rights / bonus / split / buyback dates, F&O expiries and market holidays, nearest first."""
    return calendar_svc.calendar(days)


@router.get("/tax", response_model=None, response_class=SafeJSONResponse)
def tax(st: float | None = Query(None, ge=-1e10, le=1e10), lt: float | None = Query(None, ge=-1e10, le=1e10)):
    """Your lots as short / long term, this financial year's tax, and gain / loss harvesting before 31 March.
    `st` / `lt`: net short / long-term gains already booked this year (losses negative); default: Quant Desk's
    recorded real orders."""
    return tax_svc.view(st, lt)


class PayoffLeg(Model):
    kind: Literal["CE", "PE", "FUT"]
    side: Literal["buy", "sell"]
    strike: float | None = Field(None, ge=0, le=1e7)
    lots: int = Field(1, ge=1, le=500)
    price: float | None = Field(None, ge=0, le=1e7)
    iv_pct: float | None = Field(None, gt=0, le=500)


class PayoffBody(Model):
    symbol: str = Field(..., max_length=25)
    expiry: str | None = Field(None, max_length=10)
    legs: list[PayoffLeg] = Field(..., min_length=1, max_length=payoff_svc.MAX_LEGS)
    days: float = Field(0, ge=0, le=400)
    iv_shift: float = Field(0, ge=-50, le=100)
    lot: int | None = Field(None, ge=1, le=100000)


@router.post("/options/payoff", response_model=None, response_class=SafeJSONResponse)
def options_payoff(body: PayoffBody):
    """Profit and loss of a multi-leg options position on a stored chain: at expiry and today, breakevens, maximum
    profit / loss, Greeks and the chance of profit."""
    return payoff_svc.build(body.symbol.upper(), body.expiry, [x.model_dump() for x in body.legs], days=body.days,
                            iv_shift=body.iv_shift, lot=body.lot)


@router.get("/risk", response_model=None, response_class=SafeJSONResponse)
def risk():
    """Money at risk to your stops, concentration, beta, one-day loss estimate, stress and correlation."""
    return risk_svc.view()
