"""Simulated trading on today's live prices (GET /api/sim, POST /api/sim/order ...): a practice account with no real
money and nothing sent to FYERS - the same order ticket as the real one, filled against the live quotes.

Fills: a market order at the live price plus slippage (only while the market is open); a limit order rests until the
live price reaches it (a buy at or below the limit, a sell at or above) and fills at the limit, or at the live price if
that is better. A position may carry a stop-loss and a target: the stop fills at the live price plus slippage once it
is touched, the target at the target. Intraday positions (product INTRADAY, which may be short) are squared off from
15:20. Charges are FYERS' (delivery or intraday) from the cost model. Orders and positions are checked whenever live
quotes arrive (the dashboard's price stream) and on every read of the account.

State in data/sim_account.json. Personal use only: NSE's data policy does not allow offering simulated trading on
live prices to other people.
"""
from __future__ import annotations

import dataclasses
import json
import threading
import uuid

from scanner.costs import CostModel

from . import clock, data, quotes_svc
from ..errors import ApiException
from ..paths import P
from ..util import now_ist

FILE = "sim_account.json"
START_CASH = 500_000.0
SQUARE_OFF = (15, 20)
LIVE = ("live", "fyers", "yahoo")
_lock = threading.Lock()


def _path():
    return P.data / FILE


def _blank(cash: float) -> dict:
    return {"cash": cash, "start_cash": cash, "created": now_ist().isoformat(timespec="seconds"), "positions": {},
            "orders": [], "trades": [], "charges": 0.0}


