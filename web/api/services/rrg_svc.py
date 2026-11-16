"""Sector rotation (GET /api/rrg): NSE's sector indices on a relative rotation graph against the Nifty 50.

  RS          sector / Nifty 50 (weekly or daily closes)
  RS-Ratio    100 + the z-score of RS over the last 10 periods (above 100: stronger than the Nifty, relative to its
              own recent range)
  RS-Momentum 100 + the z-score of RS-Ratio over the last 10 periods (above 100: getting stronger)
  Quadrants   Leading (ratio and momentum above 100), Weakening (ratio above, momentum below), Lagging (both below),
              Improving (ratio below, momentum above). Sectors usually turn clockwise.
These are open approximations of the published JdK measures (their exact formula is proprietary).

The record: for every week since 2018, each sector's quadrant and its next 4 weeks against the Nifty 50, averaged
per quadrant with a t-statistic on the weekly averages: does the quadrant tell anything about what comes next?
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from . import data

SECTORS = ("Nifty Bank", "Nifty Private Bank", "Nifty PSU Bank", "Nifty Financial Services", "Nifty Capital Markets",
           "Nifty IT", "Nifty Auto", "Nifty FMCG", "Nifty Pharma", "Nifty Healthcare Index", "Nifty Metal",
           "Nifty Realty", "Nifty Energy", "Nifty Oil & Gas", "Nifty Media", "Nifty Consumer Durables",
           "Nifty Infrastructure", "Nifty PSE", "Nifty CPSE", "Nifty Commodities", "Nifty India Consumption",
           "Nifty Services Sector", "Nifty Chemicals", "Nifty India Defence", "Nifty MNC")
BENCH = "Nifty 50"
N = 10
FWD = 4


def quadrant(x: float, y: float) -> str:
    return "Leading" if x >= 100 and y >= 100 else "Weakening" if x >= 100 else "Lagging" if y < 100 else "Improving"


def rrg_frames(px: pd.DataFrame, bench: pd.Series, n: int = N) -> tuple[pd.DataFrame, pd.DataFrame]:
    rs = px.div(bench, axis=0) * 100
    ratio = 100 + (rs - rs.rolling(n, min_periods=n).mean()) / rs.rolling(n, min_periods=n).std()
    mom = 100 + (ratio - ratio.rolling(n, min_periods=n).mean()) / ratio.rolling(n, min_periods=n).std()
    return ratio, mom


def record(px: pd.DataFrame, bench: pd.Series, ratio: pd.DataFrame, mom: pd.DataFrame, fwd: int = FWD) -> list[dict]:
    """Per quadrant: the sectors' next `fwd` periods against the benchmark, since the start of the data."""
    rel = px.div(bench, axis=0)
    nxt = (rel.shift(-fwd) / rel - 1) * 100
    rows = []
    for col in px.columns:
        df = pd.DataFrame({"x": ratio[col], "y": mom[col], "f": nxt[col]}).dropna()
        for t, r in df.iterrows():
            rows.append((t, quadrant(r.x, r.y), r.f))
    if not rows:
        return []
    ev = pd.DataFrame(rows, columns=["t", "q", "f"])
    out = []
    for q in ("Leading", "Weakening", "Lagging", "Improving"):
        s = ev[ev["q"] == q]
        per = s.groupby("t")["f"].mean()
        t = float(per.mean() / (per.std(ddof=1) / math.sqrt(len(per)))) if len(per) > 2 and per.std(ddof=1) > 0 else None
        out.append({"quadrant": q, "n": int(len(s)), "avg_pct": round(float(s["f"].mean()), 2) if len(s) else None,
                    "hit_pct": round(float((s["f"] > 0).mean() * 100), 1) if len(s) else None,
                    "t": round(t, 2) if t is not None else None})
    return out


def view(tf: str = "weekly", tail: int = 8) -> dict:
    ih = data.index_history()
    cols = [c for c in SECTORS if c in ih.columns]
    px = ih[cols + [BENCH]].ffill()
    if tf == "weekly":
        last_day = px.index.to_series().resample("W-FRI").last()     # label each week by its real last session
        px = px.resample("W-FRI").last()
        px.index = pd.DatetimeIndex(last_day.reindex(px.index).to_numpy())
    px = px.dropna(subset=[BENCH])
    bench = px[BENCH]
    secs = px[cols]
    ratio, mom = rrg_frames(secs, bench)
    out = []
    for c in cols:
        r, m = ratio[c].dropna(), mom[c].dropna()
        idx = r.index.intersection(m.index)[-tail:]
        if not len(idx):
            continue
        pts = [{"t": t.date().isoformat(), "x": round(float(r[t]), 2), "y": round(float(m[t]), 2)} for t in idx]
        last = pts[-1]
        s = secs[c].dropna()
        out.append({"name": c.replace("Nifty ", "").replace(" Index", ""), "full": c, "tail": pts,
                    "quadrant": quadrant(last["x"], last["y"]),
                    "ret_4": round(float(s.iloc[-1] / s.iloc[-5] - 1) * 100, 2) if len(s) > 5 else None,
                    "vs_nifty_4": round(float((s.iloc[-1] / s.iloc[-5]) / (bench.iloc[-1] / bench.iloc[-5]) - 1) * 100, 2) if len(s) > 5 else None})
    return {"tf": tf, "as_of": px.index[-1].date().isoformat(), "sectors": out,
            "record": record(secs, bench, ratio, mom), "fwd": FWD,
            "note": "Open approximations of the JdK RS-Ratio / RS-Momentum (10 periods). The record: each quadrant's "
                    f"next {FWD} {'weeks' if tf == 'weekly' else 'days'} against the Nifty 50 since 2018, t on the "
                    "per-period averages."}
