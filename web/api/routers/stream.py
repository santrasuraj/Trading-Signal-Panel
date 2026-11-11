"""GET /api/stream/quotes?symbols=A,B: live prices as Server-Sent Events (one stream per open tab).

The first event is a full snapshot ("full": true). After that only symbols whose price changed are sent:
from the FYERS live feed (quotes.json, checked four times a second, about a second behind the exchange) and,
for symbols the feed doesn't stream yet, the REST / Yahoo quotes every 30 s (cached per symbol and shared by
every tab, so more tabs cost no more calls). The stream registers its symbols, so the live service starts
streaming them within a few seconds (services/live_subs.py). A comment line every 15 s keeps the connection
open; the browser's EventSource reconnects by itself if it drops. Your FYERS order updates (fills, rejections) from the
live service's order socket (scanner/intraday/order_feed.py) ride the same stream as "order" events.
"""
from __future__ import annotations

import asyncio
import json
import time

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse

from scanner import rule_alerts, watch
from scanner.intraday import order_feed

from .. import errors
from ..paths import P
from ..services import clock, data, live_subs, quotes_svc, sim_svc

router = APIRouter(prefix="/api/stream", tags=["stream"])

TICK_S = 0.25
REST_EVERY_S = {"open": 30.0, "post_close": 300.0}
HEARTBEAT_S = 15.0
CLOCK_EVERY_S = 1.0
ORDERS_EVERY_S = 0.5


def _key(q: dict) -> tuple:
    return (q.get("price"), q.get("source"), q.get("change_pct"), q.get("volume"))


def _event(payload: dict, kind: str = "quotes") -> str:
    return f"event: {kind}\ndata: {json.dumps(payload, default=str, separators=(',', ':'))}\n\n"


def _feed_mtime() -> float | None:
    try:
        return (P.intraday_live / order_feed.FILE_NAME).stat().st_mtime
    except OSError:
        return None


def _check_alerts(quotes: list[dict], rules: bool = False) -> None:
    """Price alerts on the quotes this stream just got (REST / Yahoo ones too: the live service only sees the FYERS
    feed), and with `rules` the RSI / moving-average alerts on the daily history (rule_alerts.py). One-shot under a
    file lock, so the live service and several tabs never fire one twice."""
    try:
        by = {q["symbol"]: q for q in quotes}
        fired = watch.evaluate(by)
        if rules and any(a.get("active") and a.get("kind") in rule_alerts.LIVE_KINDS for a in watch.alerts()):
            fired += rule_alerts.check_live(data.store()["close"], by)
        watch.notify(fired)
    except Exception:
        errors.log.exception("Checking price alerts failed")
    try:                                   # the practice account: resting limit orders, stops and targets
        sim_svc.on_quotes({q["symbol"]: q for q in quotes})
    except Exception:
        errors.log.exception("Practice account check failed")


async def quote_events(request: Request, syms: list[str]):
    sid = live_subs.open_stream(syms)
    sent: dict[str, tuple] = {}
    last_rest = last_beat = last_clock = last_alert = last_orders = 0.0
    session = None
    alerts_after = started = time.time()
    order_seq, order_mtime = 0, _feed_mtime()
    try:
        # first what is at hand without a network call (live feed, today's cached quotes): instant on screen, even
        # for 100 symbols; then the full snapshot, which may wait seconds on Yahoo / FYERS for the rest
        fast = await asyncio.to_thread(quotes_svc.quotes, syms, False)
        at_hand = [q for q in fast["quotes"] if q.get("source") != "close"]
        if at_hand:
            sent = {q["symbol"]: _key(q) for q in at_hand}
            yield _event({**fast, "quotes": at_hand, "full": False})
        snap = await asyncio.to_thread(quotes_svc.quotes, syms, True)
        await asyncio.to_thread(_check_alerts, snap["quotes"])
        last_rest = last_beat = time.monotonic()
        sent.update({q["symbol"]: _key(q) for q in snap["quotes"]})
        yield _event({**snap, "full": True})
        while True:
            await asyncio.sleep(TICK_S)
            if await request.is_disconnected():
                break
            now = time.monotonic()
            if now - last_clock >= CLOCK_EVERY_S:
                session, last_clock = clock.market_clock()["session"], now
            if now - last_alert >= CLOCK_EVERY_S:            # alerts fired by anyone (live service, other tabs)
                last_alert = now
                alerts_after, fired = await asyncio.to_thread(watch.fired_since, alerts_after)
                for a in fired:
                    last_beat = now
                    yield _event({"alert": a, "text": a.get("text") or watch.message(a)}, "alert")
            if now - last_orders >= ORDERS_EVERY_S:           # your order updates, pushed by FYERS' order socket
                last_orders = now
                m = _feed_mtime()
                if m != order_mtime:
                    order_mtime = m
                    order_seq, evs = await asyncio.to_thread(order_feed.since, P.intraday_live, order_seq, started)
                    for e in evs:
                        last_beat = now
                        yield _event({"order": e, "text": e.get("text") or order_feed.text(e)}, "order")
            every = REST_EVERY_S.get(session)
            if every is None:                         # market shut: prices don't change, only keep the line open
                if now - last_beat >= HEARTBEAT_S:
                    last_beat = now
                    yield ": ping\n\n"
                continue
            rest_due = now - last_rest >= every
            snap = await asyncio.to_thread(quotes_svc.quotes, syms, rest_due)
            if rest_due:
                last_rest = now
            changed = [q for q in snap["quotes"] if sent.get(q["symbol"]) != _key(q)]
            if changed or rest_due:
                # every changed quote, and everything once per refresh: a new alert already met fires without a move
                await asyncio.to_thread(_check_alerts, snap["quotes"] if rest_due else changed, rest_due)
            if changed:
                for q in changed:
                    sent[q["symbol"]] = _key(q)
                last_beat = now
                yield _event({**snap, "quotes": changed, "full": False})
            elif now - last_beat >= HEARTBEAT_S:
                last_beat = now
                yield ": ping\n\n"
    finally:
        live_subs.close_stream(sid)


@router.get("/quotes", include_in_schema=False)
async def stream_quotes(request: Request,
                        symbols: str = Query(..., max_length=2500, description="up to 100 NSE symbols, comma separated")):
    syms = quotes_svc.parse(symbols)
    return StreamingResponse(quote_events(request, syms), media_type="text/event-stream",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})
