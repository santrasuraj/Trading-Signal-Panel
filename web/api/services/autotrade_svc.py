"""High-speed auto-trader, PRACTICE ONLY (GET /api/autotrade, POST /api/autotrade/settings, /stop, /reset): takes the
app's signals automatically, within about a second, in its own practice account. Nothing is ever sent to FYERS.

Every second while the market is open (only while this dashboard's server runs):
  * Intraday signals (data/results/intraday_signals.json, written every 5 minutes by `intraday_sync.py --signals`): a
    new signal that is still open is entered at the live price plus slippage, with the signal's own stop and target
    attached. "proven" mode takes only strategies whose backtest beat costs; "all" takes every one (each keeps its
    label). Live F&O OI build-ups (strategy key oi_buildup) can be switched separately.
  * Exits: the stop and the target on every price update (the practice account's rules), the strategy's own exit when
    the signal file shows it closed, and everything at 15:00 (the strategies' square-off for F&O stocks).
  * Limits: one position per stock, at most `max_positions` open and `max_trades_per_day`, each trade's notional at
    most capital x 2 / max_positions, no entry more than `max_late_min` minutes after the strategy's own entry bar, and
    no new entry once today's P&L falls below -`daily_loss_pct` of capital.
  * Index options: a BUY CALL / BUY PUT verdict of the last session (scanner/option_verdict.py) is bought - one lot -
    from 09:20 at the stored chain's ask, with the exact charges; marked from the chain and settled at expiry at NSE's
    official index close.
  * Daily strategies: the switch turns the practice bot (bot_svc) on for the working strategies (at most 5).

Speed path (when the FYERS live feed runs): ticks arrive over the ZeroMQ tick bus (tickbus_svc), so a held stock's stop
and target are checked on every tick, not once a second; new 5-minute bars reach the live signal engine (livesig_svc)
about a second after the close and the engine wakes this loop the moment its signals are ready; the engine's state is
kept in memory (written to data/autotrade.json on every change). latency_svc records each step's P50 / P95 / P99.

Each trade keeps how fast and how well it was filled: the signal's lag behind the strategy's own entry bar, the
engine's reaction (signal file written -> filled, in ms), the age of the price it filled on, and the slippage against
the signal's price. That is the record a backtest can't give: what the strategies earn when they are actually traded.
Speed through FYERS from a home PC is about 0.1-0.5 s a round trip; HFT firms co-located at the exchange react in
microseconds. Speed multiplies an edge - it doesn't create one.
"""
from __future__ import annotations

import copy
import json
import math
import os
import statistics
import threading
import time
import uuid
from datetime import datetime, timedelta

from . import bot_svc, clock, data, latency_svc, livesig_svc, quotes_svc, sim_svc, tickbus_svc
from ..errors import ApiException
from ..paths import P
from ..util import now_ist, today_ist

FILE = "autotrade.json"
LOOP_S = 1.0
OPTIONS_EVERY_S = 60                 # option chains are stored about once a minute
SQUARE_OFF = (15, 0)                 # the intraday strategies' square-off for F&O stocks (FYERS MIS cut-off 15:05)
START_AT = (9, 20)                   # the first 5-minute bar is complete; also when option buys start
OI_KEY = "oi_buildup"
LEVERAGE = 2.0                       # total intraday notional at most 2x capital (config intraday.leverage)
LOG_MAX, CLOSED_MAX = 300, 5000
DEFAULTS = {"on": False, "mode": "all", "intraday": True, "oi": True, "options": True, "daily": False,
            "max_positions": 10, "max_trades_per_day": 30, "daily_loss_pct": 2.0, "max_late_min": 10}
LIMITS = {"max_positions": (1, 50), "max_trades_per_day": (1, 200), "daily_loss_pct": (0.1, 20.0), "max_late_min": (1, 60)}
_lock = threading.RLock()
_thread: threading.Thread | None = None
_wake = threading.Event()             # set when new signals are ready: the loop runs at once instead of within 1 s
_cache: dict = {"path": None, "mtime": None, "st": None}   # the state in memory (file read only when it changed)
_held: frozenset = frozenset()       # the engine's open stocks, for the bus thread's quick check (replaced, not mutated)


def _path():
    return P.data / FILE


def _capital() -> float:
    return float((data.config().get("account") or {}).get("capital") or sim_svc.START_CASH)


