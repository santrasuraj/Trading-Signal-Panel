"""Market depth for the order ladder (GET /api/depth/{symbol}): FYERS' five best bids and offers with their quantities
and order counts, and the total buy / sell quantity in the book. One REST call per symbol at most every 1.5 s however
many tabs ask (cached), through the shared rate limiter. Needs today's FYERS login."""
from __future__ import annotations

import threading
import time

from scanner.intraday.quote_hub import to_ticker
from scanner.providers import FyersAuthError, FyersProvider, FyersRateLimited, load_token, token_expired

from . import data
from ..errors import ApiException

TTL_S = 1.5
_cache: dict[str, tuple[float, dict]] = {}
_lock = threading.Lock()


def _num(x) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v else None


def parse(symbol: str, resp: dict) -> dict:
    d = (resp.get("d") or {}).get(to_ticker(symbol)) or {}
    side = lambda rows: [{"price": _num(r.get("price")), "qty": int(r.get("volume") or 0), "orders": int(r.get("ord") or 0)}  # noqa: E731
                         for r in rows or [] if _num(r.get("price"))]
    return {"symbol": symbol, "bids": side(d.get("bids")), "asks": side(d.get("ask")),
            "total_buy": int(d.get("totalbuyqty") or 0), "total_sell": int(d.get("totalsellqty") or 0),
            "ltp": _num(d.get("ltp")), "at": time.time()}


def depth(symbol: str) -> dict:
    sym = symbol.upper().strip()
    hit = _cache.get(sym)
    if hit and time.time() - hit[0] < TTL_S:
        return hit[1]
    tok = load_token()
    if not tok or token_expired(tok):
        raise ApiException("FYERS_LOGIN_REQUIRED", "Market depth needs today's FYERS login.",
                           "Click the Fyers chip in the top bar.")
    with _lock:
        hit = _cache.get(sym)
        if hit and time.time() - hit[0] < TTL_S:
            return hit[1]
        plan = str(data.config().get("fyers_plan") or "standard").lower()
        prov = FyersProvider(tok["client_id"], tok["access_token"], plan=plan)
        try:
            r = prov._call(prov.api.depth, {"symbol": to_ticker(sym), "ohlcv_flag": "1"})
        except (FyersAuthError, FyersRateLimited) as e:
            raise ApiException("FEATURE_UNAVAILABLE", f"Market depth unavailable: {e}", None, {"feature": "depth"})
        if r.get("s") != "ok":
            raise ApiException("FEATURE_UNAVAILABLE", f"FYERS gave no depth for {sym}: {r.get('message')}", None,
                               {"feature": "depth"})
        out = parse(sym, r)
        _cache[sym] = (time.time(), out)
        if len(_cache) > 200:
            _cache.clear()
        return out
