"""7. holdings and 8. paper."""
from __future__ import annotations

from fastapi import APIRouter

from ..errors import ApiException, not_found
from ..models import (FyersImportResponse, HoldingsPutRequest, HoldingsPutResponse, HoldingsResponse, PaperDetail,
                      PaperListResponse)
from ..services import data, fyers_svc, holdings_svc, paper_svc
from ..util import num

router = APIRouter(prefix="/api", tags=["portfolio"])


@router.get("/holdings", response_model=HoldingsResponse)
def holdings():
    return holdings_svc.response(data.latest())


@router.put("/holdings", response_model=HoldingsPutResponse)
def put_holdings(body: HoldingsPutRequest):
    ok, rejected, unknown = holdings_svc.validate([r.model_dump() for r in body.rows])
    try:
        holdings_svc.save(ok)
    except PermissionError:         # Windows: Excel locks an open csv, so the rename onto it fails
        raise ApiException("INTERNAL", "holdings.csv is open in another program (Excel?), so it cannot be saved.",
                           "Close it there and save again.", status=409)
    return {"saved": len(ok), "rejected": rejected, "unknown_symbols": unknown}


@router.post("/holdings/import/fyers", response_model=FyersImportResponse)
def import_fyers():
    client = fyers_svc.get_client()
    from scanner.fyers_limits import FyersRateLimited
    from scanner.providers import FyersAuthError
    try:
        # Not client.holdings(): it returns [] for ANY failed reply (network error, FYERS outage), which would
        # read as "your demat account is empty".
        r = client._call(client.api.holdings, bucket="user")
    except FyersAuthError as e:
        raise ApiException("FYERS_AUTH", f"Fyers rejected today's token ({e}).", "Log in to Fyers again.")
    except FyersRateLimited as e:
        raise ApiException("FYERS_RATE_LIMIT", f"FYERS request budget used up: {e}", "Try again later.")
    if r.get("s") not in ("ok", "no_data"):
        raise ApiException("FYERS_AUTH", f"Fyers did not return your holdings ({r.get('message') or 'error'}).",
                           "Try again in a minute; log in to Fyers again if it keeps failing.")
    raw = r.get("holdings") or []
    rows = holdings_svc.from_fyers(raw)
    return {"rows": rows, "count": len(rows),
            "note": ("Preview only - nothing is saved until you choose Replace or Merge and save. Fyers cost prices are "
                     "already split/bonus adjusted; buy dates are unknown.") if rows else "Fyers returned no holdings."}


@router.get("/paper", response_model=PaperListResponse)
def paper_list():
    ji = data.journal_info()
    rep = paper_svc.report() if ji else None
    strategies = [paper_svc.summary(k, v) for k, v in ((rep or {}).get("strategies") or {}).items()]
    return {"available": bool(rep), "journal": ji if ji and ji.get("first") else None,
            "survivorship_haircut_pct": paper_svc.survivorship_haircut(), "min_days_to_judge": paper_svc.min_days(),
            "strategies": strategies}


@router.get("/paper/{key}", response_model=PaperDetail)
def paper_detail(key: str):
    rep = paper_svc.report()
    if not rep:
        raise ApiException("FEATURE_UNAVAILABLE", "No paper-trading journal yet.",
                           "It starts automatically with the next scan of a completed trading day.", {"feature": "paper"})
    r = (rep.get("strategies") or {}).get(key)
    if r is None:
        raise not_found(f"Paper portfolio '{key}'")
    stats = r.get("trade_stats") or {}
    return {"summary": paper_svc.summary(key, r), "capital": num(r.get("capital")) or 0.0, "cash": num(r.get("cash")) or 0.0,
            "equity": paper_svc.columnar_equity(r),
            "open": [{**p, "stop": num(p.get("stop"))} for p in r.get("open") or []],
            "trades": r.get("trades") or [], "pending": r.get("pending") or [],
            "trade_stats": {"trades": int(stats.get("trades") or 0),
                            **{k: num(stats.get(k)) for k in ("win_rate", "avg_win_pct", "avg_loss_pct",
                                                               "expectancy_pct", "profit_factor", "avg_days")}},
            "expect": r.get("expect") or {}, "journal_days": int(r.get("journal_days") or 0),
            "last_journal": str(r.get("last_journal") or "")}