def _blank() -> dict:
    return {"settings": dict(DEFAULTS), "account": sim_svc._blank(_capital()), "open": {}, "closed": [], "taken": [],
            "skipped": {}, "log": [], "day": today_ist().isoformat(), "options": {"open": [], "closed": [], "taken": []}}


def _mtime(p) -> int | None:
    try:
        return p.stat().st_mtime_ns
    except OSError:
        return None


def _load() -> dict:
    """The engine's state: the in-memory copy while data/autotrade.json is unchanged since this process last wrote or read
    it (the loop runs every second and on every tick of a held stock), else read from the file. Call under _lock."""
    p = _path()
    m = _mtime(p)
    if _cache["st"] is not None and _cache["path"] == str(p) and _cache["mtime"] == m:
        st = _cache["st"]
    else:
        try:
            st = json.loads(p.read_text(encoding="utf-8"))
            if not isinstance(st, dict):
                raise ValueError
        except (OSError, ValueError):
            st = _blank()
        for k, v in _blank().items():
            st.setdefault(k, v)
        st["settings"] = {**DEFAULTS, **(st.get("settings") or {})}
        _cache.update(path=str(p), mtime=m, st=st)
    if st.get("day") != today_ist().isoformat():           # a new day: today's dedupe lists start empty
        st.update(day=today_ist().isoformat(), taken=[], skipped={})
    return st


def _invalidate() -> None:
    """After an error half-way through a change: the next _load reads the last saved state again."""
    _cache.update(path=None, mtime=None, st=None)


def _refresh_held(st: dict) -> None:
    global _held
    _held = frozenset(st["open"])


def _save(st: dict) -> None:
    st.pop("_dirty", None)
    st["log"] = st["log"][-LOG_MAX:]
    st["closed"] = st["closed"][-CLOSED_MAX:]
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(st, default=str), encoding="utf-8")
    for i in range(21):                                    # Windows: a reader may hold the file for an instant
        try:
            tmp.replace(p)
            break
        except PermissionError:
            if i == 20:
                raise
            time.sleep(0.05)
    _cache.update(path=str(p), mtime=_mtime(p), st=st)
    _refresh_held(st)


def _event(st: dict, now: datetime, kind: str, text: str, **kw) -> dict:
    e = {"at": now.isoformat(timespec="seconds"), "kind": kind, "text": text, **kw}
    st["log"].append(e)
    st["_dirty"] = True
    return e


# ------------------------------------------------------------------ inputs: signals and quotes
def _signals(now: datetime) -> tuple[dict, float | None]:
    """Today's signals and when they were ready (epoch seconds): the live signal engine's (in memory, about a second
    after each bar) unless the signal file - the 5-minute task's - has later bars."""
    day = now.date().isoformat()
    path = P.results / "intraday_signals.json"
    try:
        mtime = path.stat().st_mtime
        f = json.loads(path.read_text(encoding="utf-8"))
        if str(f.get("generated_at") or "")[:10] != day:
            f, mtime = {}, None
    except (OSError, ValueError):
        f, mtime = {}, None
    live, ready = livesig_svc.latest()
    if live and str(live.get("generated_at") or "")[:10] == day and \
            str(live.get("bars_to") or "") >= str(f.get("bars_to") or ""):
        return live, ready
    return f, mtime


def _iso(epoch: float | None) -> str | None:
    return datetime.fromtimestamp(epoch, now_ist().tzinfo).isoformat(timespec="seconds") if epoch else None


def _quotes(syms: list[str]) -> dict[str, dict]:
    """Live quotes: the tick bus's latest tick (milliseconds old) where it has one, quotes_svc for the rest."""
    if not syms:
        return {}
    out, rest = {}, []
    for s in sorted(set(syms)):
        b = tickbus_svc.latest(s)
        if b is not None:
            out[s] = {"symbol": s, "price": b["price"], "source": "live", "bus": True,
                      "time": _iso(b.get("exch_ts")) or now_ist().isoformat(timespec="seconds")}
        else:
            rest.append(s)
    if rest:
        q = quotes_svc.quotes(rest, allow_network=True)
        out.update({x["symbol"]: x for x in q["quotes"]})
    return out


def _live(q: dict | None) -> float | None:
    if not q or q.get("price") is None or (q.get("source") or "") not in sim_svc.LIVE:
        return None
    return float(q["price"])


