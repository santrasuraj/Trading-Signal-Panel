"""Research checks on the app itself: walk-forward of the "working" rule, published benchmarks."""
from __future__ import annotations

from fastapi import APIRouter

from ..errors import SafeJSONResponse
from ..services import benchmarks, walkforward

router = APIRouter(prefix="/api/research", tags=["research"])


@router.get("/walk-forward", response_model=None, response_class=SafeJSONResponse)
def walk_forward():
    """Does following the strategies the app calls working pay? (the rule replayed month by month, out of sample)"""
    return walkforward.report()


@router.get("/benchmarks", response_model=None, response_class=SafeJSONResponse)
def bench():
    """This app's speed and depth, measured now on this PC, next to what the competitors publish."""
    return benchmarks.measure()
