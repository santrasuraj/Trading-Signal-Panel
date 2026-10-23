"""The daily run (v2): refresh data, re-test every strategy, and produce today's actions.

Everything the dashboard / Telegram shows comes from one result dict saved to
data/results/latest.json (plus equity curves in data/results/curves.parquet).
"""
from __future__ import annotations

import json
import math
import time
from datetime import timedelta

import numpy as np
import pandas as pd

from .costs import CostModel, TaxModel
from .engine import EventStrategy, evaluate, equal_weight_index, simulate, working_status
from .events import upcoming_results
from .holdings import adjustment_factor, current_symbol, load_holdings
from .lock import scan_lock
from .panel import Factors, panel_from_wide
from .providers import INDEX_NIFTY, INDEX_VIX, get_fyers
from .settings import RESULTS_DIR, SESSION_END, SESSION_START, ist_now, load_config
from .store import load_store, refresh_store
from .strategies import build_strategies, tradable_mask
from .universe import get_universe

LATEST_FILE = RESULTS_DIR / "latest.json"
CURVES_FILE = RESULTS_DIR / "curves.parquet"
KEEP_SCAN_FILES = 60

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


def _num(x, nd=2):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(x) or math.isinf(x) else round(x, nd)


def _clean_metrics(m: dict) -> dict:
    out = {}
    for k, v in m.items():
        out[k] = _clean_metrics(v) if isinstance(v, dict) else (_num(v, 3) if isinstance(v, float) else v)
    return out


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
    symbols = list(dict.fromkeys(list(uni["symbol"]) + list(holdings["symbol"])))

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
    p = panel_from_wide(frames, symbols)
    f = Factors(p)
    flt = cfg.get("filters") or {}
    trad = tradable_mask(f, float(flt.get("min_price", 50)), float(flt.get("min_turnover_cr", 5)))
    ew = equal_weight_index(f, trad)
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

    strat_out, curves = [], {}
    for s in build_strategies(cfg):
        res = simulate(s, f, costs, trad, capital=capital, min_position=min_position)
        m = evaluate(res, p.index_close, ew, tax=tax)
        status, why = working_status(m)
        eq = res.equity.dropna()
        curves[s.key] = eq / eq.iloc[0]
        yearly = (eq.groupby(eq.index.year).last() / eq.groupby(eq.index.year).first() - 1) * 100
        per_pos = capital / s.max_positions

        def sized(sym: str, stop: float | None = None) -> dict:
            px = float(close_last.get(sym, np.nan))
            qty = int(per_pos // px) if px > 0 else 0
            if isinstance(s, EventStrategy) and s.sizing == "risk" and stop and px > stop:
                qty = min(int(capital * s.risk_pct / 100 / (px - stop)), int(2 * per_pos // px))
            return {"price": _num(px), "qty": qty, "amount": _num(qty * px, 0)}

        actions = []
        for o in res.next_orders:
            sym = o["symbol"]
            stop = None
            if o["action"] == "BUY" and getattr(s, "stop_pct", None):
                stop = close_last.get(sym, np.nan) * (1 - s.stop_pct / 100)
            info = results_info(sym)
            warn = (o["action"] == "BUY" and info.get("results_on") is not None
                    and info["results_in_days"] <= int((cfg.get("results") or {}).get("warn_days", 7)))
            actions.append({**o, **meta.get(sym, {}), **sized(sym, stop), **info,
                            "results_warning": warn, "stop": _num(stop), "provisional": live})
        ranking = []
        if s.kind == "rank":
            score = s.score(f).iloc[-1]
            elig = s.eligible(f).iloc[-1] if s.eligible else pd.Series(True, index=score.index)
            ok = score[elig.reindex(score.index).fillna(False).astype(bool) & trad.iloc[-1].reindex(score.index).fillna(False)]
            held = {pp["symbol"] for pp in res.open_positions}
            for rank, (sym, val) in enumerate(ok.dropna().sort_values(ascending=False).head(40).items(), 1):
                ranking.append({"rank": rank, "symbol": sym, **meta.get(sym, {}), "score": _num(val, 3),
                                "price": _num(close_last.get(sym)), "ret_6m": _num(f.ret_6m[sym].iloc[-1] * 100, 1),
                                "ret_12m": _num(f.ret_12m[sym].iloc[-1] * 100, 1), "rs": _num(f.rs_rating[sym].iloc[-1], 0),
                                "in_portfolio": sym in held, **results_info(sym)})
        strat_out.append({
            "key": s.key, "name": s.name, "description": s.description, "kind": s.kind,
            "status": status, "status_reason": why, "metrics": _clean_metrics(m),
            "yearly": {str(k): _num(v, 1) for k, v in yearly.items()},
            "positions": [{**pp, **meta.get(pp["symbol"], {}), **results_info(pp["symbol"])} for pp in res.open_positions],
            "actions": actions, "ranking": ranking,
            "max_positions": s.max_positions, "per_position": _num(per_pos, 0),
            "next_rebalance": _next_rebalance(p.dates, s.rebalance) if s.kind == "rank" else None,
            "recent_trades": [{"symbol": t.symbol, "entry": t.entry_date.date().isoformat(),
                               "exit": t.exit_date.date().isoformat(), "ret_pct": _num(t.ret_pct, 1),
                               "days": t.days, "reason": t.reason} for t in res.trades[-25:]][::-1],
        })
    order = {"working": 0, "mixed": 1, "unknown": 2, "not-working": 3}
    strat_out.sort(key=lambda x: (order.get(x["status"], 9), -((x["metrics"].get("12m") or {}).get("return_pct") or -1e9)))

    # Market snapshot
    fresh = observed_last & close_last.notna()
    chg = (p.close.iloc[-1] / p.close.iloc[-2] - 1) * 100
    pool = chg[fresh & trad.iloc[-1]].dropna()
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
        advice = ("Nifty is below its 200-day average. Strategies make no new buys in this regime (protects capital) "
                  "and only manage existing positions.")
    else:
        mood, level = "Mixed", "neutral"
        advice = "Nifty is in an uptrend but fewer than half of stocks are. Be selective."
    if (vix or 0) >= 20:
        advice += " India VIX is high: expect large swings."

    def mover(sym):
        return {"symbol": sym, **meta.get(sym, {}), "price": _num(close_last[sym]), "change_pct": _num(chg[sym]),
                "vol_ratio": _num(f.vol_ratio[sym].iloc[-1], 1)}

    movers_n = int(cfg.get("movers_count", 15))
    vr = f.vol_ratio.iloc[-1][fresh & trad.iloc[-1]].dropna()

    # Holdings health check
    mom_rank = f.momentum.iloc[-1][trad.iloc[-1]].rank(ascending=False)
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
    result = {
        "version": 2,
        "generated_at": started.isoformat(timespec="seconds"),
        "elapsed_s": round(time.perf_counter() - t_start, 1),
        "data_date": last.date().isoformat(), "live": live, "live_source": info.get("live_source"),
        "complete_upto": info.get("complete_upto"), "fyers_note": fyers_note, "nse_status": info.get("nse_status"),
        "universe": uni_note, "stocks": int(trad.iloc[-1].sum()), "stale_symbols": stale[:50],
        "errors": info.get("errors", {}), "corporate_actions": info.get("corporate_actions", []),
        "capital": capital, "costs_round_trip_pct": _num(costs.round_trip_pct(capital / 15), 3),
        "market": {"label": mood, "level": level, "advice": advice, "regime_up": regime_up,
                   "nifty": nifty, "nifty_change_pct": nifty_chg, "vix": vix, "vix_change_pct": vix_chg,
                   "breadth_50": breadth, "advances": int((pool > 0).sum()), "declines": int((pool < 0).sum())},
        "strategies": strat_out,
        "gainers": [mover(s) for s in pool.sort_values(ascending=False).head(movers_n).index],
        "losers": [mover(s) for s in pool.sort_values().head(movers_n).index],
        "volume_spikes": [mover(s) for s in vr[vr >= 3].sort_values(ascending=False).head(movers_n).index],
        "holdings": holding_rows,
        "symbols": sorted(c for c in p.close.columns),
        "results_note": results_note,
    }
    _save(result, curves, p, ew, started)
    log(f"Done in {result['elapsed_s']}s: {len(strat_out)} strategies tested on {result['stocks']} stocks.")
    return result


def _save(result: dict, curves: dict, p, ew: pd.Series, started) -> None:
    text = json.dumps(result, indent=1, default=str)
    tmp = LATEST_FILE.with_suffix(".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(LATEST_FILE)
    (RESULTS_DIR / f"scan_{started:%Y%m%d_%H%M}.json").write_text(text, encoding="utf-8")
    old = sorted(RESULTS_DIR.glob("scan_*.json"))[:-KEEP_SCAN_FILES]
    for o in old:
        o.unlink(missing_ok=True)
    df = pd.DataFrame(curves)
    df["NIFTY 50"] = p.index_close.reindex(df.index).ffill() / p.index_close.reindex(df.index).ffill().iloc[0]
    df["Average stock"] = ew.reindex(df.index) / ew.reindex(df.index).iloc[0]
    df.to_parquet(CURVES_FILE)


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