def _age_s(q: dict, now: datetime) -> float | None:
    try:
        t = datetime.fromisoformat(str(q.get("time")))
        if t.tzinfo is None:
            t = t.replace(tzinfo=now.tzinfo)
        return round(max((now - t).total_seconds(), 0.0), 1)
    except (TypeError, ValueError):
        return None


def _bar_start(now: datetime, hhmm: str) -> datetime | None:
    try:
        h, m = (int(x) for x in str(hhmm).split(":"))
        return now.replace(hour=h, minute=m, second=0, microsecond=0)
    except (TypeError, ValueError):
        return None


def _key(now: datetime, x: dict) -> str:
    return f"{now.date().isoformat()}|{x.get('strategy_key')}|{x.get('symbol')}|{x.get('entry_time')}"


# ------------------------------------------------------------------ P&L
def _unrealized(st: dict, quotes: dict) -> float:
    out = 0.0
    for sym, pos in st["account"]["positions"].items():
        if sym in st["open"]:
            px = _live(quotes.get(sym))
            if px is not None:
                out += (px - pos["avg"]) * pos["qty"]
    return out


def _today_pnl(st: dict, quotes: dict, now: datetime) -> float:
    day = now.date().isoformat()
    closed = sum(t["pnl_net"] for t in st["closed"] if str(t.get("closed_at", ""))[:10] == day)
    entry_charges = sum(r.get("entry_charges") or 0.0 for r in st["open"].values())
    return round(closed + _unrealized(st, quotes) - entry_charges, 2)


# ------------------------------------------------------------------ orders on the engine's own practice account
def _order(st: dict, sym: str, side: str, qty: int, px: float, stop=None, target=None) -> dict:
    o = {"id": uuid.uuid4().hex[:10], "symbol": sym, "side": side, "qty": int(qty), "type": "MARKET",
         "product": "INTRADAY", "limit_price": None, "stop": stop, "target": target, "status": "open",
         "created": now_ist().isoformat(timespec="seconds"), "ref_price": px, "trail": None, "targets": [],
         "breakeven": False, "by": "autotrade"}
    sim_svc._fill(st["account"], o, sim_svc._slip(px, side == "BUY", "INTRADAY"), "market")
    st["account"]["orders"].append(o)
    st["account"]["orders"] = st["account"]["orders"][-2000:]
    return o


def _close(st: dict, sym: str, quotes: dict, hint: str, now: datetime) -> bool:
    pos = st["account"]["positions"].get(sym)
    px = _live(quotes.get(sym))
    if not pos or px is None:
        if pos:
            _event(st, now, "warn", f"{sym}: no live price to close at ({hint}) - trying again next second")
        return False
    st["open"][sym]["exit_hint"] = hint
    _order(st, sym, "SELL" if pos["qty"] > 0 else "BUY", abs(pos["qty"]), px)
    return True


def _finalize(st: dict, now: datetime, events: list) -> None:
    """Engine positions the practice account no longer holds (stop, target, square-off or our own close): book them."""
    trades = st["account"]["trades"]
    for sym, rec in list(st["open"].items()):
        if sym in st["account"]["positions"]:
            continue
        mine = [t for t in trades[int(rec.get("n_trades") or 0):] if t["symbol"] == sym]   # booked after our entry
        if not mine:
            st["open"].pop(sym)
            continue
        t = mine[-1]
        gross = float(t["pnl"])
        charges = round((rec.get("entry_charges") or 0.0) + float(t.get("charges") or 0.0), 2)
        net = round(gross - charges, 2)
        reason = rec.get("exit_hint") or {"stop": "stop", "target": "target", "square-off": "square-off 15:20",
                                          "market": "closed"}.get(t.get("reason"), str(t.get("reason")))
        done = {**{k: v for k, v in rec.items() if k != "exit_hint"}, "exit": t["exit"], "exit_reason": reason,
                "closed_at": now.isoformat(timespec="seconds"), "pnl_gross": round(gross, 2), "charges": charges,
                "pnl_net": net, "ret_pct": round(net / (rec["fill"] * rec["qty"]) * 100, 3) if rec.get("fill") else None}
        st["closed"].append(done)
        st["open"].pop(sym)
        events.append(_event(st, now, "exit", f"{sym} {rec['side']} closed at {t['exit']:,.2f} ({reason}): "
                                               f"Rs {net:+,.0f} after charges", symbol=sym, strategy=rec["strategy_key"]))


