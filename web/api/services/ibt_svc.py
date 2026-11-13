"""Intraday backtests with your settings (POST /api/intraday-backtest): opening-range breakout, VWAP reclaim or gap
fade / go (scanner/intraday/custom.py) on the stored 5-minute bars of the liquid F&O stocks, sized by risk with
MIS charges and slippage (scanner/intraday/engine.py). The day objects are built once per bar-store version."""
from __future__ import annotations

import threading
from datetime import timedelta

import pandas as pd

from scanner.intraday import custom, data as idata, run as irun
from scanner.intraday.engine import IntradayCosts, run_intraday
from scanner.universe import get_universe

from . import data
from ..errors import ApiException
from ..paths import P
from ..util import today_ist

_cache: dict = {}
_lock = threading.Lock()


def _days():
    store = idata.IntradayStore(P.intraday_bars)
    months = store.months("5m")
    key = (tuple(months), str(store.manifest("5m").get("months", {}).get(months[-1])) if months else None)
    with _lock:
        if _cache.get("key") == key:
            return _cache["days"], _cache["meta"]
        cfg = data.config()
        frames = data.store()
        symbols, info = irun.intraday_universe(cfg, frames)
        bars = store.load("5m")
        if bars.empty:
            raise ApiException("FEATURE_UNAVAILABLE", "No stored 5-minute bars yet.",
                               "The 19:30 intraday job stores them (FYERS history) once you log in.", {"feature": "intraday"})
        bars = bars[bars["symbol"].isin(symbols)]
        large = set(get_universe("nifty50")[0]["symbol"])
        days = irun.build_days(bars, frames, info, large, {})
        flat = [d for ds in days.values() for d in ds if d.date < pd.Timestamp(today_ist())]
        meta = {"symbols": len(days), "sessions": len({d.date for d in flat}),
                "first": min(d.date for d in flat).date().isoformat() if flat else None,
                "last": max(d.date for d in flat).date().isoformat() if flat else None}
        _cache.update(key=key, days=flat, meta=meta)
        return flat, meta


def run(spec: dict) -> dict:
    days, meta = _days()
    try:
        strat = custom.strategy(spec)
    except ValueError as e:
        raise ApiException("VALIDATION", str(e)) from e
    cfg = data.config()
    ic = cfg.get("intraday") or {}
    costs = IntradayCosts.from_config(ic.get("costs"))
    capital = float((cfg.get("account") or {}).get("capital", 500000))
    res = run_intraday(strat, days, costs, capital, float(spec.get("risk_pct", ic.get("risk_pct", 0.5))),
                       float(ic.get("leverage", 2.0)))
    trades = res.trades
    reasons = {}
    for t in trades:
        reasons[t.reason] = reasons.get(t.reason, 0) + 1
    by_hour = {}
    for t in trades:
        h = f"{(9 * 60 + 15 + t.entry_slot * 5) // 60:02d}:00"
        by_hour.setdefault(h, []).append(t.pnl)
    m = res.metrics
    return {"spec": spec, "data": meta, "metrics": m, "exits": reasons,
            "by_hour": [{"hour": h, "trades": len(v), "pnl": round(sum(v), 2)} for h, v in sorted(by_hour.items())],
            "curve": [{"date": d.date().isoformat(), "equity": round(float(e), 2)} for d, e in res.daily.items()],
            "trades": [{"date": t.date, "symbol": t.symbol, "side": "LONG" if t.side > 0 else "SHORT",
                        "entry": f"{(555 + t.entry_slot * 5) // 60:02d}:{(555 + t.entry_slot * 5) % 60:02d}",
                        "entry_px": round(t.entry_px, 2), "exit_px": round(t.exit_px, 2), "reason": t.reason,
                        "qty": t.qty, "pnl": round(t.pnl, 2)} for t in trades[-300:]][::-1],
            "note": (f"{meta['sessions']} sessions of stored 5-minute bars ({meta['first']} to {meta['last']}), "
                     f"{meta['symbols']} liquid F&O stocks. MIS charges and slippage included; a few months is a small "
                     "sample: read the t-statistic, not just the total.")}
