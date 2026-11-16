"""Which symbols the open screens need on the FYERS live feed.

Every open event stream (/api/stream/quotes) registers its symbols here. The union - the top bar's indices
first, then the most recently opened screens - is written to data/intraday/live/subscriptions.json, which the
live service reads every few seconds to stream exactly what is on screen (scanner/intraday/quote_hub.py).
"""
from __future__ import annotations

import itertools
import threading

from scanner.intraday import data as idata
from scanner.intraday import quote_hub

from ..errors import log
from ..paths import P

ALWAYS = ["NIFTY50", "INDIAVIX", "NIFTY500"]      # the top bar's ticker, on every page

_streams: dict[int, list[str]] = {}
_ids = itertools.count(1)
_lock = threading.Lock()
_written: list[str] | None = None


def wanted() -> list[str]:
    with _lock:
        out = list(ALWAYS)
        for sid in sorted(_streams, reverse=True):     # the newest screen first: it is what the user looks at now
            for s in _streams[sid]:
                if s not in out:
                    out.append(s)
        return out


def _publish() -> None:
    global _written
    w = wanted()
    if w == _written:
        return
    try:
        quote_hub.write_subscriptions(P.intraday_live, w, idata._replace)
        _written = w
    except Exception:
        log.exception("Writing the live-feed subscriptions failed")


def open_stream(symbols: list[str]) -> int:
    with _lock:
        sid = next(_ids)
        _streams[sid] = list(symbols)
    _publish()
    return sid


def close_stream(sid: int) -> None:
    with _lock:
        _streams.pop(sid, None)
    _publish()


def reset() -> None:
    """Tests: forget every stream."""
    global _written
    with _lock:
        _streams.clear()
        _written = None