# ------------------------------------------------------------------ one pass
def _entries(st: dict, sig: dict, mtime: float | None, quotes: dict, now: datetime, events: list) -> None:
    s = st["settings"]
    cap = float(st["account"].get("start_cash") or _capital())
    pnl = _today_pnl(st, quotes, now)
    trades_today = sum(1 for k in st["taken"])
    for x in sorted(sig.get("signals") or [], key=lambda v: str(v.get("entry_time"))):
        if x.get("state") != "open":
            continue
        is_oi = x.get("strategy_key") == OI_KEY
        if (is_oi and not s["oi"]) or (not is_oi and not s["intraday"]):
            continue
        if s["mode"] == "proven" and not x.get("proven"):
            continue
        key, sym = _key(now, x), str(x.get("symbol"))
        if key in st["taken"] or key in st["skipped"]:
            continue

        def skip(why: str, final: bool = True) -> None:
            if final:
                st["skipped"][key] = why
                _event(st, now, "skip", f"{sym} {x.get('strategy_name')}: {why}", symbol=sym,
                       strategy=x.get("strategy_key"))

        bar = _bar_start(now, x.get("entry_time"))
        late = (now - bar).total_seconds() / 60 if bar else None
        if late is not None and late > s["max_late_min"]:
            skip(f"too late: the strategy entered at {x.get('entry_time')}, {late:.0f} min ago "
                 f"(max {s['max_late_min']})")
            continue
        if sym in st["account"]["positions"] or sym in st["open"]:
            skip("already holding this stock (one position per stock)")
            continue
        if len(st["open"]) >= s["max_positions"]:
            skip(f"{s['max_positions']} positions already open")
            continue
        if trades_today >= s["max_trades_per_day"]:
            skip(f"{s['max_trades_per_day']} trades already today")
            continue
        if pnl <= -cap * s["daily_loss_pct"] / 100:
            skip(f"daily loss stop: today Rs {pnl:,.0f} (limit -{s['daily_loss_pct']:g}% of capital)")
            continue
        q = quotes.get(sym)
        px = _live(q)
        if px is None:
            continue                                       # no price yet: try again next second (until late)
        side = 1 if x.get("side") == "LONG" else -1
        stop, target = x.get("stop"), x.get("target")
        if stop is not None and side * (px - float(stop)) <= 0:
            skip(f"price {px:,.2f} already beyond the stop {float(stop):,.2f}")
            continue
        if target is not None and side * (float(target) - px) <= 0:
            skip(f"price {px:,.2f} already beyond the target {float(target):,.2f}")
            continue
        lev = float((data.config().get("intraday") or {}).get("leverage", LEVERAGE))
        qty = min(int(x.get("qty") or 0), int(cap * lev / s["max_positions"] / px))
        if qty < 1:
            skip("position too small for the per-trade cap")
            continue
        seen = time.time()
        n_trades = len(st["account"]["trades"])
        o = _order(st, sym, "BUY" if side > 0 else "SELL", qty, px, stop, target)
        filled = time.time()
        if mtime:
            latency_svc.record("signal_to_fill", filled - mtime)
        if bar:
            latency_svc.record("decision_to_fill", filled - bar.timestamp())
        entry = float(x.get("entry") or px)
        gen = sig.get("generated_at")
        try:
            gen_dt = datetime.fromisoformat(str(gen))
        except (TypeError, ValueError):
            gen_dt = None
        rec = {"key": key, "symbol": sym, "strategy_key": x.get("strategy_key"), "strategy_name": x.get("strategy_name"),
               "strategy_status": x.get("strategy_status") or ("working" if x.get("proven") else "untested"),
               "proven": bool(x.get("proven")), "detail": x.get("detail"), "side": "LONG" if side > 0 else "SHORT",
               "qty": qty, "signal_entry": round(entry, 2), "signal_time": x.get("entry_time"), "stop": stop,
               "target": target, "fill": o["fill_price"], "opened_at": now.isoformat(timespec="seconds"),
               "entry_charges": o["charges"], "source": (q or {}).get("source"), "quote_age_s": _age_s(q or {}, now),
               "slippage_bps": round(side * (o["fill_price"] / entry - 1) * 1e4, 1) if entry else None,
               "signal_lag_s": round((gen_dt - bar).total_seconds(), 1) if gen_dt and bar else None,
               "react_ms": round((filled - mtime) * 1000) if mtime else None,
               "decision_to_fill_s": round(filled - bar.timestamp(), 2) if bar else None,
               "bus": bool((q or {}).get("bus")),
               "order_ms": round((filled - seen) * 1000, 1), "signal_file_at": gen, "n_trades": n_trades}
        st["open"][sym] = rec
        st["taken"].append(key)
        trades_today += 1
        events.append(_event(st, now, "entry", f"{sym} {rec['side']} {qty} at {o['fill_price']:,.2f} "
                                                f"({x.get('strategy_name')}, {rec['strategy_status']}); signal "
                                                f"{entry:,.2f}, slippage {rec['slippage_bps']:+.1f} bps",
                             symbol=sym, strategy=x.get("strategy_key")))


