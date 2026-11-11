"""Watchlists and price alerts: the user's own lists, shared by the dashboard and the live service.

  data/watchlists.json    {"lists": [{"name": "Main", "symbols": ["RELIANCE", ...]}]}
  data/alerts.json        {"alerts": [{id, symbol, kind, value, note, created, active, fired_at, fired_price, source}]}
  data/alerts_fired.jsonl one line per fired alert (newest last)

Alert kinds - on every live quote: "above" / "below" (price at or above / below the level), "change_above" /
"change_below" (day change %), "line_above" / "line_below" (price crosses a trendline drawn on the chart: its level
today, from its two points). With the live price on the daily history (rule_alerts.py, every few minutes):
"rsi_above" / "rsi_below" (RSI 14), "sma_above" / "sma_below" (price above / below its N-day average, value = N),
"scan_hit" (a saved scan gets a stock it didn't have; symbol "ALL", ref = the scan's id) and "pattern" (a candle
pattern with a tested edge appears on the stock's daily chart, checked after each scan). Alerts fire once: a fired
alert turns inactive (re-arm it to use it again).

They are checked on every live quote: by the live service on each FYERS tick batch (twice a second, even with no
dashboard open) and by the dashboard's price stream on REST / Yahoo quotes. A file lock and the one-shot rule make
sure an alert fires once even though two processes check it. A quote from Yahoo is ~15 minutes late, and the fired
alert says so. Watchlist and alert symbols are streamed by the live service right after the screen's own symbols.
"""
from __future__ import annotations

import json
import re
import threading
import uuid
from datetime import datetime
from pathlib import Path

from . import settings
from .settings import ist_now

WATCH_FILE_NAME = "watchlists.json"
ALERTS_FILE_NAME = "alerts.json"
FIRED_FILE_NAME = "alerts_fired.jsonl"
PRICE_KINDS = ("above", "below", "change_above", "change_below", "line_above", "line_below")   # every live quote
RULE_KINDS = ("rsi_above", "rsi_below", "sma_above", "sma_below", "scan_hit", "pattern")       # rule_alerts.py
KINDS = PRICE_KINDS + RULE_KINDS
SMA_PERIODS = (10, 20, 50, 100, 200)
ALL = "ALL"                                    # the "symbol" of a scan alert (any stock)
LIVE_SOURCES = ("live", "fyers", "yahoo")      # a stored close never fires an alert
MAX_LISTS, MAX_PER_LIST, MAX_ALERTS = 20, 200, 500
SYMBOL = re.compile(r"^[A-Z0-9][A-Z0-9&_.-]{0,24}$")
DEFAULT = {"lists": [{"name": "Main", "symbols": []}]}

DATA_DIR: Path | None = None           # web/api/paths.configure() repoints it (tests); default settings.DATA_DIR
_cache: dict[str, tuple[tuple, object]] = {}
_cache_lock = threading.Lock()


def data_dir() -> Path:
    return DATA_DIR or settings.DATA_DIR


def _key(p: Path) -> tuple:
    try:
        st = p.stat()
        return (st.st_mtime_ns, st.st_size)
    except OSError:
        return (None, None)


def _read(p: Path, default):
    """JSON file, re-read only when it changes (the live service checks alerts twice a second)."""
    k = _key(p)
    with _cache_lock:
        hit = _cache.get(str(p))
        if hit and hit[0] == k:
            return hit[1]
    try:
        val = json.loads(p.read_text(encoding="utf-8")) if k[0] is not None else default
    except Exception:
        return hit[1] if hit else default            # mid-replace: the last good read
    with _cache_lock:
        _cache[str(p)] = (k, val)
    return val


def _write(p: Path, obj) -> None:
    from .intraday.data import _replace           # retried atomic rename (Windows readers hold files briefly)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(f".{uuid.uuid4().hex[:8]}.tmp")
    tmp.write_text(json.dumps(obj, indent=1), encoding="utf-8")
    _replace(tmp, p)


def _lock(name: str):
    from .intraday.data import FileLock
    return FileLock(data_dir() / f".{name}.lock", timeout=5.0)


def clean_symbols(symbols) -> list[str]:
    out = []
    for s in symbols or []:
        s = str(s).strip().upper()
        if SYMBOL.match(s) and s not in out:
            out.append(s)
    return out


# ---- watchlists ---------------------------------------------------------------------------------------------------

