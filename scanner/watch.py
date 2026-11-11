"""Watchlists and price alerts: the user's own lists, shared by the dashboard and the live service.

  data/watchlists.json    {"lists": [{"name": "Main", "symbols": ["RELIANCE", ...]}]}
  data/alerts.json        {"alerts": [{id, symbol, kind, value, note, created, active, fired_at, fired_price, source}]}
  data/alerts_fired.jsonl one line per fired alert (newest last)

Alert kinds: "above" (price at or above the level), "below" (at or below), "change_above" (day change % at or
above), "change_below" (at or below). Alerts fire once: a fired alert turns inactive (re-arm it to use it again).

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
KINDS = ("above", "below", "change_above", "change_below")
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


def add_alert(symbol: str, kind: str, value: float, note: str = "") -> dict:
    sym = (clean_symbols([symbol]) or [None])[0]
    if not sym:
        raise ValueError("Not an NSE symbol.")
    if kind not in KINDS:
        raise ValueError(f"Kind must be one of {', '.join(KINDS)}.")
    value = float(value)
    if not value == value or (kind in ("above", "below") and value <= 0):
        raise ValueError("Give a positive price level.")
    a = {"id": uuid.uuid4().hex[:12], "symbol": sym, "kind": kind, "value": round(value, 2), "note": str(note or "")[:120],
         "created": ist_now().isoformat(timespec="seconds"), "active": True, "fired_at": None, "fired_price": None,
         "source": None}
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
    price, chg = q.get("price"), q.get("change_pct")
    v = a.get("value")
    if v is None:
        return False
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
    v = a["value"]
    return {"above": f"{a['symbol']} at or above {v:,.2f}", "below": f"{a['symbol']} at or below {v:,.2f}",
            "change_above": f"{a['symbol']} up {v:+.2f}% or more today",
            "change_below": f"{a['symbol']} {v:+.2f}% or worse today"}[a["kind"]]


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
    note = f" - {a['note']}" if a.get("note") else ""
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
    out = clean_symbols([a.get("symbol") for a in alerts() if a.get("active")])
    for lst in watchlists()["lists"]:
        for s in lst["symbols"]:
            if s not in out:
                out.append(s)
    return out
