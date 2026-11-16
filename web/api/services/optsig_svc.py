"""Options signals in the dashboard (GET /api/options/signals, POST /api/options/signals/refresh, GET
/api/options/vol-test): the app's intraday and stock signals as option trades, volatility (IV rank) trades and the index
verdicts, with their records (scanner/option_signals.py).

Live, during market hours only: a loop in the server re-marks every open position on NSE's chain each LOOP_S, and runs at
once - within about POLL_S - when new intraday signals appear (the live signal engine's, about a second after each bar,
or the 5-minute task's file), so an option opens seconds after its signal. The 5-minute scheduled task does the same
when the dashboard is closed, and the nightly F&O download scores what is left at NSE's official closes."""
from __future__ import annotations

import logging
import threading
import time

from scanner import option_signals as osg
from scanner import option_verdict as ov

from . import livesig_svc
from ..util import now_ist

log = logging.getLogger("quantdesk")
LOOP_S = 60                 # marks and exits on NSE's chain (it changes every few seconds to minutes)
POLL_S = 5                  # how often new intraday signals are looked for between those passes
_thread: threading.Thread | None = None
_wake = threading.Event()
_state = {"last_run": None, "last_report": None, "last_error": None, "runs": 0, "last_trigger": None}
_vol_cache: dict = {}


def _intraday() -> dict | None:
    """The newest intraday signals: the live engine's (in memory) when it ran today, else the signal file (None)."""
    live, _ready = livesig_svc.latest()
    if live and str(live.get("generated_at") or "")[:10] == now_ist().date().isoformat():
        return live
    return None


def run_once() -> dict:
    rep = osg.refresh(intraday=_intraday())
    _state.update(last_run=now_ist().isoformat(timespec="seconds"), last_report=rep, runs=_state["runs"] + 1)
    return rep


def _signal_stamp() -> tuple:
    """Changes when there are new intraday signals: the live engine's ready time and the 5-minute task's file."""
    _live, ready = livesig_svc.latest()
    try:
        mtime = (osg.RESULTS_DIR / "intraday_signals.json").stat().st_mtime_ns
    except OSError:
        mtime = None
    return ready, mtime


def _loop() -> None:
    last_run, last_stamp = 0.0, None
    while True:
        try:
            if osg._market_open(now_ist()):
                stamp = _signal_stamp()
                why = ("new signals" if _wake.is_set() or stamp != last_stamp else
                       "every minute" if time.monotonic() - last_run >= LOOP_S else None)
                if why:
                    _wake.clear()
                    last_stamp = stamp
                    _state["last_trigger"] = why
                    run_once()
                    last_run = time.monotonic()
                    _state["last_error"] = None
        except Exception as e:                       # never let the loop die
            _state["last_error"] = f"{type(e).__name__}: {e}"
            log.exception("options signals loop failed")
        _wake.wait(POLL_S)


def start() -> None:
    global _thread
    if _thread and _thread.is_alive():
        return
    livesig_svc.on_signals(lambda _sig: _wake.set())   # the live engine's new signals wake the loop at once
    _thread = threading.Thread(target=_loop, name="option-signals", daemon=True)
    _thread.start()


def _verdicts() -> dict:
    """Today's (or the last session's) index verdicts with their reasons, and their record so far."""
    rows = ov.load_journal()
    if not rows:
        return {"day": None, "rows": [], "track": None}
    day = max(r["day"] for r in rows)
    today = [r for r in rows if r["day"] == day]
    try:
        track = ov.track(ov.score(rows, {}))
    except Exception:
        track = None
    keep = ("symbol", "expiry", "verdict", "side", "strike", "premium", "breakeven", "headline", "bias", "lot", "spot",
            "plan", "closest")
    return {"day": day, "rows": [{k: r.get(k) for k in keep} for r in today], "track": track}


def view(source: str | None = None) -> dict:
    rows = osg.load()
    today = now_ist().date().isoformat()
    show = [r for r in rows if r.get("state") == "open" or r.get("day") == today]
    if not show:                                     # weekend / before the first signal: the last session's
        last = max((r["day"] for r in rows), default=None)
        show = [r for r in rows if r.get("day") == last]
    if source in osg.SOURCES:
        show = [r for r in show if r["source"] == source]
    show.sort(key=lambda r: (r.get("state") != "open", r.get("opened_at") or ""), reverse=False)
    return {"signals": show, "record": osg.record(rows), "verdicts": _verdicts(), "loop": dict(_state),
            "market_open": osg._market_open(now_ist()),
            "rules": {"delta_near": osg.DELTA_NEAR, "delta_month": osg.DELTA_MONTH, "iv_high": osg.IV_HIGH,
                      "iv_low": osg.IV_LOW, "vol_target_pct": osg.VOL_TARGET_PCT, "vol_stop_pct": osg.VOL_STOP_PCT},
            "note": ("Practice only: nothing is sent to FYERS. Entry at NSE's live ask (sold legs at the bid); stop and "
                     "target premiums are the option re-priced at the underlying's stop and target, a guide since "
                     "volatility moves too. The directional sources can't be backtested on options here (no intraday "
                     "option prices stored): each carries its strategy's backtest label and builds its own record "
                     "below. Buying options loses money for most traders (SEBI, 2024: 93% of individual F&O traders "
                     "lost money over three years).")}


def vol_test() -> dict:
    """The volatility source's backtest on NIFTY and BANKNIFTY (cached until the option history changes)."""
    from scanner import option_history as oh
    from . import vol_svc
    p = oh.path()
    ver = p.stat().st_mtime_ns if p.exists() else None
    if _vol_cache.get("ver") == ver:
        return _vol_cache["out"]
    out = {"tests": [], "note": ""}
    for sym in ("NIFTY", "BANKNIFTY"):
        hist = oh.load(sym)
        if hist.empty:
            continue
        try:
            out["tests"].append(osg.vol_backtest(sym, hist, vol_svc.atm_iv_series(sym)))
        except Exception as e:
            out["tests"].append({"symbol": sym, "error": f"{type(e).__name__}: {e}"})
    days = oh.summary().get("days", 0)
    out["note"] = (f"Monthly iron condor (shorts 4% out, wings 6%, entry ~35 days before expiry, profit taken at half "
                   f"the credit, stopped at a loss of one credit) on NSE's daily option closes: sold only when the IV "
                   f"rank and percentile were both {osg.IV_HIGH:.0f}+ vs sold every month. {days} days of history"
                   + ("" if days >= 400 else " - fetch 2 years on the Options backtest page for a fairer test") + ".")
    _vol_cache.update(ver=ver, out=out)
    return out
