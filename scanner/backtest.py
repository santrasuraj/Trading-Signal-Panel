"""Test every rule on past data, so you know which ones actually worked before trusting them.

BUY rules: simulated trade - buy at next day's open, exit at stop-loss, target, or after
max_hold_days (whichever comes first), minus trading costs.
SELL rules: how often the stock fell over the next max_hold_days (i.e. selling helped).
Both are compared with a "baseline": buying every stock on every day.
"""
from __future__ import annotations

import json
from datetime import timedelta

import numpy as np
import pandas as pd

from .data import load_cached
from .indicators import add_indicators
from .rules import active_rules
from .settings import RESULTS_DIR, ist_now, ist_today
from .universe import get_universe

BACKTEST_FILE = RESULTS_DIR / "backtest.json"
MIN_TRADES = 30


def _simulate_long(o, h, l, c, idx, sl, tg, hold, cost):
    """Returns list of (return_pct, days_held)."""
    n = len(c)
    trades = []
    for i in idx:
        if i + hold >= n:
            continue
        entry = o[i + 1]
        if not entry > 0:
            continue
        stop, target = entry * (1 - sl), entry * (1 + tg)
        exit_price, days = c[i + hold], hold
        for j in range(i + 1, i + hold + 1):
            if j > i + 1 and o[j] <= stop:  # gapped below stop
                exit_price, days = o[j], j - i
                break
            if j > i + 1 and o[j] >= target:  # gapped above target
                exit_price, days = o[j], j - i
                break
            if l[j] <= stop:  # stop checked first = conservative when both hit same day
                exit_price, days = stop, j - i
                break
            if h[j] >= target:
                exit_price, days = target, j - i
                break
        trades.append(((exit_price / entry - 1) * 100 - cost, days))
    return trades


def run_backtest(cfg: dict, provider_name: str, progress=None, log=print) -> dict:
    bt = cfg.get("backtest") or {}
    years = float(bt.get("years", 2))
    sl = float(bt.get("stop_loss_pct", 5)) / 100
    tg = float(bt.get("target_pct", 10)) / 100
    hold = int(bt.get("max_hold_days", 15))
    cost = float(bt.get("cost_pct", 0.25))
    filters = cfg.get("filters") or {}
    min_price = float(filters.get("min_price", 0))
    min_vol = float(filters.get("min_avg_volume", 0))

    uni, _ = get_universe(cfg.get("universe", "nifty500"))
    symbols = list(uni["symbol"])
    histories = load_cached(provider_name, symbols)
    if sum(len(df) > 0 for df in histories.values()) < 10:
        raise RuntimeError("Not enough cached price history. Run a scan first (it downloads the data).")

    window_start = pd.Timestamp(ist_today() - timedelta(days=int(years * 365)))
    rules = active_rules(cfg)
    results = {r.key: [] for r, _ in rules}
    baseline = []
    used = 0

    for k, sym in enumerate(symbols, 1):
        df = histories.get(sym)
        if df is None or len(df) < 260:
            continue
        df = add_indicators(df)
        used += 1
        o, h, l, c = (df[x].to_numpy() for x in ("open", "high", "low", "close"))
        tradable = ((df["close"] >= min_price) & (df["vol_avg20"] >= min_vol) & (df.index >= window_start)).to_numpy()

        fwd = (df["close"].shift(-hold) / df["open"].shift(-1) - 1) * 100
        base = fwd[tradable].dropna()
        baseline.extend(base.tolist())

        for rule, params in rules:
            fired = rule.evaluate(df, params).to_numpy() & tradable
            idx = np.flatnonzero(fired)
            if rule.side == "BUY":
                results[rule.key].extend(_simulate_long(o, h, l, c, idx, sl, tg, hold, cost))
            else:
                f = fwd.to_numpy()
                results[rule.key].extend((f[i], hold) for i in idx if not np.isnan(f[i]))
        if progress:
            progress(k, len(symbols), sym)

    base = np.array(baseline) if baseline else np.array([0.0])
    base_avg = float(base.mean() - cost)
    base_up = float((base > 0).mean() * 100)

    rows = []
    for rule, params in rules:
        arr = np.array([t[0] for t in results[rule.key]])
        days = np.array([t[1] for t in results[rule.key]])
        n = len(arr)
        row = {"key": rule.key, "name": rule.name, "side": rule.side, "signals": n, "explain": rule.explain}
        if n:
            if rule.side == "BUY":
                wins, losses = arr[arr > 0].sum(), -arr[arr <= 0].sum()
                edge = arr.mean() - base_avg
                row.update(
                    win_rate=float((arr > 0).mean() * 100), avg_return=float(arr.mean()),
                    median_return=float(np.median(arr)), worst=float(arr.min()), best=float(arr.max()),
                    profit_factor=float(wins / losses) if losses > 0 else None,
                    avg_days=float(days.mean()), edge=float(edge),
                )
            else:
                edge = (base_avg + cost) - arr.mean()  # positive = stock did worse than average after signal
                row.update(
                    win_rate=float((arr < 0).mean() * 100), avg_return=float(arr.mean()),
                    median_return=float(np.median(arr)), worst=float(arr.min()), best=float(arr.max()),
                    edge=float(edge),
                )
            if n < MIN_TRADES:
                row["verdict"] = "Not enough data"
            elif edge > 0.3:
                row["verdict"] = "Worked better than random"
            elif edge > -0.3:
                row["verdict"] = "No real edge"
            else:
                row["verdict"] = "Worse than random"
        else:
            row["verdict"] = "No signals"
        rows.append(row)

    out = {
        "generated_at": ist_now().isoformat(timespec="seconds"),
        "provider": provider_name,
        "settings": {"years": years, "stop_loss_pct": sl * 100, "target_pct": tg * 100,
                     "max_hold_days": hold, "cost_pct": cost},
        "stocks_tested": used,
        "baseline": {"avg_return": base_avg, "pct_up": base_up},
        "rules": rows,
    }
    BACKTEST_FILE.write_text(json.dumps(out, indent=1), encoding="utf-8")
    log(f"Backtest done: {used} stocks, {sum(r['signals'] for r in rows)} signals tested.")
    return out


def load_backtest() -> dict | None:
    if not BACKTEST_FILE.exists():
        return None
    try:
        return json.loads(BACKTEST_FILE.read_text(encoding="utf-8"))
    except Exception:
        return None
