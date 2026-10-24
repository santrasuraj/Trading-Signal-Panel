"""One scan at a time across processes (scheduled task, dashboard, manual run)."""
from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager

from .settings import DATA_DIR, ist_now

LOCK_FILE = DATA_DIR / ".scan.lock"
INFO_FILE = DATA_DIR / ".scan.lock.json"
ACQUIRE_GRACE_S = 2.0   # running_scan() probes take the lock for an instant: don't mistake that for a scan


class ScanBusy(RuntimeError):
    pass


def _try_lock(fh) -> bool:
    try:
        if os.name == "nt":
            import msvcrt
            fh.seek(0)   # msvcrt locks from the current position ("a+" starts at the end): always byte 0
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def _unlock(fh) -> None:
    try:
        if os.name == "nt":
            import msvcrt
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass


def running_scan() -> dict | None:
    """Info about a scan currently holding the lock, or None."""
    if not LOCK_FILE.exists():
        return None
    with open(LOCK_FILE, "a+") as fh:
        if _try_lock(fh):
            _unlock(fh)
            return None
    try:
        return json.loads(INFO_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"started": "?", "by": "?"}


@contextmanager
def scan_lock(by: str):
    fh = open(LOCK_FILE, "a+")
    deadline = time.monotonic() + ACQUIRE_GRACE_S
    locked = _try_lock(fh)
    while not locked and time.monotonic() < deadline:
        time.sleep(0.1)
        locked = _try_lock(fh)
    if not locked:
        fh.close()
        info = running_scan() or {}
        raise ScanBusy(f"A scan is already running (started {info.get('started', '?')} by {info.get('by', '?')}). "
                       "Wait for it to finish.")
    try:
        INFO_FILE.write_text(json.dumps({"started": ist_now().strftime("%H:%M:%S"), "by": by, "pid": os.getpid()}),
                             encoding="utf-8")
        yield
    finally:
        _unlock(fh)
        fh.close()
