"""The daily run (v2): refresh data, re-test every strategy, and produce today's actions.

Everything the dashboard / Telegram shows comes from one result dict saved to
data/results/latest.json (plus equity curves in data/results/curves.parquet).
"""
from __future__ import annotations

import json
import math
import os
import subprocess
import time
from dataclasses import replace
from datetime import timedelta

import numpy as np
import pandas as pd

from . import paper, pit
from .costs import CostModel, TaxModel
from .engine import EventStrategy, _curve_stats, evaluate, equal_weight_index, simulate, working_status
from .events import results_history, upcoming_results
from .nse import index_history
from .holdings import adjustment_factor, current_symbol, load_holdings
from .lock import scan_lock
from .panel import Factors, panel_from_wide
from .providers import INDEX_N500, INDEX_NIFTY, INDEX_VIX, get_fyers
from .settings import RESULTS_DIR, ROOT, SESSION_END, SESSION_START, ist_now, load_config
from .store import _replace, load_store, refresh_store
from .strategies import build_strategies, strategy_lifecycle, tradable_mask
from .universe import get_universe, industry_map

LATEST_FILE = RESULTS_DIR / "latest.json"
TIMING_CACHE = RESULTS_DIR / "timing_cache.json"
REJECTED_CACHE = RESULTS_DIR / "rejected_cache.json"   # B4: re-test results of strategies that never trade
ENGINE_VERSION = 5   # bump when simulation logic changes, so cached timing ranges are recomputed
NEEDS_INDUSTRY = {"sector_rotation"}   # strategies whose picks depend on each stock's industry
# (4: ETF stray open prints cleaned, low-vol "most traded" among stocks only)
CURVES_FILE = RESULTS_DIR / "curves.parquet"
TRADES_FILE = RESULTS_DIR / "trades.parquet"       # B1: every closed trade of every strategy's backtest
SCREENER_FILE = RESULTS_DIR / "screener.parquet"   # B2: one row per tradable stock at scan time
KEEP_SCAN_FILES = 60
SCHEMA = 3            # latest.json content version (the file format itself stays `version: 2`)

# Typical NSE cumulative volume by minutes since 09:15 (U-shaped day: heavy open and close).
_VOLUME_CURVE = [(0, 0.0), (15, 0.12), (30, 0.20), (60, 0.32), (120, 0.48), (180, 0.60),
                 (240, 0.72), (300, 0.84), (345, 0.93), (375, 1.0)]


def expected_volume_fraction(now=None) -> float | None:
    """Share of a normal day's volume traded by now, or None outside market hours."""
    now = now or ist_now()
    if now.weekday() >= 5:
        return None
    start = now.replace(hour=SESSION_START[0], minute=SESSION_START[1], second=0, microsecond=0)
    mins = (now - start).total_seconds() / 60
    if mins <= 0 or (now.hour, now.minute) >= SESSION_END:
        return None
    xs, ys = zip(*_VOLUME_CURVE)
    return max(float(np.interp(mins, xs, ys)), 0.05)


