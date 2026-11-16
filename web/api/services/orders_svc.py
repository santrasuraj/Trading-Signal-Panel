"""Orders on your own FYERS account: preview, checks, place, cancel, protect, kill switch, audit.

Safety model (every rule is enforced here, on the server - the page only shows them):
  - Off until you switch it on (Orders page, typed confirmation): data/orders_state.json, never config.yaml.
  - Two steps: POST /api/orders/preview returns the exact FYERS order, the checks and the charges, valid for 60 s;
    only POST /api/orders/place with that preview id (and confirm=true) sends it. Nothing places an order by itself.
  - One attempt per order, never a retry: if FYERS doesn't answer (timeout), the order may or may not exist, so the
    app says "check the order book" instead of sending it again (a retry could buy twice).
  - Checks: switched on, kill switch off, logged in to FYERS today, market open (no after-market orders through the
    API), limit orders only unless market orders are allowed, the limit within `price_band_pct` of the last price,
    order value within `max_order_value_pct` of your capital, at most `max_orders_per_day`, at least
    `min_seconds_between_orders` apart (FYERS / SEBI allow 10 a second; this stays far below), no repeat of the same
    order within 2 minutes, today's P&L above -`daily_loss_limit_pct` of capital for buys (a lockout for the day), and
    for a delivery sell no more than you hold.
  - Kill switch: blocks every new order and cancels every pending order.
  - Audit: every preview, order, answer, cancel and kill is appended to data/orders_audit.jsonl (no tokens).

SEBI's retail algo framework (fully in force from 1 Apr 2026): orders through the API need the daily FYERS login
and a static IP registered in the FYERS API dashboard; below 10 orders a second a client's own orders need no
strategy registration (they carry a generic algo ID). Market orders are converted to price-protected orders by the
broker. These are your own orders on your own account: the app never trades for anyone else.
"""
from __future__ import annotations

import json
import math
import threading
import time
import uuid
from datetime import datetime

from scanner import fills
from scanner.costs import CostModel
from scanner.intraday import order_feed
from scanner.providers import FyersProvider, load_token, token_expired

from . import clock, data, quotes_svc
from ..errors import ApiException, log
from ..paths import P
from ..util import now_ist

DEFAULTS = {"product": "CNC", "max_order_value_pct": 10.0, "max_orders_per_day": 20, "daily_loss_limit_pct": 2.0,
            "price_band_pct": 3.0, "min_seconds_between_orders": 1.0, "allow_market": False, "repeat_block_s": 120}
PREVIEW_TTL_S = 60
PRODUCTS = ("CNC", "INTRADAY")
TYPES = {"LIMIT": 1, "MARKET": 2, "SL-M": 3, "SL-L": 4}
PENDING_STATUS = {6, 4}          # FYERS order status: 6 pending, 4 transit (2 traded, 1 cancelled, 5 rejected)
STATUS_TEXT = {1: "cancelled", 2: "filled", 4: "in transit", 5: "rejected", 6: "pending", 7: "expired"}

_lock = threading.Lock()
_previews: dict[str, dict] = {}


# ---- config, state and audit --------------------------------------------------------------------------------------

def limits() -> dict:
    cfg = (data.config().get("orders") or {})
    out = dict(DEFAULTS)
    for k, v in cfg.items():
        if k in DEFAULTS:
            out[k] = type(DEFAULTS[k])(v) if not isinstance(DEFAULTS[k], bool) else bool(v)
    return out


def _state_file():
    return P.data / "orders_state.json"


def state() -> dict:
    try:
        st = json.loads(_state_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        st = {}
    today = now_ist().date().isoformat()
    if st.get("day") != today:                    # a new day: the counters reset, the switches stay
        st.update(day=today, count=0, last_ts=0.0, recent=[])
    st.setdefault("enabled", False)
    st.setdefault("kill", False)
    return st


def _save_state(st: dict) -> None:
    f = _state_file()
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(st, indent=1), encoding="utf-8")
    tmp.replace(f)


