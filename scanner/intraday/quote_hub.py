"""Real-time quotes from the FYERS data socket: the screen's live prices, at no REST cost.

The live service (live.py) feeds every SymbolUpdate tick into a QuoteBook and writes
data/intraday/live/quotes.json about twice a second, only when something changed. The web server reads that
file and streams the changes to the browser (web/api/routers/stream.py), so a trade reaches the screen in about
a second instead of the 30-60 s of REST polling.

The web server also tells the live service which symbols the screen needs (open pages, holdings, watchlists)
through subscriptions.json. The live service subscribes to those first, within FYERS' symbol limit, and fills
the remaining slots with the most liquid intraday stocks it streams for the 5-minute bars.

Symbols in both files are the app's own names (RELIANCE, NIFTY50, INDIAVIX); F&O instruments keep their FYERS
ticker (NSE:NIFTY26NOVFUT).
"""
from __future__ import annotations

import json
import threading
import time
from datetime import datetime
from pathlib import Path

from ..settings import IST, ist_now

QUOTES_FILE_NAME = "quotes.json"
SUBSCRIPTIONS_FILE_NAME = "subscriptions.json"
WRITE_EVERY_S = 0.5
STALE_S = 15.0                 # quotes.json not rewritten for this long during the session = the feed is down

# The app's index names <-> FYERS index tickers (same map as providers.FyersProvider.INDEX_MAP, plus the
# index the F&O pages use).
INDEX_TICKERS = {"NIFTY50": "NSE:NIFTY50-INDEX", "INDIAVIX": "NSE:INDIAVIX-INDEX", "NIFTY500": "NSE:NIFTY500-INDEX",
                 "BANKNIFTY": "NSE:NIFTYBANK-INDEX"}
_TICKER_INDEX = {v: k for k, v in INDEX_TICKERS.items()}


def to_ticker(sym: str) -> str:
    """App symbol -> FYERS ticker."""
    if ":" in sym:
        return sym
    return INDEX_TICKERS.get(sym, f"NSE:{sym}-EQ")


def from_ticker(ticker: str) -> str:
    """FYERS ticker -> app symbol (equities and indices); F&O tickers stay as they are."""
    if ticker in _TICKER_INDEX:
        return _TICKER_INDEX[ticker]
    if ticker.startswith("NSE:") and ticker.endswith("-EQ"):
        return ticker[4:-3]
    return ticker


def _num(v) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None             # NaN -> None


class QuoteBook:
    """The latest quote per symbol, built from FYERS SymbolUpdate ticks. Thread-safe."""

    def __init__(self):
        self._q: dict[str, dict] = {}
        self._lock = threading.Lock()
        self.seq = 0                      # bumped on every accepted tick
        self._written_seq = -1

    def on_tick(self, msg: dict) -> None:
        ticker, ltp = msg.get("symbol"), _num(msg.get("ltp"))
        if not ticker or ltp is None or ltp <= 0:
            return
        t = msg.get("last_traded_time") or msg.get("exch_feed_time")
        ts = datetime.fromtimestamp(int(t), IST) if t else ist_now()
        prev = _num(msg.get("prev_close_price"))
        chp = _num(msg.get("chp"))
        if chp is None and prev:
            chp = (ltp / prev - 1) * 100
        q = {"symbol": from_ticker(ticker), "price": round(ltp, 2), "prev_close": prev,
             "change_pct": round(chp, 2) if chp is not None else None,
             "open": _num(msg.get("open_price")), "high": _num(msg.get("high_price")),
             "low": _num(msg.get("low_price")), "volume": _num(msg.get("vol_traded_today")),
             "bid": _num(msg.get("bid_price")), "ask": _num(msg.get("ask_price")),
             "time": ts.isoformat(timespec="seconds"), "received": time.time()}
        with self._lock:
            self._q[q["symbol"]] = q
            self.seq += 1

    def snapshot(self) -> tuple[int, dict[str, dict]]:
        with self._lock:
            return self.seq, {k: dict(v) for k, v in self._q.items()}

    def write_if_changed(self, live_dir: Path, replace) -> bool:
        """Write quotes.json when a tick arrived since the last write. `replace` is the retried atomic rename
        (data._replace). Returns True when it wrote."""
        seq, quotes = self.snapshot()
        if seq == self._written_seq:
            return False
        f = live_dir / QUOTES_FILE_NAME
        tmp = f.with_suffix(".qtmp")
        tmp.write_text(json.dumps({"updated": ist_now().isoformat(timespec="milliseconds"), "written": time.time(),
                                   "seq": seq, "quotes": quotes}, default=str), encoding="utf-8")
        replace(tmp, f)
        self._written_seq = seq
        return True


def read_quotes(live_dir: Path) -> dict | None:
    """quotes.json as written by the live service, or None (missing, unreadable mid-replace, from another day)."""
    try:
        info = json.loads((live_dir / QUOTES_FILE_NAME).read_text(encoding="utf-8"))
        if datetime.fromisoformat(info["updated"]).date() != ist_now().date():
            return None
        return info
    except Exception:
        return None


def feed_live(info: dict | None, now: float | None = None) -> bool:
    """True when the live service wrote quotes within STALE_S seconds (it rewrites the file twice a second
    while ticks arrive; a quiet minute on all 100 symbols does not happen in the session)."""
    if not info:
        return False
    return ((now or time.time()) - float(info.get("written") or 0)) <= STALE_S


# ---- which symbols the screen wants on the socket ---------------------------------------------------------------

def write_subscriptions(live_dir: Path, wanted: list[str], replace) -> None:
    live_dir.mkdir(parents=True, exist_ok=True)
    f = live_dir / SUBSCRIPTIONS_FILE_NAME
    tmp = f.with_suffix(".stmp")
    tmp.write_text(json.dumps({"updated": ist_now().isoformat(timespec="seconds"), "symbols": wanted}),
                   encoding="utf-8")
    replace(tmp, f)


def read_subscriptions(live_dir: Path) -> list[str]:
    try:
        info = json.loads((live_dir / SUBSCRIPTIONS_FILE_NAME).read_text(encoding="utf-8"))
        return [str(s) for s in info.get("symbols") or [] if s]
    except Exception:
        return []


def plan_tickers(wanted: list[str], base: list[str], fno: list[str], limit: int) -> list[str]:
    """The FYERS tickers to stream, at most `limit`: the screen's symbols first (they are what the user is
    looking at) in the slots the F&O instruments leave (big trades keep theirs), then those F&O instruments,
    then the liquid stocks for the 5-minute bars."""
    out: list[str] = []
    screen_room = max(limit - len(fno), 0)
    for t in [to_ticker(s) for s in wanted]:
        if len(out) >= screen_room:
            break
        if t not in out:
            out.append(t)
    for t in fno + [to_ticker(s) for s in base]:
        if len(out) >= limit:
            break
        if t not in out:
            out.append(t)
    return out
