"""Intraday backtest re-run in the background, plus the GET /api/intraday payload.

Run as a module (the API starts it with CREATE_NO_WINDOW):
    python -m web.api.services.intraday_job --status data/results/intraday_status.json [--no-update]
It calls scanner.intraday.run.run_intraday_all(config), which refreshes the 5-minute bars from Yahoo (unless
--no-update), re-tests every intraday strategy and writes data/results/intraday.json.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
import traceback
from pathlib import Path

NO_WINDOW = 0x08000000 if os.name == "nt" else 0
LOCK_NAME = ".intraday.lock"      # next to the status file (paths.P.intraday_lock)


def main() -> int:
    ap = argparse.ArgumentParser(description="Re-run the intraday backtest")
    ap.add_argument("--status", required=True)
    ap.add_argument("--lock", help="lock file held while the job runs (default: .intraday.lock next to --status)")
    ap.add_argument("--no-update", action="store_true")
    args = ap.parse_args()
    root = Path(__file__).resolve().parents[3]
    sys.path.insert(0, str(root))
    from scanner.lock import _try_lock, _unlock
    from scanner.settings import load_config
    from scanner.intraday.run import run_intraday_all

    # One job at a time, also across API restarts: the lock tells a new API process that this job still runs.
    fh = open(args.lock or Path(args.status).with_name(LOCK_NAME), "a+")
    deadline = time.monotonic() + 2.0           # a status probe holds the lock for an instant
    locked = _try_lock(fh)
    while not locked and time.monotonic() < deadline:
        time.sleep(0.1)
        locked = _try_lock(fh)
    if not locked:
        fh.close()
        return 2                                # another run owns the status file: leave it alone
    try:
        state = {"state": "running", "message": "Starting...", "started": time.time(), "pid": os.getpid()}

        def write(**kw):
            state.update(kw)
            try:
                Path(args.status).write_text(json.dumps(state), encoding="utf-8")
            except OSError:
                pass
        write()
        try:
            r = run_intraday_all(load_config(), update=not args.no_update, log=lambda m: write(message=str(m)[:300]))
        except Exception as e:
            write(state="failed", message=f"{type(e).__name__}: {e}"[:500], trace=traceback.format_exc()[-2000:])
            return 1
        write(state="done", message=f"Done in {r.get('elapsed_s')}s: {len(r.get('strategies', []))} strategies")
        return 0
    finally:
        _unlock(fh)
        fh.close()


# ------------------------------------------------------------------ used by the API process
_lock = threading.Lock()
_proc: dict = {"popen": None}


def _job_holds_lock() -> bool:
    """A job is running that this API process did not start (it was restarted while the job ran): the job
    holds its lock file. Probed like scanner.lock.running_scan (never os.kill(pid, 0): on Windows that
    sends CTRL_C_EVENT)."""
    from scanner.lock import _try_lock, _unlock
    from ..paths import P
    if not P.intraday_lock.exists():
        return False
    try:
        with open(P.intraday_lock, "a+") as fh:
            if _try_lock(fh):
                _unlock(fh)
                return False
    except OSError:
        return False
    return True


def run_status() -> dict:
    from ..paths import P
    from ..util import iso_dt_from_epoch
    from . import data
    s = data.read_json_file(P.intraday_status) or {}
    pop = _proc["popen"]
    code = pop.poll() if pop is not None else None
    alive = pop is not None and code is None
    # a job started by an earlier API process (restart while it ran); only probed when the file says running
    # and we have no live process of our own
    orphan = not alive and s.get("state") == "running" and _job_holds_lock()
    state = s.get("state") or "idle"
    if alive or orphan:
        state = "running"
    elif state == "running":
        state = "failed" if pop is None or code not in (None, 0) else state
    elif code not in (None, 0) and state not in ("done", "failed"):
        state = "failed"            # exited before its first status write (e.g. an import error)
    if state == "failed" and s.get("state") in ("running", None):
        s["message"] = s.get("message") or "The intraday run stopped without finishing."
    return {"state": state if state in ("idle", "running", "done", "failed") else "idle", "running": alive or orphan,
            "message": s.get("message"), "started_at": iso_dt_from_epoch(s.get("started")),
            "pid": pop.pid if alive else s.get("pid"), "exit_code": code}


def start(update: bool = True) -> dict:
    from ..errors import ApiException
    from ..paths import P
    with _lock:
        pop = _proc["popen"]
        if pop is not None and pop.poll() is None:
            raise ApiException("SCAN_BUSY", "The intraday backtest is already running.", None,
                               {"started": "running", "by": "platform", "pid": pop.pid})
        if _job_holds_lock():
            raise ApiException("SCAN_BUSY", "The intraday backtest is already running (scheduled task, intraday_sync.py or before a restart).",
                               "Wait for it to finish.", {"started": "running", "by": "platform", "pid": None})
        P.intraday_status.unlink(missing_ok=True)
        args = [sys.executable, "-m", "web.api.services.intraday_job", "--status", str(P.intraday_status),
                "--lock", str(P.intraday_lock)]
        if not update:
            args.append("--no-update")
        _proc["popen"] = subprocess.Popen(args, cwd=str(P.root), creationflags=NO_WINDOW, stdout=subprocess.DEVNULL,
                                          stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
    return run_status()


if __name__ == "__main__":
    sys.exit(main())
