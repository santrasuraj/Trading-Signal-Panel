"""Paper-trading journal: live, forward evidence for the strategies.

Backtests flatter (survivorship bias, timing luck), so every scan of a *completed* trading day
writes each strategy's orders for the next open and its model portfolio to data/journal.sqlite -
one record per strategy and day; scanning the same day again replaces that day's record.
Intraday scans are provisional (today's candle can still change) and are never journaled.

The paper portfolios are rebuilt from scratch from the journal and the price store every time they
are shown, so the same inputs always give the same P&L, and corrected prices or split adjustments
flow through automatically:
  - each strategy starts with the account capital (config.yaml) of its first journal day;
  - orders fill at the next trading day's official open with slippage and full charges (costs.py),
    sized like the backtest (equity / max positions, never more than the cash available);
  - stop-losses / targets trigger intraday from the day's low / high, as in the backtest;
  - the paper portfolio follows the model portfolio: on the first day it buys the current model
    holdings, and if a scan was missed it catches up at the open after the next scan.
"""
from __future__ import annotations

import json
import math
import sqlite3
from contextlib import closing
from pathlib import Path

import numpy as np
import pandas as pd

from .costs import CostModel
from .engine import Trade, _curve_stats, _trade_stats
from .panel import TRADING_DAYS
from .providers import INDEX_N500, INDEX_NIFTY
from .settings import DATA_DIR

JOURNAL_FILE = DATA_DIR / "journal.sqlite"
SURVIVORSHIP_HAIRCUT_PCT = 8.0   # backtests on today's index list overstate returns by ~8%/yr (see README)
MIN_DAYS_TO_JUDGE = 21           # under a month, any result is mostly noise
NOT_IN_MODEL = "no longer in model portfolio"
CATCH_UP = "in model portfolio (catch-up)"

_COLUMNS = {
    "scans": ["date", "strategy", "name", "kind", "generated_at", "capital", "rules", "expect"],
    "orders": ["date", "strategy", "symbol", "action", "seq", "reason", "qty", "price", "stop"],
    "positions": ["date", "strategy", "symbol", "entry_date", "entry_price", "last_price", "stop"],
}
_SCHEMA = """
CREATE TABLE IF NOT EXISTS scans (
    date TEXT NOT NULL, strategy TEXT NOT NULL, name TEXT, kind TEXT, generated_at TEXT,
    capital REAL, rules TEXT, expect TEXT, PRIMARY KEY (strategy, date));
CREATE TABLE IF NOT EXISTS orders (
    date TEXT NOT NULL, strategy TEXT NOT NULL, symbol TEXT NOT NULL, action TEXT NOT NULL, seq INTEGER,
    reason TEXT, qty INTEGER, price REAL, stop REAL, PRIMARY KEY (strategy, date, symbol));
CREATE TABLE IF NOT EXISTS positions (
    date TEXT NOT NULL, strategy TEXT NOT NULL, symbol TEXT NOT NULL, entry_date TEXT, entry_price REAL,
    last_price REAL, stop REAL, PRIMARY KEY (strategy, date, symbol));
"""
_EXPECT_KEYS = ("cagr_pct", "cagr_range", "vol_pct", "max_dd_pct", "after_tax_cagr_pct", "te_n500_pct", "start", "end")


def _connect(path=None) -> sqlite3.Connection:
    con = sqlite3.connect(str(path or JOURNAL_FILE), timeout=30)
    con.executescript(_SCHEMA)
    return con


def _ok(x) -> bool:
    return x is not None and not (isinstance(x, float) and math.isnan(x))


