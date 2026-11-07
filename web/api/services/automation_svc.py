"""Automatic jobs: what setup_schedule.ps1 registers in Windows Task Scheduler, whether each one is there and how its
last run went, and a one-click setup / repair that runs the script (no PowerShell window for the user).

Status reads one `schtasks /query` per job in parallel (~1 s; the full task list takes 12 s, PowerShell's
Get-ScheduledTask 16 s), cached for a minute. Nothing here needs admin rights: the tasks are the user's own.
"""
from __future__ import annotations

import csv
import io
import os
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from ..errors import ApiException
from ..paths import P

NO_WINDOW = 0x08000000 if os.name == "nt" else 0
CACHE_S = 60
SETUP_TIMEOUT_S = 180
# (task name, when, what): the tasks setup_schedule.ps1 registers, in the order of a trading day
JOBS = [
    ("NSE Scanner 0830", "Weekdays 08:30", "Scan on yesterday's official NSE data; Telegram summary"),
    ("NSE Scanner option chains", "Weekdays 09:12", "Option chains every minute in market hours; collects last night's Claude forecasts"),
    ("NSE Scanner intraday live", "Weekdays 09:14", "Live 5-minute bars from the FYERS feed (starts once you log in to Fyers)"),
    ("NSE Scanner intraday signals", "Weekdays 09:20-15:05, every 5 min", "Intraday signals (proven strategies only) and Big money live"),
    ("NSE Scanner live", "Weekdays 09:45-15:15, every 30 min", "Live scan on today's candle (provisional signals)"),
    ("NSE Scanner 1540", "Weekdays 15:40", "Scan right after the close; Telegram summary"),
    ("NSE Scanner intraday archive", "Weekdays 15:45", "Today's FYERS 5-minute bars (the first time: a year of history) and the intraday re-test"),
    ("NSE Scanner 1915", "Weekdays 19:15", "Scan on NSE's official end-of-day files (final signals); Telegram summary"),
    ("NSE Scanner F&O positioning", "Weekdays 19:30", "F&O positions and build-ups, then Claude's option-chain forecasts"),
    ("NSE Scanner pattern study", "Saturdays 11:00", "Re-tests every candle and chart pattern on 8 years of data (~17 min)"),
]
# Windows' LastTaskResult codes worth a word (others are shown as their hex code)
RESULTS = {0: "ok", 267011: "not run yet", 267009: "running", 267014: "stopped by Windows (time limit)",
           2147946720: "Windows did not start it (signed out, or the previous run was still going)"}
DATE_FORMATS = ("%d-%m-%Y %H:%M:%S", "%d/%m/%Y %H:%M:%S", "%m/%d/%Y %I:%M:%S %p", "%m/%d/%Y %H:%M:%S",
                "%Y-%m-%d %H:%M:%S")

_cache: dict = {"at": 0.0, "status": None}
_lock = threading.Lock()


def _when(s: str | None) -> str | None:
    """Windows prints dates in the PC's own format: ISO where it can be read, else as shown; 'N/A' is none."""
    s = (s or "").strip()
    if not s or s.upper() in ("N/A", "NEVER") or s.startswith("30-11-1999") or s.startswith("11/30/1999"):
        return None
    for f in DATE_FORMATS:
        try:
            return datetime.strptime(s, f).isoformat(timespec="minutes")
        except ValueError:
            continue
    return s


def _result(code: str | None) -> tuple[str | None, bool | None]:
    try:
        n = int(str(code).strip())
    except (TypeError, ValueError):
        return None, None
    n &= 0xFFFFFFFF
    if n in RESULTS:
        word = RESULTS[n]
        return word, (True if n == 0 else None if n in (267011, 267009) else False)
    return f"failed (code 0x{n:X})", False


def _query(name: str) -> dict:
    """One task, by name: (registered, state, next, last, result). Columns by position (their titles are in the
    PC's language): 1 name, 2 next run, 3 status, 5 last run, 6 last result."""
    try:
        r = subprocess.run(["schtasks", "/query", "/tn", name, "/fo", "csv", "/v"], capture_output=True, text=True,
                           timeout=20, creationflags=NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired):
        return {"registered": False}
    rows = list(csv.reader(io.StringIO(r.stdout or "")))
    if r.returncode != 0 or len(rows) < 2 or len(rows[1]) < 7:
        return {"registered": False}
    row = rows[1]
    word, ok = _result(row[6])
    return {"registered": True, "state": row[3].strip() or None, "next_run": _when(row[2]), "last_run": _when(row[5]),
            "last_result": word, "ok": ok}


def status(refresh: bool = False) -> dict:
    with _lock:
        if not refresh and _cache["status"] is not None and time.monotonic() - _cache["at"] < CACHE_S:
            return _cache["status"]
    if os.name != "nt":
        out = {"available": False, "jobs": [{"name": n, "when": w, "what": t, "registered": False} for n, w, t in JOBS],
               "missing": len(JOBS), "note": "Automatic jobs use Windows Task Scheduler (this PC is not Windows)."}
    else:
        with ThreadPoolExecutor(max_workers=len(JOBS)) as ex:
            found = list(ex.map(_query, [n for n, _, _ in JOBS]))
        jobs = [{"name": n, "when": w, "what": t, **f} for (n, w, t), f in zip(JOBS, found)]
        out = {"available": True, "jobs": jobs, "missing": sum(1 for j in jobs if not j["registered"]),
               "note": "Windows runs these while you are signed in to this PC (a sleeping PC catches up when it wakes, "
                       "a shut-down PC misses them). Fyers asks for one login each morning: the live jobs wait for it."}
    with _lock:
        _cache.update(at=time.monotonic(), status=out)
    return out


def setup() -> dict:
    """Run setup_schedule.ps1 (registers or repairs every job, idempotent) and return its output and the new status."""
    if os.name != "nt":
        raise ApiException("FEATURE_UNAVAILABLE", "Automatic jobs need Windows Task Scheduler.", None,
                           {"feature": "automation"})
    script = P.root / "setup_schedule.ps1"
    if not script.exists():
        raise ApiException("NOT_FOUND", "setup_schedule.ps1 is missing next to the app.", None)
    if ".worktrees" in P.root.parts:
        raise ApiException("VALIDATION", "This copy of the app is a git worktree.",
                           "Set up the automatic jobs from the main copy of the app: tasks from a worktree would "
                           "replace the main copy's tasks.")
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
                            str(script)], cwd=str(P.root), capture_output=True, text=True, timeout=SETUP_TIMEOUT_S,
                           creationflags=NO_WINDOW, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        raise ApiException("INTERNAL", "Setting up the automatic jobs took too long.", "Try again in a minute.")
    except OSError as e:
        raise ApiException("INTERNAL", f"PowerShell could not be started ({type(e).__name__}).", None)
    lines = [ln.rstrip() for ln in ((r.stdout or "") + (r.stderr or "")).splitlines() if ln.strip()]
    st = status(refresh=True)
    return {"ok": r.returncode == 0 and st["missing"] == 0, "output": lines[-30:], "status": st}
