"""Check the Seasonality page's numbers on THIS copy's data, independently of the code that makes them.

    python check_seasonality.py            every month and season
    python check_seasonality.py --quick    the current month only

Everything the page shows is recomputed here with plain loops over the raw closes (no scanner/seasonal.py code) and
compared field by field with what the page's API returns (web/api/services/seasonal_svc.py):

  build      the dashboard (web/ui/dist) is built and includes the Seasonality page
  index      NIFTY 500's monthly returns in the price store against NSE's own index file
  left out   the stock-months where the store and the point-in-time NSE history differ by over 2 points
  rows       the top 5 rising and top 5 falling stocks of each period: years, averages, years beaten / lagged, t and
             every year's excess; the NIFTY 500 row
  so far     this year's move in the period under way
  sectors    every sector cell of the current month
  backtest   every walk-forward year of the current month: eligible stocks, the 10 picks and their result
  chance     the fast chance count against the plain month shuffle (same random draws)

Prints OK / MISMATCH per check and ends with ALL OK, or the number of problems (exit code 1).
"""
from __future__ import annotations

import math
import sys
import time
import warnings
from datetime import date

warnings.filterwarnings("ignore")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from scanner.settings import DATA_DIR, ROOT  # noqa: E402
from web.api.paths import configure  # noqa: E402

configure(ROOT, DATA_DIR)

from scanner import seasonal as sz  # noqa: E402  (only for the period list and the chance shuffle check)
from web.api.services import data, seasonal_svc as svc  # noqa: E402

B = "NIFTY500"
TOL = 0.011                      # the page rounds to 2 decimals
problems: list[str] = []


def report(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'OK      ' if ok else 'MISMATCH'} {name}{(': ' + detail) if detail else ''}")
    if not ok:
        problems.append(name)


# ------------------------------------------------------------------ plain-loop arithmetic (independent of the app)
def month_ends(s: pd.Series, last_day: pd.Timestamp) -> dict:
    out = {}
    for d, v in s.dropna().items():
        out[(d.year, d.month)] = float(v)             # later days overwrite: the month's last close
    if (last_day.year, last_day.month) in out and last_day.month == (last_day + pd.offsets.BDay(1)).month:
        del out[(last_day.year, last_day.month)]      # the month is not over yet
    return out


def month_ret(me: dict, y: int, m: int) -> float | None:
    prev = (y, m - 1) if m > 1 else (y - 1, 12)
    if (y, m) not in me or prev not in me:
        return None
    return (me[(y, m)] / me[prev] - 1) * 100


def period_ret(me: dict, y: int, months, skip: set, sym: str) -> float | None:
    g = 1.0
    for m in months:
        r = month_ret(me, y, m)
        if r is None or (sym, y, m) in skip:
            return None
        g *= 1 + r / 100
    return (g - 1) * 100


def tstat(xs: list[float]) -> float | None:
    n = len(xs)
    if n < 3:
        return None
    mu = sum(xs) / n
    sd = math.sqrt(sum((x - mu) ** 2 for x in xs) / (n - 1))
    return mu / (sd / math.sqrt(n)) if sd > 0 else None


def near(a, b, tol=TOL) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return abs(float(a) - float(b)) <= tol


