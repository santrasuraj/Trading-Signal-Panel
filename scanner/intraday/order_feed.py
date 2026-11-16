"""Order updates pushed by FYERS' order WebSocket (wss://socket.fyers.in/trade/v3) while the live service runs: a fill,
rejection or cancellation reaches every open dashboard tab within about a second, instead of on the Orders page's
next poll.

The live service (live.py) starts it after the daily login and keeps it subscribed. Every order update is written
to data/intraday/live/orders_feed.json (the last 50 events, each with a sequence number); the quote stream
(web/api/routers/stream.py) forwards new ones to the browser as "order" events, and a filled order is appended to
data/fills.jsonl (scanner/fills.py), your trade history for the coach. Read-only: this socket never places, changes
or cancels an order.
"""
from __future__ import annotations

import json
import os
import threading
import time
from collections import deque
from pathlib import Path

from .. import fills

FILE_NAME = "orders_feed.json"
KEEP = 50
HEARTBEAT_S = 60.0               # the file is rewritten at least this often while the feed runs
FRESH_S = 150.0                  # older than this: the live service isn't running, so the feed isn't either
STATUS_TEXT = {1: "cancelled", 2: "filled", 4: "in transit", 5: "rejected", 6: "pending", 7: "expired"}


def _num(x) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v else None


def normalize(o: dict) -> dict | None:
    """One FYERS order update (the SDK's mapped field names) as a small event; None when it has no order id."""
    if not isinstance(o, dict) or not o.get("id"):
        return None
    try:
        status = int(o.get("status") or 0)
    except (TypeError, ValueError):
        status = 0
    try:
        side = "BUY" if int(o.get("side") or 0) == 1 else "SELL"
    except (TypeError, ValueError):
        side = "SELL"
    return {"id": str(o["id"]), "symbol": str(o.get("symbol") or "").removeprefix("NSE:").removesuffix("-EQ"),
            "side": side, "status": STATUS_TEXT.get(status, str(status)), "qty": _num(o.get("qty")),
            "filled": _num(o.get("filledQty")), "avg_price": _num(o.get("tradedPrice")),
            "limit_price": _num(o.get("limitPrice")), "product": o.get("productType"),
            "time": o.get("orderDateTime"), "message": (str(o.get("message"))[:200] if o.get("message") else None)}


def text(ev: dict) -> str:
    """'BUY 10 TCS filled at 3,512.00' and the like (the toast in the browser)."""
    qty = ev.get("filled") if ev.get("status") == "filled" else ev.get("qty")
    q = f"{qty:g}" if isinstance(qty, (int, float)) else ""
    head = f"{ev.get('side', '')} {q} {ev.get('symbol', '')}".replace("  ", " ").strip()
    if ev.get("status") == "filled" and ev.get("avg_price"):
        return f"{head} filled at {ev['avg_price']:,.2f}"
    tail = f": {ev['message']}" if ev.get("status") == "rejected" and ev.get("message") else ""
    return f"{head} {ev.get('status')}{tail}"


