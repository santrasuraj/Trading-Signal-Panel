"""Options strategy backtest on NSE's daily option prices (scanner/option_history.py).

One position per expiry cycle (monthly: each month's last expiry; weekly: every expiry):
  * entry at the close of the first trading day with at most `entry_dte` calendar days left; each leg's strike is the
    one nearest the underlying x (1 + offset %); the entry price is that day's close (bhavcopy), plus slippage;
  * exits, checked at each later day's close: a stop when the loss reaches `stop_pct` % of the premium collected (or
    paid, for a debit), a profit target at `target_pct` % of the maximum profit, else at expiry, where every leg
    settles at its intrinsic value on the underlying's close;
  * charges: FYERS' Rs 20 per order and leg, STT on sold premium (0.0625% until 30 Sep 2024, 0.1% since) and on
    options bought and exercised in the money (0.125% of the intrinsic value), the exchange's 0.03503% of premium, SEBI
    fees, stamp duty on buys and GST.

Honest limits: daily closes only (a stop is seen at the close, never the intraday spike that may have hit it); a
thinly traded strike's close can be stale (legs with no trades that day are skipped at entry); no margin or its
interest. P&L is per the number of lots chosen, in rupees.
"""
from __future__ import annotations

import math
from datetime import date

import numpy as np
import pandas as pd

from . import option_history as oh

STRATEGIES = {
    "short_straddle": [("sell", "CE", 0.0), ("sell", "PE", 0.0)],
    "short_strangle": [("sell", "CE", "+s"), ("sell", "PE", "-s")],
    "iron_condor": [("buy", "PE", "-w"), ("sell", "PE", "-s"), ("sell", "CE", "+s"), ("buy", "CE", "+w")],
    "iron_fly": [("buy", "PE", "-w"), ("sell", "PE", 0.0), ("sell", "CE", 0.0), ("buy", "CE", "+w")],
    "bull_put": [("sell", "PE", "-s"), ("buy", "PE", "-w")],
    "bear_call": [("sell", "CE", "+s"), ("buy", "CE", "+w")],
    "long_straddle": [("buy", "CE", 0.0), ("buy", "PE", 0.0)],
    "long_strangle": [("buy", "CE", "+s"), ("buy", "PE", "-s")],
    "bull_call": [("buy", "CE", 0.0), ("sell", "CE", "+s")],
    "bear_put": [("buy", "PE", 0.0), ("sell", "PE", "-s")],
}
BROKERAGE = 20.0
EXCH_PCT, SEBI_PCT, STAMP_PCT, GST_PCT, STT_EXERCISE_PCT = 0.03503, 0.0001, 0.003, 18.0, 0.125
STT_CHANGE = pd.Timestamp("2024-10-01")


def _stt_sell(day) -> float:
    return 0.0625 if pd.Timestamp(day) < STT_CHANGE else 0.1


def _charges(premium_value: float, side: str, day) -> float:
    """Rupees for one order of one leg at `premium_value` (price x quantity)."""
    exch = premium_value * EXCH_PCT / 100
    sebi = premium_value * SEBI_PCT / 100
    stt = premium_value * _stt_sell(day) / 100 if side == "sell" else 0.0
    stamp = premium_value * STAMP_PCT / 100 if side == "buy" else 0.0
    return BROKERAGE + exch + sebi + stt + stamp + (BROKERAGE + exch + sebi) * GST_PCT / 100


def legs_for(spec: dict) -> list[tuple[str, str, float]]:
    s, w = float(spec.get("short_pct", 2.0)), float(spec.get("wing_pct", 4.0))
    tpl = STRATEGIES.get(spec["strategy"])
    if tpl is None:
        raise ValueError(f"Unknown strategy {spec['strategy']}")
    out = []
    for side, typ, off in tpl:
        o = {"+s": s, "-s": -s, "+w": w, "-w": -w}.get(off, off) if isinstance(off, str) else off
        out.append((side, typ, float(o)))
    if spec["strategy"] in ("iron_condor", "bull_put", "bear_call", "iron_fly") and w <= (0 if spec["strategy"] == "iron_fly" else s):
        raise ValueError("The wings must be further out than the short strikes")
    return out


