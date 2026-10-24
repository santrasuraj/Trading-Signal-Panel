"""One FYERS API rate limiter shared by every process (scans, intraday sync, live service, web API).

FYERS limits (fyers.in/api-docs/v3 "Plans & limits"):
  Standard (free)  data APIs (history, quotes, depth):  5 / second,  50 / minute,   5,000 / day
                   user APIs (profile, holdings, funds): 10 / second, 200 / minute, 100,000 / day
  Prime            data APIs: 10 / second, 500 / minute, 5,00,000 / day
Breaching a per-minute limit more than 3 times in a day blocks the user for the REST OF THE DAY
(error codes -429 / -360). So this limiter:
  * runs below the limits (safety margins),
  * counts calls in a file shared by all processes (data/fyers_usage.json, guarded by a file lock),
  * after a rate-limit error ("strike") makes EVERY process wait for a fresh minute window,
  * after 2 strikes in a day stops using FYERS until tomorrow (callers fall back to other sources),
    so the blocking third strike can never happen.
The day (counts and strikes) resets at IST midnight; the last minute's call times carry over, so calls just
before and just after midnight still respect the per-minute limit.
The WebSocket (live ticks) does not count against these REST limits.
"""
from __future__ import annotations

import json
import math
import os
import time
from contextlib import contextmanager

from .settings import DATA_DIR, ist_today

STATE_FILE = DATA_DIR / "fyers_usage.json"
LOCK_FILE = DATA_DIR / ".fyers_usage.lock"

# (per second, per minute, per day) actually used - each a little under the published limit.
LIMITS = {
    "standard": {"data": (4, 45, 4500), "user": (8, 180, 90000)},
    "prime": {"data": (9, 450, 450000), "user": (9, 450, 450000)},
}
MAX_STRIKES = 2
STRIKE_PAUSE_S = 61.0        # after a rate-limit error nobody calls FYERS until a fresh minute window
LOCK_TIMEOUT_S = 10.0


class FyersRateLimited(RuntimeError):
    """FYERS budget for today is used up (or we stopped after rate-limit strikes) - use another source."""


@contextmanager
def _file_lock(timeout: float = LOCK_TIMEOUT_S):
    """Exclusive cross-process lock. Windows: msvcrt locks bytes from the CURRENT file position, so always
    lock/unlock byte 0 (seek first); LK_NBLCK + our own retry loop instead of LK_LOCK's fixed 10 s.
    A lock that stays busy raises FyersRateLimited, which every caller already handles (falls back)."""
    try:
        fh = open(LOCK_FILE, "a+")       # creates the file if missing
    except OSError as e:                 # antivirus / permissions: fall back like a busy lock, never crash
        raise FyersRateLimited(f"FYERS usage lock cannot be opened ({type(e).__name__}) - "
                               "skipping FYERS for now") from e
    locked = False
    deadline = time.monotonic() + timeout
    try:
        while True:
            try:
                if os.name == "nt":
                    import msvcrt
                    fh.seek(0)
                    msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                locked = True
                break
            except OSError:
                if time.monotonic() > deadline:
                    raise FyersRateLimited("FYERS usage file is busy (another program holds its lock) - "
                                           "skipping FYERS for now") from None
                time.sleep(0.02)
        yield
    finally:
        if locked:
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
        fh.close()


def _blank(day: str) -> dict:
    return {"date": day, "strikes": 0, "pause_until": 0.0, "buckets": {}}


def _normalise(raw) -> dict:
    """Coerce whatever is on disk into the current schema (an older or hand-edited file must not crash)."""
    if not isinstance(raw, dict):
        raise ValueError("usage state is not an object")
    buckets = {}
    src = raw.get("buckets")
    if isinstance(src, dict):
        for name, b in src.items():
            if not isinstance(b, dict):
                continue
            # json.loads accepts NaN / Infinity: drop them (time.sleep(nan) would raise ValueError).
            recent = sorted(float(t) for t in (b.get("recent") or [])
                            if isinstance(t, (int, float)) and not isinstance(t, bool) and math.isfinite(t))
            buckets[str(name)] = {"count": max(int(b.get("count") or 0), 0), "recent": recent}
    pause = float(raw.get("pause_until") or 0.0)
    return {"date": str(raw.get("date") or ""), "strikes": max(int(raw.get("strikes") or 0), 0),
            "pause_until": pause if math.isfinite(pause) else 0.0, "buckets": buckets}


