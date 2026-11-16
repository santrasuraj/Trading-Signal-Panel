"""Company numbers (GET /api/fundamentals/{symbol}, GET /api/fundamentals-status, POST /api/fundamentals/refresh):
quarterly revenue, profit, EPS, growth, margin and P/E from NSE's filings (scanner/fundamentals.py). A company is
fetched the first time its page asks (a few seconds); the whole universe in the background on request (and kept
current by the nightly job), which also feeds the scan fields (P/E, sales and profit growth, net margin, EPS)."""
from __future__ import annotations

import threading
from datetime import date

from scanner import financials as fin
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
            n = len(syms)                                  # quarterly numbers first, then ten years of financials
            rep = fu.refresh(syms, log=lambda *_: None, progress=lambda d, t: _job.update(done=d, total=t + n))
            _job.update(total=_job["total"] or 2 * n)
            base = _job["done"]
            rep2 = fin.refresh(syms, log=lambda *_: None, stop=lambda: False,
                               progress=lambda d, t: _job.update(done=base + d, total=base + t))
            _job["report"] = {"quarterly": rep, "financials": rep2}
        except Exception as e:
            _job["error"] = f"{type(e).__name__}: {e}"
        finally:
            _job.update(running=False, finished=now_ist().isoformat(timespec="seconds"))

    threading.Thread(target=work, name="fundamentals", daemon=True).start()
    return status()


def screener() -> dict:
    """Every universe stock whose filings are stored: P/E, revenue and profit growth against a year ago, margin and
    EPS, next to its price trend from the last scan (screener.parquet)."""
    import math
    sc = data.screener()
    if sc is None or sc.empty:
        return {"rows": [], "stored": 0, "universe": 0, "note": "No scan yet."}
    rows = []
    from . import company_svc
    qvm = company_svc.scores()
    for r in sc.itertuples(index=False):
        rec = fu.load(r.symbol)
        if not rec.get("quarters"):
            continue
        s = fu.summary(rec, float(r.price) if r.price == r.price else None)
        lt = s.get("latest") or {}
        if not lt:
            continue

        def f(x, nd=1):
            return None if x is None or (isinstance(x, float) and math.isnan(x)) else round(float(x), nd)
        fs = fin.snapshot(fin.load(r.symbol), float(r.price) if r.price == r.price else None)             if fin._file(r.symbol).exists() else {}
        sq = qvm.get(r.symbol) or {}
        rows.append({"score": sq.get("score"), "quality": sq.get("quality"), "value": sq.get("value"),
                     "momentum": sq.get("momentum"), "roce": f(fs.get("roce")), "roe": f(fs.get("roe")), "de": f(fs.get("de"), 2), "opm": f(fs.get("opm")),
                     "sales_cagr_5y": f(fs.get("sales_cagr_5y")), "profit_cagr_5y": f(fs.get("profit_cagr_5y")),
                     "market_cap_cr": f((fs.get("market_cap") or 0) / 1e7, 0) if fs.get("market_cap") else None,
                     "pb": f(fs.get("pb"), 2),
                     "symbol": r.symbol, "company": r.company, "industry": r.industry, "price": f(r.price, 2),
                     "ret_3m": f(r.ret_3m), "ret_12m": f(r.ret_12m), "rs": f(r.rs, 0),
                     "above_sma200": bool(r.above_sma200) if r.above_sma200 == r.above_sma200 else None,
                     "pct_from_52w_high": f(r.pct_from_52w_high), "turnover_cr": f(r.turnover_cr),
                     "qe": lt.get("qe"), "filed": lt.get("filed"), "revenue_cr": lt.get("revenue_cr"),
                     "profit_cr": lt.get("profit_cr"), "sales_growth": lt.get("sales_growth"),
                     "profit_growth": lt.get("profit_growth"), "net_margin": lt.get("net_margin"),
                     "eps_ttm": lt.get("eps_ttm"), "pe": lt.get("pe"), "basis": s.get("basis")})
    return {"rows": rows, "stored": len(rows), "universe": int(len(sc)),
            "note": "From NSE's quarterly filings (consolidated when filed) and the last scan's prices. Growth is "
                    "against the same quarter a year earlier; P/E uses the last four quarters' EPS."}