def watchlists() -> dict:
    v = _read(data_dir() / WATCH_FILE_NAME, DEFAULT)
    lists = [{"name": str(x.get("name") or "List")[:40], "symbols": clean_symbols(x.get("symbols"))[:MAX_PER_LIST]}
             for x in (v.get("lists") or []) if isinstance(x, dict)][:MAX_LISTS]
    return {"lists": lists or [dict(DEFAULT["lists"][0])]}


def save_watchlists(lists: list[dict]) -> dict:
    clean, names = [], set()
    for x in lists[:MAX_LISTS]:
        name = str(x.get("name") or "").strip()[:40] or f"List {len(clean) + 1}"
        if name.lower() in names:
            raise ValueError(f"Two lists are called {name!r}.")
        names.add(name.lower())
        clean.append({"name": name, "symbols": clean_symbols(x.get("symbols"))[:MAX_PER_LIST]})
    out = {"lists": clean or [dict(DEFAULT["lists"][0])]}
    with _lock("watchlists"):
        _write(data_dir() / WATCH_FILE_NAME, out)
    return out


# ---- alerts -------------------------------------------------------------------------------------------------------

def alerts() -> list[dict]:
    return list((_read(data_dir() / ALERTS_FILE_NAME, {"alerts": []}).get("alerts")) or [])


def line_level(a: dict, b: dict, day) -> float:
    """A trendline's price on `day` (straight line through its two points, by calendar days, extended both ways)."""
    from datetime import date as _d
    ta, tb, td = (_d.fromisoformat(str(x)[:10]) for x in (a["t"], b["t"], day))
    span = (tb - ta).days
    return float(a["v"]) if span == 0 else float(a["v"]) + (float(b["v"]) - float(a["v"])) * (td - ta).days / span


def add_alert(symbol: str, kind: str, value: float = 0.0, note: str = "", a: dict | None = None, b: dict | None = None,
              ref: str | None = None, seen: list[str] | None = None) -> dict:
    if kind not in KINDS:
        raise ValueError(f"Kind must be one of {', '.join(KINDS)}.")
    sym = ALL if kind == "scan_hit" else (clean_symbols([symbol]) or [None])[0]
    if not sym:
        raise ValueError("Not an NSE symbol.")
    value = float(value or 0)
    extra: dict = {}
    if not value == value or (kind in ("above", "below") and value <= 0):
        raise ValueError("Give a positive price level.")
    if kind in ("line_above", "line_below"):
        pa, pb = _point(a), _point(b)
        if pa["t"] == pb["t"]:
            raise ValueError("A trendline needs two different dates.")
        extra = {"a": pa, "b": pb}
        value = line_level(pa, pb, ist_now().date())
    elif kind in ("rsi_above", "rsi_below") and not 0 < value < 100:
        raise ValueError("RSI is between 0 and 100.")
    elif kind in ("sma_above", "sma_below") and int(value) not in SMA_PERIODS:
        raise ValueError(f"Moving average of {', '.join(map(str, SMA_PERIODS))} days.")
    elif kind == "scan_hit":
        if not ref:
            raise ValueError("Pick a saved scan.")
        extra = {"ref": str(ref)[:40], "seen": clean_symbols(seen or [])}
    a = {"id": uuid.uuid4().hex[:12], "symbol": sym, "kind": kind, "value": round(value, 2), "note": str(note or "")[:120],
         "created": ist_now().isoformat(timespec="seconds"), "active": True, "fired_at": None, "fired_price": None,
         "source": None, **extra}
    with _lock("alerts"):
        cur = alerts()
        if sum(1 for x in cur if x.get("active")) >= MAX_ALERTS:
            raise ValueError(f"At most {MAX_ALERTS} active alerts.")
        _write(data_dir() / ALERTS_FILE_NAME, {"alerts": cur + [a]})
    return a


def update_alert(alert_id: str, active: bool | None = None, delete: bool = False) -> dict | None:
    """Delete an alert, or re-arm (active=True) / pause (active=False) it. Returns it (None when deleted / unknown)."""
    with _lock("alerts"):
        cur = alerts()
        hit = next((x for x in cur if x.get("id") == alert_id), None)
        if hit is None:
            return None
        if delete:
            cur = [x for x in cur if x.get("id") != alert_id]
            out = None
        else:
            if active is not None:
                hit["active"] = bool(active)
                if active:
                    hit["fired_at"] = hit["fired_price"] = hit["source"] = None
            out = hit
        _write(data_dir() / ALERTS_FILE_NAME, {"alerts": cur})
    return out


