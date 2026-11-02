"""Pattern evidence: does each candle and chart pattern (levels.py) say anything about a stock's next weeks?

Event study on the survivorship-free point-in-time universe (pit.py: each day's 500 most-traded NSE stocks since
2018, including the ones that later collapsed or were delisted):

  event   the first day a pattern is visible using only the bars up to that day (a chart pattern's breakout day
          when its swings were already confirmed then, else the first later day they were); the stock must be a
          universe member that day
  trade   buy at the next day's open, measure to the close 5, 10 and 20 trading days later
  excess  that return minus the average universe stock's return over exactly the same open-to-close stretch
  signed  excess for bullish patterns, -excess for bearish ones (a bearish pattern "works" when the stock lags);
          neutral chart patterns take the side of their breakout, neutral candles (doji, inside bar, NR7) have no side
  t       events of one month are not independent (a market-wide day moves them together), so the t-statistic is
          computed on monthly averages
  verdict at the pattern family's main horizon (candles 10 days, chart patterns 20): "edge" only when the signed
          excess clears COST_PCT round-trip costs and t >= 2 on at least MIN_EVENTS events over MIN_MONTHS months

  python -m scanner.pattern_study        (~20 minutes on 4 cores; writes data/results/pattern_study.json)
"""
from __future__ import annotations

import json
import math
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor

import numpy as np
import pandas as pd

from . import levels as lv
from .settings import RESULTS_DIR, ist_now

RESULT_FILE = RESULTS_DIR / "pattern_study.json"
HORIZONS = (5, 10, 20)
PRIMARY = {"candle": 10, "chart": 20}
SAMPLE_STEP = 10             # chart patterns are looked for every 10 bars (a confirmation stays listed for 20)
FIRST_BAR = 120              # ... once a stock has 120 bars of history
COST_PCT = 0.45              # round trip: STT 0.1% x 2, slippage 0.1% x 2, exchange / stamp / GST (config costs:)
MIN_EVENTS, MIN_MONTHS = 100, 24
FIELDS = ("open", "high", "low", "close", "volume")


def _direction(bias: str, direction: str | None = None) -> int:
    if bias == "bullish":
        return 1
    if bias == "bearish":
        return -1
    return {"up": 1, "down": -1}.get(direction or "", 0)


def candle_events(df: pd.DataFrame) -> list[tuple[int, str, int]]:
    """(bar, key, side) of every candle pattern in the history (each bar only looks back)."""
    n = len(df)
    return [(n - 1 - p["bars_ago"], p["key"], _direction(p["bias"])) for p in lv.patterns(df, last=n)]


def _visible(df: pd.DataFrame, ident: tuple[str, str], e: int) -> bool:
    return any(p["status"] == "confirmed" and (p["key"], p["start"]) == ident for p in lv.chart_patterns(df.iloc[:e + 1]))


def chart_events(df: pd.DataFrame, member: np.ndarray, step: int = SAMPLE_STEP) -> list[tuple[int, str, int]]:
    """(bar, key, side) of confirmed chart patterns, dated to the first bar they were visible with only past bars."""
    n = len(df)
    out, seen = [], set()
    samples = list(range(FIRST_BAR, n, step)) + [n - 1]
    for t in samples:
        if t < FIRST_BAR or not member[max(t - step + 1, 0):t + 1].any():
            continue
        for p in lv.chart_patterns(df.iloc[:t + 1]):
            if p["status"] != "confirmed" or p["confirmed_bars_ago"] >= step:
                continue
            ident = (p["key"], p["start"])
            if ident in seen:
                continue
            seen.add(ident)
            first = next((e for e in range(t - p["confirmed_bars_ago"], t + 1) if e == t or _visible(df, ident, e)), t)
            out.append((first, p["key"], _direction(p["bias"], p["direction"])))
    return out


def _work(item: tuple[str, pd.DataFrame, np.ndarray]) -> list[tuple[str, int, str, str, int]]:
    sym, df, member = item
    ev = [(sym, b, k, "candle", s) for b, k, s in candle_events(df)]
    ev += [(sym, b, k, "chart", s) for b, k, s in chart_events(df, member)]
    return [e for e in ev if 0 <= e[1] < len(member) and member[e[1]]]


def forward_excess(frames: dict, universe: pd.DataFrame, events: pd.DataFrame) -> pd.DataFrame:
    """Adds ret_h / bench_h / excess_h (fractions) for each horizon: buy at the open after the event bar, sell at the
    close h-1 bars after that; the benchmark is the average universe member over the same stretch."""
    o = frames["open"]
    c = frames["close"].ffill(limit=20)                    # a stock that stops trading is valued at its last close
    member_prev = universe.reindex(index=c.index, columns=c.columns, fill_value=False).shift(1, fill_value=False)
    dates = c.index
    out = events.copy()
    pos = {s: j for j, s in enumerate(c.columns)}
    rows = out["bar"].to_numpy() + 1                       # the entry day
    cols = out["symbol"].map(pos).to_numpy()
    for h in HORIZONS:
        r = c.shift(-(h - 1)) / o.where(o > 0) - 1        # open of day d to the close h-1 days later
        bench = r.where(member_prev).mean(axis=1)          # members on the day before entry (the event day)
        ok = rows < len(dates)
        vals = np.full(len(out), np.nan)
        b = np.full(len(out), np.nan)
        vals[ok] = r.to_numpy()[rows[ok], cols[ok]]
        b[ok] = bench.to_numpy()[rows[ok]]
        out[f"ret_{h}"], out[f"bench_{h}"], out[f"excess_{h}"] = vals, b, vals - b
    return out