def cycles(hist: pd.DataFrame, cycle: str) -> list[pd.Timestamp]:
    exps = sorted(hist["expiry"].unique())
    if cycle == "weekly":
        return [pd.Timestamp(e) for e in exps]
    s = pd.Series(pd.to_datetime(exps))
    return [pd.Timestamp(x) for x in s.groupby(s.dt.to_period("M")).max()]


def backtest(hist: pd.DataFrame, spec: dict) -> dict:
    """hist: option_history.load(symbol). spec: strategy, cycle, entry_dte, short_pct, wing_pct, stop_pct, target_pct,
    lots, slippage_pct."""
    legs = legs_for(spec)
    lots = int(spec.get("lots", 1))
    entry_dte = int(spec.get("entry_dte", 30))
    stop_pct = spec.get("stop_pct")
    target_pct = spec.get("target_pct")
    slip = float(spec.get("slippage_pct", 1.0)) / 100
    days = sorted(hist["date"].unique())
    if not days:
        return {"trades": [], "skipped": [], "stats": {"trades": 0}, "curve": []}
    first_day, last_day = pd.Timestamp(days[0]), pd.Timestamp(days[-1])
    by_day = {pd.Timestamp(d): g for d, g in hist.groupby("date")}
    under_close = hist.groupby("date")["underlying"].first()
    trades, skipped = [], []
    busy_until = None
    for exp in cycles(hist, spec.get("cycle", "monthly")):
        if exp > last_day:
            skipped.append({"expiry": exp.date().isoformat(), "why": "expires after the last stored day"})
            continue
        cands = [pd.Timestamp(d) for d in days if pd.Timestamp(d) < exp and (exp - pd.Timestamp(d)).days <= entry_dte]
        if busy_until is not None:
            cands = [d for d in cands if d > busy_until]
        if not cands:
            continue
        d0 = cands[0]
        if (exp - d0).days < max(1, entry_dte // 3) and d0 == first_day:
            continue                                   # history starts too close to this expiry
        g0 = by_day[d0]
        g0 = g0[g0["expiry"] == exp]
        spot = float(under_close.loc[d0])
        lot = float(g0["lot"].iloc[0]) if len(g0) else math.nan
        pos, ok = [], True
        for side, typ, off in legs:
            ks = g0[g0["type"] == typ]
            ks = ks[(ks["volume"] > 0) & (ks["close"] > 0)]
            if ks.empty:
                ok = False
                break
            k = oh.nearest_strike(ks["strike"].to_numpy(), spot * (1 + off / 100))
            px = float(ks.loc[ks["strike"] == k, "close"].iloc[0])
            fill = px * (1 + slip) if side == "buy" else px * (1 - slip)
            pos.append({"side": side, "type": typ, "strike": k, "entry": round(fill, 2), "sign": 1 if side == "buy" else -1})
        if not ok or math.isnan(lot):
            skipped.append({"expiry": exp.date().isoformat(), "why": f"no traded strike on {d0.date()}"})
            continue
        qty = lot * lots
        credit = -sum(p["sign"] * p["entry"] for p in pos) * qty
        # maximum profit: a credit position keeps the credit; a debit one is measured against what it paid
        max_profit = credit if credit > 0 else None
        cost_in = sum(_charges(p["entry"] * qty, p["side"], d0) for p in pos)
        exit_day, why, values = exp, "expiry", None
        last_vals = {i: p["entry"] for i, p in enumerate(pos)}
        path = []
        for d in [pd.Timestamp(x) for x in days if d0 < pd.Timestamp(x) <= exp]:
            g = by_day[d]
            g = g[g["expiry"] == exp]
            if d == exp or d.date() == exp.date():
                u = float(under_close.loc[d])
                vals = {i: max(u - p["strike"], 0.0) if p["type"] == "CE" else max(p["strike"] - u, 0.0) for i, p in enumerate(pos)}
            else:
                vals = {}
                for i, p in enumerate(pos):
                    r = g[(g["type"] == p["type"]) & (g["strike"] == p["strike"])]
                    vals[i] = float(r["close"].iloc[0]) if len(r) and r["close"].iloc[0] > 0 else last_vals[i]
            last_vals = vals
            pnl = sum(p["sign"] * (vals[i] - p["entry"]) for i, p in enumerate(pos)) * qty
            path.append(round(pnl, 2))
            if d.date() == exp.date():
                values = vals
                break
            base = abs(credit)
            if stop_pct and base > 0 and pnl <= -float(stop_pct) / 100 * base:
                exit_day, why, values = d, "stop", vals
                break
            if target_pct and max_profit and pnl >= float(target_pct) / 100 * max_profit:
                exit_day, why, values = d, "target", vals
                break
            if target_pct and not max_profit and base > 0 and pnl >= float(target_pct) / 100 * base:
                exit_day, why, values = d, "target", vals
                break
        if values is None:
            skipped.append({"expiry": exp.date().isoformat(), "why": "prices missing before expiry"})
            continue
        cost_out = 0.0
        exit_px = []
        for i, p in enumerate(pos):
            v = values[i]
            if why == "expiry":
                fill = v
                if p["side"] == "buy" and v > 0:
                    cost_out += v * qty * STT_EXERCISE_PCT / 100
            else:
                fill = v * (1 - slip) if p["side"] == "buy" else v * (1 + slip)
                cost_out += _charges(fill * qty, "sell" if p["side"] == "buy" else "buy", exit_day)
            exit_px.append(round(fill, 2))
        gross = sum(p["sign"] * (exit_px[i] - p["entry"]) for i, p in enumerate(pos)) * qty
        charges = cost_in + cost_out
        trades.append({"entry": d0.date().isoformat(), "exit": exit_day.date().isoformat(), "expiry": exp.date().isoformat(),
                       "spot_in": round(spot, 2), "spot_out": round(float(under_close.loc[exit_day]), 2),
                       "legs": [{"side": p["side"], "type": p["type"], "strike": p["strike"], "entry": p["entry"],
                                 "exit": exit_px[i]} for i, p in enumerate(pos)],
                       "qty": qty, "credit": round(credit, 2), "why": why, "gross": round(gross, 2),
                       "charges": round(charges, 2), "pnl": round(gross - charges, 2), "worst_open": min(path) if path else 0.0})
        busy_until = exit_day
    return {"trades": trades, "skipped": skipped, "stats": stats(trades), "curve": curve(trades)}


def curve(trades: list[dict]) -> list[dict]:
    eq, out = 0.0, []
    for t in sorted(trades, key=lambda t: t["exit"]):
        eq += t["pnl"]
        out.append({"date": t["exit"], "equity": round(eq, 2)})
    return out


def stats(trades: list[dict]) -> dict:
    n = len(trades)
    if not n:
        return {"trades": 0}
    pnl = np.array([t["pnl"] for t in trades])
    eq = np.cumsum(pnl)
    dd = float((eq - np.maximum.accumulate(np.r_[0.0, eq])[1:]).min())
    wins, losses = pnl[pnl > 0], pnl[pnl <= 0]
    years: dict[str, list[float]] = {}
    for t in trades:
        years.setdefault(t["exit"][:4], []).append(t["pnl"])
    return {"trades": n, "win_rate": round(len(wins) / n * 100, 1), "total": round(float(pnl.sum()), 2),
            "avg": round(float(pnl.mean()), 2), "avg_win": round(float(wins.mean()), 2) if len(wins) else None,
            "avg_loss": round(float(losses.mean()), 2) if len(losses) else None, "best": round(float(pnl.max()), 2),
            "worst": round(float(pnl.min()), 2), "max_drawdown": round(dd, 2),
            "profit_factor": round(float(wins.sum() / -losses.sum()), 2) if len(losses) and losses.sum() < 0 else None,
            "charges": round(sum(t["charges"] for t in trades), 2),
            "exits": {k: sum(1 for t in trades if t["why"] == k) for k in ("expiry", "stop", "target")},
            "by_year": [{"year": y, "trades": len(v), "total": round(sum(v), 2)} for y, v in sorted(years.items())],
            "first": min(t["entry"] for t in trades), "last": max(t["exit"] for t in trades)}


def today_range(hist: pd.DataFrame) -> tuple[date | None, date | None]:
    if hist.empty:
        return None, None
    return hist["date"].min().date(), hist["date"].max().date()
