"""Option chains for the Options page: reads data/options/ (written by scanner/options.py) - never NSE, except the
POST /refresh job, which runs scanner.options.refresh in a background thread of this process."""
from __future__ import annotations

import json
import threading
from datetime import date, datetime

import pandas as pd

from scanner import fno, fno_live, options as opt, options_research
from scanner.settings import load_config

from .. import errors
from ..caches import FileCache, KeyedCache, file_key, register
from ..errors import ApiException, not_found
from ..paths import P
from ..util import now_ist, num, today_ist
from .clock import market_clock

STALE_MINUTES = 10
NOTE = ("NSE's public option chain, stamped with NSE's own time (it updates every few minutes in the session). "
        "Open interest and volume in contracts. Implied volatility and greeks are computed on the forward "
        "(Black-76); NSE's own IV, on the spot, is shown for reference. This is positioning, not a signal: no backtest "
        "here shows that PCR, max pain or OI levels predict prices.")

_latest = register(FileCache(lambda p: json.loads(p.read_text(encoding="utf-8")), missing={}))
_snaps = register(KeyedCache(8))
_analysis = register(KeyedCache(16))
_summary = register(KeyedCache(4))
_lots = register(KeyedCache(1))
_research = register(KeyedCache(2))
RESEARCH_NOTE = ("Measured on this app's own stored end-of-day chains, nothing assumed. A claim gets a verdict only "
                 "after enough days; until one holds, nothing here becomes a signal.")


def _config() -> dict:
    try:
        return load_config()
    except Exception:          # a missing or broken config.yaml must not break the page: the defaults apply
        return {}


def _cfg() -> dict:
    return opt.settings(_config())


def _refs() -> list[dict]:
    """Stored chains still to expire (expired ones stay on disk but leave the page), nearest expiry first."""
    chains = (_latest.get(P.options / opt.LATEST_NAME) or {}).get("chains") or {}
    today = today_ist().isoformat()
    refs = [c for c in chains.values() if isinstance(c, dict) and str(c.get("expiry", "")) >= today]
    return sorted(refs, key=lambda c: (str(c.get("symbol")), str(c.get("expiry"))))


def _ref(symbol: str, expiry: str | None) -> tuple[dict, list[str]]:
    sym = symbol.upper()
    mine = [c for c in _refs() if c.get("symbol") == sym]
    if not mine:
        raise not_found(f"Option chain for {sym}", "Refresh the option chains (Options page), or add the symbol to "
                                                   "options.underlyings in config.yaml.")
    exps = [str(c["expiry"]) for c in mine]
    if expiry is None:
        return mine[0], exps
    for c in mine:
        if c["expiry"] == expiry:
            return c, exps
    raise not_found(f"{sym} expiry {expiry}", f"Stored expiries: {', '.join(exps)}.")


def _load_snaps(ref: dict) -> tuple[pd.DataFrame, tuple]:
    path = opt.snap_file(date.fromisoformat(ref["day"]), ref["symbol"], date.fromisoformat(ref["expiry"]))
    key = file_key(path)
    if key[1] is None:
        raise not_found(f"Stored chain {ref['symbol']} {ref['expiry']}", "Refresh the option chains.")
    return _snaps.get(key, lambda: pd.read_parquet(path)), key


def _lot(symbol: str) -> int | None:
    """Contract size from the newest stored F&O bhavcopy (scanner/fno.py), or None before the first F&O fetch."""
    def table() -> dict:
        _, day = fno.day_futures(fno.load_futures())
        return dict(zip(day["symbol"], day["lot"]))

    v = _lots.get(file_key(P.fno / fno.FUT_NAME), table).get(symbol)
    return int(v) if v is not None and pd.notna(v) and v > 0 else None


def chain(symbol: str, expiry: str | None, window: int) -> dict:
    ref, exps = _ref(symbol, expiry)
    snaps, key = _load_snaps(ref)
    rate = _cfg()["risk_free_pct"]

    def compute() -> dict:
        cur, when = opt.chain_at(snaps)
        spot = num(snaps.loc[pd.to_datetime(snaps["time"]) == when, "spot"].iloc[0])
        meta = {"symbol": ref["symbol"], "expiry": date.fromisoformat(ref["expiry"]), "spot": spot,
                "time": when.to_pydatetime(), "source": ref.get("source", "nse")}
        return opt.analyze(cur, meta, rate)

    a = _analysis.get((key, rate), compute)
    w = _analysis.get((key, "window", window), lambda: opt.window_change(snaps, window))
    wrows = (w or {}).get("rows") or {}
    rows = []
    for r in a["rows"]:
        ce_w, pe_w = wrows.get(r["strike"], (None, None))
        rows.append({**r, "ce": {**r["ce"], "oi_chg_window": ce_w}, "pe": {**r["pe"], "oi_chg_window": pe_w}})
    lot = _lot(ref["symbol"])
    unusual = _analysis.get((key, "unusual", window, lot), lambda: opt.unusual(opt.chain_at(snaps)[0], w, lot))
    clock = market_clock()
    age_min = (now_ist() - datetime.fromisoformat(a["time"])).total_seconds() / 60
    return {**{k: a[k] for k in ("symbol", "expiry", "time", "source", "spot", "forward", "atm", "days_to_expiry",
                                 "summary", "levels", "readings")},
            "expiries": exps, "stale": clock["session"] == "open" and age_min > STALE_MINUTES,
            "window_minutes": window, "window_since": (w or {}).get("since"), "lot": lot, "unusual": unusual,
            "rows": rows, "note": NOTE}