def _load(strict: bool = True) -> dict:
    """Today's usage state.

    strict=True (used while holding the lock, before a write): if the file exists but cannot be read
    (Windows: another program has it open exclusively), raise FyersRateLimited rather than start again
    from zero - writing a fresh state back would forget today's strikes and calls."""
    today = ist_today().isoformat()
    text = None
    for i in range(5):
        try:
            text = STATE_FILE.read_text(encoding="utf-8")
            break
        except FileNotFoundError:
            return _blank(today)
        except ValueError:               # undecodable bytes: treat like a damaged file below
            text = ""
            break
        except OSError:
            time.sleep(0.05 * (i + 1))
    if text is None:
        if strict:
            raise FyersRateLimited("FYERS usage file cannot be read right now - skipping FYERS for now")
        return _blank(today)
    try:
        state = _normalise(json.loads(text))
    except (ValueError, TypeError, ArithmeticError):
        # Damaged file (_save never leaves one half-written): start a fresh count.
        return _blank(today)
    if state["date"] != today:
        # New IST day: counts and strikes reset, the last minute's call times and any pause carry over.
        state = {**_blank(today), "pause_until": state["pause_until"],
                 "buckets": {k: {"count": 0, "recent": v["recent"]} for k, v in state["buckets"].items()}}
    return state


def _save(state: dict) -> None:
    """Atomic write (tmp file + os.replace). On Windows os.replace raises PermissionError while another
    process has the file open (a status read, antivirus): retry, then rewrite it in place (we hold the
    lock, so no other writer can interleave). An update is never dropped silently."""
    body = json.dumps(state)
    tmp = STATE_FILE.with_name(f"{STATE_FILE.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(body, encoding="utf-8")
    except OSError as e:
        raise FyersRateLimited(f"Could not record FYERS usage ({type(e).__name__}) - skipping FYERS for now") from e
    for i in range(8):
        try:
            os.replace(tmp, STATE_FILE)
            return
        except OSError:                  # PermissionError on Windows; anything else: the in-place write below
            time.sleep(0.05 * (i + 1))
    try:
        STATE_FILE.write_text(body, encoding="utf-8")
    except OSError as e:
        raise FyersRateLimited(f"Could not record FYERS usage ({type(e).__name__}) - skipping FYERS for now") from e
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass


class FyersLimiter:
    def __init__(self, plan: str = "standard"):
        self.limits = LIMITS.get(str(plan).lower(), LIMITS["standard"])

    def acquire(self, bucket: str = "data") -> None:
        """Block until one more call in `bucket` is allowed; raise FyersRateLimited if the day's budget is
        exhausted or we stopped after strikes."""
        per_sec, per_min, per_day = self.limits.get(bucket, self.limits["data"])
        while True:
            with _file_lock():
                state = _load(strict=True)
                if state["strikes"] >= MAX_STRIKES:
                    raise FyersRateLimited("Stopped using FYERS for today after rate-limit warnings "
                                           "(a third breach would block your account for the day)")
                b = state["buckets"].setdefault(bucket, {"count": 0, "recent": []})
                if b["count"] >= per_day:
                    raise FyersRateLimited(f"FYERS daily {bucket} budget used ({b['count']} calls) - resumes tomorrow")
                now = time.time()
                if (b["recent"] and b["recent"][-1] > now) or state["pause_until"] > now + STRIKE_PAUSE_S:
                    # The wall clock was set back: re-date those calls to now and cap the strike pause at one
                    # window (and save), so they still count but cannot block us until the clock catches up.
                    b["recent"] = [min(t, now) for t in b["recent"]]
                    state["pause_until"] = min(state["pause_until"], now + STRIKE_PAUSE_S)
                    _save(state)
                b["recent"] = [t for t in b["recent"] if now - t < 60]
                last_sec = [t for t in b["recent"] if now - t < 1]
                wait = min(state["pause_until"] - now, STRIKE_PAUSE_S)    # a strike pauses every process
                if len(b["recent"]) >= per_min:
                    wait = max(wait, 60 - (now - b["recent"][-per_min]) + 0.05)
                if len(last_sec) >= per_sec:
                    wait = max(wait, 1 - (now - last_sec[-per_sec]) + 0.02)
                if wait <= 0:
                    b["recent"].append(now)
                    b["count"] += 1
                    _save(state)
                    return
            time.sleep(min(wait, 5.0))

    def strike(self) -> int:
        """Record a rate-limit error from FYERS and pause every process for a fresh minute window.
        Returns today's strike count (MAX_STRIKES or more = FYERS is off until tomorrow)."""
        with _file_lock(timeout=30.0):
            state = _load(strict=True)
            state["strikes"] += 1
            state["pause_until"] = max(state["pause_until"], time.time() + STRIKE_PAUSE_S)
            _save(state)
            return state["strikes"]

    def usage(self) -> dict:
        """Today's usage for display: calls per bucket, limits, strikes (read-only, never raises)."""
        state = _load(strict=False)
        out = {"date": state["date"], "strikes": state["strikes"], "stopped": state["strikes"] >= MAX_STRIKES}
        for bucket, (ps, pm, pd_) in self.limits.items():
            b = state["buckets"].get(bucket, {"count": 0, "recent": []})
            out[bucket] = {"calls_today": b["count"], "daily_limit": pd_, "per_minute": pm, "per_second": ps,
                           "remaining_today": max(pd_ - b["count"], 0)}
        return out


def usage(plan: str = "standard") -> dict:
    return FyersLimiter(plan).usage()