class OrderFeed:
    """Collects order updates from the socket thread; write() persists them for the API (called by live.py)."""

    def __init__(self, live_dir, data_dir: Path | None = None, clock=time.time):
        self.dir = Path(live_dir)
        self.data_dir = data_dir
        self.clock = clock
        self.lock = threading.Lock()
        self.events: deque[dict] = deque(maxlen=KEEP)
        self.seq = 0
        self.connected = False
        self.subscribed = False
        self.dirty = True
        self.written_at = 0.0
        self._seen: dict[str, tuple] = {}

    def on_order(self, msg) -> None:
        ev = normalize((msg or {}).get("orders") if isinstance(msg, dict) else None)
        if ev is None:
            return
        with self.lock:
            sig = (ev["status"], ev["filled"])
            if self._seen.get(ev["id"]) == sig:          # the socket repeats updates after a reconnect
                return
            self._seen[ev["id"]] = sig
            self.seq += 1
            ev.update(seq=self.seq, at=self.clock(), text=text(ev))
            self.events.append(ev)
            self.dirty = True
        if ev["status"] == "filled" and ev["avg_price"] and ev["filled"]:
            try:
                fills.record([{"id": ev["id"], "symbol": ev["symbol"], "side": ev["side"], "qty": ev["filled"],
                               "price": ev["avg_price"], "time": ev["time"], "product": ev["product"] or "CNC",
                               "source": "order_socket"}], self.data_dir)
            except Exception:
                pass                                     # the Orders page records it from the order book too

    def set_connected(self, ok: bool) -> None:
        with self.lock:
            if ok != self.connected:
                self.connected, self.dirty = ok, True

    def write(self, replace=os.replace) -> bool:
        """orders_feed.json when something changed, or as a heartbeat; True when written."""
        now = self.clock()
        with self.lock:
            if not self.dirty and now - self.written_at < HEARTBEAT_S:
                return False
            payload = {"seq": self.seq, "updated": now, "connected": self.connected, "events": list(self.events)}
            self.dirty = False
            self.written_at = now
        self.dir.mkdir(parents=True, exist_ok=True)
        tmp = self.dir / f"{FILE_NAME}.{os.getpid()}.tmp"
        tmp.write_text(json.dumps(payload, separators=(",", ":"), default=str), encoding="utf-8")
        replace(tmp, self.dir / FILE_NAME)
        return True


def read(live_dir) -> dict:
    try:
        return json.loads((Path(live_dir) / FILE_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"seq": 0, "updated": None, "connected": False, "events": []}


def status(live_dir, now: float | None = None) -> dict:
    """Is the order feed running now? (the live service rewrites the file at least every minute while it runs)"""
    d = read(live_dir)
    upd = d.get("updated")
    fresh = bool(upd) and (now or time.time()) - float(upd) < FRESH_S
    return {"connected": bool(fresh and d.get("connected")), "updated": upd, "seq": int(d.get("seq") or 0)}


def since(live_dir, seq: int, started: float) -> tuple[int, list[dict]]:
    """Events newer than `seq` that happened after `started` (a new tab doesn't replay old updates)."""
    d = read(live_dir)
    top = int(d.get("seq") or 0)
    if top < seq:                                        # the live service restarted: its numbers start again at 1
        seq = 0
    evs = [e for e in d.get("events") or [] if int(e.get("seq") or 0) > seq and float(e.get("at") or 0) >= started]
    return top, evs


def start_socket(tok: dict, feed: OrderFeed, log, log_dir) -> object | None:
    """Connect FYERS' order socket for this login (orders only; read-only). None if the SDK can't be used."""
    try:
        from fyers_apiv3.FyersWebsocket import order_ws
    except Exception as e:                               # an SDK without the order socket: the page keeps polling
        log(f"Order updates: the FYERS order socket is unavailable ({type(e).__name__}) - the Orders page polls instead")
        return None

    def on_error(msg):
        log(f"Order socket error: {msg}")

    def on_close(msg):
        feed.set_connected(False)
        with feed.lock:
            feed.subscribed = False

    sock = order_ws.FyersOrderSocket(access_token=f"{tok['client_id']}:{tok['access_token']}", write_to_file=False,
                                     log_path=str(log_dir), on_orders=feed.on_order, on_error=on_error,
                                     on_close=on_close, reconnect=True, reconnect_retry=10)
    sock.background_flag = True                         # daemon threads: never keep the process alive after the session
    sock.connect()
    return sock


def keep_subscribed(sock, feed: OrderFeed) -> None:
    """Subscribe once the socket is really open (the SDK's connect callback fires even when it is not), and again
    after a reconnect. Called every few seconds by live.py."""
    if sock is None:
        return
    try:
        ok = bool(sock.is_connected())
    except Exception:
        ok = False
    if ok and not feed.subscribed:
        sock.subscribe(data_type="OnOrders")
        feed.subscribed = True
    elif not ok:
        feed.subscribed = False
    feed.set_connected(ok)


def stop_socket(sock) -> None:
    if sock is None:
        return
    try:
        sock.restart_flag = False
        sock.close_connection()
    except Exception:
        pass                                             # close_connection() joins threads that may never have started