def triggered(a: dict, q: dict) -> bool:
    """A price alert's condition on a quote (rule kinds are checked by rule_alerts.py, never here)."""
    price, chg = q.get("price"), q.get("change_pct")
    v = a.get("value")
    if v is None or a.get("kind") not in PRICE_KINDS:
        return False
    if a["kind"] in ("line_above", "line_below"):
        if price is None or not a.get("a") or not a.get("b"):
            return False
        lvl = line_level(a["a"], a["b"], ist_now().date())
        return price >= lvl if a["kind"] == "line_above" else price <= lvl
    if a["kind"] == "above":
        return price is not None and price >= v
    if a["kind"] == "below":
        return price is not None and price <= v
    if a["kind"] == "change_above":
        return chg is not None and chg >= v
    if a["kind"] == "change_below":
        return chg is not None and chg <= v
    return False


def describe(a: dict) -> str:
    v, s, k = a["value"], a["symbol"], a["kind"]
    if k in ("line_above", "line_below"):
        lvl = line_level(a["a"], a["b"], ist_now().date()) if a.get("a") and a.get("b") else v
        return f"{s} {'above' if k == 'line_above' else 'below'} its trendline (today {lvl:,.2f})"
    return {"above": f"{s} at or above {v:,.2f}", "below": f"{s} at or below {v:,.2f}",
            "change_above": f"{s} up {v:+.2f}% or more today", "change_below": f"{s} {v:+.2f}% or worse today",
            "rsi_above": f"{s} RSI(14) at or above {v:g}", "rsi_below": f"{s} RSI(14) at or below {v:g}",
            "sma_above": f"{s} above its {int(v)}-day average", "sma_below": f"{s} below its {int(v)}-day average",
            "scan_hit": f"scan '{a.get('note') or a.get('ref')}' has a new stock",
            "pattern": f"{s}: a candle pattern with a tested edge"}.get(k, f"{s} {k} {v}")


def fire(check) -> list[dict]:
    """Fire every active alert for which `check(alert)` returns {"price": .., "source": .., "detail": ..} (None = not
    met). One-shot under the file lock, as evaluate(); used by rule_alerts.py for the rule kinds."""
    if not any(a.get("active") and check(a) for a in alerts()):
        return []
    fired = []
    with _lock("alerts"):
        cur = alerts()
        for a in cur:
            if not a.get("active"):
                continue
            hit = check(a)
            if not hit:
                continue
            a.update(active=False, fired_at=ist_now().isoformat(timespec="seconds"), fired_price=hit.get("price"),
                     source=hit.get("source") or "rule")
            if hit.get("detail"):
                a["detail"] = str(hit["detail"])[:200]
            fired.append(dict(a))
        if fired:
            _write(data_dir() / ALERTS_FILE_NAME, {"alerts": cur})
            with open(data_dir() / FIRED_FILE_NAME, "a", encoding="utf-8") as f:
                for a in fired:
                    f.write(json.dumps({**a, "text": message(a)}) + "\n")
    return fired


def evaluate(quotes: dict[str, dict]) -> list[dict]:
    """Fire every active alert whose condition the given quotes ({symbol: quote}) meet. One-shot: a fired alert is
    switched off under the file lock, so another process checking the same moment cannot fire it again."""
    cur = alerts()
    due = [a for a in cur if a.get("active") and a.get("symbol") in quotes
           and (quotes[a["symbol"]].get("source") or "live") in LIVE_SOURCES and triggered(a, quotes[a["symbol"]])]
    if not due:
        return []
    fired = []
    with _lock("alerts"):
        cur = alerts()                                   # re-read under the lock: the other process may have fired it
        for a in cur:
            q = quotes.get(a.get("symbol"))
            if not a.get("active") or q is None or not triggered(a, q):
                continue
            src = q.get("source") or "live"
            if src not in LIVE_SOURCES:
                continue
            a.update(active=False, fired_at=ist_now().isoformat(timespec="seconds"), fired_price=q.get("price"),
                     source=src)
            fired.append(dict(a))
        if fired:
            _write(data_dir() / ALERTS_FILE_NAME, {"alerts": cur})
            with open(data_dir() / FIRED_FILE_NAME, "a", encoding="utf-8") as f:
                for a in fired:
                    f.write(json.dumps({**a, "text": message(a)}) + "\n")
    return fired


