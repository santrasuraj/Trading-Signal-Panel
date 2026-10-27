"""Signal track record: what happened to every BUY signal the scanner actually gave.

The paper portfolios (paper.py) answer "how would a whole account following the strategy have done"; they can
skip a signal (no free slot, no cash). This module answers the narrower question "was each signal right":
every BUY order in the journal (data/journal.sqlite, completed-day scans only) is followed on its own, on the
stored real prices, exactly as the strategy's rules say:
  - entry at the next trading day's official open plus slippage and full charges (costs.py); no fill at an
    upper-circuit lock, without an open price, or when the stock opens below the order's own stop;
  - quantity as the signal said (sized like the scan), else an equal slot of the capital;
  - exit at the first of: the intraday stop-loss / target (from the day's low / high, as in the backtest; not
    at a lower-circuit lock), the trailing stop (at the close), or the next open after a later scan of the same
    strategy sells it or no longer holds it in its model portfolio;
  - still held = open, marked at the last close (P&L if sold there, after charges).
Nothing is estimated or simulated beyond those fills: a signal with no next trading day yet is 'pending'.
"""
from __future__ import annotations

import json
import math

import numpy as np
import pandas as pd

from .costs import CostModel
from .paper import NOT_IN_MODEL, _clean_etfs, _ok, _sorted, load_journal

MIN_CLOSED = 10      # fewer closed signals than this: too few to judge a strategy's live record


def _stats(rows: list[dict]) -> dict:
    """Statistics of closed signals (ret_pct after costs, pnl in rupees)."""
    closed = [r for r in rows if r["state"] == "closed"]
    opened = [r for r in rows if r["state"] == "open"]
    out = {"signals": len(rows), "closed": len(closed), "open": len(opened),
           "pending": sum(1 for r in rows if r["state"] == "pending"),
           "not_filled": sum(1 for r in rows if r["state"] == "not_filled"),
           "win_rate": None, "avg_win_pct": None, "avg_loss_pct": None, "expectancy_pct": None,
           "profit_factor": None, "avg_days": None,
           "realised_pnl": float(sum(r["pnl"] for r in closed)),
           "open_pnl": float(sum(r["pnl"] for r in opened))}
    if closed:
        r = np.array([x["ret_pct"] for x in closed])
        pnl = np.array([x["pnl"] for x in closed])
        wins, losses = r[r > 0], r[r <= 0]
        gross_loss = -pnl[pnl <= 0].sum()
        out.update(win_rate=float((r > 0).mean() * 100),
                   avg_win_pct=float(wins.mean()) if len(wins) else None,
                   avg_loss_pct=float(losses.mean()) if len(losses) else None,
                   expectancy_pct=float(r.mean()),
                   profit_factor=float(pnl[pnl > 0].sum() / gross_loss) if gross_loss > 0 else None,
                   avg_days=float(np.mean([x["days"] for x in closed])))
    return out


def verdict(stats: dict) -> tuple[str, str]:
    """(level, text) of a live record: 'unknown' until MIN_CLOSED signals have closed."""
    n = stats["closed"]
    if n < MIN_CLOSED:
        return "unknown", f"Too few closed signals to judge yet ({n} of {MIN_CLOSED})."
    e = stats["expectancy_pct"] or 0.0
    if e > 0:
        return "good", f"Making money: the average closed signal returned {e:+.2f}% after costs ({n} closed)."
    return "bad", f"Losing money: the average closed signal returned {e:+.2f}% after costs ({n} closed)."