def _strategy_exits(st: dict, sig: dict, quotes: dict, now: datetime) -> None:
    closed = {(x.get("strategy_key"), x.get("symbol"), x.get("entry_time")): x for x in sig.get("signals") or []
              if x.get("state") == "closed"}
    for sym, rec in list(st["open"].items()):
        x = closed.get((rec["strategy_key"], sym, rec["signal_time"]))
        if x and sym in st["account"]["positions"] and not rec.get("exit_hint"):
            _close(st, sym, quotes, f"strategy exit ({x.get('reason')})", now)


def tick(now: datetime | None = None) -> dict:
    """One pass of the engine (the loop calls it every second and when new signals are ready; tests call it)."""
    now = now or now_ist()
    sess = clock.market_clock()["session"]
    events: list = []
    with _lock:
        try:
            st = _load()
            s = st["settings"]
            beat = st.get("last_loop")
            st["last_loop"] = now.isoformat(timespec="seconds")
            if st.get("session") != sess or not beat or (now - datetime.fromisoformat(beat)).total_seconds() >= 10:
                st["_dirty"] = True                        # a heartbeat for the page about every 10 s
            st["session"] = sess
            if s["options"] or st["options"]["open"]:
                _options_pass(st, now, sess, events)
            if sess != "open":
                if st.get("_dirty"):
                    _save(st)
                return {"ran": False, "session": sess, "events": events}
            sig, mtime = _signals(now) if s["on"] else ({}, None)
            if st.get("signals_at") != sig.get("generated_at"):
                st["signals_at"], st["signals_engine"] = sig.get("generated_at"), sig.get("engine")
                st["_dirty"] = True
            syms = set(st["account"]["positions"]) | set(st["open"])
            if s["on"] and (now.hour, now.minute) >= START_AT:
                syms |= {str(x.get("symbol")) for x in sig.get("signals") or [] if x.get("state") == "open"}
        except Exception:
            _invalidate()
            raise
    quotes = _quotes(sorted(syms))          # outside the lock: a slow price source never holds up tick-level exits
    with _lock:
        try:
            st = _load()
            s = st["settings"]
            srcs = {q.get("source") for q in quotes.values() if q.get("price") is not None}
            feed = "live" if "live" in srcs else "fyers" if "fyers" in srcs else "yahoo" if "yahoo" in srcs else None
            if st.get("feed") != feed:
                st["feed"], st["_dirty"] = feed, True
            if sim_svc.process(st["account"], quotes, sess):          # stops / targets on this price update
                st["_dirty"] = True
            _finalize(st, now, events)
            if s["on"]:
                _strategy_exits(st, sig, quotes, now)
                if (now.hour, now.minute) >= SQUARE_OFF:
                    for sym in list(st["open"]):
                        if not st["open"][sym].get("exit_hint"):
                            _close(st, sym, quotes, "square-off 15:00", now)
                elif (now.hour, now.minute) >= START_AT:
                    _entries(st, sig, mtime, quotes, now, events)
                _finalize(st, now, events)
            if st.get("_dirty"):
                _save(st)
            else:
                _refresh_held(st)
        except Exception:
            _invalidate()
            raise
    return {"ran": True, "session": sess, "events": events}