def _load() -> dict:
    try:
        return json.loads(_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return _blank(float((data.config().get("account") or {}).get("capital") or START_CASH))


def _save(st: dict) -> None:
    p = _path()
    tmp = p.with_suffix(".tmp")
    st["orders"] = st["orders"][-300:]
    st["trades"] = st["trades"][-1000:]
    tmp.write_text(json.dumps(st, indent=1, default=str), encoding="utf-8")
    tmp.replace(p)


def _costs(product: str) -> CostModel:
    cm = CostModel.from_config(data.config().get("costs"))
    if product == "CNC":
        return cm
    return dataclasses.replace(cm, brokerage_pct=0.03, stt_pct=0.0125, stamp_buy_pct=0.003, dp_per_sell=0.0)


def _fill(st: dict, o: dict, px: float, why: str) -> None:
    """Apply a fill to cash and positions (FIFO average price); a reduction books a trade."""
    sym, qty, side, product = o["symbol"], int(o["qty"]), o["side"], o["product"]
    cm = _costs(product)
    value = qty * px
    charges = cm.buy_cost(value) if side == "BUY" else cm.sell_cost(value)
    st["charges"] = round(st.get("charges", 0.0) + charges, 2)
    pos = st["positions"].get(sym) or {"qty": 0, "avg": 0.0, "product": product, "stop": None, "target": None,
                                         "opened": now_ist().isoformat(timespec="seconds")}
    signed = qty if side == "BUY" else -qty
    st["cash"] = round(st["cash"] - signed * px - charges, 2)
    old = pos["qty"]
    if old == 0 or (old > 0) == (signed > 0):                      # opening or adding
        new = old + signed
        pos["avg"] = round((abs(old) * pos["avg"] + qty * px) / abs(new), 4)
        pos["qty"] = new
        pos["product"] = product
        if o.get("stop") is not None:
            pos["stop"] = o["stop"]
        if o.get("target") is not None:
            pos["target"] = o["target"]
    else:                                                          # reducing / closing / flipping
        closed = min(abs(old), qty)
        pnl = (px - pos["avg"]) * closed * (1 if old > 0 else -1)
        st["trades"].append({"symbol": sym, "side": "LONG" if old > 0 else "SHORT", "qty": closed, "entry": pos["avg"],
                             "exit": px, "pnl": round(pnl, 2), "charges": round(charges, 2), "reason": why,
                             "opened": pos.get("opened"), "closed": now_ist().isoformat(timespec="seconds"),
                             "product": pos["product"]})
        rest = old + signed
        if rest == 0:
            pos = None
        elif (rest > 0) != (old > 0):                              # flipped: the remainder opens the other way
            pos.update(qty=rest, avg=px, stop=o.get("stop"), target=o.get("target"),
                       opened=now_ist().isoformat(timespec="seconds"))
        else:
            pos["qty"] = rest
    if pos is None:
        st["positions"].pop(sym, None)
    else:
        st["positions"][sym] = pos
    o.update(status="filled", fill_price=round(px, 2), filled_at=now_ist().isoformat(timespec="seconds"),
             charges=round(charges, 2), note=why)


def _slip(px: float, buying: bool, product: str) -> float:
    s = _costs(product).slippage_pct / 100
    return round(px * (1 + s if buying else 1 - s), 2)


def process(st: dict, quotes: dict[str, dict], session: str | None = None) -> bool:
    """Fill what the live quotes allow: resting limit orders, stops / targets, the intraday square-off. True if
    anything changed."""
    session = session or clock.market_clock()["session"]
    if session != "open":
        return False
    changed = False
    for o in st["orders"]:
        if o["status"] != "open":
            continue
        q = quotes.get(o["symbol"])
        if not q or q.get("price") is None or (q.get("source") or "live") not in LIVE:
            continue
        px = float(q["price"])
        lim = float(o["limit_price"])
        if o["side"] == "BUY" and px <= lim:
            _fill(st, o, min(px, lim), "limit"); changed = True
        elif o["side"] == "SELL" and px >= lim:
            _fill(st, o, max(px, lim), "limit"); changed = True
    now = now_ist()
    square = (now.hour, now.minute) >= SQUARE_OFF
    for sym, pos in list(st["positions"].items()):
        q = quotes.get(sym)
        if not q or q.get("price") is None or (q.get("source") or "live") not in LIVE:
            continue
        px, long = float(q["price"]), pos["qty"] > 0
        why = None
        if square and pos["product"] == "INTRADAY":
            why, fill = "square_off", _slip(px, not long, "INTRADAY")
        elif pos.get("stop") is not None and (px <= pos["stop"] if long else px >= pos["stop"]):
            why, fill = "stop", _slip(px, not long, pos["product"])
        elif pos.get("target") is not None and (px >= pos["target"] if long else px <= pos["target"]):
            why, fill = "target", float(pos["target"])
        if why:
            o = {"id": uuid.uuid4().hex[:10], "symbol": sym, "side": "SELL" if long else "BUY", "qty": abs(pos["qty"]),
                 "type": "MARKET", "product": pos["product"], "limit_price": None, "status": "open",
                 "created": now.isoformat(timespec="seconds"), "auto": why}
            _fill(st, o, fill, why)
            st["orders"].append(o)
            changed = True
    return changed


def _quotes(syms: list[str], network: bool = True) -> tuple[dict, str | None]:
    if not syms:
        return {}, clock.market_clock()["session"]
    q = quotes_svc.quotes(sorted(set(syms)), allow_network=network)
    return {x["symbol"]: x for x in q["quotes"]}, q.get("session")


def _symbols(st: dict) -> list[str]:
    return list(st["positions"]) + [o["symbol"] for o in st["orders"] if o["status"] == "open"]


def on_quotes(quotes: dict[str, dict]) -> None:
    """The price stream's hook: check resting orders and stops on the quotes that just arrived (no network)."""
    if not _path().exists():
        return
    with _lock:
        st = _load()
        if not _symbols(st):
            return
        if process(st, quotes):
            _save(st)


def place(t: dict) -> dict:
    sym = str(t["symbol"]).upper().strip()
    side, qty, typ, product = t["side"], int(t["qty"]), t.get("type") or "LIMIT", t.get("product") or "CNC"
    if qty < 1:
        raise ApiException("VALIDATION", "Quantity must be at least 1.")
    if typ not in ("MARKET", "LIMIT"):
        raise ApiException("VALIDATION", "The practice account takes market and limit orders.")
    with _lock:
        st = _load()
        quotes, session = _quotes([sym])
        q = quotes.get(sym) or {}
        live = q.get("price") if (q.get("source") or "") in LIVE else None
        held = (st["positions"].get(sym) or {}).get("qty", 0)
        if side == "SELL" and product == "CNC" and qty > max(held, 0):
            raise ApiException("VALIDATION", f"Delivery: you hold {max(held, 0)} {sym} in the practice account.",
                               "Use Intraday to sell short (squared off at 15:20).")
        if typ == "MARKET":
            if session != "open" or live is None:
                raise ApiException("VALIDATION", "Market orders fill only while the market is open, on a live price.",
                                   "Place a limit order instead: it waits for the price.")
        else:
            if not t.get("limit_price") or float(t["limit_price"]) <= 0:
                raise ApiException("VALIDATION", "Give the limit price.")
        o = {"id": uuid.uuid4().hex[:10], "symbol": sym, "side": side, "qty": qty, "type": typ, "product": product,
             "limit_price": float(t["limit_price"]) if typ == "LIMIT" else None, "stop": t.get("stop"),
             "target": t.get("target"), "status": "open", "created": now_ist().isoformat(timespec="seconds"),
             "ref_price": live}
        if typ == "MARKET":
            _fill(st, o, _slip(float(live), side == "BUY", product), "market")
        st["orders"].append(o)
        if typ == "LIMIT":
            process(st, quotes, session)                          # a marketable limit fills at once
        _save(st)
        return o


def cancel(order_id: str) -> dict:
    with _lock:
        st = _load()
        o = next((x for x in st["orders"] if x["id"] == order_id), None)
        if not o or o["status"] != "open":
            raise ApiException("NOT_FOUND", "No open practice order with that id.")
        o["status"] = "cancelled"
        _save(st)
        return o


def close(symbol: str) -> dict:
    """Close a practice position at the live price (market)."""
    sym = symbol.upper()
    with _lock:
        st = _load()
        pos = st["positions"].get(sym)
        if not pos:
            raise ApiException("NOT_FOUND", f"No practice position in {sym}.")
    long = pos["qty"] > 0
    return place({"symbol": sym, "side": "SELL" if long else "BUY", "qty": abs(pos["qty"]), "type": "MARKET",
                  "product": pos["product"]})


def set_levels(symbol: str, stop: float | None, target: float | None) -> dict:
    with _lock:
        st = _load()
        pos = st["positions"].get(symbol.upper())
        if not pos:
            raise ApiException("NOT_FOUND", f"No practice position in {symbol.upper()}.")
        pos["stop"], pos["target"] = stop, target
        _save(st)
        return pos


def reset(cash: float | None = None) -> dict:
    with _lock:
        st = _blank(float(cash or (data.config().get("account") or {}).get("capital") or START_CASH))
        _save(st)
    return view()


def view() -> dict:
    with _lock:
        st = _load()
        quotes, session = _quotes(_symbols(st))
        if process(st, quotes, session):
            _save(st)
    positions, mtm = [], 0.0
    for sym, pos in sorted(st["positions"].items()):
        q = quotes.get(sym) or {}
        px = q.get("price")
        val = pos["qty"] * px if px is not None else pos["qty"] * pos["avg"]
        mtm += val
        positions.append({"symbol": sym, **pos, "price": px, "source": q.get("source"), "value": round(val, 2),
                          "pnl": round((px - pos["avg"]) * pos["qty"], 2) if px is not None else None})
    trades = st["trades"]
    wins = [t for t in trades if t["pnl"] > 0]
    equity = round(st["cash"] + mtm, 2)
    return {"cash": st["cash"], "start_cash": st["start_cash"], "equity": equity,
            "pnl": round(equity - st["start_cash"], 2), "charges": st.get("charges", 0.0), "positions": positions,
            "orders": list(reversed(st["orders"][-60:])), "trades": list(reversed(trades[-60:])),
            "stats": {"trades": len(trades), "wins": len(wins),
                      "win_rate": round(len(wins) / len(trades) * 100, 1) if trades else None,
                      "realised": round(sum(t["pnl"] for t in trades), 2)},
            "session": session, "created": st.get("created"),
            "note": "Practice account on live prices: nothing is sent to FYERS. Market orders fill at the live price plus "
                    "slippage, limit orders when the price reaches them; stops and targets close a position; intraday "
                    "positions are squared off from 15:20. FYERS' charges apply."}
