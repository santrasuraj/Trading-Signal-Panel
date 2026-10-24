"""Start the daily scan as a background process and merge its state from files (spec 6.14, review A6).

State merge (same logic as app.py's scan_monitor):
- our own scan process is alive -> starting / running (or its final state while it is exiting);
- the lock is held (any scan: platform, dashboard, scheduled task) or we launched < 30 s ago and the status
  file is not final -> running / starting;
- otherwise status.json's state (done / failed / busy), or idle when there is no file;
- our process exited non-zero without writing a final status -> failed with a pointer to the log.
status.json 'progress' is a 0..1 fraction (-> progress_pct x 100); its 'started' is epoch seconds and the
lock's 'started' is 'HH:MM:SS' (today, IST) - both become ISO datetimes.
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from datetime import datetime

from scanner.lock import running_scan
from scanner.settings import IST

from . import data
from ..errors import ApiException
from ..paths import P
from ..util import iso_dt_from_epoch, now_ist, num

NO_WINDOW = 0x08000000 if os.name == "nt" else 0       # CREATE_NO_WINDOW
FINAL = ("done", "failed", "busy")

_lock = threading.Lock()
_proc: dict = {"popen": None, "at": 0.0, "update": None, "wall": 0.0}


def _lock_started(hhmmss) -> str | None:
    try:
        t = datetime.strptime(str(hhmmss), "%H:%M:%S").time()
    except ValueError:
        return None
    now = now_ist()
    dt = datetime.combine(now.date(), t, IST)
    return dt.isoformat(timespec="seconds")


def _own_lock_info() -> dict | None:
    """The lock info our running scan wrote: by 'platform' and written after we launched it. Not matched on
    pid: the venv's python.exe is a launcher, so the scanning interpreter has another pid than Popen.pid."""
    info = data.read_json_file(P.lock_info) or {}
    try:
        fresh = P.lock_info.stat().st_mtime >= _proc.get("wall", 0.0) - 2
    except OSError:
        fresh = False
    return info if fresh and info.get("by") == "platform" else None


def status() -> dict:
    s = data.status_file()
    pop = _proc["popen"]
    launched = time.monotonic() - _proc["at"] < 30 if _proc["at"] else False
    exit_code = pop.poll() if pop is not None else None
    file_state = s.get("state")
    started_at = iso_dt_from_epoch(s.get("started"))
    prog = num(s.get("progress"))
    out = {"state": "idle", "running": False, "progress_pct": round(prog * 100, 1) if prog is not None else None,
           "message": s.get("message"), "started_at": started_at, "by": None, "pid": None,
           "update": _proc["update"], "exit_code": exit_code}
    if pop is not None and exit_code is None:
        # Our own scan is alive. Read the lock info without probing the lock, so a status poll can never grab
        # the lock in the instant the new process tries to take it. Once it has written its final state it is
        # only exiting (e.g. sending Telegram): report that state, not "starting".
        info = _own_lock_info() if file_state not in FINAL else None
        running = file_state not in FINAL
        out.update(state=file_state if not running else ("running" if file_state == "running" else "starting"),
                   running=running, by="platform", pid=(info or {}).get("pid") or pop.pid)
        if info and running and not (file_state == "running" and started_at):
            out["started_at"] = _lock_started(info.get("started"))
        return out
    lock = running_scan()
    if lock:
        out.update(state="running", running=True, by=lock.get("by"), pid=lock.get("pid"),
                   started_at=started_at if file_state == "running" and started_at else _lock_started(lock.get("started")))
        if file_state != "running" and lock.get("by") != "platform":
            out["progress_pct"], out["message"] = None, f"Scan started by {lock.get('by')}"
        return out
    if exit_code not in (None, 0) and file_state not in FINAL:
        # died early (e.g. an import error before its first status write): failed, not "starting" for 30 s
        out.update(state="failed", message=f"Scan process exited (code {exit_code}), see data/logs/scanner.log")
        return out
    if launched and file_state not in FINAL:
        out.update(state="starting", running=True, by="platform", pid=pop.pid if pop else None)
        return out
    if file_state in FINAL:
        out["state"] = file_state
    elif file_state == "running":
        # status says running but no lock and no live process: the scan died without a final status
        out.update(state="failed", message=s.get("message") or "The scan stopped without finishing; see data/logs/scanner.log")
    return out


def start(update: bool = True) -> dict:
    with _lock:
        lock = running_scan()
        if lock:
            raise ApiException("SCAN_BUSY", f"A scan is already running (started {lock.get('started', '?')} by "
                               f"{lock.get('by', '?')}).", "Wait for it to finish - progress shows in the top bar.",
                               {"started": str(lock.get("started", "?")), "by": str(lock.get("by", "?")),
                                "pid": lock.get("pid")})
        pop = _proc["popen"]
        if pop is not None and pop.poll() is None:
            raise ApiException("SCAN_BUSY", "A scan is already starting.", None,
                               {"started": "now", "by": "platform", "pid": pop.pid})
        P.status.unlink(missing_ok=True)
        args = [sys.executable, str(P.run_scan), "--status", str(P.status), "--by", "platform"]
        if not update:
            args.append("--no-update")
        _proc["wall"] = time.time()         # lock info written after this belongs to this run
        _proc["popen"] = subprocess.Popen(args, cwd=str(P.root), creationflags=NO_WINDOW,
                                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                          stdin=subprocess.DEVNULL)
        _proc["at"], _proc["update"] = time.monotonic(), update
    return status()
