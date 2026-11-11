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
        return watch.save_watchlists([x.model_dump() for x in body.lists])
    except ValueError as e:
        raise ApiException("VALIDATION", str(e))


@router.get("/alerts", response_model=AlertsResponse)
def get_alerts():
    return {"alerts": watch.alerts(), "fired": watch.recent_fired(20), "note": ALERT_NOTE}


@router.post("/alerts", response_model=PriceAlert)
def post_alert(body: AlertBody):
    try:
        return watch.add_alert(body.symbol, body.kind, body.value, body.note)
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
