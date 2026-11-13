"""Results reaction study: what a stock did in the weeks after its quarterly results, by how the market first took
them. Same method as the pattern study (scanner/pattern_study.py): survivorship-free universe (scanner/pit.py),
returns measured against the average universe stock over the same days, t-statistics on monthly averages, costs.

  * Events: every results board meeting of a universe stock since Aug 2018 (NSE's event calendar,
    data/nse/results_YYYYMM.json).
  * Reaction: the stock's move from the close before the meeting day to the close after it (results come out
    during or after market hours), minus the average stock's move. Buckets: below -6%, -6 to -2%, -2 to +2%,
    +2 to +6%, above +6%.
  * After: the excess return from the close after the meeting over 5, 20 and 60 trading days. "Drift" = the reaction
    continues (a positive bucket keeps rising), "reversal" = it gives back. An edge needs t >= 2 and a positive
    result after a 0.45% round trip, traded in the reaction's direction (a short is an F&O trade in India).

    python -m scanner.results_study
"""
from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

from .settings import DATA_DIR

RESULT_FILE = DATA_DIR / "results" / "results_study.json"
HORIZONS = (5, 20, 60)
BUCKETS = ((-math.inf, -6.0, "Fell over 6%"), (-6.0, -2.0, "Fell 2-6%"), (-2.0, 2.0, "Within 2%"),
           (2.0, 6.0, "Rose 2-6%"), (6.0, math.inf, "Rose over 6%"))
COST_PCT = 0.45
MIN_EVENTS, MIN_MONTHS = 100, 24


def results_dates(folder: Path | None = None) -> list[tuple[str, pd.Timestamp]]:
    folder = folder or DATA_DIR / "nse"
    out = set()
    for f in sorted(folder.glob("results_*.json")):
        try:
            rows = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for r in rows if isinstance(rows, list) else []:
            if "result" not in str(r.get("purpose", "")).lower():
                continue
            d = pd.to_datetime(str(r.get("date", "")).strip().title(), format="%d-%b-%Y", errors="coerce")
            if pd.notna(d):
                out.add((str(r.get("symbol", "")).strip().upper(), d))
    return sorted(out, key=lambda x: (x[1], x[0]))


def bucket(x: float) -> str | None:
    for lo, hi, name in BUCKETS:
        if lo <= x < hi:
            return name
    return None


def events_table(close: pd.DataFrame, member: pd.DataFrame, dates: list[tuple[str, pd.Timestamp]]) -> pd.DataFrame:
    """One row per results event of a member stock: reaction and forward excess returns (%)."""
    idx = close.index
    ret = close.pct_change(fill_method=None)
    avg = ret.where(member).mean(axis=1)                    # the average universe stock's daily return
    avg_cum = (1 + avg.fillna(0)).cumprod()
    c = close.to_numpy(float)
    pos = {s: i for i, s in enumerate(close.columns)}
    rows = []
    for sym, d in dates:
        j = pos.get(sym)
        if j is None:
            continue
        t0 = idx.searchsorted(d) - 1                         # the close before the meeting day
        t1 = idx.searchsorted(d, side="right")               # the close after it
        if t0 < 0 or t1 >= len(idx) or not member.iat[t1, j]:
            continue
        p0, p1 = c[t0, j], c[t1, j]
        if not (p0 > 0 and p1 > 0):
            continue
        react = (p1 / p0 - (avg_cum.iat[t1] / avg_cum.iat[t0])) * 100
        row = {"symbol": sym, "date": d, "t1": t1, "reaction": react, "bucket": bucket(react)}
        for h in HORIZONS:
            t2 = t1 + h
            if t2 < len(idx) and c[t2, j] > 0:
                row[f"fwd_{h}"] = (c[t2, j] / p1 - avg_cum.iat[t2] / avg_cum.iat[t1]) * 100
            else:
                row[f"fwd_{h}"] = np.nan
        rows.append(row)
    return pd.DataFrame(rows)


def _stats(x: pd.Series, months: pd.Series, side: int) -> dict:
    x = x.dropna()
    if x.empty:
        return {"n": 0}
    m = x.groupby(months.reindex(x.index)).mean()
    t = float(m.mean() / (m.std(ddof=1) / math.sqrt(len(m)))) if len(m) > 2 and m.std(ddof=1) > 0 else None
    mean = float(x.mean())
    return {"n": int(len(x)), "months": int(len(m)), "excess_pct": round(mean, 2), "median_pct": round(float(x.median()), 2),
            "hit_pct": round(float((x * side > 0).mean() * 100), 1), "t": round(t, 2) if t is not None else None,
            "after_cost_pct": round(mean * side - COST_PCT, 2)}


def summarise(ev: pd.DataFrame) -> list[dict]:
    out = []
    months = ev["date"].dt.to_period("M").astype(str)
    for lo, hi, name in BUCKETS:
        sub = ev[ev["bucket"] == name]
        side = 1 if lo >= 2.0 else -1 if hi <= -2.0 else 1
        hz = {str(h): _stats(sub[f"fwd_{h}"], months, side) for h in HORIZONS}
        s20 = hz["20"]
        if name == "Within 2%":
            verdict = "no_direction"
        elif s20.get("n", 0) < MIN_EVENTS or s20.get("months", 0) < MIN_MONTHS or s20.get("t") is None:
            verdict = "too_few"
        elif abs(s20["t"]) >= 2 and s20["after_cost_pct"] > 0:
            verdict = "drift_edge"
        elif abs(s20["t"]) >= 2 and s20["excess_pct"] * side > 0:
            verdict = "drift_before_costs"
        elif abs(s20["t"]) >= 2:
            verdict = "reversal"
        else:
            verdict = "no_edge"
        out.append({"bucket": name, "side": side, "events": int(len(sub)),
                    "reaction_avg": round(float(sub["reaction"].mean()), 2) if len(sub) else None,
                    "horizons": hz, "verdict": verdict})
    return out


def run(log=print) -> dict:
    from . import pit
    t0 = time.monotonic()
    data = pit.load()
    if data is None:
        raise RuntimeError("point-in-time universe not built: run 4_build_universe.bat first")
    close = data.frames["close"]
    member = data.universe.reindex(index=close.index, columns=close.columns, fill_value=False)
    dates = results_dates()
    log(f"Results study: {len(dates):,} results meetings")
    ev = events_table(close, member, dates)
    rep = {"generated_at": pd.Timestamp.now().isoformat(timespec="seconds"), "events": int(len(ev)),
           "first_day": ev["date"].min().date().isoformat() if len(ev) else None,
           "last_day": ev["date"].max().date().isoformat() if len(ev) else None,
           "cost_pct": COST_PCT, "buckets": summarise(ev) if len(ev) else [],
           "elapsed_s": round(time.monotonic() - t0, 1)}
    RESULT_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = RESULT_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(rep, indent=1, default=str), encoding="utf-8")
    tmp.replace(RESULT_FILE)
    return rep


def load() -> dict | None:
    try:
        return json.loads(RESULT_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


if __name__ == "__main__":
    r = run()
    for b in r["buckets"]:
        h = b["horizons"]["20"]
        print(f"{b['bucket']:<14} events {b['events']:>6}  20d excess {h.get('excess_pct')}%  after costs "
              f"{h.get('after_cost_pct')}%  t {h.get('t')}  -> {b['verdict']}")
    sys.exit(0)
