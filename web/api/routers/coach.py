"""Trade coach (services/coach_svc.py): your own record's numbers, and Claude's review of them on request."""
from __future__ import annotations

from fastapi import APIRouter

from ..errors import SafeJSONResponse
from ..services import coach_svc

router = APIRouter(prefix="/api/coach", tags=["coach"])


@router.get("", response_model=None, response_class=SafeJSONResponse)
def coach():
    """Your numbers (practice, real fills, holdings now) and the last written review."""
    return coach_svc.view()


@router.post("/review", response_model=None, response_class=SafeJSONResponse)
def review():
    """Ask Claude to review your numbers (one call; costs a few rupees)."""
    return coach_svc.review()
