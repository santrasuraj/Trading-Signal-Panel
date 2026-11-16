"""ZeroMQ tick bus: the live feed's ticks and new bars reach the dashboard server the moment they arrive.

The live feed (live.py) runs in its own process. Before the bus, the dashboard learnt about prices through quotes.json
(rewritten every 0.5 s) and about new bars through the bars file (flushed every 5 s), both polled - so a stop was
checked up to ~1.5 s after the price crossed it, and a new bar reached the signals minutes later.

Now the live feed PUBlishes on tcp://127.0.0.1:<port> (loopback only, never the network) and the server SUBscribes:
  T  every tick: symbol, last price, bid, ask, day volume, the exchange's time and when the live feed received it
  B  new completed bars were just written (interval, how many): the live signal engine recomputes at once
  H  a heartbeat every second, so the server can tell a quiet feed from a stopped one
Messages are fixed-layout binary (struct, like SBE / FlatBuffers - no JSON to parse on the hot path); a tick costs a
few microseconds end to end on one PC. ZeroMQ never blocks the publisher: with no subscriber (dashboard closed)
messages are simply dropped, and a full queue drops instead of stalling the feed.

Everything still works without the bus (pyzmq not installed, the port taken): the server falls back to the files.
"""
from __future__ import annotations

import math
import struct
import threading
import time

DEFAULT_PORT = 5557
TICK = struct.Struct("<dddddd")      # ltp, bid, ask, day volume, exchange time (epoch s), received (epoch s)
BARS = struct.Struct("<dI")          # written at (epoch s), number of new bars
BEAT = struct.Struct("<d")
ALIVE_S = 5.0                         # no message (heartbeats included) for this long = the publisher is gone


def port(cfg: dict | None) -> int:
    try:
        return int(((cfg or {}).get("intraday") or {}).get("bus_port") or DEFAULT_PORT)
    except (TypeError, ValueError):
        return DEFAULT_PORT


def available() -> bool:
    try:
        import zmq  # noqa: F401
        return True
    except Exception:
        return False


def _num(v) -> float:
    try:
        f = float(v)
        return f if f == f else math.nan
    except (TypeError, ValueError):
        return math.nan


class Publisher:
    """The live feed's side. Thread-safe (the FYERS SDK's thread sends ticks, the main loop bars, another heartbeats)."""

    def __init__(self, port_no: int = DEFAULT_PORT):
        import zmq
        self._zmq = zmq
        self.sock = zmq.Context.instance().socket(zmq.PUB)
        self.sock.setsockopt(zmq.SNDHWM, 100_000)
        self.sock.setsockopt(zmq.LINGER, 0)
        self.sock.bind(f"tcp://127.0.0.1:{int(port_no)}")
        self.port = int(port_no)
        self._lock = threading.Lock()
        self.sent = 0

    def _send(self, frames: list[bytes]) -> None:
        with self._lock:
            try:
                self.sock.send_multipart(frames, flags=self._zmq.NOBLOCK)
                self.sent += 1
            except self._zmq.Again:          # queue full: drop, never stall the feed
                pass

    def tick(self, symbol: str, ltp: float, bid: float = math.nan, ask: float = math.nan, volume: float = math.nan,
             exch_ts: float = math.nan, recv_ts: float | None = None) -> None:
        self._send([b"T", symbol.encode(), TICK.pack(float(ltp), _num(bid), _num(ask), _num(volume), _num(exch_ts),
                                                     time.time() if recv_ts is None else float(recv_ts))])

    def tick_msg(self, msg: dict, recv_ts: float, symbol: str) -> None:
        """A FYERS SymbolUpdate as it came in (`symbol`: the app's name for it)."""
        ltp = _num(msg.get("ltp"))
        if math.isnan(ltp) or ltp <= 0:
            return
        self.tick(symbol, ltp, msg.get("bid_price"), msg.get("ask_price"), msg.get("vol_traded_today"),
                  msg.get("exch_feed_time") or msg.get("last_traded_time"), recv_ts)

    def bars(self, interval: str, n: int) -> None:
        self._send([b"B", interval.encode(), BARS.pack(time.time(), int(n))])

    def heartbeat(self) -> None:
        self._send([b"H", b"", BEAT.pack(time.time())])

    def close(self) -> None:
        with self._lock:
            try:
                self.sock.close(0)
            except Exception:
                pass