# ----------------------------------------------------------------------------- journal
def record_scan(result: dict, path=None) -> int:
    """Journal a completed-day scan: every strategy's next-open orders, model positions, rules and
    backtest expectation. A second scan of the same day replaces the first. Returns strategies written."""
    if result.get("live"):
        return 0          # provisional intraday orders: the candle can still change
    day = str(result["data_date"])[:10]
    capital = float(result.get("capital") or 0)
    scans, orders, positions = [], [], []
    for s in result.get("strategies", []):
        full = (s.get("metrics") or {}).get("full") or {}
        expect = {k: full.get(k) for k in _EXPECT_KEYS}
        expect["nifty_cagr_pct"] = (full.get("benchmark") or {}).get("cagr_pct")
        expect["n500_cagr_pct"] = (full.get("n500_benchmark") or {}).get("cagr_pct")
        rules = {"max_positions": s.get("max_positions"), "min_position": result.get("min_position", 0),
                 **(s.get("rules") or {})}
        scans.append((day, s["key"], s.get("name"), s.get("kind"), result.get("generated_at"), capital,
                      json.dumps(rules), json.dumps(expect)))
        for i, a in enumerate(s.get("actions", [])):
            orders.append((day, s["key"], a["symbol"], a["action"], i, a.get("reason"), a.get("qty"),
                           a.get("price"), a.get("stop")))
        for pp in s.get("positions", []):
            positions.append((day, s["key"], pp["symbol"], pp.get("entry_date"), pp.get("entry_price"),
                              pp.get("last_price"), pp.get("stop")))
    with closing(_connect(path)) as con, con:
        for table in _COLUMNS:
            con.execute(f"DELETE FROM {table} WHERE date = ?", (day,))
        con.executemany("INSERT INTO scans VALUES (?,?,?,?,?,?,?,?)", scans)
        con.executemany("INSERT OR REPLACE INTO orders VALUES (?,?,?,?,?,?,?,?,?)", orders)
        con.executemany("INSERT OR REPLACE INTO positions VALUES (?,?,?,?,?,?,?)", positions)
    return len(scans)


def load_journal(path=None) -> dict[str, pd.DataFrame]:
    p = Path(path or JOURNAL_FILE)
    if not p.exists():
        return {t: pd.DataFrame(columns=cols) for t, cols in _COLUMNS.items()}
    with closing(_connect(p)) as con:
        return {t: pd.read_sql_query(f"SELECT * FROM {t} ORDER BY date", con) for t in _COLUMNS}


