"""Published, reproducible numbers (GET /api/research/benchmarks): how fast and how deep this app is, measured on this
PC now, next to what the competitors publish (from the Nov 2026 competitor analysis). Nothing here is estimated: a
number that could not be measured says so."""
from __future__ import annotations

import time

import numpy as np

from scanner.intraday import quote_hub

from . import data
from ..paths import P

TIMINGS: dict[str, float] = {}           # last measured durations, filled by the routers that run the work


def record(name: str, seconds: float) -> None:
    TIMINGS[name] = round(float(seconds), 3)


def _timed(fn) -> float | None:
    t = time.perf_counter()
    try:
        fn()
    except Exception:
        return None
    return round(time.perf_counter() - t, 3)


def measure() -> dict:
    from scanner import scans
    from . import chart_data, robustness
    lt = data.latest() or {}
    rows = []
    sym = "RELIANCE" if "RELIANCE" in data.store_close().columns else data.store_close().columns[0]
    chart_s = _timed(lambda: chart_data.build(sym, "1d", "1y", list(chart_data.INDICATORS)))
    etfs = set(data.etfs())
    uni = [s for s in data.universe()["symbol"] if s not in etfs]
    scan_s = _timed(lambda: scans.run_today(scans.PRESETS[0], data.store(), uni))
    strat = next((s.get("key") for s in lt.get("strategies") or []), None)
    robustness._cache.clear()                     # measure the computation, not the cache
    mc_s = _timed(lambda: robustness.report(strat)) if strat else None
    info = quote_hub.read_quotes(P.intraday_live)
    feed_lag = None
    if info and quote_hub.feed_live(info):
        rec = [q.get("received") for q in (info.get("quotes") or {}).values() if q.get("received")]
        if rec:
            feed_lag = round(max(0.0, float(info.get("written") or 0) - max(rec)), 3)
    rows += [
        {"key": "chart", "label": "Daily chart, 1 year, all 33 indicator series", "value": chart_s, "unit": "s",
         "competitor": "Not published by any of the four"},
        {"key": "scan_today", "label": f"Your scan on today's market ({len(uni)} stocks, 3 rules)", "value": scan_s, "unit": "s",
         "competitor": "Trade Ideas Top Lists refresh every 15 s; TrendSpider scans don't refresh by themselves"},
        {"key": "scan_backtest", "label": "Scan backtest, 8 years x the survivorship-free top 500", "value": TIMINGS.get("scan_backtest"),
         "unit": "s", "competitor": "Trade Ideas OddsMaker: 60 days of history; TrendSpider: 2,000-30,000 candles, no survivorship-free universe"},
        {"key": "monte_carlo", "label": "Robustness: 10,000-path Monte Carlo + deflated Sharpe", "value": mc_s, "unit": "s",
         "competitor": "TrendSpider: 10,000-path Monte Carlo (Oct 2026); no deflated Sharpe anywhere"},
        {"key": "full_scan", "label": f"Full scan: re-test {len(lt.get('strategies') or [])} strategies on 8 years", "value": lt.get("elapsed_s"),
         "unit": "s", "competitor": "NinjaTrader users report ~4 hours per month of tick replay on one core (forum)"},
        {"key": "feed_to_file", "label": "FYERS tick to the dashboard's price file", "value": feed_lag, "unit": "s",
         "competitor": "None publish tick-to-screen latency (Trade Ideas shows a 37 ms client-server example)"},
    ]
    bt = lt.get("backtest") or {}
    coverage = {"universe": len(uni), "strategies": len(lt.get("strategies") or []),
                "pit_companies": bt.get("members"), "pit_no_longer_trading": bt.get("gone"),
                "pit_last_day": bt.get("last_day"), "backtest_universe": lt.get("backtest_universe")}
    return {"measured_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "rows": rows, "coverage": coverage,
            "client_note": "Tick-to-screen latency is measured in your browser from the live feed's own tick times "
                           "(shown below when the FYERS feed runs).",
            "note": NOTE}


NOTE = ("Measured on this PC when you open the page (the scan backtest when it last ran). Competitor figures are what "
        "they publish or what users report (Nov 2026 analysis), not our measurements of their products.")


def percentile(xs: list[float], p: float) -> float | None:
    return round(float(np.percentile(xs, p)), 3) if xs else None
