"""Results reaction (GET /api/results-study, POST /api/results-study/run): the tested record of how stocks moved
after their quarterly results, by the first reaction (scanner/results_study.py), and the stocks that reported in the
last weeks with their reaction and what that bucket did historically."""
from __future__ import annotations

import threading
from datetime import timedelta

import pandas as pd

from scanner import results_study as rs

from . import data
from ..util import now_ist, today_ist

_job = {"running": False, "error": None, "finished": None}


def start() -> dict:
    if _job["running"]:
        return view()
    _job.update(running=True, error=None)

    def work():
        try:
            rs.run(log=lambda *_: None)
        except Exception as e:
            _job["error"] = f"{type(e).__name__}: {e}"
        finally:
            _job.update(running=False, finished=now_ist().isoformat(timespec="seconds"))
    threading.Thread(target=work, name="results-study", daemon=True).start()
    return view()


def recent(days: int = 30) -> list[dict]:
    """Universe stocks that reported in the last `days` days: reaction, the move since, and their bucket."""
    try:
        close = data.store_close()
    except Exception:
        return []
    uni = set(data.universe()["symbol"])
    cols = [c for c in close.columns if c in uni]
    if not cols:
        return []
    c = close[cols].iloc[-260:]
    member = c.notna()
    since = pd.Timestamp(today_ist() - timedelta(days=days))
    dates = [(s, d) for s, d in rs.results_dates() if d >= since and s in uni]
    ev = rs.events_table(c, member, dates)
    if ev.empty:
        return []
    names = dict(zip(data.universe()["symbol"], data.universe()["company"]))
    out = []
    for r in ev.sort_values("date", ascending=False).itertuples(index=False):
        t1 = int(r.t1)
        last = c[r.symbol].dropna()
        p1 = float(c[r.symbol].iat[t1])
        out.append({"symbol": r.symbol, "company": names.get(r.symbol), "date": r.date.date().isoformat(),
                    "reaction": round(float(r.reaction), 2), "bucket": r.bucket,
                    "since_pct": round((float(last.iloc[-1]) / p1 - 1) * 100, 2) if p1 > 0 else None,
                    "days_since": int(len(c) - 1 - t1)})
    return out


def view() -> dict:
    study = rs.load()
    return {"study": study, "job": dict(_job), "recent": recent(),
            "note": "Reaction = the move from the close before the results day to the close after it, against the average "
                    "stock. History: the same bucket's excess return over the next 5 / 20 / 60 trading days since 2018, "
                    "survivorship-free, 0.45% round-trip costs. A fall is only tradable short through F&O."}
