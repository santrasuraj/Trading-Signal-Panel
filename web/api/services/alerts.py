"""Alert generation (spec 6.13 + review A12) and "since last scan" changes.

Alert ids are `${category}:${symbol ?? ''}:${rule}`, stable across scans so the UI can remember dismissals.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from . import data, holdings_svc
from ..caches import KeyedCache, file_key, register
from ..paths import P
from ..util import days_until, fmt_date, today_ist

SEVERITY_ORDER = {"danger": 0, "warn": 1, "info": 2, "good": 3}
LEVEL_SEVERITY = {"danger": "danger", "watch": "warn", "good": "good", "unknown": "warn", "ok": "info"}


def _rule(text: str) -> str:
    """Stable rule id from an alert text: digits/amounts removed, then hashed."""
    core = re.sub(r"[\d.,₹%]+", "", text.lower())
    return hashlib.md5(core.encode("utf-8")).hexdigest()[:8]


def _a(severity, category, title, detail=None, symbol=None, strategy_key=None, href=None, rule=None) -> dict:
    return {"id": f"{category}:{symbol or ''}:{rule or _rule(title)}", "severity": severity, "category": category,
            "title": title, "detail": detail, "symbol": symbol, "strategy_key": strategy_key, "href": href}


def build(lt: dict, as_of: dict, clock: dict, fyers: dict, scan: dict, summaries: list[dict], orders: list[dict],
          papers: list[dict], prev: dict | None) -> list[dict]:
    out: list[dict] = []
    # 1. holdings: every alert line of every CURRENT holding (holdings.csv now, health from the last scan;
    #    a holding removed after the scan is gone, one added after it gets its first health check here)
    try:
        held_rows = holdings_svc.rows(lt)[0]
    except Exception:
        held_rows = lt.get("holdings") or []
    for h in held_rows:
        sev = LEVEL_SEVERITY.get(h.get("level"), "info")
        for text in h.get("alerts") or []:
            out.append(_a(sev, "holding", f"{h.get('symbol')}: {text}", symbol=h.get("symbol"), href="/portfolio"))
    # 2. orders with a results date inside the warning window
    for o in orders:
        if o["results_warning"] and not o["comparison_only"]:
            d = o["results_in_days"]
            when = "today" if d == 0 else ("tomorrow" if d == 1 else f"in {d} days")
            out.append(_a("warn", "order", f"{o['symbol']} reports results {when}; consider waiting before buying",
                          detail=f"{o['strategy_name']}: BUY {o['symbol']}", symbol=o["symbol"],
                          strategy_key=o["strategy_key"], href="/signals", rule="results_warning"))
    # 3. results: held / model / order / ranked top-5 symbols reporting within warn_days
    warn_days = int((data.config().get("results") or {}).get("warn_days", 7) or 7)
    roles: dict[str, list[str]] = {}
    when_on: dict[str, str] = {}

    def note(sym, role, d):
        if sym and d:
            roles.setdefault(sym, [])
            if role not in roles[sym]:
                roles[sym].append(role)
            when_on[sym] = d
    for h in held_rows:
        note(h.get("symbol"), "you hold", h.get("results_on"))
    acting = {x["key"] for x in summaries if not x["comparison_only"]}
    for s in lt.get("strategies") or []:
        if s.get("key") not in acting:      # not-working strategies are comparison only: no results alerts
            continue
        for p in s.get("positions") or []:
            note(p.get("symbol"), f"in {s.get('name')}", p.get("results_on"))
        for a in s.get("actions") or []:
            note(a.get("symbol"), f"{a.get('action')} order ({s.get('name')})", a.get("results_on"))
        for r in (s.get("ranking") or [])[:5]:
            note(r.get("symbol"), f"#{r.get('rank')} {s.get('name')}", r.get("results_on"))
    today = today_ist()
    for sym, rs in roles.items():
        d = days_until(when_on[sym], today)
        if d is None or not 0 <= d <= warn_days:
            continue
        when = "today" if d == 0 else ("tomorrow" if d == 1 else f"in {d} days")
        sev = "warn" if d <= 1 or "you hold" in rs or any("order" in r for r in rs) else "info"
        out.append(_a(sev, "results", f"{sym} ({', '.join(rs[:2])}) reports results {when}",
                      detail="Expect a big move either way.", symbol=sym, href=f"/chart/{sym}", rule="results"))
    # 4. login
    if clock["session"] in ("open", "pre_open") and not fyers["logged_in_today"]:
        out.append(_a("warn", "login", "Fyers not logged in: live prices come from Yahoo (~15 min delayed)",
                      href="/settings/fyers", rule="not_logged_in"))
    # 5. scan
    if as_of["stale"]:
        out.append(_a("warn", "scan", f"Prices are from {fmt_date(as_of['data_date'])}: run a scan for the latest close",
                      href="/settings/scan", rule="stale"))
    if scan.get("state") == "failed":
        out.append(_a("danger", "scan", "The last scan failed", detail=scan.get("message"), href="/settings/scan",
                      rule="failed"))
    if as_of["legacy_producer"]:
        out.append(_a("warn", "scan", "The latest results were written by an older version of the scanner",
                      detail="Some columns are missing until the next scan from Quant Desk.", href="/settings/scan",
                      rule="legacy"))
    # 6. data
    stale = lt.get("stale_symbols") or []
    if stale:
        out.append(_a("info", "data", f"{len(stale)} symbol(s) without a fresh price ({', '.join(stale[:3])}"
                      f"{' ...' if len(stale) > 3 else ''})", href="/settings/data", rule="stale_symbols"))
    errors = lt.get("errors") or {}
    if errors:
        out.append(_a("warn", "data", f"{len(errors)} download error(s) in the last scan", href="/settings/data",
                      rule="errors"))
    nse = str(lt.get("nse_status") or "")
    if nse.startswith("NSE file not available"):
        out.append(_a("warn", "data", nse, href="/settings/data", rule="nse"))
    # 7. market
    m = lt.get("market") or {}
    if prev is not None and (prev.get("market") or {}).get("regime_up") is not None \
            and bool(prev["market"]["regime_up"]) != bool(m.get("regime_up")):
        out.append(_a("info", "market", "Market regime changed: Nifty is now "
                      f"{'above' if m.get('regime_up') else 'below'} its 200-day average", href="/", rule="regime"))
    if (m.get("vix") or 0) >= 20:
        out.append(_a("warn", "market", f"India VIX is high ({m.get('vix')}): expect large swings", href="/market/factors",
                      rule="vix"))
    # 8. paper
    for p in papers:
        if p.get("level") == "bad":
            out.append(_a("warn", "paper", f"{p['name']}: paper trading is behind the backtest by more than noise",
                          detail=p.get("verdict"), strategy_key=p["key"], href=f"/paper/{p['key']}", rule="behind"))
    # 9. bias
    if as_of["backtest_universe"] == "current_list":
        out.append(_a("info", "bias", "Backtests use today's index list (survivorship bias): judge strategies by "
                      "their edge over the average stock", href="/strategies", rule="survivorship"))
    seen, uniq = set(), []
    for a in out:
        if a["id"] not in seen:
            seen.add(a["id"])
            uniq.append(a)
    uniq.sort(key=lambda a: SEVERITY_ORDER[a["severity"]])
    return uniq


# ------------------------------------------------------------------ scan history + changes
_HEAD_RE = {k: re.compile(rf'"{k}":\s*("([^"]*)"|true|false|null|-?[0-9.]+)') for k in
            ("generated_at", "data_date", "live", "elapsed_s")}


def _head(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    out = {}
    head = text[:1500]
    for k, rx in _HEAD_RE.items():
        m = rx.search(head)
        if not m:
            out[k] = None
            continue
        raw = m.group(1)
        out[k] = m.group(2) if raw.startswith('"') else json.loads(raw)
    active = text.count('"lifecycle": "active"')   # B4 scans also carry rejected strategies
    out["strategies"] = active or text.count('"status_reason":') or None
    out["has_producer"] = '"producer":' in head
    return out


_heads = register(KeyedCache(256))


def scan_files() -> list[dict]:
    """Saved scans, newest first: {file, scan_id, data_date, live, elapsed_s, strategies}."""
    out = []
    for f in sorted(P.results.glob("scan_*.json"), reverse=True):
        try:
            h = _heads.get(file_key(f), lambda f=f: _head(f))
        except OSError:
            continue
        out.append({"file": f.name, "path": f, **h})
    return out


_prev = register(KeyedCache(4))


def previous_scan(lt: dict) -> dict | None:
    """The newest saved scan with an OLDER data_date than latest (intraday re-scans don't count)."""
    cur = str(lt.get("data_date") or "")
    for h in scan_files():
        if h.get("data_date") and h["data_date"] < cur:
            return _prev.get(file_key(h["path"]), lambda p=h["path"]: data.read_json_file(p))
    return None


def changes(lt: dict, prev: dict | None) -> dict:
    if not prev:
        return {"since_scan_id": None, "since_data_date": None, "items": []}
    items = []
    now = {s["key"]: s for s in lt.get("strategies") or []}
    before = {s["key"]: s for s in prev.get("strategies") or [] if "key" in s}
    labels = {"working": "working", "mixed": "mixed", "not-working": "not working", "unknown": "too new"}
    both = [k for k in now if k in before]           # diff only keys present in both scans
    for k in both:
        a, b = before[k].get("status"), now[k].get("status")
        if a and b and a != b:
            items.append({"kind": "status", "text": f"{now[k].get('name')}: {labels.get(a, a)} -> {labels.get(b, b)}",
                          "strategy_key": k, "symbol": None})
    ra, rb = (prev.get("market") or {}).get("regime_up"), (lt.get("market") or {}).get("regime_up")
    if ra is not None and rb is not None and bool(ra) != bool(rb):
        items.append({"kind": "regime", "text": f"Regime flipped: Nifty now {'above' if rb else 'below'} its 200-DMA",
                      "strategy_key": None, "symbol": None})
    for k in both:
        old = {(o.get("action"), o.get("symbol")) for o in before[k].get("actions") or []}
        for o in now[k].get("actions") or []:
            if (o.get("action"), o.get("symbol")) not in old:
                items.append({"kind": "new_order", "text": f"New: {o.get('action')} {o.get('symbol')} ({now[k].get('name')})",
                              "strategy_key": k, "symbol": o.get("symbol")})
    for k in both:
        pa = {p.get("symbol") for p in before[k].get("positions") or []}
        pb = {p.get("symbol") for p in now[k].get("positions") or []}
        for sym in sorted(pb - pa):
            items.append({"kind": "position_opened", "text": f"{now[k].get('name')} bought {sym}",
                          "strategy_key": k, "symbol": sym})
        for sym in sorted(pa - pb):
            items.append({"kind": "position_closed", "text": f"{now[k].get('name')} sold {sym}",
                          "strategy_key": k, "symbol": sym})
    return {"since_scan_id": prev.get("generated_at"), "since_data_date": prev.get("data_date"), "items": items}