def audit(event: str, **kw) -> None:
    rec = {"ts": now_ist().isoformat(timespec="seconds"), "event": event, **kw}
    try:
        with open(P.data / "orders_audit.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, default=str) + "\n")
    except OSError:
        log.exception("Writing the order audit failed")


def audit_tail(n: int = 50) -> list[dict]:
    try:
        lines = (P.data / "orders_audit.jsonl").read_text(encoding="utf-8").splitlines()[-n:]
    except OSError:
        return []
    out = []
    for ln in reversed(lines):
        try:
            out.append(json.loads(ln))
        except ValueError:
            pass
    return out


# ---- the broker (FYERS), one attempt per call ----------------------------------------------------------------------

class Broker:
    """FYERS through the shared rate limiter ('user' bucket), ONE attempt per call (orders must never be retried)."""

    def __init__(self, provider: FyersProvider):
        self.p = provider

    def _once(self, fn, payload=None) -> dict:
        self.p.limiter.acquire("user")
        try:
            r = fn(data=payload) if payload is not None else fn()
        except Exception as e:                                       # timeout / connection: the outcome is unknown
            return {"s": "error", "code": -99, "unknown": True,
                    "message": f"No answer from FYERS ({type(e).__name__}). The order may or may not exist: check the "
                               "order book before trying again."}
        return r if isinstance(r, dict) else {"s": "error", "message": str(r)[:200]}

    def place(self, payload: dict) -> dict:
        return self._once(self.p.api.place_order, payload)

    def cancel(self, order_id: str) -> dict:
        return self._once(self.p.api.cancel_order, {"id": order_id})

    def orderbook(self) -> dict:
        return self._once(self.p.api.orderbook)

    def positions(self) -> dict:
        return self._once(self.p.api.positions)

    def holdings(self) -> dict:
        return self._once(self.p.api.holdings)

    def place_gtt(self, payload: dict) -> dict:
        return self._once(self.p.api.place_gtt_order, payload)

    def gtt_orders(self) -> dict:
        return self._once(self.p.api.gtt_orderbook)

    def cancel_gtt(self, gtt_id: str) -> dict:
        return self._once(self.p.api.cancel_gtt_order, {"id": gtt_id})


def broker() -> Broker:
    """A FYERS client for today's login, or FYERS_LOGIN_REQUIRED. Independent of the data budget (orders count in
    FYERS' separate order / user limits)."""
    tok = load_token()
    if not tok or token_expired(tok):
        raise ApiException("FYERS_LOGIN_REQUIRED", "Log in to FYERS today before placing orders.",
                           "Click the Fyers chip in the top bar (SEBI requires a fresh login every trading day).")
    plan = str(data.config().get("fyers_plan") or "standard").lower()
    return Broker(FyersProvider(tok["client_id"], tok["access_token"], plan=plan))


# ---- tickets -------------------------------------------------------------------------------------------------------

def _num(x) -> float | None:
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def normalize(t: dict) -> dict:
    sym = str(t.get("symbol") or "").strip().upper()
    if not quotes_svc.SYMBOL.match(sym):
        raise ApiException("VALIDATION", "Not an NSE symbol.")
    side = str(t.get("side") or "").upper()
    if side not in ("BUY", "SELL"):
        raise ApiException("VALIDATION", "Side must be BUY or SELL.")
    otype = str(t.get("type") or "LIMIT").upper()
    if otype not in TYPES:
        raise ApiException("VALIDATION", f"Order type must be one of {', '.join(TYPES)}.")
    product = str(t.get("product") or limits()["product"]).upper()
    if product not in PRODUCTS:
        raise ApiException("VALIDATION", "Product must be CNC (delivery) or INTRADAY.")
    qty = t.get("qty")
    if not isinstance(qty, (int, float)) or int(qty) != qty or qty < 1:
        raise ApiException("VALIDATION", "Quantity must be a whole number of shares, at least 1.")
    out = {"symbol": sym, "side": side, "type": otype, "product": product, "qty": int(qty),
           "limit_price": _num(t.get("limit_price")), "trigger_price": _num(t.get("trigger_price")),
           "stop": _num(t.get("stop")), "target": _num(t.get("target")),
           "ref_price": _num(t.get("ref_price")), "strategy_key": str(t.get("strategy_key") or "")[:40] or None,
           "source": str(t.get("source") or "manual")[:20]}
    if otype in ("LIMIT", "SL-L") and not (out["limit_price"] and out["limit_price"] > 0):
        raise ApiException("VALIDATION", "A limit order needs a limit price.")
    if otype in ("SL-M", "SL-L") and not (out["trigger_price"] and out["trigger_price"] > 0):
        raise ApiException("VALIDATION", "A stop order needs a trigger price.")
    for k in ("limit_price", "trigger_price", "stop", "target"):
        if out[k] is not None:
            out[k] = round(out[k], 2)
    return out


def payload(t: dict) -> dict:
    """The exact FYERS place_order body (fyers_apiv3 fyersModel.place_order)."""
    return {"symbol": f"NSE:{t['symbol']}-EQ", "qty": t["qty"], "type": TYPES[t["type"]],
            "side": 1 if t["side"] == "BUY" else -1, "productType": t["product"],
            "limitPrice": t["limit_price"] or 0, "stopPrice": t["trigger_price"] or 0, "validity": "DAY",
            "disclosedQty": 0, "offlineOrder": False}


def _today_pnl(b: Broker) -> tuple[float | None, str | None]:
    r = b.positions()
    if r.get("s") != "ok":
        return None, str(r.get("message") or "positions unavailable")
    ov = r.get("overall") or {}
    pl = _num(ov.get("pl_total"))
    if pl is None:
        pl = sum((_num(x.get("pl")) or 0.0) for x in r.get("netPositions") or [])
    return pl, None


def _held_qty(b: Broker, sym: str) -> tuple[float | None, str | None]:
    r = b.holdings()
    if r.get("s") != "ok":
        return None, str(r.get("message") or "holdings unavailable")
    q = 0.0
    for h in r.get("holdings") or []:
        if str(h.get("symbol", "")).upper() in (f"NSE:{sym}-EQ", sym):
            q += _num(h.get("remainingQuantity") if h.get("remainingQuantity") is not None else h.get("quantity")) or 0.0
    p = b.positions()                                   # today's delivery buys show as positions until T+1
    for x in (p.get("netPositions") or []) if p.get("s") == "ok" else []:
        if str(x.get("symbol", "")).upper() == f"NSE:{sym}-EQ" and str(x.get("productType")) == "CNC":
            q += max(0.0, _num(x.get("netQty")) or 0.0)
    return q, None


def checks(t: dict, st: dict, lim: dict, b: Broker | None, live: dict | None, session: str) -> list[dict]:
    """Every pre-trade check, in order; `ok: False` with `blocking: True` stops the order."""
    out = []

    def add(key, name, ok, detail, blocking=True):
        out.append({"key": key, "name": name, "ok": bool(ok), "detail": detail, "blocking": blocking})

    capital = _num(data.config().get("account", {}).get("capital")) or _num((data.latest() or {}).get("capital")) or 0.0
    add("enabled", "Order placement switched on", st["enabled"], "on" if st["enabled"] else "off: switch it on on the Orders page")
    add("kill", "Kill switch off", not st["kill"], "off" if not st["kill"] else f"on since {st.get('kill_at')}: {st.get('kill_reason') or ''}")
    add("login", "Logged in to FYERS today", b is not None, "yes" if b is not None else "log in first (daily login rule)")
    add("market", "Market open", session == "open", "open" if session == "open" else f"market {session.replace('_', ' ')}: no after-market orders through the API")
    add("type", "Order type allowed", t["type"] != "MARKET" or lim["allow_market"],
        "limit / stop orders" if t["type"] != "MARKET" else ("market orders allowed (the broker converts them to price-protected orders)" if lim["allow_market"]
                                                               else "market orders are off: use a limit price (orders.allow_market in config.yaml)"))
    price = (live or {}).get("price")
    src = (live or {}).get("source")
    px = t["limit_price"] or t["trigger_price"] or price
    if price and t["type"] in ("LIMIT", "SL-L"):
        band = abs(t["limit_price"] / price - 1) * 100
        add("band", f"Limit within {lim['price_band_pct']:g}% of the last price", band <= lim["price_band_pct"],
            f"{t['limit_price']:,.2f} vs last {price:,.2f} ({band:.1f}% away{', Yahoo price ~15 min late' if src == 'yahoo' else ''})")
    elif not price:
        add("price", "Last price known", False, "no price for this symbol: can't check the limit against the market")
    value = (px or 0) * t["qty"]
    cap = capital * lim["max_order_value_pct"] / 100
    add("value", f"Order value within {lim['max_order_value_pct']:g}% of capital", capital > 0 and value <= cap,
        f"₹{value:,.0f} of max ₹{cap:,.0f}" if capital > 0 else "set account.capital in config.yaml")
    add("count", f"At most {lim['max_orders_per_day']} orders today", st["count"] < lim["max_orders_per_day"], f"{st['count']} placed today")
    gap = time.time() - float(st.get("last_ts") or 0)
    add("gap", f"At least {lim['min_seconds_between_orders']:g} s since the last order", gap >= lim["min_seconds_between_orders"],
        f"{gap:.1f} s" if st.get("last_ts") else "first order today")
    sig = f"{t['symbol']}|{t['side']}|{t['qty']}"
    recent = [r for r in st.get("recent") or [] if r["sig"] == sig and time.time() - r["ts"] < lim["repeat_block_s"]]
    add("repeat", "Not a repeat of an order placed in the last 2 minutes", not recent, "new" if not recent else "the same order went out moments ago: check the order book")
    if b is not None and t["side"] == "BUY":
        pl, err = _today_pnl(b)
        floor = -capital * lim["daily_loss_limit_pct"] / 100
        if pl is None:
            add("loss", "Daily-loss lockout", False, f"today's P&L couldn't be read ({err}): buys stay blocked until it can")
        else:
            add("loss", f"Today's P&L above -{lim['daily_loss_limit_pct']:g}% of capital", pl > floor, f"₹{pl:,.0f} (lockout at ₹{floor:,.0f})")
    if b is not None and t["side"] == "SELL" and t["product"] == "CNC":
        held, err = _held_qty(b, t["symbol"])
        if held is None:
            add("held", "You hold the shares you sell", False, f"holdings couldn't be read ({err})")
        else:
            add("held", "You hold the shares you sell", t["qty"] <= held, f"{held:g} held, selling {t['qty']}")
    return out


def _charges(t: dict, value: float) -> dict:
    cm = CostModel.from_config(data.config().get("costs"))
    c = cm.buy_cost(value) if t["side"] == "BUY" else cm.sell_cost(value)
    return {"charges": round(c, 2), "slippage_estimate": round(value * cm.slippage_pct / 100, 2)}


def preview(ticket: dict) -> dict:
    t = normalize(ticket)
    lim, st = limits(), state()
    session = clock.market_clock()["session"]
    try:
        b = broker()
    except ApiException:
        b = None
    q = quotes_svc.quotes([t["symbol"]]).get("quotes") or []
    live = q[0] if q else None
    cks = checks(t, st, lim, b, live, session)
    px = t["limit_price"] or t["trigger_price"] or (live or {}).get("price") or 0
    value = round(px * t["qty"], 2)
    risk = round((px - t["stop"]) * t["qty"], 2) if t["side"] == "BUY" and t["stop"] and px > t["stop"] else None
    pid = uuid.uuid4().hex[:16]
    ok = all(c["ok"] for c in cks if c["blocking"])
    with _lock:
        now = time.time()
        for k in [k for k, v in _previews.items() if now - v["at"] > PREVIEW_TTL_S]:
            _previews.pop(k, None)
        if ok:
            _previews[pid] = {"at": now, "ticket": t}
    audit("preview", ticket=t, ok=ok, failed=[c["name"] for c in cks if not c["ok"] and c["blocking"]])
    return {"preview_id": pid if ok else None, "ok": ok, "ticket": t, "payload": payload(t), "checks": cks,
            "last": live, "value": value, "risk_if_stopped": risk, **_charges(t, value), "limits": lim,
            "expires_in_s": PREVIEW_TTL_S if ok else 0,
            "note": "Nothing is sent until you confirm. One attempt only: if FYERS doesn't answer, check the order book."}


def place(preview_id: str, confirm: bool) -> dict:
    if not confirm:
        raise ApiException("VALIDATION", "Confirm the order to send it.")
    with _lock:
        pv = _previews.pop(preview_id, None)
    if pv is None or time.time() - pv["at"] > PREVIEW_TTL_S:
        raise ApiException("VALIDATION", "This preview expired or was already used.", "Review the order again (previews last 60 s).")
    t = pv["ticket"]
    lim, st = limits(), state()
    b = broker()
    session = clock.market_clock()["session"]
    q = quotes_svc.quotes([t["symbol"]], allow_network=False).get("quotes") or []
    # the fast checks again at the moment of sending (switches, counters, market, repeat); P&L / holdings were read
    # at the preview seconds ago
    fast = {"enabled", "kill", "market", "type", "band", "value", "count", "gap", "repeat"}
    bad = [c for c in checks(t, st, lim, None, q[0] if q else None, session)
           if c["key"] in fast and c["blocking"] and not c["ok"]]
    if bad:
        audit("blocked", ticket=t, failed=[c["name"] for c in bad])
        raise ApiException("VALIDATION", f"Not sent: {bad[0]['name'].lower()} ({bad[0]['detail']}).", "Review the order again.")
    body = payload(t)
    audit("send", ticket=t, payload=body)
    r = b.place(body)
    st = state()
    st["count"] = int(st.get("count") or 0) + (0 if r.get("s") != "ok" and not r.get("unknown") else 1)
    st["last_ts"] = time.time()
    st["recent"] = [x for x in st.get("recent") or [] if time.time() - x["ts"] < 600] + [{"sig": f"{t['symbol']}|{t['side']}|{t['qty']}", "ts": time.time()}]
    _save_state(st)
    ok = r.get("s") == "ok"
    audit("placed" if ok else ("unknown" if r.get("unknown") else "rejected"), ticket=t, order_id=r.get("id"),
          code=r.get("code"), message=r.get("message"))
    return {"ok": ok, "unknown": bool(r.get("unknown")), "order_id": r.get("id"), "message": r.get("message"),
            "code": r.get("code"), "ticket": t,
            "next": ("Once it fills, protect it with a stop-loss and target (Orders page)." if ok and t["side"] == "BUY" and t["product"] == "CNC" else None)}


MAX_BASKET = 20


def basket_preview(tickets: list[dict]) -> dict:
    """Review several orders at once (today's BUYs): one preview each, every check as for a single order, and the
    basket's total against your capital. Nothing is sent."""
    if not tickets or len(tickets) > MAX_BASKET:
        raise ApiException("VALIDATION", f"A basket holds 1 to {MAX_BASKET} orders.")
    pvs = [preview(t) for t in tickets]
    cap = float((data.config().get("account") or {}).get("capital") or 0)
    buys = sum(p["value"] for p in pvs if p["ticket"]["side"] == "BUY")
    return {"previews": pvs, "ok": sum(1 for p in pvs if p["ok"]), "total": len(pvs), "buy_value": round(buys, 2),
            "capital": cap, "over_capital": bool(cap and buys > cap),
            "note": "Each order is sent on its own, one at a time, at least the minimum gap apart; one that fails does "
                    "not stop the others. Previews last 60 seconds."}


def basket_place(preview_ids: list[str], confirm: bool, sleep=time.sleep) -> dict:
    """Send previewed orders one by one (each once, never retried), spaced by the minimum gap between orders."""
    if not confirm:
        raise ApiException("VALIDATION", "Confirm the basket to send it.")
    gap = float(limits().get("min_seconds_between_orders") or 1) + 0.1
    out = []
    for i, pid in enumerate(preview_ids[:MAX_BASKET]):
        if i:
            sleep(gap)
        try:
            out.append({"preview_id": pid, **place(pid, True)})
        except ApiException as e:
            out.append({"preview_id": pid, "ok": False, "unknown": False, "order_id": None, "message": e.message})
    return {"results": out, "sent": sum(1 for r in out if r.get("ok")), "total": len(out)}


def cancel(order_id: str) -> dict:
    b = broker()
    r = b.cancel(order_id)
    audit("cancel", order_id=order_id, ok=r.get("s") == "ok", message=r.get("message"))
    return {"ok": r.get("s") == "ok", "message": r.get("message")}


def set_kill(on: bool, reason: str = "") -> dict:
    """On: block every new order and cancel every pending one. Off: allow orders again (the switch itself stays off)."""
    st = state()
    st["kill"] = bool(on)
    st["kill_at"] = now_ist().isoformat(timespec="seconds") if on else None
    st["kill_reason"] = reason[:120] if on else None
    _save_state(st)
    cancelled, errors = [], []
    if on:
        try:
            b = broker()
            ob = b.orderbook()
            for o in ob.get("orderBook") or []:
                if int(o.get("status") or 0) in PENDING_STATUS:
                    r = b.cancel(str(o.get("id")))
                    (cancelled if r.get("s") == "ok" else errors).append({"id": o.get("id"), "symbol": o.get("symbol"), "message": r.get("message")})
        except ApiException as e:
            errors.append({"id": None, "symbol": None, "message": e.message})
    audit("kill_on" if on else "kill_off", reason=reason, cancelled=cancelled, errors=errors)
    return {"kill": st["kill"], "cancelled": cancelled, "errors": errors}


def set_enabled(on: bool, phrase: str = "") -> dict:
    if on and phrase.strip().upper() != "ENABLE":
        raise ApiException("VALIDATION", "Type ENABLE to switch order placement on.")
    st = state()
    st["enabled"] = bool(on)
    _save_state(st)
    audit("enabled" if on else "disabled")
    return {"enabled": st["enabled"]}


# ---- protection (GTT OCO: stop-loss and target on a delivery holding) ----------------------------------------------

def gtt_payload(sym: str, qty: int, stop: float, target: float, stop_limit_pct: float = 0.5) -> dict:
    """FYERS place_gtt_order body for an OCO sell: leg1 = target (trigger above the price), leg2 = stop-loss (trigger
    below); each fills as a limit order a little through its trigger so it isn't left unfilled in a fast move."""
    return {"side": -1, "symbol": f"NSE:{sym}-EQ", "productType": "CNC",
            "orderInfo": {"leg1": {"price": round(target, 2), "triggerPrice": round(target, 2), "qty": int(qty)},
                          "leg2": {"price": round(stop * (1 - stop_limit_pct / 100), 2), "triggerPrice": round(stop, 2), "qty": int(qty)}}}


def protect(sym: str, qty: int, stop: float, target: float, confirm: bool) -> dict:
    sym = sym.strip().upper()
    if not confirm:
        raise ApiException("VALIDATION", "Confirm to place the stop-loss / target.")
    if not (stop and target and stop > 0 and target > stop):
        raise ApiException("VALIDATION", "The target must be above the stop-loss.")
    st = state()
    if not st["enabled"] or st["kill"]:
        raise ApiException("VALIDATION", "Order placement is off or the kill switch is on.")
    b = broker()
    held, err = _held_qty(b, sym)
    if held is None or qty > held:
        raise ApiException("VALIDATION", f"You hold {held or 0:g} {sym}: can't protect {qty}." if held is not None else f"Holdings unavailable ({err}).")
    q = quotes_svc.quotes([sym], allow_network=False).get("quotes") or []
    px = q[0]["price"] if q else None
    if px and not (stop < px < target):
        raise ApiException("VALIDATION", f"The stop ({stop:,.2f}) must be below and the target ({target:,.2f}) above the price ({px:,.2f}).")
    body = gtt_payload(sym, qty, stop, target)
    r = b.place_gtt(body)
    audit("gtt", symbol=sym, payload=body, ok=r.get("s") == "ok", id=r.get("id"), message=r.get("message"))
    return {"ok": r.get("s") == "ok", "id": r.get("id"), "message": r.get("message"), "payload": body}


# ---- the Orders page ------------------------------------------------------------------------------------------------

def _orders_view(ob: dict) -> list[dict]:
    out = []
    for o in ob.get("orderBook") or []:
        s = int(o.get("status") or 0)
        out.append({"id": str(o.get("id")), "symbol": str(o.get("symbol", "")).removeprefix("NSE:").removesuffix("-EQ"),
                    "side": "BUY" if int(o.get("side") or 0) == 1 else "SELL", "qty": o.get("qty"), "filled": o.get("filledQty"),
                    "type": {1: "LIMIT", 2: "MARKET", 3: "SL-M", 4: "SL-L"}.get(int(o.get("type") or 0), str(o.get("type"))),
                    "limit_price": _num(o.get("limitPrice")), "avg_price": _num(o.get("tradedPrice")),
                    "status": STATUS_TEXT.get(s, str(s)), "pending": s in PENDING_STATUS, "product": o.get("productType"),
                    "time": o.get("orderDateTime"), "message": o.get("message")})
    return out


def reconcile(orders: list[dict], trail: list[dict]) -> list[dict]:
    """Filled orders that came from a signal: the fill price against the signal's reference price (slippage)."""
    ref = {str(a.get("order_id")): a.get("ticket") or {} for a in trail if a.get("event") == "placed" and a.get("order_id")}
    out = []
    for o in orders:
        t = ref.get(o["id"])
        if not t or o["status"] != "filled" or not o.get("avg_price") or not t.get("ref_price"):
            continue
        slip = (o["avg_price"] / t["ref_price"] - 1) * 100 * (1 if o["side"] == "BUY" else -1)
        out.append({"id": o["id"], "symbol": o["symbol"], "side": o["side"], "ref_price": t["ref_price"], "fill": o["avg_price"],
                    "slippage_pct": round(slip, 2), "strategy_key": t.get("strategy_key")})
    return out


def view() -> dict:
    st, lim = state(), limits()
    out = {"enabled": st["enabled"], "kill": st["kill"], "kill_at": st.get("kill_at"), "kill_reason": st.get("kill_reason"),
           "today_count": st["count"], "limits": lim, "logged_in": False, "orders": [], "positions": [], "pnl_today": None,
           "gtt": [], "errors": [], "audit": audit_tail(40), "reconciliation": [], "note": __doc__.split("\n\n")[1],
           "feed": order_feed.status(P.intraday_live)}
    try:
        b = broker()
    except ApiException as e:
        out["errors"].append(e.message)
        return out
    out["logged_in"] = True
    ob = b.orderbook()
    if ob.get("s") == "ok":
        out["orders"] = _orders_view(ob)
    else:
        out["errors"].append(f"Order book: {ob.get('message')}")
    pos = b.positions()
    if pos.get("s") == "ok":
        out["positions"] = [{"symbol": str(x.get("symbol", "")).removeprefix("NSE:").removesuffix("-EQ"), "qty": x.get("netQty"),
                             "avg": _num(x.get("netAvg")), "ltp": _num(x.get("ltp")), "pl": _num(x.get("pl")),
                             "product": x.get("productType")} for x in pos.get("netPositions") or []]
        out["pnl_today"] = _num((pos.get("overall") or {}).get("pl_total"))
    gtt = b.gtt_orders()
    if gtt.get("s") == "ok":
        out["gtt"] = [{"id": str(g.get("id")), "symbol": str(g.get("symbol", "")).removeprefix("NSE:").removesuffix("-EQ"),
                       "status": g.get("gttOrderStatus") or g.get("status"), "info": g.get("orderInfo")}
                      for g in (gtt.get("orderBook") or gtt.get("data") or [])]
    trail = audit_tail(500)
    out["reconciliation"] = reconcile(out["orders"], trail)
    try:
        fills.record(fills_from(out["orders"], trail), P.data)   # FYERS' order book is today only: keep your fills
    except Exception:
        log.exception("Recording fills failed")
    return out


def fills_from(orders: list[dict], trail: list[dict]) -> list[dict]:
    """Filled orders as fills.jsonl rows, with the signal they came from when the order was placed here."""
    ref = {str(a.get("order_id")): a.get("ticket") or {} for a in trail if a.get("event") == "placed" and a.get("order_id")}
    out = []
    for o in orders:
        if o["status"] != "filled" or not o.get("avg_price") or not o.get("filled"):
            continue
        t = ref.get(o["id"], {})
        out.append({"id": o["id"], "symbol": o["symbol"], "side": o["side"], "qty": o["filled"], "price": o["avg_price"],
                    "time": o.get("time"), "product": o.get("product") or "CNC", "strategy_key": t.get("strategy_key"),
                    "ref_price": t.get("ref_price"), "stop": t.get("stop"), "source": "here" if t else "fyers"})
    return out
