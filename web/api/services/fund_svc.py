"""Company numbers (GET /api/fundamentals/{symbol}, GET /api/fundamentals-status, POST /api/fundamentals/refresh):
quarterly revenue, profit, EPS, growth, margin and P/E from NSE's filings (scanner/fundamentals.py). A company is
fetched the first time its page asks (a few seconds); the whole universe in the background on request (and kept
current by the nightly job), which also feeds the scan fields (P/E, sales and profit growth, net margin, EPS)."""
from __future__ import annotations

import threading
from datetime import date

from scanner import fundamentals as fu

from . import data, quotes_svc
from ..util import now_ist

_job = {"running": False, "done": 0, "total": 0, "started": None, "finished": None, "report": None, "error": None}
_lock = threading.Lock()
STALE_DAYS = 7


def view(symbol: str) -> dict:
    sym = symbol.upper()
    rec = fu.load(sym)
    note = None
    checked = rec.get("checked")
    if not checked or (date.today() - date.fromisoformat(checked)).days >= STALE_DAYS:
        try:
            rec = fu.update(sym)
        except Exception as e:                     # NSE down: what is stored still shows
            note = f"NSE did not answer ({type(e).__name__}); showing what is stored."
    q = quotes_svc.quotes([sym]).get("quotes") or []
    price = float(q[0]["price"]) if q and q[0].get("price") else None
    out = fu.summary(rec, price)
    return {"symbol": sym, "price": price, **out, "note": note or (
        "From NSE's quarterly filings (consolidated when the company files one). Growth is against the same quarter a "
        "year earlier; P/E uses the last four quarters' EPS (a bonus or split inside them distorts it).")}


def status() -> dict:
    d = fu.folder()
    n = len(list(d.glob("*.json"))) if d.exists() else 0
    return {"companies": n, "universe": len(data.universe()), "job": dict(_job)}


def start_refresh() -> dict:
    with _lock:
        if _job["running"]:
            return status()
        _job.update(running=True, done=0, total=0, started=now_ist().isoformat(timespec="seconds"), finished=None,
                    report=None, error=None)
    syms = [str(s) for s in data.universe()["symbol"]]
    etfs = set(data.etfs())
    syms = [s for s in syms if s not in etfs]

    def work():
        try:
            _job["report"] = fu.refresh(syms, log=lambda *_: None, progress=lambda d, t: _job.update(done=d, total=t))
        except Exception as e:
            _job["error"] = f"{type(e).__name__}: {e}"
        finally:
            _job.update(running=False, finished=now_ist().isoformat(timespec="seconds"))

    threading.Thread(target=work, name="fundamentals", daemon=True).start()
    return status()