def _load_json(path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _calendar_yearly(eq: pd.Series) -> pd.Series:
    """Calendar-year returns in %: year-end over the PREVIOUS year-end (the first year over the first value), so
    each year includes its first trading day and matches the monthly table (the API computes the same)."""
    eq = eq.dropna()
    if eq.empty:
        return pd.Series(dtype=float)
    year_end = eq.groupby(eq.index.year).last()
    base = year_end.shift(1)
    base.iloc[0] = eq.iloc[0]
    return (year_end / base - 1) * 100


def _num(x, nd=2):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(x) or math.isinf(x) else round(x, nd)


def _clean_metrics(m: dict) -> dict:
    out = {}
    for k, v in m.items():
        if isinstance(v, dict):
            out[k] = _clean_metrics(v)
        elif isinstance(v, list):   # e.g. cagr_range: same rounding as cagr_pct, and never NaN in the JSON
            out[k] = [_num(x, 3) if isinstance(x, float) else x for x in v]
        else:
            out[k] = _num(v, 3) if isinstance(v, float) else v
    return out


def _rank_candidates(s, f: Factors, trad: pd.DataFrame) -> pd.Series:
    """Today's scores of what the simulation may buy (the same masks as engine.simulate): eligible, tradable,
    and stocks or ETFs by the strategy's universe - so the shown ranking matches the backtest's ranks."""
    score = s.score(f).iloc[-1]
    elig = s.eligible(f).iloc[-1] if s.eligible else pd.Series(True, index=score.index)
    is_etf = score.index.isin(list(f.etfs))
    ok = (elig.reindex(score.index).fillna(False).astype(bool)
          & trad.iloc[-1].reindex(score.index).fillna(False).astype(bool)
          & (is_etf if s.universe == "etfs" else ~is_etf))
    return score[ok]


def _next_rebalance(dates: pd.DatetimeIndex, how: str) -> str:
    """Approximate next rebalance decision day (last trading day of the period)."""
    last = dates[-1]
    if how == "weekly":
        target = last + pd.offsets.Week(weekday=4)
    elif how == "biweekly":
        target = last + pd.offsets.Week(weekday=4) + pd.Timedelta(days=7 * ((last.isocalendar().week + 1) % 2))
    elif how == "quarterly":
        target = last + pd.offsets.BQuarterEnd(0, startingMonth=3)
    elif how == "semiannual":
        target = last + pd.offsets.BMonthEnd(0)
        while target.month not in (6, 12):
            target += pd.offsets.BMonthEnd(1)
    else:
        target = last + pd.offsets.BMonthEnd(0)
    return target.date().isoformat()


def _rules(s, conf: dict | None) -> dict:
    """Every rule the simulation used for this strategy (B5), plus the raw config.yaml values, so the
    platform never has to re-read a config that may have been edited after the scan."""
    rank = s.kind == "rank"
    return {
        "kind": s.kind, "rebalance": s.rebalance if rank else None,
        "top_n": s.top_n if rank else None, "keep_rank": (s.keep_rank or s.top_n) if rank else None,
        "max_positions": s.max_positions, "stop_pct": s.stop_pct,
        "stop_atr": None if rank else s.stop_atr, "target_pct": None if rank else s.target_pct,
        "trail_pct": None if rank else s.trail_pct, "max_hold": None if rank else s.max_hold,
        "sizing": "equal" if rank else s.sizing, "risk_pct": None if rank else s.risk_pct,
        "use_regime": bool(s.use_regime), "regime_action": s.regime_action if rank else None,
        "params": json.loads(json.dumps(conf or {}, default=str)),
    }


def _producer() -> dict:
    """Which code wrote this result (B10): lets the platform spot scans from other checkouts."""
    def git(*args):
        try:
            out = subprocess.run(["git", *args], cwd=str(ROOT), capture_output=True, text=True, timeout=5,
                                 creationflags=0x08000000 if os.name == "nt" else 0)
            return out.stdout.strip() or None if out.returncode == 0 else None
        except Exception:
            return None
    return {"app": "quant-desk", "schema": SCHEMA, "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
            "commit": git("rev-parse", "--short", "HEAD")}


def run_daily(cfg: dict | None = None, update: bool = True, progress=None, log=print, by: str = "manual") -> dict:
    """Run one full scan (holds the cross-process scan lock for its whole duration)."""
    with scan_lock(by):
        return _run_daily(cfg or load_config(), update, progress, log)


def _run_daily(cfg: dict, update: bool, progress, log) -> dict:
    t_start = time.perf_counter()
    started = ist_now()
    fyers, fyers_note = get_fyers(cfg)
    log(fyers_note)

    uni, uni_note = get_universe(cfg.get("universe", "nifty500"))
    meta = uni.set_index("symbol")[["company", "industry"]].to_dict("index")
    holdings = load_holdings()
    known = set(uni["symbol"])
    rename_notes = {}
    for i, sym in enumerate(holdings["symbol"]):
        new, note = current_symbol(sym, known)
        if note:
            holdings.loc[i, "symbol"] = new
            rename_notes[new] = note
    etfs = [str(e).upper() for e in (cfg.get("etfs") or [])]
    symbols = list(dict.fromkeys(list(uni["symbol"]) + list(holdings["symbol"]) + etfs))

    if update:
        frames, info = refresh_store(symbols, int(cfg.get("lookback_days", 3000)), fyers=fyers,
                                     progress=progress, log=log)
    else:
        frames, info = load_store(), {"live_day": None, "errors": {}, "corporate_actions": [], "nse_status": "cached"}
    if frames["close"].empty:
        raise RuntimeError("No price data yet. Check your internet connection and run the scan again.")

    live = bool(info.get("live_day"))
    vol_frac = expected_volume_fraction() if live else None
    if live and vol_frac:
        # Project today's partial volume to a full day so volume filters aren't fooled.
        frames = dict(frames)
        v = frames["volume"].copy()
        v.iloc[-1] = v.iloc[-1] / vol_frac
        frames["volume"] = v

    log("Testing strategies and computing signals...")
    p = panel_from_wide(frames, symbols, etfs=set(etfs))   # ETF stray open prints cleaned (fills at the open)
    # today's list first, then NSE's wider Total Market list (the point-in-time backtest needs past members too)
    industry = {**industry_map(), **{s: v["industry"] for s, v in meta.items() if v.get("industry")}}
    first = p.dates[0].date()
    results_hist = results_history(first, ist_now().date(), log=log)
    f = Factors(p, etfs=set(etfs), industry=industry, results_dates=results_hist)
    flt = cfg.get("filters") or {}
    trad = tradable_mask(f, float(flt.get("min_price", 50)), float(flt.get("min_turnover_cr", 5)))
    stock_trad = trad & ~f.etf_mask          # market statistics use stocks only
    ew = equal_weight_index(f, stock_trad)
    costs = CostModel.from_config(cfg.get("costs"))
    tax = TaxModel.from_config(cfg.get("tax"))
    acct = cfg.get("account") or {}
    capital = float(acct.get("capital", 500000))
    min_position = float(acct.get("min_position", 0))

    last = p.dates[-1]
    results, results_note = upcoming_results(symbols, ist_now().date(), days=14)
    today_d = ist_now().date()

    def results_info(sym: str) -> dict:
        d = results.get(sym)
        if not d:
            return {"results_on": None}
        days = (pd.Timestamp(d).date() - today_d).days
        return {"results_on": d, "results_in_days": days}

    observed_last = p.observed.iloc[-1]
    close_last = p.close.iloc[-1]
    regime_up = bool(f.regime_up.iloc[-1])

    n500 = frames["close"][INDEX_N500].reindex(p.dates) if INDEX_N500 in frames["close"].columns else None
    done_upto = pd.Timestamp(info.get("complete_upto") or p.dates[-1])
    idx_hist = index_history([d.date() for d in p.dates if d <= done_upto], log=log).reindex(p.dates).ffill()
    cash_rate = idx_hist.get("Nifty 1D Rate Index")
    complete_upto = info.get("complete_upto") or p.dates[-1].date().isoformat()
    # Backtest metrics come from `bt` (the point-in-time universe when configured); today's orders,
    # model holdings and recent trades from the live panel (today's list).
    bt = pit.backtest_setup(cfg, frames, info, list(uni["symbol"]), {"f": f, "trad": trad, "ew": ew, "n500": n500},
                            log, etfs=etfs, industry=industry, results_dates=results_hist)
    bf, btrad, bew, bn500 = bt["f"], bt["trad"], bt["ew"], bt["n500"]
    timing_cache = _load_json(TIMING_CACHE)
    rejected_cache = _load_json(REJECTED_CACHE)
    # Inputs that change results without changing the config (part of every cache signature).
    data_sig = [sorted(etfs), sum(len(v) for v in results_hist.values()),
                _num(cash_rate.dropna().iloc[-1], 6) if cash_rate is not None and cash_rate.notna().any() else None,
                bt["universe"], bt.get("last_day"), len(industry)]
    # Sector rotation needs each stock's industry. NSE lists industries only for today's index members, so on
    # the point-in-time test companies that later dropped out of every index can never be picked: flattered.
    ind_cov = bt.get("industry_coverage_pct")
    ind_caveat = (f"Flattered: industries are known for only {ind_cov:.0f}% of the test's stock-days (NSE lists them "
                  "only for today's index members), so companies that later dropped out can never be picked. "
                  if ind_cov is not None and ind_cov < 99 else "")
    strat_out, rejected_out, curves, trade_rows = [], [], {}, []
    all_strats = build_strategies(cfg, include_disabled=True)
    for n_done, s in enumerate(all_strats, 1):
        log(f"Testing strategy {n_done}/{len(all_strats)}: {s.name}")   # run_scan.py turns this into progress
        conf_s = (cfg.get("strategies") or {}).get(s.key)
        lifecycle, rejected_reason = strategy_lifecycle(cfg, s.key)
        if lifecycle != "active":
            # B4: strategies that never trade are still re-tested (once per completed day, cached) so the
            # "Tested & rejected" list shows real numbers. No timing range, no orders, no positions.
            sig = json.dumps([ENGINE_VERSION, conf_s, cfg.get("costs"), cfg.get("filters"), capital, min_position,
                              complete_upto, data_sig], sort_keys=True, default=str)
            hit = rejected_cache.get(s.key)
            if not (hit and hit.get("sig") == sig):
                res = simulate(s, bf, costs, btrad, capital=capital, min_position=min_position, cash_rate=cash_rate)
                factor = idx_hist.get(s.benchmark) if s.benchmark else None
                m = evaluate(res, bf.p.index_close, bew, tax=tax, n500_benchmark=bn500, factor_benchmark=factor)
                m["full"]["factor_benchmark_name"] = s.benchmark or None
                m["full"]["backtest_universe"] = bt["universe"]
                m["full"]["cagr_range"] = None
                status, why = working_status(m)
                if s.key in NEEDS_INDUSTRY and ind_caveat:
                    why, m["full"]["industry_coverage_pct"] = ind_caveat + why, ind_cov
                eq = res.equity.dropna()
                yearly = _calendar_yearly(eq)
                hit = {"sig": sig, "entry": {
                    "key": s.key, "name": s.name, "description": s.description, "kind": s.kind,
                    "horizon": s.horizon, "evidence": s.evidence, "universe": s.universe, "benchmark": s.benchmark,
                    "status": status, "status_reason": why, "metrics": _clean_metrics(m),
                    "yearly": {str(k): _num(v, 1) for k, v in yearly.items()},
                    "positions": [], "actions": [], "ranking": [],
                    "max_positions": s.max_positions, "per_position": _num(capital / s.max_positions, 0),
                    "next_rebalance": None,
                    "recent_trades": [{"symbol": t.symbol, "entry": t.entry_date.date().isoformat(),
                                       "exit": t.exit_date.date().isoformat(), "ret_pct": _num(t.ret_pct, 1),
                                       "days": t.days, "reason": t.reason} for t in res.trades[-25:]][::-1]},
                    "curve": [[d.date().isoformat(), float(v)] for d, v in (eq / eq.iloc[0]).items()],
                    "trades": [_trade_row(s.key, t) for t in res.trades]}
                rejected_cache[s.key] = hit
            rejected_out.append({**hit["entry"], "lifecycle": lifecycle, "rejected_reason": rejected_reason,
                                 "rules": _rules(s, conf_s)})
            if hit.get("curve"):
                curves[s.key] = pd.Series([v for _, v in hit["curve"]],
                                          index=pd.DatetimeIndex([d for d, _ in hit["curve"]], name="date"))
            trade_rows.extend(hit.get("trades") or [])
            continue
        live_res = simulate(s, f, costs, trad, capital=capital, min_position=min_position, cash_rate=cash_rate)
        res = live_res if bf is f else simulate(s, bf, costs, btrad, capital=capital, min_position=min_position,
                                                cash_rate=cash_rate)
        factor = idx_hist.get(s.benchmark) if s.benchmark else None
        m = evaluate(res, bf.p.index_close, bew, tax=tax, n500_benchmark=bn500, factor_benchmark=factor)
        m["full"]["factor_benchmark_name"] = s.benchmark or None
        m["full"]["backtest_universe"] = bt["universe"]
        if bn500 is not None:   # tracking error vs the real Nifty 500: how far luck alone moves the gap
            gap = (res.equity.pct_change() - bn500.reindex(res.equity.index).ffill().pct_change()).dropna()
            m["full"]["te_n500_pct"] = float(gap.std() * np.sqrt(252) * 100) if len(gap) > 20 else None
        # Timing luck: the same rules rebalanced a few days earlier (or started a few weeks later)
        # can give quite different results - report the spread, not just one number.
        # (cached: recomputed only when the completed data or this strategy's settings change)
        sig = json.dumps([ENGINE_VERSION, conf_s, cfg.get("costs"),
                          cfg.get("filters"), capital, complete_upto, data_sig], sort_keys=True, default=str)
        hit = timing_cache.get(s.key)
        if hit and hit.get("sig") == sig:
            m["full"]["cagr_range"] = hit["range"]
        else:
            variants = ([replace(s, rebalance_offset=k) for k in (5, 10, 15)] if s.kind == "rank" else [s, s, s])
            spread = [m["full"].get("cagr_pct")]
            for i, v in enumerate(variants):
                alt = simulate(v, bf, costs, btrad, capital=capital, min_position=min_position, cash_rate=cash_rate,
                               warmup=252 if s.kind == "rank" else 252 + 21 * (i + 1))
                spread.append(_curve_stats(alt.equity)["cagr_pct"])
            spread = [x for x in spread if x is not None]
            m["full"]["cagr_range"] = [min(spread), max(spread)] if spread else None
            timing_cache[s.key] = {"sig": sig, "range": m["full"]["cagr_range"]}
        base_cagr, rng = m["full"].get("cagr_pct"), m["full"].get("cagr_range")
        if rng and base_cagr is not None:   # the base run is one of the timings: always inside the range
            m["full"]["cagr_range"] = [min(rng[0], base_cagr), max(rng[1], base_cagr)]
        trade_rows.extend(_trade_row(s.key, t) for t in res.trades)
        status, why = working_status(m)
        if s.key in NEEDS_INDUSTRY and ind_caveat:
            why, m["full"]["industry_coverage_pct"] = ind_caveat + why, ind_cov
        eq = res.equity.dropna()
        curves[s.key] = eq / eq.iloc[0]
        yearly = _calendar_yearly(eq)
        per_pos = capital / s.max_positions

        def sized(sym: str, stop: float | None = None) -> dict:
            px = float(close_last.get(sym, np.nan))
            qty = int(per_pos // px) if px > 0 else 0
            if isinstance(s, EventStrategy) and s.sizing == "risk" and stop and px > stop:
                qty = min(int(capital * s.risk_pct / 100 / (px - stop)), int(2 * per_pos // px))
            return {"price": _num(px), "qty": qty, "amount": _num(qty * px, 0)}

        actions = []
        for o in live_res.next_orders:
            sym = o["symbol"]
            stop = None
            if o["action"] == "BUY" and getattr(s, "stop_pct", None):
                stop = close_last.get(sym, np.nan) * (1 - s.stop_pct / 100)
            rinfo = results_info(sym)   # (not `info`: that name holds the store refresh info used below)
            warn = (o["action"] == "BUY" and rinfo.get("results_on") is not None
                    and rinfo["results_in_days"] <= int((cfg.get("results") or {}).get("warn_days", 7)))
            actions.append({**o, **meta.get(sym, {}), **sized(sym, stop), **rinfo,
                            "results_warning": warn, "stop": _num(stop), "provisional": live})
        ranking = []
        if s.kind == "rank":
            ok = _rank_candidates(s, f, trad)
            held = {pp["symbol"] for pp in live_res.open_positions}
            for rank, (sym, val) in enumerate(ok.dropna().sort_values(ascending=False).head(40).items(), 1):
                ranking.append({"rank": rank, "symbol": sym, **meta.get(sym, {}), "score": _num(val, 3),
                                "price": _num(close_last.get(sym)), "ret_6m": _num(f.ret_6m[sym].iloc[-1] * 100, 1),
                                "ret_12m": _num(f.ret_12m[sym].iloc[-1] * 100, 1), "rs": _num(f.rs_rating[sym].iloc[-1], 0),
                                "in_portfolio": sym in held, **results_info(sym)})
        strat_out.append({
            "key": s.key, "name": s.name, "description": s.description, "kind": s.kind,
            "horizon": s.horizon, "evidence": s.evidence, "universe": s.universe, "benchmark": s.benchmark,
            "status": status, "status_reason": why, "metrics": _clean_metrics(m),
            "yearly": {str(k): _num(v, 1) for k, v in yearly.items()},
            "positions": [{**pp, **meta.get(pp["symbol"], {}), **results_info(pp["symbol"])} for pp in live_res.open_positions],
            "actions": actions, "ranking": ranking,
            "max_positions": s.max_positions, "per_position": _num(per_pos, 0),
            "lifecycle": "active", "rejected_reason": None,
            "rules": _rules(s, conf_s),
            "next_rebalance": _next_rebalance(p.dates, s.rebalance) if s.kind == "rank" else None,
            "recent_trades": [{"symbol": t.symbol, "entry": t.entry_date.date().isoformat(),
                               "exit": t.exit_date.date().isoformat(), "ret_pct": _num(t.ret_pct, 1),
                               "days": t.days, "reason": t.reason} for t in live_res.trades[-25:]][::-1],
        })
    # Working now first; among those, strategies with long independent research behind them before
    # experimental ones; then recent performance.
    tier = {"STRONG": 0, "MODERATE": 1, "WEAK": 2, "EXPERIMENTAL": 3}
    order = {"working": 0, "mixed": 1, "unknown": 2, "not-working": 3}
    strat_out.sort(key=lambda x: (order.get(x["status"], 9), tier.get(x["evidence"], 5),
                                  -((x["metrics"].get("12m") or {}).get("return_pct") or -1e9)))
    for path, data in ((TIMING_CACHE, timing_cache), (REJECTED_CACHE, rejected_cache)):
        try:
            path.write_text(json.dumps(data), encoding="utf-8")
        except OSError:
            pass

    # Market snapshot
    fresh = observed_last & close_last.notna()
    chg = (p.close.iloc[-1] / p.close.iloc[-2] - 1) * 100
    pool = chg[fresh & stock_trad.iloc[-1]].dropna()
    vix_close = frames["close"].get(INDEX_VIX)
    nifty_close = frames["close"].get(INDEX_NIFTY)

    def series_last(s):
        s = s.dropna() if s is not None else pd.Series(dtype=float)
        return (_num(s.iloc[-1]), _num((s.iloc[-1] / s.iloc[-2] - 1) * 100)) if len(s) > 1 else (None, None)

    nifty, nifty_chg = series_last(nifty_close)
    vix, vix_chg = series_last(vix_close)
    breadth = _num(f.breadth_50.iloc[-1], 1)
    if regime_up and (breadth or 0) >= 50:
        mood, level = "Bullish", "good"
        advice = "Nifty is above its 200-day average and most stocks are in uptrends. Strategies may open new positions."
    elif not regime_up:
        mood, level = "Bearish", "bad"
        advice = ("Nifty is below its 200-day average. Strategies with the regime filter make no new buys in this "
                  "regime (protects capital) and only manage existing positions.")
    else:
        mood, level = "Mixed", "neutral"
        advice = "Nifty is in an uptrend but fewer than half of stocks are. Be selective."
    if (vix or 0) >= 20:
        advice += " India VIX is high: expect large swings."

    def mover(sym):
        return {"symbol": sym, **meta.get(sym, {}), "price": _num(close_last[sym]), "change_pct": _num(chg[sym]),
                "vol_ratio": _num(f.vol_ratio[sym].iloc[-1], 1)}

    movers_n = int(cfg.get("movers_count", 15))
    vr = f.vol_ratio.iloc[-1][fresh & stock_trad.iloc[-1]].dropna()

    # Holdings health check
    mom_rank = f.momentum.iloc[-1][stock_trad.iloc[-1]].rank(ascending=False)
    hd = cfg.get("holdings_defaults") or {}
    holding_rows = []
    for h in holdings.itertuples(index=False):
        sym = h.symbol
        if sym not in p.close.columns or pd.isna(close_last.get(sym)):
            holding_rows.append({"symbol": sym, "level": "unknown",
                                 "alerts": ["No price data - check the NSE symbol (e.g. RELIANCE, TCS, M&M)"]})
            continue
        px = float(close_last[sym])
        sl = h.stop_loss_pct if not pd.isna(h.stop_loss_pct) else float(hd.get("stop_loss_pct", 8))
        tg = h.target_pct if not pd.isna(h.target_pct) else float(hd.get("target_pct", 20))
        buy = float(h.buy_price) if not pd.isna(h.buy_price) else None
        qty = float(h.qty) if not pd.isna(h.qty) else 0.0
        alerts, level = [], "ok"
        if sym in rename_notes:
            alerts.append(rename_notes[sym])
        if results.get(sym):
            alerts.append(f"Quarterly results on {pd.Timestamp(results[sym]):%d %b} - expect a big move either way")
        # Restate the buy price in today's terms if a split/bonus/demerger happened since buying.
        factor = adjustment_factor(sym, h.buy_date, p.close[sym]) if buy and not pd.isna(h.buy_date) else None
        if factor and factor != 1.0:
            alerts.append(f"Corporate action since your buy date: buy price adjusted from ₹{buy:,.2f} "
                          f"to ₹{buy * factor:,.2f} and qty from {qty:g} to {qty / factor:g}")
            buy, qty = buy * factor, qty / factor
        elif buy and pd.isna(h.buy_date) and px < 0.6 * buy:
            alerts.append("Price is far below your buy price - if the stock had a split/bonus since you bought, "
                          "add your buy date so the price can be adjusted.")
        if not bool(observed_last.get(sym, False)):
            alerts.append(f"No fresh price today (last real data before {last.date()}) - possibly suspended/renamed")
            level = "watch"
        if buy:
            if px <= buy * (1 - sl / 100):
                alerts.append(f"STOP-LOSS HIT: down more than {sl:g}% from your buy price")
                level = "danger"
            elif px >= buy * (1 + tg / 100):
                alerts.append(f"TARGET REACHED: up more than {tg:g}% - consider booking part / trailing your stop")
                level = "good"
        if px < f.sma50[sym].iloc[-1]:
            alerts.append("Closed below its 50-day average (trend weakening)")
            level = "danger" if level == "danger" else "watch"
        if px < f.sma200[sym].iloc[-1]:
            alerts.append("Below its 200-day average (long-term downtrend)")
            level = "danger" if level == "danger" else "watch"
        holding_rows.append({
            "symbol": sym, "company": meta.get(sym, {}).get("company", sym), "qty": _num(qty, 0),
            "buy_price": _num(buy), "price": _num(px), "change_pct": _num(chg.get(sym)),
            "pnl_pct": _num((px / buy - 1) * 100) if buy else None,
            "pnl_amount": _num((px - buy) * qty, 0) if buy else None,
            "stop_price": _num(buy * (1 - sl / 100)) if buy else None,
            "target_price": _num(buy * (1 + tg / 100)) if buy else None,
            "momentum_rank": _num(mom_rank.get(sym), 0), "rs": _num(f.rs_rating[sym].iloc[-1], 0),
            "results_on": results.get(sym),
            "level": level, "alerts": alerts,
        })

    stale = [s for s in symbols if s in p.close.columns and not bool(observed_last.get(s, False))]
    screener = _screener_frame(f, frames, p, stock_trad.iloc[-1], chg, fresh, mom_rank, meta)
    result = {
        "version": 2, "schema": SCHEMA, "producer": _producer(),
        # B7: point_in_time when the point-in-time universe drove the backtests (config backtest_universe)
        "backtest_universe": "point_in_time" if bt["universe"] == "point_in_time" else "current_list",
        "generated_at": started.isoformat(timespec="seconds"),
        "elapsed_s": round(time.perf_counter() - t_start, 1),
        "data_date": last.date().isoformat(), "live": live, "live_source": info.get("live_source"),
        "complete_upto": info.get("complete_upto"), "fyers_note": fyers_note, "nse_status": info.get("nse_status"),
        "universe": uni_note, "stocks": int(trad.iloc[-1].sum()), "stale_symbols": stale[:50],
        "backtest": {k: v for k, v in bt.items() if k not in ("f", "trad", "ew", "n500")},
        "errors": info.get("errors", {}), "corporate_actions": info.get("corporate_actions", []),
        "capital": capital, "min_position": min_position,
        "costs_round_trip_pct": _num(costs.round_trip_pct(capital / 15), 3),
        "market": {"label": mood, "level": level, "advice": advice, "regime_up": regime_up,
                   "nifty": nifty, "nifty_change_pct": nifty_chg,
                   "nifty_sma200": _num(f.index_sma200.iloc[-1]),   # B3: distance to the regime line
                   "vix": vix, "vix_change_pct": vix_chg,
                   "breadth_50": breadth, "advances": int((pool > 0).sum()), "declines": int((pool < 0).sum())},
        "strategies": strat_out,
        # B4: kept out of `strategies` so older readers (Streamlit, Telegram, the paper journal) never see them
        "rejected_strategies": rejected_out,
        "gainers": [mover(s) for s in pool.sort_values(ascending=False).head(movers_n).index],
        "losers": [mover(s) for s in pool.sort_values().head(movers_n).index],
        "volume_spikes": [mover(s) for s in vr[vr >= 3].sort_values(ascending=False).head(movers_n).index],
        "holdings": holding_rows,
        "symbols": sorted(c for c in p.close.columns),
        "results_note": results_note,
        "indices": _index_tables(idx_hist, p.dates),
    }
    try:
        # Paper trading: journal completed days only, then replay the journal on stored (completed) prices.
        if not live:
            paper.record_scan(result)
        done = {k: v.iloc[:-1] for k, v in frames.items()} if live else frames
        result["paper"] = paper.summaries(done, costs, etfs=etfs)
    except Exception as e:   # the journal must never break a scan
        log(f"Paper-trading journal problem: {type(e).__name__}: {e}")
        result["paper"] = {}
    trades_df = pd.DataFrame(trade_rows, columns=_TRADE_COLS)
    _save(result, curves, bf.p, bew, bn500, started, trades=trades_df, screener=screener)
    log(f"Done in {result['elapsed_s']}s: {len(strat_out)} strategies tested on {result['stocks']} stocks.")
    return result


FACTOR_INDICES = ["Nifty 50", "Nifty 500", "Nifty200 Momentum 30", "Nifty500 Momentum 50", "Nifty Alpha 50",
                  "Nifty100 Low Volatility 30", "NIFTY200 Quality 30", "Nifty200 Value 30", "NIFTY50 Equal Weight",
                  "Nifty500 Equal Weight", "Nifty Midcap 150", "Nifty Smallcap 250", "Nifty 1D Rate Index"]
SECTOR_INDICES = ["Nifty Bank", "Nifty Financial Services", "Nifty IT", "Nifty Pharma", "Nifty Healthcare Index",
                  "Nifty Auto", "Nifty FMCG", "Nifty Metal", "Nifty Realty", "Nifty Energy", "Nifty Oil & Gas",
                  "Nifty PSU Bank", "Nifty Private Bank", "Nifty Media", "Nifty Infrastructure", "Nifty India Consumption",
                  "Nifty Consumer Durables", "Nifty Commodities", "Nifty CPSE", "Nifty MNC", "Nifty Services Sector"]


def _index_tables(h: pd.DataFrame, dates: pd.DatetimeIndex) -> dict:
    """Factor-index gallery (real NSE indices) and sector strength, from NSE's index history."""
    def stats(s: pd.Series) -> dict | None:
        s = s.dropna()
        if len(s) < 30:
            return None
        def ret(n):
            return _num((s.iloc[-1] / s.iloc[-n - 1] - 1) * 100, 1) if len(s) > n else None
        cs = _curve_stats(s)
        # a one-day index move is shown with 2 decimals everywhere (top bar, tiles, tables)
        chg_1d = _num((s.iloc[-1] / s.iloc[-2] - 1) * 100, 2) if len(s) > 1 else None
        return {"last": _num(s.iloc[-1]), "chg_1d": chg_1d, "ret_1m": ret(21), "ret_3m": ret(63), "ret_6m": ret(126),
                "ret_1y": ret(252), "cagr": _num(cs.get("cagr_pct"), 1), "max_dd": _num(cs.get("max_dd_pct"), 1),
                "since": s.index[0].date().isoformat(),
                "above_50dma": bool(s.iloc[-1] > s.iloc[-50:].mean()) if len(s) >= 50 else None}
    factors = [{"name": n, **st} for n in FACTOR_INDICES if n in h and (st := stats(h[n]))]
    sectors = [{"name": n, **st} for n in SECTOR_INDICES if n in h and (st := stats(h[n]))]
    sectors.sort(key=lambda r: -(r.get("ret_3m") or -1e9))
    for i, r in enumerate(sectors, 1):
        r["rank"] = i
    return {"factors": factors, "sectors": sectors}


_TRADE_COLS = ["strategy", "symbol", "entry_date", "entry_price", "exit_date", "exit_price", "qty", "pnl",
               "ret_pct", "days", "reason"]


def _trade_row(key: str, t) -> dict:
    return {"strategy": key, "symbol": t.symbol, "entry_date": t.entry_date.date().isoformat(),
            "entry_price": round(float(t.entry_price), 4), "exit_date": t.exit_date.date().isoformat(),
            "exit_price": round(float(t.exit_price), 4), "qty": int(t.qty), "pnl": round(float(t.pnl), 2),
            "ret_pct": round(float(t.ret_pct), 3), "days": int(t.days), "reason": t.reason}


def _screener_frame(f: Factors, frames: dict, p, stock_now: pd.Series, chg: pd.Series, fresh: pd.Series,
                    mom_rank: pd.Series, meta: dict) -> pd.DataFrame:
    """B2: the screener's one source - every tradable stock with the indicators of this scan (same live
    overlay as the orders). Percent columns are in percent units."""
    syms = [s for s, ok in stock_now.items() if ok]
    last = lambda df: df.iloc[-1].reindex(syms)   # noqa: E731
    close, sma50, sma200 = last(p.close), last(f.sma50), last(f.sma200)

    def above(a, b):
        return pd.array([None if (pd.isna(x) or pd.isna(y)) else bool(x > y) for x, y in zip(a, b)], dtype="boolean")

    deliv = frames.get("deliv_pct")
    if deliv is not None and len(deliv):
        deliv = deliv.reindex(columns=syms).iloc[-2:].ffill().iloc[-1]
    else:
        deliv = pd.Series(np.nan, index=syms)
    df = pd.DataFrame({
        "symbol": syms,
        "company": [meta.get(s, {}).get("company") for s in syms],
        "industry": [meta.get(s, {}).get("industry") for s in syms],
        "price": close.values, "change_pct": chg.reindex(syms).values,
        "ret_1w": (last(f.ret(5)) * 100).values, "ret_1m": (last(f.ret(21)) * 100).values,
        "ret_3m": (last(f.ret_3m) * 100).values, "ret_6m": (last(f.ret_6m) * 100).values,
        "ret_12m": (last(f.ret_12m) * 100).values,
        "rs": last(f.rs_rating).values, "momentum_score": last(f.momentum).values,
        "momentum_rank": mom_rank.reindex(syms).values, "vol_ann_pct": (last(f.vol_ann) * 100).values,
        "pct_from_52w_high": last(f.pct_from_52w_high).values,
        "above_sma50": above(close, sma50), "above_sma200": above(close, sma200),
        "sma50_above_sma200": above(sma50, sma200),
        "rsi14": last(f.rsi14).values, "vol_ratio": last(f.vol_ratio).values,
        "turnover_cr": last(f.turnover_avg20_cr).values, "atr_pct": last(f.atr_pct).values,
        "deliv_pct": deliv.reindex(syms).values,
        "sma50": sma50.values, "sma200": sma200.values,
        "high_52w": last(f.high_52w).values, "low_52w": last(f.low_52w).values,
        "fresh": fresh.reindex(syms).fillna(False).astype(bool).values,
    })
    num = df.select_dtypes("number").columns
    df[num] = df[num].astype(float).replace([np.inf, -np.inf], np.nan).round(4)
    return df


def _write_atomic(path, write) -> None:
    """Write via a temporary file and a Windows-safe replace, so readers never see a half-written file."""
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    write(tmp)
    _replace(tmp, path)


def _save(result: dict, curves: dict, p, ew: pd.Series, n500: pd.Series | None, started,
          trades: pd.DataFrame | None = None, screener: pd.DataFrame | None = None) -> None:
    """B9: every artifact first, latest.json LAST. latest.json is the commit marker: a reader that sees a
    new scan_id can rely on curves / trades / screener of that scan already being in place."""
    df = pd.DataFrame(curves)
    df["NIFTY 50"] = p.index_close.reindex(df.index).ffill() / p.index_close.reindex(df.index).ffill().iloc[0]
    df["Average stock"] = ew.reindex(df.index) / ew.reindex(df.index).iloc[0]
    if n500 is not None and n500.notna().any():
        n5 = n500.reindex(df.index).ffill()
        df["NIFTY 500"] = n5 / n5.dropna().iloc[0]
    _write_atomic(CURVES_FILE, lambda t: df.to_parquet(t))
    scan_id = result["generated_at"]
    for path, frame in ((TRADES_FILE, trades), (SCREENER_FILE, screener)):
        if frame is not None:
            frame = frame.assign(scan_id=scan_id)   # lets readers reject an artifact from another scan
            _write_atomic(path, lambda t, fr=frame: fr.to_parquet(t, index=False))
    text = json.dumps(result, indent=1, default=str)
    _write_atomic(RESULTS_DIR / f"scan_{started:%Y%m%d_%H%M}.json", lambda t: t.write_text(text, encoding="utf-8"))
    old = sorted(RESULTS_DIR.glob("scan_*.json"))[:-KEEP_SCAN_FILES]
    for o in old:
        o.unlink(missing_ok=True)
    _write_atomic(LATEST_FILE, lambda t: t.write_text(text, encoding="utf-8"))


def load_latest() -> dict | None:
    if not LATEST_FILE.exists():
        return None
    try:
        r = json.loads(LATEST_FILE.read_text(encoding="utf-8"))
        return r if r.get("version") == 2 else None
    except Exception:
        return None


def load_curves() -> pd.DataFrame | None:
    return pd.read_parquet(CURVES_FILE) if CURVES_FILE.exists() else None
