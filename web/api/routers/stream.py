"""GET /api/stream/quotes?symbols=A,B: live prices as Server-Sent Events (one stream per open tab).

The first event is a full snapshot ("full": true). After that only symbols whose price changed are sent:
from the FYERS live feed (quotes.json, checked four times a second, about a second behind the exchange) and,
for symbols the feed doesn't stream yet, the REST / Yahoo quotes every 30 s (cached per symbol and shared by
every tab, so more tabs cost no more calls). The stream registers its symbols, so the live service starts
streaming them within a few seconds (services/live_subs.py). A comment line every 15 s keeps the connection
open; the browser's EventSource reconnects by itself if it drops.
"""
from __future__ import annotations

import asyncio
import json
import time

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse

from ..services import clock, live_subs, quotes_svc

router = APIRouter(prefix="/api/stream", tags=["stream"])

TICK_S = 0.25
REST_EVERY_S = {"open": 30.0, "post_close": 300.0}
HEARTBEAT_S = 15.0
CLOCK_EVERY_S = 1.0


def _key(q: dict) -> tuple:
    return (q.get("price"), q.get("source"), q.get("change_pct"), q.get("volume"))


def _event(payload: dict) -> str:
    return f"event: quotes\ndata: {json.dumps(payload, default=str, separators=(',', ':'))}\n\n"


async def quote_events(request: Request, syms: list[str]):
    sid = live_subs.open_stream(syms)
    sent: dict[str, tuple] = {}
    last_rest = last_beat = last_clock = 0.0
    session = None
    try:
        # first what is at hand without a network call (live feed, today's cached quotes): instant on screen, even
        # for 100 symbols; then the full snapshot, which may wait seconds on Yahoo / FYERS for the rest
        fast = await asyncio.to_thread(quotes_svc.quotes, syms, False)
        at_hand = [q for q in fast["quotes"] if q.get("source") != "close"]
        if at_hand:
            sent = {q["symbol"]: _key(q) for q in at_hand}
            yield _event({**fast, "quotes": at_hand, "full": False})
        snap = await asyncio.to_thread(quotes_svc.quotes, syms, True)
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