def on_tick(sym: str, q: dict) -> None:
    """The tick bus, on every tick (bus thread): a stock the engine holds has its stop / target checked on this very
    price - the practice account's own rules (sim_svc.process) - instead of on the next once-a-second pass."""
    if sym not in _held:
        return
    with _lock:
        try:
            st = _load()
            if st.get("session") != "open" or sym not in st["account"]["positions"]:
                return
            quote = {"symbol": sym, "price": q["price"], "source": "live",
                     "time": _iso(q.get("exch_ts")) or now_ist().isoformat(timespec="seconds")}
            if not sim_svc.process(st["account"], {sym: quote}, "open"):
                return
            closed = sym not in st["account"]["positions"]
            _finalize(st, now_ist(), [])
            if closed and q.get("bus_ts"):
                latency_svc.record("tick_to_exit", time.time() - q["bus_ts"])
            _save(st)
        except Exception:
            _invalidate()
            raise


def wake() -> None:
    """New signals are ready (the live signal engine): run the next pass now."""
    _wake.set()


# ------------------------------------------------------------------ index options (one lot per BUY verdict)
def _options_pass(st: dict, now: datetime, sess: str, events: list) -> None:
    from scanner import option_verdict as ov
    from scanner.intraday.fyers_sync import last_complete_day
    from . import options_svc
    book = st["options"]
    last = book.get("last_pass")
    if last and (now - datetime.fromisoformat(last)).total_seconds() < OPTIONS_EVERY_S:
        return
    book["last_pass"] = now.isoformat(timespec="seconds")
    st["_dirty"] = True
    today = now.date().isoformat()
    # settle: expiry passed - NSE's official index close on the expiry day
    if any(p["expiry"] < today for p in book["open"]):
        ih = ov.load_index_history()
        for p in [x for x in book["open"] if x["expiry"] < today]:
            s = ov.index_close(p["symbol"], ih, data.store_close())
            done = s is not None and len(s.loc[:p["expiry"]].dropna())
            if not done:
                continue
            settle = float(s.loc[:p["expiry"]].dropna().iloc[-1])
            pay = max(settle - p["strike"], 0) if p["side"] == "ce" else max(p["strike"] - settle, 0)
            per_unit = float(ov.expiry_value(pay, p["lot"]))
            net = round((per_unit - p["cost_unit"]) * p["lot"], 2)
            book["closed"].append({**p, "settle": round(settle, 2), "value_unit": round(per_unit, 2), "pnl_net": net,
                                   "closed_at": now.isoformat(timespec="seconds"), "exit_reason": "expiry"})
            book["open"].remove(p)
            events.append(_event(st, now, "exit", f"{p['symbol']} {p['strike']:,.0f} {p['side'].upper()} settled at "
                                                   f"{settle:,.2f}: Rs {net:+,.0f} after charges", symbol=p["symbol"],
                                 strategy="options_verdict"))
    if sess != "open":
        return
    # mark the open positions from the stored chain (bid, else last price)
    for p in book["open"]:
        try:
            c = options_svc.chain(p["symbol"], p["expiry"], 5)
        except ApiException:
            continue
        row = next((r for r in c["rows"] if r.get("strike") == p["strike"]), None)
        leg = (row or {}).get(p["side"]) or {}
        mark = leg.get("bid") or leg.get("ltp")
        if mark:
            p.update(mark=float(mark), marked_at=c["time"], value_net=round((float(mark) - p["cost_unit"]) * p["lot"], 2))
    if not st["settings"]["options"] or (now.hour, now.minute) < START_AT:
        return
    prev = last_complete_day().isoformat()
    for r in ov.load_journal():
        if (r.get("verdict") not in ("BUY_CALL", "BUY_PUT") or r.get("symbol") not in ov.INDEX_COLUMN
                or r.get("day") != prev or str(r.get("expiry")) <= today or r["id"] in book["taken"]):
            continue
        try:
            c = options_svc.chain(r["symbol"], r["expiry"], 5)
        except ApiException:
            continue
        if str(c.get("time", ""))[:10] != today:
            continue                                       # wait for today's chain
        row = next((x for x in c["rows"] if x.get("strike") == r.get("strike")), None)
        leg = (row or {}).get(r.get("side")) or {}
        px = leg.get("ask") if (leg.get("ask") or 0) > 0 else leg.get("ltp")
        lot = r.get("lot") or options_svc._lot(r["symbol"])
        if not px or not lot:
            continue
        cost_unit = ov.buy_cost(float(px), int(lot))
        pos = {"id": r["id"], "symbol": r["symbol"], "expiry": r["expiry"], "side": r["side"], "strike": r["strike"],
               "lot": int(lot), "premium": round(float(px), 2), "cost_unit": round(cost_unit, 4),
               "verdict_day": r["day"], "verdict_premium": r.get("premium"), "opened_at": now.isoformat(timespec="seconds"),
               "chain_time": c["time"]}
        book["open"].append(pos)
        book["taken"].append(r["id"])
        events.append(_event(st, now, "entry", f"{r['symbol']} {r['strike']:,.0f} {r['side'].upper()} expiry "
                                                f"{r['expiry']}: bought 1 lot of {lot} at {px:,.2f} (verdict of {r['day']})",
                             symbol=r["symbol"], strategy="options_verdict"))


