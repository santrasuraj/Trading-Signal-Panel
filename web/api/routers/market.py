"""9. market: movers, sectors, factor indices, results calendar, breadth history."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Query

from ..errors import SafeJSONResponse, feature_unavailable
from ..models import BreadthResponse, FactorsResponse, MoversResponse, ResultsResponse, SectorsResponse
from ..services import data, market_derived, results, strategies as st
from ..util import num
from .overview import movers

router = APIRouter(prefix="/api/market", tags=["market"])


def _index_row(r: dict) -> dict:
    return {"name": str(r.get("name")), **{k: num(r.get(k)) for k in ("last", "chg_1d", "ret_1m", "ret_3m", "ret_6m",
                                                                    "ret_1y", "cagr", "max_dd")},
            "since": r.get("since"), "above_50dma": r.get("above_50dma") if isinstance(r.get("above_50dma"), bool) else None,
            "rank": int(r["rank"]) if r.get("rank") is not None else None}


@router.get("/movers", response_model=MoversResponse)
def market_movers():
    lt = st.require_latest()
    return {"as_of": st.as_of(lt), **movers(lt)}


@router.get("/sectors", response_model=SectorsResponse)
def sectors():
    lt = st.require_latest()
    ind = market_derived.industries() or {"rows": [], "source_date": str(lt.get("data_date"))}
    return {"as_of": st.as_of(lt), "nse_sectors": [_index_row(r) for r in (lt.get("indices") or {}).get("sectors", [])],
            "industries": ind["rows"], "industries_source_date": ind["source_date"]}


@router.get("/factors", response_model=FactorsResponse)
def factors():
    lt = st.require_latest()
    return {"as_of": st.as_of(lt), "factors": [_index_row(r) for r in (lt.get("indices") or {}).get("factors", [])],
            "note": ("Investable alternatives (index funds / ETFs exist for most): real NSE indices, no survivorship "
                     "bias. Returns are price returns in percent; CAGR and max drawdown since the 'since' date.")}


@router.get("/results", response_model=ResultsResponse)
def results_calendar(days: int = Query(14, ge=0, le=60), relevant: bool = False):
    return results.events(data.latest(), days=days, relevant=relevant)


@router.get("/breadth", response_model=None, response_class=SafeJSONResponse,
            responses={200: {"model": BreadthResponse}})
def breadth(range: Literal["1y", "3y", "all"] = "1y"):  # noqa: A002
    b = market_derived.breadth(range)
    if b is None:
        raise feature_unavailable("store", "No stored prices yet.", "Run a scan.")
    return b