BIG_NOTE = ("Every single futures / options trade above the size thresholds, from the FYERS live feed (needs today's FYERS "
            "login and the 09:14 live service). Side = the likely initiator: at the ask a buyer lifted the offer, at the "
            "bid a seller hit it. Who traded, and whether it opened or closed a position, is never known live.")


def bigtrades() -> dict:
    st = fno_live.settings(_config())
    return {**fno_live.summary(P.intraday_live), "note": BIG_NOTE,
            "thresholds": {"future_print_cr": st["future_print_cr"], "option_print_lakh": st["option_print_lakh"]}}


def research() -> dict:
    """The three option-chain claims measured on the stored days (recomputed when a day's summary changes)."""
    key = tuple(file_key(p) for p in sorted(P.options.glob("[0-9]" * 8 + "/" + opt.SUMMARY_NAME)))
    rep = _research.get(key, options_research.report)
    return {**rep, "note": RESEARCH_NOTE}


def history(symbol: str, expiry: str | None) -> dict:
    ref, _ = _ref(symbol, expiry)
    path = opt.day_dir(date.fromisoformat(ref["day"])) / opt.SUMMARY_NAME
    key = file_key(path)
    df = _summary.get(key, lambda: pd.read_parquet(path)) if key[1] is not None else pd.DataFrame(columns=opt.SUMMARY_COLS)
    df = df[(df["symbol"] == ref["symbol"]) & (df["expiry"] == ref["expiry"])].sort_values("time")
    col = lambda c: [num(v) for v in df[c]]          # noqa: E731
    return {"symbol": ref["symbol"], "expiry": ref["expiry"], "day": ref["day"],
            "t": [pd.Timestamp(t).isoformat() for t in df["time"]], "spot": col("spot"), "max_pain": col("max_pain"),
            "pcr_oi": col("pcr_oi"), "atm_iv_pct": col("atm_iv"), "straddle": col("straddle"),
            "support": col("support"), "resistance": col("resistance")}


def status() -> dict:
    cfg = _cfg()
    latest = _latest.get(P.options / opt.LATEST_NAME) or {}
    last = latest.get("last_refresh")
    if isinstance(last, dict):
        last = {"started_at": last.get("started_at"), "chains": int(last.get("chains") or 0),
                "refused": bool(last.get("refused")), "errors": [str(e) for e in last.get("errors") or []]}
    else:
        last = None
    try:
        live = opt.live_running()
    except OSError:
        live = False
    return {"run": run_status(), "live_running": live, "market_open": market_clock()["session"] == "open",
            "interval_seconds": cfg["interval_seconds"], "underlyings": cfg["underlyings"],
            "chains": [{k: c.get(k) for k in ("symbol", "expiry", "day", "time", "spot")} for c in _refs()],
            "last_refresh": last, "note": NOTE}


# ------------------------------------------------------------------ background refresh
_run_lock = threading.Lock()
_run: dict = {"thread": None, "state": "idle", "message": None, "started_at": None, "finished_at": None, "errors": []}


def run_status() -> dict:
    alive = _run["thread"] is not None and _run["thread"].is_alive()
    return {"state": "running" if alive else _run["state"], "running": alive, "message": _run["message"],
            "started_at": _run["started_at"], "finished_at": _run["finished_at"], "errors": list(_run["errors"])}


def start_refresh(symbols: list[str] | None) -> dict:
    syms = None
    if symbols:
        syms = [str(s).strip().upper() for s in symbols]
        bad = [s for s in syms if not opt.valid_symbol(s)]
        if bad or len(syms) > 10:
            raise ApiException("VALIDATION", "Up to 10 NSE symbols (letters, digits, & and -).",
                               None, {"symbols": bad or syms})
    with _run_lock:
        if _run["thread"] is not None and _run["thread"].is_alive():
            raise ApiException("SCAN_BUSY", "An option-chain refresh is already running.",
                               "Wait for it to finish - this page updates by itself.",
                               {"started": str(_run["started_at"] or "?"), "by": "options", "pid": None})
        _run.update(state="running", message="Starting...", started_at=now_ist().isoformat(timespec="seconds"),
                    finished_at=None, errors=[])
        t = threading.Thread(target=_worker, args=(syms,), name="options-refresh", daemon=True)
        _run["thread"] = t
        t.start()
    return run_status()


def _worker(symbols: list[str] | None) -> None:
    try:
        rep = opt.refresh(_config(), symbols, log=lambda m: _run.update(message=str(m).strip()[:300]), reset=True)
        errs = [str(e) for e in rep["errors"]]
        n = len(rep["chains"])
        if n:
            msg = f"{n} chain{'s' if n != 1 else ''} in {rep['elapsed_s']:.0f} s" + (" with problems" if errs else "")
        else:
            msg = "No chain could be fetched" + (f": {errs[0]}" if errs else "")
        _run.update(state="done" if n else "failed", message=msg[:300], errors=errs)
    except Exception as e:
        errors.log.exception("option-chain refresh failed")
        _run.update(state="failed", message=f"{type(e).__name__}: {e}"[:300])
    finally:
        _run["finished_at"] = now_ist().isoformat(timespec="seconds")