# ----------------------------------------------------------------------------- simulation
def paper_trade(key: str, journal: dict[str, pd.DataFrame], frames: dict[str, pd.DataFrame],
                costs: CostModel) -> dict | None:
    """Rebuild one strategy's paper portfolio from its journal and the stored prices (completed days only)."""
    scans = journal["scans"][journal["scans"]["strategy"] == key].sort_values("date")
    close_all = frames["close"].sort_index()
    if scans.empty or close_all.empty:
        return None
    orders = journal["orders"][journal["orders"]["strategy"] == key]
    positions = journal["positions"][journal["positions"]["strategy"] == key]
    dates = close_all.index
    T = len(dates)
    first = str(scans["date"].iloc[0])
    i0 = int(dates.searchsorted(pd.Timestamp(first), side="right")) - 1   # last trading day <= first journal day
    if i0 < 0:
        return None
    kind = scans["kind"].iloc[0]
    capital = float(scans["capital"].iloc[0])

    syms = sorted(set(orders["symbol"]) | set(positions["symbol"]))
    col = {s: j for j, s in enumerate(syms)}

    def arr(f: str) -> np.ndarray:
        return frames[f].sort_index().reindex(index=dates, columns=syms).to_numpy(dtype=float)

    O, H, L, C = (arr(f) for f in ("open", "high", "low", "close"))
    C_ff = pd.DataFrame(C).ffill().to_numpy()
    # Slippage as in the backtest: stocks averaging under `illiquid_below_cr` a day (to yesterday) cost more.
    turnover = pd.DataFrame(C * arr("volume")).rolling(20, min_periods=15).mean().to_numpy() / 1e7
    liquid = np.zeros(C.shape, dtype=bool)
    liquid[1:] = turnover[:-1] >= costs.illiquid_below_cr
    slip = np.where(liquid, costs.slippage_pct, costs.slippage_illiquid_pct) / 100

    days: dict[str, dict] = {}
    exec_at: dict[int, str] = {}      # trading-day row -> journal day whose orders fill at its open
    for row in scans.itertuples(index=False):
        d = str(row.date)
        od = orders[orders["date"] == d].sort_values("seq")
        model = {}
        for pp in positions[positions["date"] == d].itertuples(index=False):
            frac = (pp.stop / pp.last_price if _ok(pp.stop) and _ok(pp.last_price) and pp.last_price > 0 else None)
            model[pp.symbol] = (str(pp.entry_date), frac)   # stop as a fraction of that day's close (split-proof)
        t_exec = int(dates.searchsorted(pd.Timestamp(d), side="right"))
        days[d] = {"rules": json.loads(row.rules or "{}"), "model": model, "di": t_exec - 1,
                   "sells": {o.symbol: o.reason for o in od.itertuples(index=False) if o.action == "SELL"},
                   "buys": [(o.symbol, o.reason) for o in od.itertuples(index=False) if o.action == "BUY"],
                   "t": t_exec}
        if t_exec < T:
            exec_at[t_exec] = d       # days are in order, so the newest journal day wins

    cash, fees, slippage = capital, 0.0, 0.0
    pos: dict[str, dict] = {}
    pending_sell: dict[str, str] = {}
    last_exit: dict[str, str] = {}
    trades: list[Trade] = []
    via: list[str] = []
    rules = days[first]["rules"]
    equity = np.full(T - i0, np.nan)
    equity[0] = capital

    def plan(d: str) -> tuple[dict[str, str], list[tuple]]:
        """Orders for the open after journal day `d`: its own orders, plus whatever brings the paper
        portfolio back in line with the model portfolio (first day, missed scans)."""
        info = days[d]
        model, sells = info["model"], info["sells"]
        buys = [s for s, _ in info["buys"]]
        target = (set(model) - set(sells)) | set(buys)
        out_sells = {s: sells.get(s, NOT_IN_MODEL) for s in pos if s not in target}
        out_buys = [(s, "order", None, r) for s, r in info["buys"] if s not in pos]
        for s, (entry, frac) in model.items():
            if s in pos or s in sells or s in buys:
                continue
            if s in last_exit and entry <= last_exit[s]:
                continue          # the paper position was stopped out; don't buy the same model position back
            ref = C[info["di"], col[s]] if info["di"] >= 0 else np.nan
            out_buys.append((s, "sync", frac * ref if frac is not None and ref > 0 else None, CATCH_UP))
        return out_sells, out_buys

    def mark(t: int, use_open: bool = False) -> float:
        val = 0.0
        for s, ps in pos.items():
            j = col[s]
            px = O[t, j] if use_open and O[t, j] > 0 else C_ff[t, j]
            val += ps["qty"] * (px if not math.isnan(px) else ps["entry"])
        return val

    def close_position(t: int, s: str, raw_px: float, reason: str) -> None:
        nonlocal cash, fees, slippage
        ps = pos.pop(s)
        fill = raw_px * (1 - slip[t, col[s]])
        value = ps["qty"] * fill
        fee = costs.sell_cost(value)
        cash += value - fee
        fees += fee
        slippage += ps["qty"] * (raw_px - fill)
        pnl = value - fee - ps["cost"]
        trades.append(Trade(s, dates[ps["t"]], ps["entry"], dates[t], fill, ps["qty"], pnl,
                            pnl / ps["cost"] * 100, t - ps["t"], reason))
        via.append(ps["via"])
        last_exit[s] = dates[t].date().isoformat()

    for t in range(i0 + 1, T):
        buys: list[tuple] = []
        d = exec_at.get(t)
        if d is not None:
            rules = days[d]["rules"]
            sells, buys = plan(d)
            for s, r in sells.items():
                pending_sell.setdefault(s, r)

        # 1) Sells at the open first (a missing open keeps the order for the next day), then buys.
        for s, r in list(pending_sell.items()):
            if s not in pos:
                del pending_sell[s]
            elif O[t, col[s]] > 0:
                close_position(t, s, O[t, col[s]], r)
                del pending_sell[s]
        if buys:
            max_pos = int(rules.get("max_positions") or 10)
            stop_pct, target_pct = rules.get("stop_pct"), rules.get("target_pct")
            eq_open = cash + mark(t, use_open=True)
            slots = max_pos - len(pos)
            for s, how, sync_stop, _ in buys:
                if slots <= 0:
                    break
                px = O[t, col[s]]
                if s in pos or not px > 0:
                    continue
                fill = px * (1 + slip[t, col[s]])
                stop = sync_stop if how == "sync" else (fill * (1 - stop_pct / 100) if stop_pct else None)
                if stop is not None and px <= stop:
                    continue      # opened below the model's stop: the model itself exits today
                alloc = eq_open / max_pos
                if kind == "event" and rules.get("sizing") == "risk" and stop is not None and fill > stop:
                    alloc = min(eq_open * float(rules.get("risk_pct") or 1) / 100 / (fill - stop) * fill, 2 * alloc)
                alloc = min(alloc, cash / (1 + 0.003))   # leave room for charges
                qty = int(alloc // fill)
                if qty < 1 or qty * fill < float(rules.get("min_position") or 0):
                    continue
                value = qty * fill
                fee = costs.buy_cost(value)
                if value + fee > cash:
                    continue
                cash -= value + fee
                fees += fee
                slippage += qty * (fill - px)
                target = fill * (1 + target_pct / 100) if kind == "event" and target_pct else None
                pos[s] = {"qty": qty, "entry": fill, "t": t, "stop": stop, "target": target, "peak": fill,
                          "cost": value + fee, "via": how}
                slots -= 1

        # 2) Intraday stop-loss / target, exactly as the backtest.
        for s in list(pos):
            ps, j = pos[s], col[s]
            if math.isnan(L[t, j]):
                continue
            if ps["stop"] is not None and L[t, j] <= ps["stop"]:
                close_position(t, s, min(O[t, j], ps["stop"]) if not math.isnan(O[t, j]) else ps["stop"], "stop-loss")
            elif ps["target"] is not None and H[t, j] >= ps["target"]:
                close_position(t, s, max(O[t, j], ps["target"]) if not math.isnan(O[t, j]) else ps["target"], "target")

        # 3) Trailing stops at the close, then mark to market.
        trail = rules.get("trail_pct") if kind == "event" else None
        for s, ps in pos.items():
            if not math.isnan(C[t, col[s]]):
                ps["peak"] = max(ps["peak"], C[t, col[s]])
            if trail:
                level = ps["peak"] * (1 - trail / 100)
                ps["stop"] = max(ps["stop"], level) if ps["stop"] is not None else level
        equity[t - i0] = cash + mark(t)

    # Orders not filled yet: the newest journal day has no next trading day in the store.
    last_day = str(scans["date"].iloc[-1])
    waiting = [{"action": "SELL", "symbol": s, "reason": r} for s, r in pending_sell.items() if s in pos]
    if days[last_day]["t"] >= T:
        sells, buys = plan(last_day)
        waiting += [{"action": "SELL", "symbol": s, "reason": r} for s, r in sells.items() if s not in pending_sell]
        waiting += [{"action": "BUY", "symbol": s, "reason": r} for s, _, _, r in buys]

    last = T - 1
    open_rows = []
    for s, ps in pos.items():
        px = C_ff[last, col[s]]
        value = ps["qty"] * px
        open_rows.append({"symbol": s, "entry_date": dates[ps["t"]].date().isoformat(), "entry_price": float(ps["entry"]),
                          "qty": ps["qty"], "last_price": float(px), "value": float(value),
                          "pnl": float(value - ps["cost"]), "ret_pct": float((value / ps["cost"] - 1) * 100),
                          "stop": float(ps["stop"]) if ps["stop"] is not None else np.nan, "days": last - ps["t"],
                          "via": ps["via"]})
    trade_rows = [{"symbol": tr.symbol, "entry_date": tr.entry_date.date().isoformat(),
                   "entry_price": float(tr.entry_price), "exit_date": tr.exit_date.date().isoformat(),
                   "exit_price": float(tr.exit_price), "qty": tr.qty, "pnl": float(tr.pnl), "ret_pct": float(tr.ret_pct),
                   "days": tr.days, "reason": tr.reason, "via": v} for tr, v in zip(trades, via)]

    eq_idx = dates[i0:]
    curves = pd.DataFrame({"Paper": pd.Series(equity, index=eq_idx)})
    for sym, label in ((INDEX_NIFTY, "NIFTY 50"), (INDEX_N500, "NIFTY 500")):
        if sym in close_all.columns:
            b = close_all[sym].iloc[i0:].ffill()
            if b.notna().any():
                curves[label] = b / b.dropna().iloc[0] * capital
    return {
        "key": key, "name": scans["name"].iloc[-1] or key, "kind": kind, "capital": capital,
        "start": first, "last_date": dates[-1].date().isoformat(), "days": T - 1 - i0,
        "journal_days": len(scans), "last_journal": last_day,
        "equity": curves, "cash": cash, "fees": fees, "slippage": slippage,
        "open": open_rows, "trades": trade_rows, "pending": waiting,
        "trade_stats": _trade_stats(trades), "expect": json.loads(scans["expect"].iloc[0] or "{}"),
    }


# ----------------------------------------------------------------------------- report
def summarize(rep: dict) -> dict:
    """Headline numbers and how they compare with what the backtest led us to expect."""
    curves, capital, days = rep["equity"], rep["capital"], rep["days"]
    eq = curves["Paper"]

    def ret(label: str):
        s = curves.get(label)
        return float((s.iloc[-1] / capital - 1) * 100) if s is not None and pd.notna(s.iloc[-1]) else None

    live, n50, n500 = ret("Paper"), ret("NIFTY 50"), ret("NIFTY 500")
    ref = n500 if n500 is not None else n50
    exp = rep["expect"]
    years = days / TRADING_DAYS

    def pace(cagr):
        return ((1 + cagr / 100) ** years - 1) * 100 if _ok(cagr) and cagr > -100 else None

    bt_bench = pace(exp.get("n500_cagr_pct"))

    def excess(cagr):
        """Lead over the Nifty 500 the backtest implies for this many days."""
        p = pace(cagr)
        return p - bt_bench if p is not None and bt_bench is not None else None

    def expected(cagr):
        """Return the backtest implies for these days, given what the index actually did."""
        e = excess(cagr)
        return ref + e if ref is not None and e is not None else pace(cagr)

    cagr = exp.get("cagr_pct")
    haircut = cagr - SURVIVORSHIP_HAIRCUT_PCT if _ok(cagr) else None
    exp_excess = excess(cagr)
    rng = exp.get("cagr_range")
    live_excess = live - ref if ref is not None else None
    # Two standard deviations of how far luck alone moves the gap to the index over this many days.
    noise = exp.get("te_n500_pct") or exp.get("vol_pct")
    band = 2 * noise * math.sqrt(years) if noise else None

    start = pd.Timestamp(rep["start"]).strftime("%d %b %Y")
    if days == 0:
        verdict, level = f"Started {start}: the first paper orders fill at the next market open.", "neutral"
    elif days < MIN_DAYS_TO_JUDGE or live_excess is None or exp_excess is None or band is None:
        verdict, level = (f"Too early to judge: {days} trading days. Short-term results are mostly noise - "
                          "give it 6-12 months."), "neutral"
    elif live_excess < exp_excess - band:
        verdict, level = ("Behind the backtest by more than normal noise. Evidence that the backtested edge is "
                          "not real (or has stopped working)."), "bad"
    elif live_excess > exp_excess + band:
        verdict, level = "Ahead of the backtest by more than normal noise - probably luck; keep watching.", "good"
    else:
        verdict, level = (f"Within normal noise of the backtest after {days} trading days. It takes about a year "
                          "before the gap means much."), "neutral"
    return {
        "name": rep["name"], "start": rep["start"], "days": days, "last_date": rep["last_date"],
        "equity": float(eq.iloc[-1]), "return_pct": live, "pnl": float(eq.iloc[-1] - capital),
        "nifty_pct": n50, "n500_pct": n500, "excess_pct": live_excess,
        "expected_pct": expected(cagr), "expected_range_pct": [expected(x) for x in rng] if rng else None,
        "haircut_pct": expected(haircut), "expected_excess_pct": exp_excess, "haircut_excess_pct": excess(haircut),
        "noise_pct": band,
        "backtest_cagr_pct": exp.get("cagr_pct"), "backtest_n500_cagr_pct": exp.get("n500_cagr_pct"),
        "max_dd_pct": _curve_stats(eq)["max_dd_pct"] if len(eq) > 1 else None,
        "trades": rep["trade_stats"]["trades"], "win_rate": rep["trade_stats"]["win_rate"],
        "open": len(rep["open"]), "pending": len(rep["pending"]),
        "fees": rep["fees"], "slippage": rep["slippage"],
        "verdict": verdict, "level": level,
    }


def build_report(frames: dict[str, pd.DataFrame], costs: CostModel, path=None) -> dict[str, dict]:
    """Paper portfolio + summary for every journaled strategy (deterministic: journal + stored prices)."""
    journal = load_journal(path)
    out = {}
    for key in dict.fromkeys(journal["scans"]["strategy"]):
        rep = paper_trade(key, journal, frames, costs)
        if rep is not None:
            rep["summary"] = summarize(rep)
            out[key] = rep
    return out


def summaries(frames: dict[str, pd.DataFrame], costs: CostModel, path=None) -> dict[str, dict]:
    """Rounded, JSON-ready summaries (saved with each scan for Telegram and the dashboard)."""
    def clean(v):
        if isinstance(v, list):
            return [clean(x) for x in v]
        if isinstance(v, (float, np.floating)):
            return None if math.isnan(v) or math.isinf(v) else round(float(v), 2)
        return v
    return {k: {kk: clean(vv) for kk, vv in rep["summary"].items()}
            for k, rep in build_report(frames, costs, path).items()}