def strategy_track(key: str, journal: dict[str, pd.DataFrame], frames: dict[str, pd.DataFrame],
                   costs: CostModel) -> list[dict]:
    """One row per journaled BUY signal of strategy `key` (oldest first). `frames` sorted by date."""
    scans = journal["scans"][journal["scans"]["strategy"] == key].sort_values("date")
    orders = journal["orders"][journal["orders"]["strategy"] == key]
    buys = orders[orders["action"] == "BUY"].sort_values(["date", "seq"])
    close_all = frames["close"]
    if scans.empty or buys.empty or close_all.empty:
        return []
    positions = journal["positions"][journal["positions"]["strategy"] == key]
    dates = close_all.index
    T = len(dates)
    syms = sorted(set(buys["symbol"]))
    col = {s: j for j, s in enumerate(syms)}

    def arr(f: str) -> np.ndarray:
        return frames[f].reindex(index=dates, columns=syms).to_numpy(dtype=float)

    O, H, L, C = (arr(f) for f in ("open", "high", "low", "close"))
    V = arr("volume")
    C_ff = pd.DataFrame(C).ffill().to_numpy()
    prev_c = np.vstack([np.full((1, C.shape[1]), np.nan), C[:-1]])
    locked = (H == L) & (V > 0)                      # one price all day on real volume: a circuit lock
    up_lock, dn_lock = locked & (C > prev_c), locked & (C < prev_c)
    turnover = pd.DataFrame(C * V).rolling(20, min_periods=15).mean().to_numpy() / 1e7
    liquid = np.zeros(C.shape, dtype=bool)
    liquid[1:] = turnover[:-1] >= costs.illiquid_below_cr
    slip = np.where(liquid, costs.slippage_pct, costs.slippage_illiquid_pct) / 100

    # every scan of this strategy: the open its decisions act on, what it sold, what its model held
    held_by_day = {str(d): set(g["symbol"]) for d, g in positions.groupby("date", sort=False)}
    sells_by_day = {str(d): dict(zip(g["symbol"], g["reason"]))
                    for d, g in orders[orders["action"] == "SELL"].groupby("date", sort=False)}
    meta = {}
    for row in scans.itertuples(index=False):
        d = str(row.date)
        expect = json.loads(row.expect or "{}")
        meta[d] = {"t": int(dates.searchsorted(pd.Timestamp(d), side="right")), "rules": json.loads(row.rules or "{}"),
                   "capital": float(row.capital or 0), "status": expect.get("status"),
                   "held": held_by_day.get(d, set()), "sells": sells_by_day.get(d, {})}
    journal_days = list(meta)
    name = scans["name"].iloc[-1] or key
    kind = scans["kind"].iloc[-1]

    out = []
    for o in buys.itertuples(index=False):
        d, s, j = str(o.date), o.symbol, col[o.symbol]
        info = meta.get(d)
        if info is None:
            continue
        rules = info["rules"]
        row = {"strategy_key": key, "strategy_name": name, "signal_date": d, "symbol": s,
               "reason": str(o.reason or ""), "signal_price": float(o.price) if _ok(o.price) else None,
               "status_then": info["status"], "state": "pending", "note": None, "qty": None,
               "entry_date": None, "entry_price": None, "exit_date": None, "exit_price": None, "exit_reason": None,
               "last_price": None, "stop": None, "days": 0, "pnl": 0.0, "ret_pct": 0.0}
        out.append(row)
        t = info["t"]
        if t >= T:
            row["note"] = "Fills at the next open"
            continue
        px = O[t, j]
        stop_pct, target_pct, trail = rules.get("stop_pct"), rules.get("target_pct"), rules.get("trail_pct")
        if not px > 0:
            row.update(state="not_filled", note="No opening price that day")
            continue
        if up_lock[t, j]:
            row.update(state="not_filled", note="Locked at the upper circuit: no seller")
            continue
        fill = px * (1 + slip[t, j])
        stop = fill * (1 - stop_pct / 100) if stop_pct else None
        frac = o.stop / o.price if _ok(o.stop) and _ok(o.price) and o.price > 0 else None
        if rules.get("stop_atr") and frac is not None:            # the order's own k x ATR stop, as the engine
            stop = max(stop, fill * frac) if stop is not None else fill * frac
        if stop is not None and px <= stop:
            row.update(state="not_filled", note="Opened below the stop: the strategy would exit at once")
            continue
        qty = int(o.qty) if _ok(o.qty) and o.qty and o.qty > 0 else 0
        if qty < 1:                                               # no size in the journal: an equal slot
            slot = info["capital"] / max(int(rules.get("max_positions") or 10), 1)
            qty = int(slot // fill)
        if qty < 1:
            row.update(state="not_filled", note="Too expensive for one slot of the capital")
            continue
        cost = qty * fill + costs.buy_cost(qty * fill)
        target = fill * (1 + target_pct / 100) if kind == "event" and target_pct else None
        # the next open after a later scan of this strategy that sold it or stopped holding it
        exit_at, exit_why = T, None
        for d2 in journal_days:
            m = meta[d2]
            if m["t"] <= t:
                continue               # decided before this position existed (the signal day itself included)
            if s in m["sells"]:
                exit_at, exit_why = m["t"], str(m["sells"][s] or "sell signal")
                break
            if s not in m["held"]:
                exit_at, exit_why = m["t"], NOT_IN_MODEL
                break
        peak, done = fill, None
        for t2 in range(t, T):
            if t2 >= exit_at and t2 > t and O[t2, j] > 0 and not dn_lock[t2, j]:
                done = (t2, O[t2, j], exit_why)               # sell at the open (waits through a lower-circuit lock)
                break
            if not math.isnan(L[t2, j]) and not dn_lock[t2, j]:
                if stop is not None and L[t2, j] <= stop:
                    done = (t2, min(O[t2, j], stop) if not math.isnan(O[t2, j]) else stop, "stop-loss")
                    break
                if target is not None and H[t2, j] >= target:
                    done = (t2, max(O[t2, j], target) if not math.isnan(O[t2, j]) else target, "target")
                    break
            if not math.isnan(C[t2, j]):
                peak = max(peak, C[t2, j])
            if trail and kind == "event":
                level = peak * (1 - trail / 100)
                stop = max(stop, level) if stop is not None else level
        row.update(qty=qty, entry_date=dates[t].date().isoformat(), entry_price=round(float(fill), 2),
                   stop=round(float(stop), 2) if stop is not None else None)
        if done is not None:
            t2, raw, why = done
            px_out = raw * (1 - slip[t2, j])
            value = qty * px_out
            pnl = value - costs.sell_cost(value) - cost
            row.update(state="closed", exit_date=dates[t2].date().isoformat(), exit_price=round(float(px_out), 2),
                       exit_reason=why, last_price=round(float(px_out), 2), days=t2 - t)
        else:
            last = C_ff[T - 1, j]
            last = last if not math.isnan(last) else fill
            value = qty * last
            pnl = value - costs.sell_cost(value) - cost      # what selling at the last close would leave
            row.update(state="open", last_price=round(float(last), 2), days=T - 1 - t)
        row.update(pnl=round(float(pnl), 2), ret_pct=round(float(pnl / cost * 100), 3))
    return out


def track_record(frames: dict[str, pd.DataFrame], costs: CostModel, path=None, etfs=()) -> dict:
    """{'as_of', 'min_closed', 'signals' (newest first), 'strategies': {key: stats}, 'overall': stats}."""
    journal = load_journal(path)
    frames = _clean_etfs({k: _sorted(v) for k, v in frames.items()}, etfs)
    rows: list[dict] = []
    for key in dict.fromkeys(journal["scans"]["strategy"]):
        rows += strategy_track(str(key), journal, frames, costs)
    by_key: dict[str, list[dict]] = {}
    for r in rows:
        by_key.setdefault(r["strategy_key"], []).append(r)
    strategies = {}
    for k, rs in by_key.items():
        st = _stats(rs)
        st["level"], st["verdict"] = verdict(st)
        strategies[k] = {"name": rs[-1]["strategy_name"], **st}
    overall = _stats(rows)
    overall["level"], overall["verdict"] = verdict(overall)
    close = frames.get("close")
    rows.sort(key=lambda r: (r["signal_date"], r["strategy_key"], r["symbol"]), reverse=True)
    return {"as_of": close.index[-1].date().isoformat() if close is not None and len(close) else None,
            "min_closed": MIN_CLOSED, "signals": rows, "strategies": strategies, "overall": overall}
