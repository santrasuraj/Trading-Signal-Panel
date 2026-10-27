"""Intraday jobs (FYERS first, inside the shared rate limiter).

  python intraday_sync.py --backfill      ~1 year of 5-minute history from FYERS (resumable; ~600 calls, ~14 min)
  python intraday_sync.py --archive       after the close: today's bars from FYERS into the store (~150 calls)
  python intraday_sync.py --live          real-time 5-minute bars from the FYERS WebSocket until 15:31
                                          (started before 09:13 it waits for the open; waits for today's login)
  python intraday_sync.py --run           backtest the intraday strategies
  python intraday_sync.py --signals       live signals from the strategies whose backtest passed (every 5 min)
  python intraday_sync.py --usage         FYERS calls used today vs the limits
Options combine, e.g. --archive --run (used by the 15:45 scheduled task).
Scheduled runs (pythonw, no console) write their output to data/logs/intraday.log.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from contextlib import contextmanager

from scanner.fyers_limits import usage
from scanner.intraday import fyers_sync, live
from scanner.intraday.run import INTRADAY_DIR, intraday_universe, run_intraday_all, run_intraday_signals
from scanner.lock import ScanBusy, _try_lock, _unlock
from scanner.providers import get_fyers
from scanner.settings import LOG_DIR, RESULTS_DIR, ist_now, load_config
from scanner.store import load_store

LOG_FILE = LOG_DIR / "intraday.log"
LOG_MAX_BYTES = 5_000_000
LIVE_LEAD_MINUTES = 2            # connect at 09:13 so the first 09:15 trades are not missed
# Shared with the web app's re-run (web/api/services/intraday_job.py, paths.P.intraday_lock). Not the daily
# scan lock: the 15:45 task must not fail just because the 15:40 daily scan is still running.
INTRADAY_LOCK = RESULTS_DIR / ".intraday.lock"


@contextmanager
def _intraday_lock():
    fh = open(INTRADAY_LOCK, "a+")
    deadline = time.monotonic() + 2.0           # a web status probe holds the lock for an instant
    locked = _try_lock(fh)
    while not locked and time.monotonic() < deadline:
        time.sleep(0.1)
        locked = _try_lock(fh)
    if not locked:
        fh.close()
        raise ScanBusy("The intraday backtest is already running (web app or another window). Wait for it to finish.")
    try:
        yield
    finally:
        _unlock(fh)
        fh.close()


def _log_to_file_if_windowless() -> None:
    """pythonw (the scheduled tasks) has no console: sys.stdout/stderr are None and every message and
    traceback would vanish. Send them to data/logs/intraday.log instead (rotated at ~5 MB)."""
    if sys.stdout is not None and sys.stderr is not None:
        return
    try:
        if LOG_FILE.exists() and LOG_FILE.stat().st_size > LOG_MAX_BYTES:
            LOG_FILE.replace(LOG_FILE.with_name(LOG_FILE.name + ".1"))
    except OSError:
        pass    # another intraday job has the log open (Windows): rotate next time
    f = open(LOG_FILE, "a", encoding="utf-8", buffering=1)
    sys.stdout = sys.stderr = f


def _wait_for_open() -> None:
    """The scheduled task starts at 09:14 and the .bat may be started earlier: wait until shortly before
    09:15 on a trading day instead of exiting with 'market closed'."""
    now = ist_now()
    first = now.replace(hour=9, minute=15 - LIVE_LEAD_MINUTES, second=0, microsecond=0)
    if fyers_sync.is_trading_day(now.date()) and (7, 0) <= (now.hour, now.minute) and now < first:
        print(f"Waiting for the market open (live feed starts {first:%H:%M})...", flush=True)
        time.sleep((first - now).total_seconds() + 1)


def main() -> int:
    _log_to_file_if_windowless()
    ap = argparse.ArgumentParser(description="Intraday data and strategies (FYERS first)")
    ap.add_argument("--backfill", action="store_true", help="~1 year of 5-minute history from FYERS (resumable)")
    ap.add_argument("--archive", action="store_true", help="after the close: today's bars from FYERS into the store")
    ap.add_argument("--live", action="store_true", help="real-time 5-minute bars from the FYERS WebSocket until 15:31")
    ap.add_argument("--run", action="store_true", help="backtest the intraday strategies")
    ap.add_argument("--signals", action="store_true",
                    help="today's live signals, only from strategies whose backtest shows a real edge")
    ap.add_argument("--usage", action="store_true", help="FYERS calls used today vs the limits (the default)")
    ap.add_argument("--days", type=int, default=None, help="history to keep (default: intraday.history_days)")
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(f"[{ist_now():%Y-%m-%d %H:%M:%S}] intraday_sync {' '.join(sys.argv[1:])}", flush=True)
    try:
        code = _run(args)
    except Exception:
        print(traceback.format_exc(), flush=True)
        code = 1
    print(f"[{ist_now():%Y-%m-%d %H:%M:%S}] finished (exit code {code})", flush=True)
    return code


def _run(args) -> int:
    cfg = load_config()
    plan = str(cfg.get("fyers_plan", "standard"))
    if args.usage or not any((args.backfill, args.archive, args.live, args.run, args.signals)):
        print(json.dumps(usage(plan), indent=1))
        return 0

    frames = load_store()
    symbols, _ = intraday_universe(cfg, frames)
    days = args.days or int((cfg.get("intraday") or {}).get("history_days", 365))

    if args.backfill or args.archive:
        fy, note = get_fyers(cfg)
        if fy is None:
            print(f"FYERS not available: {note}")
            if not args.run:
                return 1
        else:
            est = fyers_sync.plan_calls(symbols, INTRADAY_DIR, days)
            print(f"Needs {est['calls']} FYERS calls (~{est['minutes']} min). Calls today so far: "
                  f"{fy.limiter.usage()['data']['calls_today']}.")
            fyers_sync.sync(fy, symbols, INTRADAY_DIR, days, log=lambda m: print(m, flush=True),
                            progress=lambda i, n, s: print(f"  {i}/{n} {s}", flush=True) if i % 10 == 0 else None)

    if args.live:
        _wait_for_open()
        if not live.market_open_now(lead_minutes=LIVE_LEAD_MINUTES):
            print("Market is closed - the live feed runs 09:15-15:31 on trading days.")
        else:
            # the 100 most liquid intraday symbols (FYERS Standard plan WebSocket limit)
            live.run_live(symbols[: live.MAX_SYMBOLS], INTRADAY_DIR, log=lambda m: print(m, flush=True))

    if args.run:
        try:
            with _intraday_lock():
                run_intraday_all(cfg, frames=frames, log=lambda m: print(m, flush=True))
        except ScanBusy as e:
            print(e)
            return 2

    if args.signals:
        run_intraday_signals(cfg, frames=frames, log=lambda m: print(m, flush=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
