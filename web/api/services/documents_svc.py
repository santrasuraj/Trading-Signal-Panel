"""A company's filings timeline (GET /api/company/{symbol}/documents): earnings-call transcripts, investor
presentations, call schedules and recordings, results, board outcomes, credit ratings, deals and annual reports -
everything the company filed with NSE since 2004, sorted into what an investor looks for, newest first, each linking
to the official file on NSE's archive. (What Screener.in and Tijori collect in their "documents" tabs, from the
source they collect it from.)

Sources: www.nseindia.com/api/corporate-announcements (every announcement with its attachment) and /api/annual-reports.
Cached per company in data/documents/{SYMBOL}.json for CACHE_H hours."""
from __future__ import annotations

import json
import time
from datetime import datetime

from scanner import events

from ..errors import ApiException
from ..paths import P

CACHE_H = 6
MAX_ITEMS = 600
CATEGORIES = {                      # id -> label, in the order the page shows them
    "transcript": "Call transcripts", "presentation": "Investor presentations", "call": "Calls & meetings",
    "recording": "Call recordings", "results": "Results", "annual_report": "Annual reports", "board": "Board meetings",
    "rating": "Credit ratings", "deal": "Acquisitions & schemes", "press": "Press releases",
}


def _dt(s) -> datetime | None:
    for fmt in ("%d-%b-%Y %H:%M:%S", "%d-%b-%Y %H:%M", "%d-%b-%Y"):
        try:
            return datetime.strptime(str(s).strip().title(), fmt)
        except ValueError:
            pass
    return None


def category(desc: str, text: str) -> str | None:
    """Which shelf an announcement goes on (None = routine, left out)."""
    d, t = (desc or "").lower(), (text or "").lower()
    if "transcript" in t:
        return "transcript"
    if "presentation" in t or d == "investor presentation":
        return "presentation"
    if "recording" in t and ("audio" in t or "video" in t or "call" in t):
        return "recording"
    if "con. call" in d or "analyst" in d or "investor meet" in d:
        return "call"
    if "financial result" in d or ("outcome of board meeting" in d and "result" in t):
        return "results"
    if "credit rating" in d:
        return "rating"
    if any(k in d for k in ("acquisition", "amalgamation", "scheme of arrangement", "merger", "demerger")):
        return "deal"
    if "outcome of board meeting" in d or "board meeting" in d:
        return "board"
    if d == "press release":
        return "press"
    return None


def _path(sym: str):
    return P.data / "documents" / f"{sym}.json"


def _fetch(sym: str) -> dict:
    items = []
    ann = events._get_json("corporate-announcements", {"index": "equities", "symbol": sym})
    for r in ann if isinstance(ann, list) else []:
        cat = category(r.get("desc"), r.get("attchmntText"))
        if not cat:
            continue
        dt = _dt(r.get("an_dt") or r.get("sort_date"))
        url = str(r.get("attchmntFile") or "")
        items.append({"time": dt.isoformat(timespec="minutes") if dt else None, "category": cat,
                      "subject": r.get("desc") or "", "text": " ".join(str(r.get("attchmntText") or "").split())[:400],
                      "url": url if url.startswith("https://") and url.lower().endswith((".pdf", ".zip", ".xml", ".html", ".mp3", ".mp4")) else None,
                      "size": r.get("attFileSize") or r.get("fileSize")})
    try:
        ar = events._get_json("annual-reports", {"index": "equities", "symbol": sym})
        rows = ar.get("data") if isinstance(ar, dict) else ar
    except Exception:
        rows = []
    latest: dict[str, dict] = {}
    for r in rows or []:
        key = f"{r.get('fromYr')}-{r.get('toYr')}"
        dt = _dt(r.get("disseminationDateTime") or r.get("broadcast_dttm"))
        if key not in latest or (dt and dt.isoformat() > (latest[key]["time"] or "")):
            latest[key] = {"time": dt.isoformat(timespec="minutes") if dt else None, "category": "annual_report",
                           "subject": f"Annual report {r.get('fromYr')}-{str(r.get('toYr'))[-2:]}",
                           "text": "Revised" if str(r.get("submission_type")).lower() == "revised" else "",
                           "url": r.get("fileName") if str(r.get("fileName") or "").startswith("https://") else None,
                           "size": r.get("attFileSize")}
    items += latest.values()
    items.sort(key=lambda x: x["time"] or "", reverse=True)
    return {"symbol": sym, "fetched": time.time(), "items": items[:MAX_ITEMS]}


def documents(symbol: str, refresh: bool = False) -> dict:
    sym = symbol.upper().strip()
    if not sym.replace("-", "").replace("&", "").isalnum() or len(sym) > 20:
        raise ApiException("VALIDATION", f"{symbol!r} is not a stock symbol.")
    p = _path(sym)
    rec = None
    try:
        rec = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    note = None
    if refresh or not rec or time.time() - float(rec.get("fetched") or 0) > CACHE_H * 3600:
        try:
            rec = _fetch(sym)
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(".tmp")
            tmp.write_text(json.dumps(rec), encoding="utf-8")
            tmp.replace(p)
        except Exception as e:
            note = f"NSE did not answer ({type(e).__name__}); showing what is stored."
            rec = rec or {"symbol": sym, "fetched": None, "items": []}
    counts = {k: 0 for k in CATEGORIES}
    for it in rec["items"]:
        counts[it["category"]] = counts.get(it["category"], 0) + 1
    return {"symbol": sym, "categories": [{"id": k, "label": v, "count": counts.get(k, 0)} for k, v in CATEGORIES.items()],
            "items": rec["items"], "fetched": datetime.fromtimestamp(rec["fetched"]).isoformat(timespec="seconds")
            if rec.get("fetched") else None,
            "note": note or "Everything the company filed with NSE since 2004 that an investor reads, newest first; each "
                            "links to the official file. Routine filings (trading-window closures, newspaper copies) "
                            "are left out."}
