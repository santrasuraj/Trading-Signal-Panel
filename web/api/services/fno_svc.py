"""F&O positioning page: reads data/fno/ (written by scanner/fno.py) - never NSE, except the POST /refresh job, which
runs scanner.fno.refresh in a background thread of this process."""
from __future__ import annotations

import threading
from datetime import date

import pandas as pd

from scanner import fno

from .. import errors
from ..caches import KeyedCache, file_key, register
from ..errors import ApiException
from ..paths import P
from ..util import inum, now_ist, num

NOTE_POSITIONS = ("NSE's participant-wise open interest after each close (contracts). FII = foreign portfolio "
                  "investors, DII = domestic institutions, Pro = brokers trading their own money, Client = everyone "
                  "else. Totals per group - NSE names no one. Positioning, not a signal.")
NOTE_FUTURES = ("NSE's F&O bhavcopy after the close. Build-up compares the nearest future's price change with the "
                "change in open interest (all expiries; under 2% counts as no build-up). Call / put wall: the strike "
                "with the most open interest in the nearest expiry. Positioning, not a signal.")

_part = register(KeyedCache(1))
_fut = register(KeyedCache(1))


def _participants() -> pd.DataFrame:
    return _part.get(file_key(P.fno / fno.PART_NAME), fno.load_participants)


def _futures() -> pd.DataFrame:
    return _fut.get(file_key(P.fno / fno.FUT_NAME), fno.load_futures)


def positions(days: int) -> dict:
    return {**fno.positions(_participants(), days), "note": NOTE_POSITIONS}


def futures(day: str | None, kind: str, buildup: str, sort: str, limit: int) -> dict:
    fut = _futures()
    dates = sorted({d.isoformat() for d in pd.to_datetime(fut["date"]).dt.date}, reverse=True) if len(fut) else []
    d, rows = fno.day_futures(fut, date.fromisoformat(day) if day else None)
    if day and d is not None and rows.empty:
        raise ApiException("NOT_FOUND", f"No F&O data stored for {day}.", f"Stored days: {', '.join(dates[:5])}...")
    counts = {b: int((rows["buildup"] == b).sum()) for b in ("long_buildup", "short_buildup", "short_covering",
                                                              "long_unwinding")}
    if kind != "all":
        rows = rows[rows["kind"] == kind]
    if buildup != "all":
        rows = rows[rows["buildup"] == buildup]
    key = {"oi_chg": rows["oi_chg_pct"].abs(), "chg": rows["chg_pct"].abs(), "value": rows["value_cr"],
           "pcr": rows["pcr"]}[sort]
    rows = rows.assign(_k=key).sort_values("_k", ascending=False, na_position="last").head(limit)
    out = []
    for r in rows.itertuples(index=False):
        lot = r.lot if pd.notna(r.lot) and r.lot > 0 else None
        out.append({"symbol": str(r.symbol), "kind": str(r.kind), "close": num(r.close, 2), "chg_pct": num(r.chg_pct, 2),
                    "oi_contracts": inum(r.oi / lot) if lot else None,
                    "oi_chg_contracts": inum(r.oi_chg / lot) if lot else None,
                    "oi_chg_pct": num(r.oi_chg_pct, 2), "volume": inum(r.volume), "value_cr": num(r.value_cr, 1),
                    "lot": inum(lot), "basis_pct": num(r.basis_pct, 2),
                    "buildup": r.buildup if isinstance(r.buildup, str) else None, "pcr": num(r.pcr, 2),
                    "call_wall": num(r.call_wall, 2), "put_wall": num(r.put_wall, 2)})
    return {"date": d.isoformat() if d else None, "dates": dates, "counts": counts, "rows": out, "note": NOTE_FUTURES}


def status() -> dict:
    fut = _futures()
    ds = sorted(pd.to_datetime(fut["date"]).dt.date.unique()) if len(fut) else []
    last = (fno.load_state().get("last_refresh") or {})
    return {"run": run_status(), "days": len(ds), "first_day": ds[0].isoformat() if ds else None,
            "last_day": ds[-1].isoformat() if ds else None, "last_refresh_at": last.get("started_at"),
            "pending": [str(x) for x in last.get("pending") or []], "errors": [str(x) for x in last.get("errors") or []]}


# ------------------------------------------------------------------ background refresh
_run_lock = threading.Lock()
_run: dict = {"thread": None, "state": "idle", "message": None, "started_at": None, "finished_at": None, "errors": []}


def run_status() -> dict:
    alive = _run["thread"] is not None and _run["thread"].is_alive()
    return {"state": "running" if alive else _run["state"], "running": alive, "message": _run["message"],
            "started_at": _run["started_at"], "finished_at": _run["finished_at"], "errors": list(_run["errors"])}


def start_refresh(days: int) -> dict:
    with _run_lock:
        if _run["thread"] is not None and _run["thread"].is_alive():
            raise ApiException("SCAN_BUSY", "An F&O refresh is already running.",
                               "Wait for it to finish - this page updates by itself.",
                               {"started": str(_run["started_at"] or "?"), "by": "fno", "pid": None})
        _run.update(state="running", message="Starting...", started_at=now_ist().isoformat(timespec="seconds"),
                    finished_at=None, errors=[])
        t = threading.Thread(target=_worker, args=(days,), name="fno-refresh", daemon=True)
        _run["thread"] = t
        t.start()
    return run_status()


def _worker(days: int) -> None:
    try:
        rep = fno.refresh(days, log=lambda m: _run.update(message=str(m).strip()[:300]))
        n, errs = len(rep["added"]), [str(e) for e in rep["errors"]]
        if n or not errs:
            msg = (f"{n} day{'s' if n != 1 else ''} added" if n else "Already up to date") + \
                  (f"; {len(rep['pending'])} not published yet" if rep["pending"] else "")
            _run.update(state="done", message=msg, errors=errs)
        else:
            _run.update(state="failed", message=f"Nothing fetched: {errs[0]}"[:300], errors=errs)
    except Exception as e:
        errors.log.exception("F&O refresh failed")
        _run.update(state="failed", message=f"{type(e).__name__}: {e}"[:300])
    finally:
        _run["finished_at"] = now_ist().isoformat(timespec="seconds")
