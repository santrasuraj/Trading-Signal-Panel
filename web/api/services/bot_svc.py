"""Practice bot (GET /api/bot, POST /api/bot/settings, POST /api/bot/run): forward-tests strategies in the PRACTICE
account on live prices. Nothing is ever sent to FYERS.

For each strategy you switch on, the bot mirrors the strategy's model portfolio from each scan (latest.json
`positions`): a stock the model buys after the bot started is bought in the practice account at the live price
(market order, slippage and FYERS' charges as in sim_svc); a stock the model no longer holds is sold. Stocks the
model already held when you switched the bot on are left out (joining late is a different trade; the Today page
tests it separately). Size: the bot's capital for the strategy / the strategy's number of positions.

The bot checks every minute while the market is open (from 09:20, after the opening auction's noise), only while
this dashboard's server runs. Its own lots and orders are kept in data/practice_bot.json, so a manual practice trade
in the same stock never confuses it. The record compares its fills with the model's prices: the slippage and timing
cost a backtest can't show.
"""
from __future__ import annotations

import json
import threading
import time

from . import clock, data, sim_svc
from ..errors import ApiException
from ..paths import P
from ..util import now_ist, num

FILE = "practice_bot.json"
START_AT = (9, 20)
CHECK_S = 60
MAX_STRATEGIES = 5
_lock = threading.Lock()
_thread: threading.Thread | None = None


def _path():
    return P.data / FILE