# ------------------------------------------------------------------ settings, kill switch, view
def settings(body: dict) -> dict:
    with _lock:
        _invalidate()                                      # a settings change always starts from the saved state
        st = _load()
        s = st["settings"]
        for k in ("on", "intraday", "oi", "options", "daily"):
            if k in body and body[k] is not None:
                s[k] = bool(body[k])
        if body.get("mode") in ("all", "proven"):
            s["mode"] = body["mode"]
        for k, (lo, hi) in LIMITS.items():
            if body.get(k) is not None:
                v = float(body[k])
                if not lo <= v <= hi:
                    raise ApiException("VALIDATION", f"{k} must be between {lo:g} and {hi:g}.")
                s[k] = int(v) if isinstance(DEFAULTS[k], int) else v
        _event(st, now_ist(), "settings", "Settings: " + ", ".join(f"{k}={v}" for k, v in s.items()))
        _save(st)
    if "daily" in body and body["daily"] is not None:
        _daily_bot(bool(body["daily"]))
    return view()


def _daily_bot(on: bool) -> None:
    """The daily strategies' orders through the existing practice bot: on = the working strategies (at most 5)."""
    working = [x["key"] for x in (data.latest() or {}).get("strategies") or [] if x.get("status") == "working"]
    cap = bot_svc._load().get("capital") or _capital()
    bot_svc.settings(working[:bot_svc.MAX_STRATEGIES] if on else [], float(cap))


def stop_all() -> dict:
    """Kill switch: switch the engine off and close every engine position at the live price (market open)."""
    now = now_ist()
    with _lock:
        _invalidate()
        st = _load()
        st["settings"]["on"] = False
        quotes = _quotes(sorted(st["open"]))
        n = 0
        if clock.market_clock()["session"] == "open":
            for sym in list(st["open"]):
                n += _close(st, sym, quotes, "kill switch", now)
        _finalize(st, now, [])
        _event(st, now, "kill", f"Stopped: engine off, {n} position(s) closed")
        _save(st)
    return view()


def reset() -> dict:
    """A new practice account for the engine (the record of closed trades stays)."""
    with _lock:
        _invalidate()
        st = _load()
        if st["open"]:
            raise ApiException("VALIDATION", "Close the engine's open positions first (Stop and close all).")
        st["account"] = sim_svc._blank(_capital())
        _event(st, now_ist(), "reset", f"Practice account reset to Rs {_capital():,.0f}")
        _save(st)
    return view()


def _median(xs: list) -> float | None:
    xs = [x for x in xs if x is not None and not (isinstance(x, float) and math.isnan(x))]
    return round(float(statistics.median(xs)), 1) if xs else None


def _summary(rows: list[dict]) -> dict:
    n = len(rows)
    wins = sum(1 for r in rows if r["pnl_net"] > 0)
    return {"trades": n, "wins": wins, "win_rate": round(wins / n * 100, 1) if n else None,
            "pnl_net": round(sum(r["pnl_net"] for r in rows), 2), "charges": round(sum(r["charges"] for r in rows), 2),
            "slippage_bps": _median([r.get("slippage_bps") for r in rows]),
            "signal_lag_s": _median([r.get("signal_lag_s") for r in rows]),
            "react_ms": _median([r.get("react_ms") for r in rows]),
            "quote_age_s": _median([r.get("quote_age_s") for r in rows])}


def speed() -> dict:
    """The live path's latency (P50 / P95 / P99), the tick bus and the live signal engine."""
    return {"latency": latency_svc.summary(), "bus": tickbus_svc.status(), "engine": livesig_svc.status()}


