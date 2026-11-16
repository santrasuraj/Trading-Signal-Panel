"""Watchlists, price alerts (scanner/watch.py) and action cards for many symbols at once."""
from __future__ import annotations

from fastapi import APIRouter, Path, Query

from scanner import watch

from ..errors import ApiException
from ..models import ActionsResponse, AlertBody, AlertPatch, AlertsResponse, PriceAlert, WatchlistsBody, WatchlistsResponse
from ..services import action_svc, quotes_svc

router = APIRouter(prefix="/api", tags=["watch"])

ALERT_NOTE = ("Alerts fire once, on the live price: FYERS real-time ticks (checked twice a second by the live service, "
              "even with Quant Desk closed) or, without a FYERS login, Yahoo prices about 15 minutes late. Fired alerts "
              "show here and in the app, and go to Telegram when it is set up. Re-arm an alert to use it again.")
ALERT_ID = r"^[0-9a-f]{12}$"


@router.get("/watchlists", response_model=WatchlistsResponse)
def get_watchlists():
    return watch.watchlists()


@router.put("/watchlists", response_model=WatchlistsResponse)
def put_watchlists(body: WatchlistsBody):
    try:
        out = watch.save_watchlists([x.model_dump() for x in body.lists])
        sids = {lst["scan_id"] for lst in out["lists"] if lst.get("scan_id")}
        if sids:                                          # fill a new smart list now, not only after the next scan
            from scanner import scans
            from ..services import data
            saved = {s["id"]: s for s in scans.saved()}
            etfs = set(data.etfs())
            syms = [s for s in data.universe()["symbol"] if s not in etfs]
            hits = {sid: [r["symbol"] for r in scans.run_today(saved[sid], data.store(), syms, limit=200)["rows"]]
                    for sid in sids if sid in saved}
            if watch.refresh_smart(hits):
                out = watch.watchlists()
        return out
    except ValueError as e:
        raise ApiException("VALIDATION", str(e))


@router.get("/alerts", response_model=AlertsResponse)
def get_alerts():
    return {"alerts": watch.alerts(), "fired": watch.recent_fired(20), "note": ALERT_NOTE}


@router.post("/alerts", response_model=PriceAlert)
def post_alert(body: AlertBody):
    try:
        seen = None
        if body.kind == "scan_hit":           # what the scan matches now: only stocks added later fire it
            from scanner import scans
            from ..services import data
            sc = next((s for s in scans.saved() if s["id"] == body.ref), None)
            if sc is None:
                raise ValueError("That saved scan no longer exists.")
            etfs = set(data.etfs())
            syms = [s for s in data.universe()["symbol"] if s not in etfs]
            seen = [r["symbol"] for r in scans.run_today(sc, data.store(), syms, limit=10_000)["rows"]]
        return watch.add_alert(body.symbol, body.kind, body.value, body.note,
                               a=body.a.model_dump() if body.a else None, b=body.b.model_dump() if body.b else None,
                               ref=body.ref, seen=seen)
    except ValueError as e:
        raise ApiException("VALIDATION", str(e))


@router.patch("/alerts/{alert_id}", response_model=PriceAlert)
def patch_alert(body: AlertPatch, alert_id: str = Path(..., pattern=ALERT_ID)):
    a = watch.update_alert(alert_id, active=body.active)
    if a is None:
        raise ApiException("NOT_FOUND", "No such alert.")
    return a


@router.delete("/alerts/{alert_id}", response_model=None)
def delete_alert(alert_id: str = Path(..., pattern=ALERT_ID)):
    watch.update_alert(alert_id, delete=True)          # deleting an unknown id is not an error (already gone)
    return {"deleted": True}


@router.get("/actions", response_model=ActionsResponse)
def actions(symbols: str = Query(..., max_length=2500, description="up to 100 NSE symbols, comma separated")):
    """The one tested answer (BUY / SELL / HOLD / NO EDGE) for each symbol, from one read of the scan."""
    syms = quotes_svc.parse(symbols)
    ctx = action_svc.Context()
    return {"cards": [action_svc.card(ctx, s) for s in syms]}


@router.get("/drawings/{symbol}", response_model=None)
def get_drawings(symbol: str = Path(..., pattern=r"^[A-Za-z0-9][A-Za-z0-9&_.-]{0,24}$")):
    """Your drawings on this symbol's chart: levels, trendlines, Fibonacci retracements."""
    return {"symbol": symbol.upper(), "drawings": watch.drawings(symbol)}


@router.put("/drawings/{symbol}", response_model=None)
def put_drawings(body: dict, symbol: str = Path(..., pattern=r"^[A-Za-z0-9][A-Za-z0-9&_.-]{0,24}$")):
    items = body.get("drawings") if isinstance(body, dict) else None
    if not isinstance(items, list):
        raise ApiException("VALIDATION", "Send {drawings: [...]}.")
    try:
        return {"symbol": symbol.upper(), "drawings": watch.save_drawings(symbol, items)}
    except (TypeError, ValueError) as e:
        raise ApiException("VALIDATION", str(e) or "Bad drawing.")