def _load() -> dict:
    try:
        v = json.loads(_path().read_text(encoding="utf-8"))
        return v if isinstance(v, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(st: dict) -> None:
    st["log"] = (st.get("log") or [])[-2000:]
    tmp = _path().with_suffix(".tmp")
    tmp.write_text(json.dumps(st, indent=1, default=str), encoding="utf-8")
    tmp.replace(_path())


def _strategies() -> dict[str, dict]:
    lt = data.latest() or {}
    return {s["key"]: s for s in lt.get("strategies") or [] if s.get("key")}


def settings(enabled: list[str], capital: float) -> dict:
    """Switch strategies on or off. A strategy switched on now remembers the model's current positions (not bought)."""
    strats = _strategies()
    bad = [k for k in enabled if k not in strats]
    if bad:
        raise ApiException("VALIDATION", f"Unknown strategy: {', '.join(bad)}.")
    if len(enabled) > MAX_STRATEGIES:
        raise ApiException("VALIDATION", f"At most {MAX_STRATEGIES} strategies at once.")
    with _lock:
        st = _load()
        bots = st.get("bots") or {}
        for k in enabled:
            if k not in bots or not bots[k].get("on"):
                held = sorted({p["symbol"] for p in strats[k].get("positions") or [] if p.get("symbol")})
                bots[k] = {**(bots.get(k) or {}), "on": True, "since": now_ist().isoformat(timespec="seconds"),
                           "skip": held, "lots": (bots.get(k) or {}).get("lots") or {}}
        for k, b in bots.items():
            if k not in enabled:
                b["on"] = False
        st.update(bots=bots, capital=float(capital))
        _save(st)
    return view()


def _quote_session(syms: list[str]):
    return sim_svc._quotes(syms)


def reconcile(force: bool = False) -> dict:
    """One pass: the orders that bring each running strategy's practice lots in line with its model portfolio."""
    now = now_ist()
    sess = clock.market_clock()["session"]
    if sess != "open" or (now.hour, now.minute) < START_AT:
        return {"ran": False, "why": "The bot trades from 09:20 while the market is open."}
    lt = data.latest() or {}
    strats = _strategies()
    with _lock:
        st = _load()
        bots = {k: b for k, b in (st.get("bots") or {}).items() if b.get("on")}
        if not bots:
            return {"ran": False, "why": "No strategy is switched on."}
        scan = str(lt.get("generated_at") or "")
        if not force and st.get("last_scan_done") == scan and not st.get("pending"):
            return {"ran": False, "why": "Already in line with the last scan."}
    capital = float(st.get("capital") or 100_000)
    per_bot = capital / max(len(bots), 1)
    done, failed = [], []
    for key, b in bots.items():
        s = strats.get(key)
        if not s:
            continue
        want = {p["symbol"]: p for p in s.get("positions") or [] if p.get("symbol") and p["symbol"] not in set(b.get("skip") or [])}
        lots = b.get("lots") or {}
        slots = max(int(s.get("max_positions") or len(want) or 1), 1)
        # exits first (frees practice cash), then entries
        for sym in [x for x in lots if x not in want]:
            qty = int(lots[sym]["qty"])
            try:
                o = sim_svc.place({"symbol": sym, "side": "SELL", "qty": qty, "type": "MARKET", "product": "CNC"})
                done.append(_log(st, key, sym, "SELL", qty, o, None))
                lots.pop(sym)
            except ApiException as e:
                failed.append(f"{key} sell {sym}: {e.message}")
        for sym, p in want.items():
            if sym in lots:
                continue
            q, _ = _quote_session([sym])
            px = num((q.get(sym) or {}).get("price"))
            if not px:
                failed.append(f"{key} buy {sym}: no live price yet")
                continue
            qty = int((per_bot / slots) // px)
            if qty < 1:
                failed.append(f"{key} buy {sym}: ₹{per_bot / slots:,.0f} buys less than one share at ₹{px:,.2f}")
                b.setdefault("skip", []).append(sym)
                continue
            try:
                o = sim_svc.place({"symbol": sym, "side": "BUY", "qty": qty, "type": "MARKET", "product": "CNC",
                                   "stop": num(p.get("stop"))})
                lots[sym] = {"qty": qty, "price": o.get("fill_price"), "at": o.get("filled_at"),
                             "model_price": num(p.get("entry_price")), "model_date": p.get("entry_date")}
                done.append(_log(st, key, sym, "BUY", qty, o, num(p.get("entry_price"))))
            except ApiException as e:
                failed.append(f"{key} buy {sym}: {e.message}")
        b["lots"] = lots
    with _lock:
        cur = _load()
        for k, b in bots.items():
            if k in (cur.get("bots") or {}):
                cur["bots"][k]["lots"] = b.get("lots") or {}
                cur["bots"][k]["skip"] = b.get("skip") or []
        cur["log"] = (cur.get("log") or []) + [x for x in done if x]
        cur["last_scan_done"] = str(lt.get("generated_at") or "")
        cur["pending"] = bool(failed)
        cur["last_run"] = {"at": now.isoformat(timespec="seconds"), "orders": len(done), "problems": failed[:20]}
        _save(cur)
    return {"ran": True, "orders": len(done), "problems": failed}


def _log(st: dict, key: str, sym: str, side: str, qty: int, o: dict, model_price: float | None) -> dict:
    fill = num(o.get("fill_price"))
    return {"at": o.get("filled_at"), "strategy": key, "symbol": sym, "side": side, "qty": qty, "price": fill,
            "charges": o.get("charges"), "model_price": model_price,
            "slip_pct": round((fill / model_price - 1) * 100, 2) if fill and model_price and side == "BUY" else None}


def record(st: dict) -> dict[str, dict]:
    """Per strategy: closed round trips (FIFO from the bot's own log), open lots marked live, slippage vs the model."""
    out: dict[str, dict] = {}
    open_syms = sorted({s for b in (st.get("bots") or {}).values() for s in (b.get("lots") or {})})
    q, _ = _quote_session(open_syms) if open_syms else ({}, None)
    for key, b in (st.get("bots") or {}).items():
        lots: dict[str, list] = {}
        realised, trades, wins, charges = 0.0, 0, 0, 0.0
        for e in [x for x in st.get("log") or [] if x.get("strategy") == key]:
            charges += float(e.get("charges") or 0)
            if e["side"] == "BUY":
                lots.setdefault(e["symbol"], []).append([e["qty"], e["price"] or 0.0])
            else:
                left = e["qty"]
                pnl = 0.0
                for lot in lots.get(e["symbol"], []):
                    take = min(left, lot[0])
                    pnl += take * ((e["price"] or 0.0) - lot[1])
                    lot[0] -= take
                    left -= take
                    if not left:
                        break
                lots[e["symbol"]] = [x for x in lots.get(e["symbol"], []) if x[0] > 0]
                realised += pnl
                trades += 1
                wins += pnl > 0
        unreal = 0.0
        for sym, lot in (b.get("lots") or {}).items():
            px = num((q.get(sym) or {}).get("price"))
            if px and lot.get("price"):
                unreal += (px - float(lot["price"])) * int(lot["qty"])
        slips = [x["slip_pct"] for x in st.get("log") or [] if x.get("strategy") == key and x.get("slip_pct") is not None]
        out[key] = {"realised": round(realised, 2), "unrealised": round(unreal, 2), "charges": round(charges, 2),
                    "net": round(realised + unreal - charges, 2), "closed": trades,
                    "win_rate": round(wins / trades * 100, 1) if trades else None,
                    "avg_entry_vs_model_pct": round(sum(slips) / len(slips), 2) if slips else None,
                    "open": [{"symbol": s, **lot, "price_now": num((q.get(s) or {}).get("price"))}
                             for s, lot in sorted((b.get("lots") or {}).items())]}
    return out


def view() -> dict:
    st = _load()
    strats = _strategies()
    rec = record(st)
    bots = st.get("bots") or {}
    rows = []
    for k, s in strats.items():
        b = bots.get(k) or {}
        rows.append({"key": k, "name": s.get("name"), "status": s.get("status"), "horizon": s.get("horizon"),
                     "max_positions": s.get("max_positions"), "on": bool(b.get("on")), "since": b.get("since"),
                     "skipped": len(b.get("skip") or []), "record": rec.get(k)})
    rows.sort(key=lambda r: (not r["on"], r["status"] != "working", r["name"] or ""))
    return {"capital": st.get("capital") or 100_000, "strategies": rows, "last_run": st.get("last_run"),
            "log": list(reversed((st.get("log") or [])[-100:])), "running": bool(_thread and _thread.is_alive()),
            "session": clock.market_clock()["session"], "note": __doc__.split("\n\n")[1].replace("\n", " ")}


def _loop() -> None:
    while True:
        try:
            if any(b.get("on") for b in (_load().get("bots") or {}).values()):
                reconcile()
        except Exception:                          # never let the loop die
            pass
        time.sleep(CHECK_S)


def start() -> None:
    """Start the once-a-minute check in this server (idempotent)."""
    global _thread
    if _thread and _thread.is_alive():
        return
    _thread = threading.Thread(target=_loop, name="practice-bot", daemon=True)
    _thread.start()