def message(a: dict) -> str:
    late = " (Yahoo price, ~15 min late)" if a.get("source") == "yahoo" else ""
    note = f" - {a['note']}" if a.get("note") and a.get("kind") != "scan_hit" else ""
    if a.get("detail"):
        note += f": {a['detail']}"
    px = a.get("fired_price")
    return f"Alert: {describe(a)}: now {px:,.2f}{late}{note}" if isinstance(px, (int, float)) else f"Alert: {describe(a)}{note}"


def fired_since(after: float) -> tuple[float, list[dict]]:
    """Alerts fired after the epoch `after` (from alerts_fired.jsonl); returns (newest epoch seen, alerts)."""
    p = data_dir() / FIRED_FILE_NAME
    try:
        if p.stat().st_mtime <= after:
            return after, []
        lines = p.read_text(encoding="utf-8").splitlines()[-200:]
    except OSError:
        return after, []
    out, newest = [], after
    for ln in lines:
        try:
            a = json.loads(ln)
            t = datetime.fromisoformat(a["fired_at"]).timestamp()
        except Exception:
            continue
        if t > after:
            out.append(a)
            newest = max(newest, t)
    return newest, out


def recent_fired(n: int = 50) -> list[dict]:
    p = data_dir() / FIRED_FILE_NAME
    try:
        lines = p.read_text(encoding="utf-8").splitlines()[-n:]
    except OSError:
        return []
    out = []
    for ln in reversed(lines):
        try:
            out.append(json.loads(ln))
        except Exception:
            pass
    return out


def notify(fired: list[dict]) -> None:
    """Telegram for fired alerts (when TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID are set), off the caller's thread."""
    if not fired:
        return

    def send():
        try:
            from .alerts import send_telegram
            send_telegram("\n".join(message(a) for a in fired))
        except Exception:
            pass
    threading.Thread(target=send, name="alert-telegram", daemon=True).start()


def feed_symbols() -> list[str]:
    """What the live service should stream for the user beyond the screen: active alerts first, then watchlists."""
    out = clean_symbols([a.get("symbol") for a in alerts() if a.get("active") and a.get("symbol") != ALL])
    for lst in watchlists()["lists"]:
        for s in lst["symbols"]:
            if s not in out:
                out.append(s)
    return out


# ---- chart drawings (per symbol) ----------------------------------------------------------------------------------

DRAWINGS_FILE_NAME = "drawings.json"
DRAW_KINDS = ("hline", "trend", "fib", "rect", "text", "avwap")
MAX_DRAWINGS = 50


def _point(p) -> dict:
    t = str((p or {}).get("t") or "")[:10]
    v = float((p or {}).get("v"))
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", t) or not v == v or v <= 0:
        raise ValueError("A drawing point needs a date and a positive price.")
    return {"t": t, "v": round(v, 2)}


def drawings(symbol: str) -> list[dict]:
    sym = (clean_symbols([symbol]) or [""])[0]
    return list((_read(data_dir() / DRAWINGS_FILE_NAME, {"symbols": {}}).get("symbols") or {}).get(sym) or [])


def save_drawings(symbol: str, items: list[dict]) -> list[dict]:
    sym = (clean_symbols([symbol]) or [None])[0]
    if not sym:
        raise ValueError("Not an NSE symbol.")
    out = []
    for d in items[:MAX_DRAWINGS]:
        kind = d.get("kind")
        if kind not in DRAW_KINDS:
            raise ValueError(f"Unknown drawing {kind!r}.")
        x = {"id": str(d.get("id") or uuid.uuid4().hex[:12])[:24], "kind": kind, "note": str(d.get("note") or "")[:60]}
        if kind == "hline":
            v = float(d.get("price"))
            if not v == v or v <= 0:
                raise ValueError("A level needs a positive price.")
            x["price"] = round(v, 2)
        elif kind in ("text", "avwap"):              # one point: a note on the chart / the anchor of a VWAP
            x["a"] = _point(d.get("a"))
            if kind == "text" and not x["note"].strip():
                raise ValueError("A text note needs some text.")
        else:
            x["a"], x["b"] = _point(d.get("a")), _point(d.get("b"))
        out.append(x)
    with _lock("drawings"):
        allv = _read(data_dir() / DRAWINGS_FILE_NAME, {"symbols": {}})
        syms = dict(allv.get("symbols") or {})
        if out:
            syms[sym] = out
        else:
            syms.pop(sym, None)
        _write(data_dir() / DRAWINGS_FILE_NAME, {"symbols": syms})
    return out