def open_publisher(port_no: int, log=print) -> Publisher | None:
    """The publisher, or None (pyzmq missing, port taken): the live feed then runs exactly as before, files only."""
    try:
        pub = Publisher(port_no)
        log(f"Tick bus: publishing on 127.0.0.1:{port_no} (ZeroMQ)")
        return pub
    except Exception as e:
        log(f"Tick bus: not started ({type(e).__name__}: {e}) - the dashboard reads the files instead")
        return None


class Subscriber:
    """The dashboard's side: a daemon thread that keeps the latest tick per symbol and calls the handlers.
    Handlers run on this thread and must be quick (they are: a dict lookup for symbols nobody holds)."""

    def __init__(self, port_no: int = DEFAULT_PORT, on_tick=None, on_bars=None):
        self.port = int(port_no)
        self.on_tick = on_tick or []          # callables (symbol, quote dict)
        self.on_bars = on_bars or []          # callables (interval, n, written_at)
        self.quotes: dict[str, dict] = {}
        self.last_msg: float | None = None
        self.counts = {"T": 0, "B": 0, "H": 0}
        self.errors = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> "Subscriber":
        self._thread = threading.Thread(target=self._run, name="tick-bus", daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)

    def alive(self, now: float | None = None) -> bool:
        return self.last_msg is not None and (now or time.time()) - self.last_msg <= ALIVE_S

    def latest(self, symbol: str, max_age_s: float = ALIVE_S) -> dict | None:
        q = self.quotes.get(symbol)
        if q is None or not self.alive() or time.time() - q["bus_ts"] > max_age_s:
            return None
        return q

    def _run(self) -> None:
        import zmq
        sock = zmq.Context.instance().socket(zmq.SUB)
        sock.setsockopt(zmq.LINGER, 0)
        sock.setsockopt(zmq.RCVHWM, 100_000)
        for t in (b"T", b"B", b"H"):
            sock.setsockopt(zmq.SUBSCRIBE, t)
        sock.connect(f"tcp://127.0.0.1:{self.port}")     # connects whenever the live feed starts; reconnects by itself
        poller = zmq.Poller()
        poller.register(sock, zmq.POLLIN)
        try:
            while not self._stop.is_set():
                if not dict(poller.poll(500)):
                    continue
                while True:
                    try:
                        frames = sock.recv_multipart(flags=zmq.NOBLOCK)
                    except zmq.Again:
                        break
                    try:
                        self._handle(frames)
                    except Exception:
                        self.errors += 1
        finally:
            sock.close(0)

    def _handle(self, frames: list[bytes]) -> None:
        now = time.time()
        self.last_msg = now
        kind = frames[0].decode()
        self.counts[kind] = self.counts.get(kind, 0) + 1
        if kind == "T":
            ltp, bid, ask, vol, exch_ts, recv_ts = TICK.unpack(frames[2])
            sym = frames[1].decode()
            q = {"symbol": sym, "price": ltp, "bid": None if math.isnan(bid) else bid,
                 "ask": None if math.isnan(ask) else ask, "volume": None if math.isnan(vol) else vol,
                 "exch_ts": None if math.isnan(exch_ts) else exch_ts, "recv_ts": recv_ts, "bus_ts": now,
                 "source": "live"}
            self.quotes[sym] = q
            for f in self.on_tick:
                f(sym, q)
        elif kind == "B":
            written, n = BARS.unpack(frames[2])
            for f in self.on_bars:
                f(frames[1].decode(), n, written)
