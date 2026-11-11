"""Your own scans (scanner/scans.py): the field catalog, saved scans, run on today's market, 8-year backtest."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Path
from pydantic import Field

from scanner import scans

from ..errors import ApiException, SafeJSONResponse
from ..models import Model
from ..services import data

router = APIRouter(prefix="/api/scans", tags=["scans"])
SCAN_ID = r"^[0-9a-f]{12}$"


class RuleRight(Model):
    value: float | None = None
    field: str | None = Field(None, max_length=40)
    mult: float | None = None


class Rule(Model):
    left: str = Field(..., max_length=40)
    op: Literal[">", ">=", "<", "<=", "crosses_above", "crosses_below"]
    right: RuleRight


class ScanBody(Model):
    name: str = Field("My scan", max_length=60)
    match: Literal["all", "any"] = "all"
    direction: Literal["long", "short"] = "long"
    rules: list[Rule] = Field(..., min_length=1, max_length=scans.MAX_RULES)


def _scan(body: ScanBody) -> dict:
    d = body.model_dump()
    for r in d["rules"]:
        r["right"] = {k: v for k, v in r["right"].items() if v is not None}
    try:
        return scans.validate(d)
    except ValueError as e:
        raise ApiException("VALIDATION", str(e))


@router.get("/catalog", response_model=None, response_class=SafeJSONResponse)
def catalog():
    """Every field a rule can use, the comparisons, and example scans."""
    return scans.catalog()


@router.get("", response_model=None, response_class=SafeJSONResponse)
def saved():
    return {"scans": scans.saved()}


@router.post("", response_model=None, response_class=SafeJSONResponse)
def save(body: ScanBody):
    try:
        return scans.save(_scan(body))
    except ValueError as e:
        raise ApiException("VALIDATION", str(e))


@router.put("/{scan_id}", response_model=None, response_class=SafeJSONResponse)
def update(body: ScanBody, scan_id: str = Path(..., pattern=SCAN_ID)):
    try:
        return scans.save(_scan(body), scan_id)
    except KeyError:
        raise ApiException("NOT_FOUND", "No such saved scan.")


@router.delete("/{scan_id}", response_model=None, response_class=SafeJSONResponse)
def delete(scan_id: str = Path(..., pattern=SCAN_ID)):
    scans.delete(scan_id)
    return {"deleted": True}


@router.post("/run", response_model=None, response_class=SafeJSONResponse)
def run(body: ScanBody):
    """The stocks of the scan's universe matching the scan on the last stored day (no network)."""
    scan = _scan(body)
    etfs = set(data.etfs())
    syms = [s for s in data.universe()["symbol"] if s not in etfs]
    if not syms:
        raise ApiException("FEATURE_UNAVAILABLE", "No universe list yet.", "Run a scan first.", {"feature": "scans"})
    return scans.run_today(scan, data.store(), syms, data.symbol_meta())


@router.post("/backtest", response_model=None, response_class=SafeJSONResponse)
def backtest(body: ScanBody):
    """The scan's event study on 8 years of the survivorship-free top 500 (a few seconds; the first one loads the data)."""
    scan = _scan(body)
    try:
        return scans.backtest(scan)
    except RuntimeError as e:
        raise ApiException("FEATURE_UNAVAILABLE", str(e), "Double-click 4_build_universe.bat once (about 30 minutes).",
                           {"feature": "pit"})