def view() -> dict:
    now = now_ist()
    with _lock:
        st = copy.deepcopy(_load())                        # the loop keeps changing the live copy
    acct = st["account"]
    quotes: dict = {}
    if st["open"] and clock.market_clock()["session"] == "open":
        try:
            quotes = quotes_svc.quotes(sorted(st["open"]), allow_network=False)
            quotes = {x["symbol"]: x for x in quotes["quotes"]}
        except Exception:
            quotes = {}
    positions = []
    for sym, rec in st["open"].items():
        pos = acct["positions"].get(sym) or {}
        last = _live(quotes.get(sym))
        unreal = round((last - pos["avg"]) * pos["qty"], 2) if last is not None and pos else None
        positions.append({**{k: rec.get(k) for k in ("symbol", "strategy_key", "strategy_name", "strategy_status",
                                                      "proven", "side", "qty", "fill", "signal_entry", "signal_time",
                                                      "stop", "target", "opened_at", "slippage_bps", "react_ms",
                                                      "signal_lag_s", "detail")},
                          "stop": pos.get("stop", rec.get("stop")), "target": pos.get("target", rec.get("target")),
                          "last": last, "unrealized": unreal})
    day = now.date().isoformat()
    today = [r for r in st["closed"] if str(r.get("closed_at", ""))[:10] == day]
    by: dict[str, list] = {}
    for r in st["closed"]:
        by.setdefault(r["strategy_key"], []).append(r)
    record = sorted(({"strategy_key": k, "strategy_name": v[-1]["strategy_name"], "strategy_status": v[-1].get("strategy_status"),
                      **_summary(v)} for k, v in by.items()), key=lambda r: -r["pnl_net"])
    equity = acct["cash"] + sum((_live(quotes.get(s)) or p["avg"]) * p["qty"] for s, p in acct["positions"].items())
    try:
        daily = bot_svc.view()
        daily = {"on": any(x["on"] for x in daily["strategies"]),
                 "strategies": [{"key": x["key"], "name": x["name"], "on": x["on"], "status": x["status"]}
                                for x in daily["strategies"] if x["on"]],
                 "last_run": daily.get("last_run")}
    except Exception:
        daily = {"on": False, "strategies": [], "last_run": None}
    return {"settings": st["settings"], "running": bool(_thread and _thread.is_alive()),
            "session": clock.market_clock()["session"], "feed": st.get("feed"), "last_loop": st.get("last_loop"),
            "signals_at": st.get("signals_at"), "capital": acct.get("start_cash"), "cash": round(acct["cash"], 2),
            "equity": round(equity, 2), "today_pnl": round(sum(r["pnl_net"] for r in today), 2),
            "positions": positions, "trades_today": list(reversed(today))[:200],
            "skipped_today": [{"key": k, "why": v} for k, v in list(st["skipped"].items())[-200:]],
            "today": _summary(today), "all_time": _summary(st["closed"]), "record": record,
            "options": {"open": st["options"]["open"], "closed": list(reversed(st["options"]["closed"]))[:100]},
            "signals_engine": st.get("signals_engine"), "speed": speed(),
            "daily": daily, "log": list(reversed(st["log"]))[:150], "note": __doc__.split("\n\n")[0].replace("\n", " ")}


def _loop() -> None:
    idle_at = 0.0
    while True:
        t0 = time.monotonic()
        try:
            with _lock:
                st = _load()
                s = st["settings"]
                busy = s["on"] or bool(st["open"])
                options = s["options"] or bool(st["options"]["open"])
            if busy:
                tick()                                     # every second: entries, stops, targets, exits
                latency_svc.record("engine_pass", time.monotonic() - t0)
            elif options and t0 - idle_at >= OPTIONS_EVERY_S:
                idle_at = t0
                tick()                                     # off: only the option book, once a minute
        except Exception:                                  # never let the loop die
            pass
        _wake.wait(max(0.05, LOOP_S - (time.monotonic() - t0)))   # new signals cut the wait short
        _wake.clear()


def start() -> None:
    """Start the once-a-second engine in this server (idempotent)."""
    global _thread
    tickbus_svc.on_tick(on_tick)                           # stops / targets on every tick of a held stock
    livesig_svc.on_signals(lambda _out: wake())            # new signals: trade them now
    if _thread and _thread.is_alive():
        return
    _thread = threading.Thread(target=_loop, name="autotrade", daemon=True)
    _thread.start()