def stats(ev: pd.DataFrame, h: int) -> dict:
    x = ev.dropna(subset=[f"excess_{h}"])
    signed = x[f"excess_{h}"] * x["side"].replace(0, 1) * 100      # no side (neutral candles): the raw excess
    if signed.empty:
        return {"n": 0, "months": 0, "excess_pct": None, "median_pct": None, "hit_pct": None, "t": None,
                "after_cost_pct": None}
    monthly = signed.groupby(pd.to_datetime(x["date"]).dt.to_period("M")).mean()
    t = (monthly.mean() / (monthly.std(ddof=1) / math.sqrt(len(monthly)))
         if len(monthly) > 2 and monthly.std(ddof=1) > 0 else None)
    r = lambda v, nd=2: None if v is None or not np.isfinite(v) else round(float(v), nd)    # noqa: E731
    return {"n": int(len(signed)), "months": int(len(monthly)), "excess_pct": r(signed.mean()),
            "median_pct": r(signed.median()), "hit_pct": r((signed > 0).mean() * 100, 1), "t": r(t),
            "after_cost_pct": r(signed.mean() - COST_PCT)}


def verdict(s: dict, directional: bool) -> str:
    if s["n"] < MIN_EVENTS or s["months"] < MIN_MONTHS:
        return "too_few"
    if not directional:
        return "no_direction"
    if s["t"] is not None and s["t"] >= 2 and s["after_cost_pct"] is not None and s["after_cost_pct"] > 0:
        return "edge"
    if s["t"] is not None and s["t"] >= 2 and s["excess_pct"] > 0:
        return "edge_before_costs"
    if s["t"] is not None and s["t"] <= -2:
        return "opposite"
    return "no_edge"


def summarise(ev: pd.DataFrame, first_day: str, last_day: str) -> dict:
    info = {**{k: (v[0], v[1]) for k, v in lv.PATTERN_INFO.items()}, **{k: (v[0], v[1]) for k, v in lv.CHART_INFO.items()}}
    out = {}
    for (family, key), g in ev.groupby(["family", "key"]):
        name, bias = info.get(key, (key, "neutral"))
        directional = (g["side"] != 0).any()
        hs = {str(h): stats(g, h) for h in HORIZONS}
        main = PRIMARY[family]
        out[key] = {"family": family, "name": name, "bias": bias, "horizons": hs, "primary": main,
                    "verdict": verdict(hs[str(main)], bool(directional))}
    return {"generated_at": ist_now().isoformat(timespec="seconds"), "universe": "point-in-time top 500 (pit.py)",
            "first_day": first_day, "last_day": last_day, "cost_pct": COST_PCT, "horizons": list(HORIZONS),
            "min_events": MIN_EVENTS, "min_months": MIN_MONTHS, "patterns": out}


def run(workers: int | None = None, log=print, limit: int | None = None) -> dict:
    from . import pit
    data = pit.load()
    if data is None:
        raise RuntimeError("point-in-time universe not built: run 4_build_universe.bat first")
    fr, uni = data.frames, data.universe
    syms = list(data.members)[:limit] if limit else list(data.members)
    items = []
    for s in syms:
        df = pd.DataFrame({f: fr[f][s] for f in FIELDS})
        keep = df["close"].notna().to_numpy()
        df = df[keep]
        for f in ("open", "high", "low"):
            df[f] = df[f].fillna(df["close"])
        member = uni[s].reindex(df.index, fill_value=False).to_numpy(dtype=bool)
        if len(df) >= FIRST_BAR and member.any():
            items.append((s, df, member))
    log(f"Pattern study: {len(items)} stocks, {sum(int(m.sum()) for _, _, m in items):,} member-days")
    t0 = time.monotonic()
    rows = []
    with ProcessPoolExecutor(max_workers=workers or os.cpu_count()) as ex:
        for i, ev in enumerate(ex.map(_work, items, chunksize=4), 1):
            rows.extend(ev)
            if i % 50 == 0:
                log(f"  {i}/{len(items)} stocks, {len(rows):,} events ({time.monotonic() - t0:.0f} s)")
    ev = pd.DataFrame(rows, columns=["symbol", "local_bar", "key", "family", "side"])
    # the bar was counted in each stock's own (gap-free) rows: map it to the shared calendar
    idx = {s: df.index for s, df, _ in items}
    ev["date"] = [idx[s][b] for s, b in zip(ev["symbol"], ev["local_bar"])]
    cal = fr["close"].index
    ev["bar"] = cal.get_indexer(pd.DatetimeIndex(ev["date"]))
    ev = forward_excess(fr, uni, ev)
    rep = summarise(ev, cal[0].date().isoformat(), cal[-1].date().isoformat())
    rep["elapsed_s"] = round(time.monotonic() - t0, 1)
    rep["events"] = int(len(ev))
    RESULT_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = RESULT_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(rep, indent=1), encoding="utf-8")
    tmp.replace(RESULT_FILE)
    return rep


def load() -> dict | None:
    try:
        return json.loads(RESULT_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


if __name__ == "__main__":
    lim = int(sys.argv[1]) if len(sys.argv) > 1 else None
    r = run(limit=lim, log=lambda m: print(m, flush=True))
    for k, p in sorted(r["patterns"].items(), key=lambda kv: (kv[1]["family"], kv[0])):
        s = p["horizons"][str(p["primary"])]
        print(f"{p['family']:6} {p['name']:28} n={s['n']:>7,} {p['primary']:>2}d excess {s['excess_pct']}%  "
              f"after costs {s['after_cost_pct']}%  hit {s['hit_pct']}%  t {s['t']}  -> {p['verdict']}")