def main(quick: bool) -> int:
    t0 = time.perf_counter()
    close = data.store_close()
    last_day = pd.Timestamp(close.index[-1])
    today = date.today()
    print(f"Seasonality check on {ROOT} (prices to {last_day.date()})")

    # build -------------------------------------------------------------------------------------------------------
    dist = ROOT / "web" / "ui" / "dist"
    page_src = ROOT / "web" / "ui" / "src" / "pages" / "Seasonality.tsx"
    chunks = list((dist / "assets").glob("Seasonality-*.js")) if (dist / "assets").exists() else []
    fresh = bool(chunks) and (dist / "index.html").stat().st_mtime >= page_src.stat().st_mtime - 1
    report("build", fresh, "built with the page" if fresh else
           "the dashboard is not rebuilt since the update: cd web\\ui ; npm install ; npm run build")

    # index ---------------------------------------------------------------------------------------------------------
    me_b = month_ends(close[B], last_day)
    try:
        from scanner.nse import INDEX_HISTORY
        ih = pd.read_parquet(INDEX_HISTORY)["Nifty 500"].astype(float)
        me_n = month_ends(ih, pd.Timestamp(ih.index[-1]))
        pairs = [(month_ret(me_b, y, m), month_ret(me_n, y, m)) for (y, m) in me_b]
        pairs = [(a, b) for a, b in pairs if a is not None and b is not None]
        worst = max((abs(a - b) for a, b in pairs), default=0.0)
        report("index", worst <= 0.05, f"{len(pairs)} months, largest difference {worst:.3f} points")
    except Exception as e:
        print(f"  SKIP     index: NSE's index file not readable here ({type(e).__name__})")

    # left out ------------------------------------------------------------------------------------------------------
    syms = [s for s in data.universe()["symbol"].astype(str) if s in close.columns and s != B]
    me = {s: month_ends(close[s], last_day) for s in syms}
    skip: set = set()
    pit_close = None
    try:
        from scanner import pit
        p = pit.load()
        if p is not None:
            pit_close = p.frames["close"]
            for s in syms:
                if s not in pit_close.columns:
                    continue
                mp = month_ends(pit_close[s], last_day)
                for (y, m) in me[s]:
                    a, b = month_ret(me[s], y, m), month_ret(mp, y, m)
                    if a is not None and b is not None and abs(a - b) > sz.DISAGREE_PTS:
                        skip.add((s, y, m))
    except Exception as e:
        print(f"  SKIP     point-in-time history not readable ({type(e).__name__}): no stock-month is left out")
    first = svc.view(str(today.month))
    report("left out", first["data"]["left_out"] == len(skip),
           f"{len(skip)} stock-months by hand, {first['data']['left_out']} on the page"
           + (f" (e.g. {', '.join(f'{s} {y}-{m:02d}' for s, y, m in sorted(skip)[:4])})" if skip else ""))
    print(f"  ...      backtest universe on the page: {first['test']['universe']}"
          + ("" if first["test"]["universe"] == "point_in_time" else
             " - today's list only (flattered): build the point-in-time cache with python -m scanner.pit build"))

    # rows --------------------------------------------------------------------------------------------------------
    periods = [p for p in sz.period_list() if not quick or p["key"] == str(today.month)]
    years_all = sorted({y for (y, _m) in me_b})
    for p in periods:
        v = first if p["key"] == str(today.month) else svc.view(p["key"])
        months = p["months"]
        bad = []
        bm = [x for x in (period_ret(me_b, y, months, set(), B) for y in years_all) if x is not None]
        if v["market"]["n"] != len(bm) or not near(v["market"]["avg_pct"], sum(bm) / len(bm)):
            bad.append(f"NIFTY 500 row (page {v['market']['avg_pct']}, hand {sum(bm) / len(bm):.2f})")
        rows = v["rows"]
        pick = (sorted([r for r in rows if r["side"] == "bullish"], key=lambda r: -(r["t"] or 0))[:5]
                + sorted([r for r in rows if r["side"] == "bearish"], key=lambda r: (r["t"] or 0))[:5])
        for r in pick:
            s = r["symbol"]
            ex, raw = {}, []
            for y in years_all:
                a, b = period_ret(me[s], y, months, skip, s), period_ret(me_b, y, months, set(), B)
                if a is not None and b is not None:
                    ex[y] = a - b
                    raw.append(a)
            e = list(ex.values())
            if not e:
                bad.append(f"{s} (no years by hand)")
                continue
            checks = [("n", r["n"], len(e), 0), ("vs NIFTY 500", r["excess_pct"], sum(e) / len(e), TOL),
                      ("average", r["avg_pct"], sum(raw) / len(raw), TOL),
                      ("years beaten", r["beat_years"], sum(x > 0 for x in e), 0),
                      ("years lagged", r["lag_years"], sum(x < 0 for x in e), 0), ("t", r["t"], tstat(e), TOL)]
            for name, page, hand, tol in checks:
                if not near(page, hand, tol):
                    bad.append(f"{s} {name} (page {page}, hand {hand})")
            for y, x in ex.items():
                if not near(r["years"].get(str(y)), x):
                    bad.append(f"{s} {y} (page {r['years'].get(str(y))}, hand {x:.2f})")
            if len(r["years"]) != len(ex):
                bad.append(f"{s} has {len(r['years'])} years on the page, {len(ex)} by hand")
        report(f"rows {p['name']}", not bad, "; ".join(bad[:4]) if bad else f"NIFTY 500 + {len(pick)} stocks")

    # so far --------------------------------------------------------------------------------------------------------
    v = first
    if v["in_progress"]:
        base = close.loc[close.index < pd.Timestamp(today.year, today.month, 1)].iloc[-1]
        sb = (close[B].iloc[-1] / base[B] - 1) * 100
        bad = []
        for r in v["rows"][:20]:
            so = (close[r["symbol"]].iloc[-1] / base[r["symbol"]] - 1) * 100
            if not (near(r["so_far_pct"], so) and near(r["so_far_excess_pct"], so - sb)):
                bad.append(r["symbol"])
        report("so far", not bad and near(v["market_so_far_pct"], sb),
               f"NIFTY 500 {sb:+.2f}%, 20 stocks" if not bad else ", ".join(bad[:5]))

    # sectors -------------------------------------------------------------------------------------------------------
    meta = data.symbol_meta()
    bad, n_cells = [], 0
    for g in v["sectors"]:
        members = [s for s in syms if (meta.get(s) or {}).get("industry") == g["industry"]]
        per_year = []
        for y in years_all:
            b = period_ret(me_b, y, (today.month,), set(), B)
            xs = [period_ret(me[s], y, (today.month,), skip, s) for s in members]
            xs = [x - b for x in xs if x is not None and b is not None]
            if xs:
                per_year.append(sum(xs) / len(xs))
        cell = next(c for c in g["cells"] if c["period"] == str(today.month))
        n_cells += 1
        if cell["n"] != len(per_year) or not near(cell["excess_pct"], sum(per_year) / len(per_year) if per_year else None):
            bad.append(f"{g['industry']} (page {cell['excess_pct']})")
    report("sectors", not bad, f"{n_cells} sectors" if not bad else "; ".join(bad[:4]))

    # backtest ------------------------------------------------------------------------------------------------------
    if pit_close is not None and v["test"]["universe"] == "point_in_time":
        uni = pit.load().universe
        pc = pit_close.copy()
        pc[B] = close[B].reindex(pc.index)
        mb = month_ends(pc[B], pd.Timestamp(pc.index[-1]))
        mp_all = {s: month_ends(pc[s], pd.Timestamp(pc.index[-1])) for s in pc.columns if s != B}
        bad = []
        for row in v["test"]["rows"]:
            y, m = row["year"], today.month
            first_day = pc.index[(pc.index.year == y) & (pc.index.month == m)][0]
            members = uni.loc[first_day]
            scores, now = {}, {}
            for s, mp in mp_all.items():
                if not bool(members.get(s, False)):
                    continue
                past = []
                for yy in range(y - 20, y):
                    a, b = period_ret(mp, yy, (m,), skip, s), period_ret(mb, yy, (m,), set(), B)
                    if a is not None and b is not None:
                        past.append(a - b)
                a, b = period_ret(mp, y, (m,), skip, s), period_ret(mb, y, (m,), set(), B)
                if len(past) >= sz.TRAIN_MIN_YEARS and a is not None and b is not None:
                    scores[s], now[s] = sum(past) / len(past), a - b
            top = [s for s, _ in sorted(scores.items(), key=lambda kv: -kv[1])[:sz.TOP_N]]
            hand = sum(now[s] for s in top) / len(top) - v["test"]["cost_pct"] if top else None
            if len(scores) != row["eligible"] or set(top) != set(row["top"]) or not near(hand, row["top_excess_pct"], 0.02):
                bad.append(f"{y} (eligible {len(scores)} vs {row['eligible']}, result {hand} vs {row['top_excess_pct']})")
        report("backtest", not bad, f"{len(v['test']['rows'])} years" if not bad else "; ".join(bad[:3]))
    else:
        print("  SKIP     backtest: no point-in-time history on this copy")

    # chance --------------------------------------------------------------------------------------------------------
    mret = sz.monthly_returns(close[syms + [B]])
    rng = np.random.default_rng(11)
    slow = [sz.consistent_counts(sz.shuffle_months(mret, rng), B, (today.month,)) for _ in range(10)]
    fast = sz.chance_counts(mret, B, (today.month,), n_perm=10, seed=11)
    report("chance", near(fast["bullish"], round(np.mean([x[0] for x in slow]), 1), 0.051)
           and near(fast["bearish"], round(np.mean([x[1] for x in slow]), 1), 0.051), "fast count = plain shuffles")

    print(f"{'ALL OK' if not problems else f'{len(problems)} problem(s): ' + ', '.join(problems)}"
          f" ({time.perf_counter() - t0:.0f} s)")
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main("--quick" in sys.argv))
