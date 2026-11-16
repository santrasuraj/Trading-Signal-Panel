"""Strategy builder (services/builder_svc.py): plain English or the form -> a spec -> the same tests as the built-in
strategies, a walk-forward optimisation, and your saved strategies."""
from __future__ import annotations

from fastapi import APIRouter, Body, Path
from pydantic import Field

from ..errors import SafeJSONResponse
from ..models import Model
from ..services import builder_svc

router = APIRouter(prefix="/api/builder", tags=["builder"])


class TextBody(Model):
    text: str = Field(..., max_length=1500)


class SaveBody(Model):
    spec: dict
    id: str | None = Field(None, max_length=20)
    result: dict | None = None
    in_scan: bool = False                 # re-test it in every scan (signals on Today while it is working)


@router.post("/from-text", response_model=None, response_class=SafeJSONResponse)
def from_text(body: TextBody):
    """Claude turns a strategy written in plain English into a spec (it never says whether it works)."""
    return builder_svc.from_text(body.text)


@router.post("/test", response_model=None, response_class=SafeJSONResponse)
def test(spec: dict = Body(...)):
    """The spec through the same tests as a built-in strategy (8 years, survivorship-free, costs and tax)."""
    return builder_svc.test(spec)


@router.post("/optimise", response_model=None, response_class=SafeJSONResponse)
def optimise(spec: dict = Body(...)):
    """Start a walk-forward optimisation of the exits (background; poll GET /api/builder/optimise/{id})."""
    return builder_svc.optimise_start(spec)


@router.get("/optimise/{job_id}", response_model=None, response_class=SafeJSONResponse)
def optimise_status(job_id: str = Path(..., pattern=r"^[0-9a-f]{16}$")):
    return builder_svc.optimise_status(job_id)


@router.get("/saved", response_model=None, response_class=SafeJSONResponse)
def saved():
    return {"strategies": builder_svc.saved()}


@router.post("/saved", response_model=None, response_class=SafeJSONResponse)
def save(body: SaveBody):
    return builder_svc.save(body.spec, body.id, body.result, body.in_scan)


@router.delete("/saved/{sid}", response_model=None, response_class=SafeJSONResponse)
def delete(sid: str = Path(..., pattern=r"^[0-9a-f]{10}$")):
    builder_svc.delete(sid)
    return {"deleted": True}
