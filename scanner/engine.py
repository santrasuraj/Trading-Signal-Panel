"""Portfolio-level backtest engine.

Simulates a real account day by day: signals are read at the close of day t, orders fill at the
open of day t+1 (with slippage), stops/targets trigger intraday from day t+1's low/high, positions
are sized from current equity, and every order pays Indian delivery charges (see costs.py).

Two kinds of strategy are supported:
  EventStrategy - buy when an entry signal fires; exit on stop / target / trailing stop /
                  exit signal / time limit.  (breakouts, pullbacks)
  RankStrategy  - every rebalance date hold the top-N stocks by a score, keeping current
                  holdings while they stay inside a wider buffer rank.  (momentum, 52w-high)
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable

import numpy as np
import pandas as pd

from .costs import CostModel, TaxModel
from .panel import TRADING_DAYS, Factors

Frame = Callable[[Factors], pd.DataFrame]


@dataclass
class EventStrategy:
    key: str
    name: str
    description: str
    entries: Frame                       # bool: signal at close of day t
    priority: Frame | None = None        # higher = preferred when there are more signals than free slots
    exit_signal: Frame | None = None     # bool: exit at next open
    stop_pct: float | None = 8.0         # initial stop, % below fill price
    stop_atr: float | None = None        # or: initial stop = fill - k * ATR(14)
    target_pct: float | None = None
    trail_pct: float | None = None       # trailing stop, % below highest close since entry
    max_hold: int | None = None          # trading days
    max_positions: int = 10
    sizing: str = "equal"                # "equal" or "risk"
    risk_pct: float = 1.0                # with sizing="risk": % of equity lost if the stop is hit
    use_regime: bool = True              # no new entries while Nifty is below its 200-DMA
    horizon: str = "swing"               # intraday | swing | longterm (for grouping in the UI)
    evidence: str = ""                   # STRONG | MODERATE | WEAK | EXPERIMENTAL - strength of published evidence
    universe: str = "stocks"             # stocks | etfs
    benchmark: str = ""                  # matching real NSE index (survivorship-free comparison)
    kind: str = field(default="event", init=False)


@dataclass
class RankStrategy:
    key: str
    name: str
    description: str
    score: Frame                         # higher = better
    eligible: Frame | None = None        # bool filter applied before ranking
    top_n: int = 20
    keep_rank: int | None = 40           # existing holdings are kept while ranked within this
    rebalance: str = "monthly"           # weekly | biweekly | monthly | quarterly | semiannual
    use_regime: bool = True
    regime_action: str = "hold"          # Nifty below 200-DMA: "hold" (no new buys) or "cash" (sell all)
    stop_pct: float | None = None        # optional per-position stop between rebalances
    rebalance_offset: int = 0            # rebalance this many trading days before the period end
    horizon: str = "longterm"
    evidence: str = ""
    universe: str = "stocks"             # stocks | etfs
    benchmark: str = ""                  # matching real NSE index (survivorship-free comparison)
    kind: str = field(default="rank", init=False)

    @property
    def max_positions(self) -> int:
        return self.top_n


@dataclass
class Trade:
    symbol: str
    entry_date: pd.Timestamp
    entry_price: float
    exit_date: pd.Timestamp
    exit_price: float
    qty: int
    pnl: float           # rupees, after all charges
    ret_pct: float       # % return on money invested, after all charges
    days: int
    reason: str


@dataclass
class SimResult:
    strategy_key: str
    equity: pd.Series
    invested: pd.Series                  # fraction of equity in stocks each day
    trades: list[Trade]
    open_positions: list[dict]           # model portfolio at the last date
    next_orders: list[dict]              # orders that would be placed at the next open
    start_index: int
    cash_income: dict[int, float] = field(default_factory=dict)   # financial year -> rupees earned on idle cash


def rebalance_days(dates: pd.DatetimeIndex, how: str, offset: int = 0,
                   next_session: pd.Timestamp | None = None) -> np.ndarray:
    """True on the last trading day of each period (decide at close, trade next open), or `offset`
    trading days before it. Results swing a lot with the rebalance day ("timing luck"), so the
    dashboard reports a range over several offsets. The final row is a rebalance day only when
    `next_session` (the trading day after it, known in a live run) starts a new period."""
    base = _period_ends(dates, how, next_session)
    if offset <= 0:
        return base
    out = np.zeros(len(dates), dtype=bool)
    idx = np.flatnonzero(base) - offset
    out[idx[idx >= 0]] = True
    return out


def _period_keys(dates: pd.DatetimeIndex, how: str) -> np.ndarray:
    """One number per row that changes when a new rebalance period starts. Weeks are ISO weeks of the ISO
    year (29-31 Dec can belong to week 1 of the next year)."""
    if how in ("weekly", "biweekly"):
        iso = dates.isocalendar()
        week = iso["week"].to_numpy(dtype=np.int64)
        return iso["year"].to_numpy(dtype=np.int64) * 100 + (week if how == "weekly" else week // 2)
    year = dates.year.to_numpy().astype(np.int64) * 100
    if how == "quarterly":
        return (dates.month.to_numpy() - 1) // 3 + year
    if how == "semiannual":
        return (dates.month.to_numpy() - 1) // 6 + year
    return dates.month.to_numpy() + year


def _period_ends(dates: pd.DatetimeIndex, how: str, next_session: pd.Timestamp | None = None) -> np.ndarray:
    key = _period_keys(dates, how)
    out = np.zeros(len(dates), dtype=bool)
    out[:-1] = key[:-1] != key[1:]
    if next_session is not None and len(dates):
        out[-1] = _period_keys(pd.DatetimeIndex([pd.Timestamp(next_session)]), how)[0] != key[-1]
    return out


STALE_EXIT_DAYS = 20   # a holding with no trade for this many days is sold at its last price


def simulate(strategy: EventStrategy | RankStrategy, f: Factors, costs: CostModel,
             tradable: pd.DataFrame, capital: float = 1_000_000.0, warmup: int = TRADING_DAYS,
             min_position: float = 0.0, cash_rate: pd.Series | None = None,
             next_session: pd.Timestamp | None = None) -> SimResult:
    """Run the strategy over the whole panel. `min_position` skips buys smaller than that many
    rupees (fixed charges make tiny positions expensive). `cash_rate` is a cash-return index (e.g. the
    Nifty 1D Rate): idle cash grows with it less `costs.cash_fee_pct` a year, as it would parked in a
    liquid fund (the income is kept per financial year in `cash_income` for the after-tax curve).
    `next_session`: the trading day after the last row (live run only), so a rank strategy whose
    review day is today decides its orders at today's close - it changes next_orders, never the past.

    Orders fill only on real bars: never on a gap-filled day (no trade printed), never a buy at an
    upper-circuit lock or a sell at a lower-circuit lock (one price all day on real volume: the order
    would sit unfilled in the queue). A sell or stop then waits for the next tradable day.

    A holding that stops trading (delisted, merged away, long suspension) keeps its last price; once
    it has not traded for STALE_EXIT_DAYS days it is sold at that price so its money is freed. This
    only matters on the point-in-time universe, which includes companies that later disappeared."""
    p = f.p
    idx, symbols = p.dates, p.symbols
    dates = list(idx)   # plain list: fast element access inside the loop
    O, H, L, C = (x.to_numpy(dtype=float) for x in (p.open, p.high, p.low, p.close))
    C_ffill = p.close.ffill().to_numpy(dtype=float)
    T, N = C.shape
    obs = p.observed.reindex(index=idx, columns=symbols).fillna(False).to_numpy(dtype=bool)
    seen = np.where(obs, np.arange(T)[:, None], -1)
    last_seen = np.maximum.accumulate(seen, axis=0)   # row of each stock's latest real trade
    V = p.volume.to_numpy(dtype=float)
    prev_c = np.vstack([np.full((1, N), np.nan), C[:-1]])
    locked = (H == L) & (V > 0) & obs                 # one price all day on real volume: locked at a band
    up_lock = locked & (C > prev_c)
    dn_lock = locked & (C < prev_c)
    trad = tradable.reindex(index=idx, columns=symbols).fillna(False).to_numpy(dtype=bool)
    is_etf = np.array([s in f.etfs for s in symbols], dtype=bool)
    trad = trad & (is_etf[None, :] if strategy.universe == "etfs" else ~is_etf[None, :])
    regime = f.regime_up.reindex(idx).fillna(True).to_numpy(dtype=bool)
    atr = f.atr14.to_numpy(dtype=float)
    # Slippage per stock and day: thinly traded stocks cost more to get in and out of.
    liquid = (f.turnover_avg20_cr.shift(1) >= costs.illiquid_below_cr).to_numpy(dtype=bool)
    slip_arr = np.where(liquid, costs.slippage_pct, costs.slippage_illiquid_pct) / 100
    t0 = min(warmup, T - 1)

    is_event = strategy.kind == "event"
    if is_event:
        entries = strategy.entries(f).reindex(index=idx, columns=symbols).fillna(False).to_numpy(dtype=bool) & trad
        exit_sig = (strategy.exit_signal(f).reindex(index=idx, columns=symbols).fillna(False).to_numpy(dtype=bool)
                    if strategy.exit_signal else None)
        prio_src = strategy.priority(f) if strategy.priority else None
    else:
        score = strategy.score(f).reindex(index=idx, columns=symbols)
        elig = (strategy.eligible(f).reindex(index=idx, columns=symbols).fillna(False).to_numpy(dtype=bool)
                if strategy.eligible else np.ones((T, N), dtype=bool))
        score_np = np.where(elig & trad, score.to_numpy(dtype=float), np.nan)
        rebal = rebalance_days(idx, strategy.rebalance, strategy.rebalance_offset, next_session)
        prio_src = None
    prio = (prio_src.reindex(index=idx, columns=symbols).to_numpy(dtype=float)
            if prio_src is not None else np.zeros((T, N)))
    prio = np.nan_to_num(prio, nan=-np.inf)

    cash = capital
    cash_growth = (cash_rate.reindex(idx).ffill().pct_change().fillna(0.0).clip(-0.01, 0.01).to_numpy()
                   if cash_rate is not None else np.zeros(len(idx)))
    # the fund's yearly fee, accrued over the calendar days since the previous row (weekends and holidays too)
    cash_fee = idx.to_series().diff().dt.days.fillna(0).to_numpy(dtype=float) / 365.25 * costs.cash_fee_pct / 100
    cash_income: dict[int, float] = {}
    pos: dict[int, dict] = {}            # col -> position
    pending_sell: dict[int, str] = {}    # col -> reason
    pending_buy: list[int] = []
    trades: list[Trade] = []
    equity = np.full(T, np.nan)
    invested = np.full(T, np.nan)

    def mark(t: int, use_open: bool = False) -> float:
        val = 0.0
        for c, ps in pos.items():
            px = O[t, c] if use_open and not math.isnan(O[t, c]) else C_ffill[t, c]
            val += ps["qty"] * (px if not math.isnan(px) else ps["entry"])
        return val

    def close_position(t: int, c: int, raw_px: float, reason: str) -> None:
        nonlocal cash
        ps = pos.pop(c)
        fill = raw_px * (1 - slip_arr[t, c])
        value = ps["qty"] * fill
        proceeds = value - costs.sell_cost(value)
        cash += proceeds
        pnl = proceeds - ps["cost"]
        trades.append(Trade(symbols[c], dates[ps["t"]], ps["entry"], dates[t], fill, ps["qty"], pnl,
                            pnl / ps["cost"] * 100, t - ps["t"], reason))

    for t in range(t0, T):
        if cash > 0 and t > t0 and cash_rate is not None:
            earned = cash * (cash_growth[t] - cash_fee[t])
            cash += earned
            fy = dates[t].year if dates[t].month >= 4 else dates[t].year - 1
            cash_income[fy] = cash_income.get(fy, 0.0) + earned
        # 0) Holdings that stopped trading: sold at their last traded price.
        for c in [c for c in pos if t - last_seen[t, c] >= STALE_EXIT_DAYS and not math.isnan(C_ffill[t, c])]:
            close_position(t, c, C_ffill[t, c], "stopped trading")
            pending_sell.pop(c, None)

        # 1) Orders at today's open: sells first to free cash, then buys (only on real, unlocked bars;
        #    an unfilled sell waits for the next day).
        for c, reason in list(pending_sell.items()):
            if c in pos and obs[t, c] and not math.isnan(O[t, c]) and not dn_lock[t, c]:
                close_position(t, c, O[t, c], reason)
                del pending_sell[c]
            elif c not in pos:
                del pending_sell[c]
        if pending_buy:
            eq_open = cash + mark(t, use_open=True)
            slots = strategy.max_positions - len(pos)
            for c in pending_buy:
                if slots <= 0:
                    break
                px = O[t, c]
                if c in pos or not obs[t, c] or math.isnan(px) or px <= 0 or up_lock[t, c]:
                    continue
                fill = px * (1 + slip_arr[t, c])
                stop = None
                if strategy.stop_pct:
                    stop = fill * (1 - strategy.stop_pct / 100)
                if is_event and strategy.stop_atr and not math.isnan(atr[t - 1, c]):
                    atr_stop = fill - strategy.stop_atr * atr[t - 1, c]
                    stop = max(stop, atr_stop) if stop is not None else atr_stop
                alloc = eq_open / strategy.max_positions
                if is_event and strategy.sizing == "risk" and stop is not None and fill > stop:
                    alloc = min(eq_open * strategy.risk_pct / 100 / (fill - stop) * fill, 2 * alloc)
                alloc = min(alloc, cash / (1 + 0.003))  # leave room for charges
                qty = int(alloc // fill)
                if qty < 1 or qty * fill < min_position:
                    continue
                value = qty * fill
                cost = value + costs.buy_cost(value)
                if cost > cash:
                    continue
                cash -= cost
                target = fill * (1 + strategy.target_pct / 100) if is_event and strategy.target_pct else None
                pos[c] = {"qty": qty, "entry": fill, "t": t, "stop": stop, "target": target,
                          "peak": fill, "cost": cost}
                slots -= 1
            pending_buy = []

        # 2) Intraday stop / target (not on a gap-filled day or at a lower-circuit lock: the next tradable
        #    day's open, or the stop if it trades above it, is the fill).
        for c in list(pos):
            ps = pos[c]
            if math.isnan(L[t, c]) or not obs[t, c] or dn_lock[t, c]:
                continue
            if ps["stop"] is not None and L[t, c] <= ps["stop"]:
                close_position(t, c, min(O[t, c], ps["stop"]) if not math.isnan(O[t, c]) else ps["stop"], "stop-loss")
            elif ps["target"] is not None and H[t, c] >= ps["target"]:
                close_position(t, c, max(O[t, c], ps["target"]) if not math.isnan(O[t, c]) else ps["target"], "target")

        # 3) At the close: trailing stops, exit signals, time limits.
        for c, ps in pos.items():
            if not math.isnan(C[t, c]):
                ps["peak"] = max(ps["peak"], C[t, c])
            if is_event and strategy.trail_pct:
                trail = ps["peak"] * (1 - strategy.trail_pct / 100)
                ps["stop"] = max(ps["stop"], trail) if ps["stop"] is not None else trail
            if is_event:
                if exit_sig is not None and exit_sig[t, c]:
                    pending_sell.setdefault(c, "exit signal")
                elif strategy.max_hold and t - ps["t"] >= strategy.max_hold:
                    pending_sell.setdefault(c, "time limit")

        # 4) New decisions for tomorrow's open.
        if is_event:
            if regime[t] or not strategy.use_regime:
                free = strategy.max_positions - len(pos) + len(pending_sell)
                if free > 0:
                    cand = np.flatnonzero(entries[t])
                    cand = [c for c in cand if c not in pos]
                    cand.sort(key=lambda c: -prio[t, c])
                    pending_buy = cand[:free]
        elif rebal[t] or (t == t0):
            go_cash = strategy.use_regime and not regime[t] and strategy.regime_action == "cash"
            no_buys = strategy.use_regime and not regime[t]
            row = score_np[t]
            valid = np.flatnonzero(~np.isnan(row))
            order = valid[np.argsort(-row[valid], kind="stable")]
            rank = {c: i + 1 for i, c in enumerate(order)}
            keep_lim = strategy.keep_rank or strategy.top_n
            for c in pos:
                if go_cash:
                    pending_sell.setdefault(c, "market regime")
                elif rank.get(c, 10 ** 9) > keep_lim:
                    pending_sell.setdefault(c, "dropped from ranking")
            if not no_buys:
                staying = len(pos) - len(pending_sell)
                need = strategy.top_n - staying
                pending_buy = [c for c in order if c not in pos][:max(need, 0)]

        pv = mark(t)
        equity[t] = cash + pv
        invested[t] = pv / equity[t] if equity[t] > 0 else 0.0

    last = T - 1
    open_positions = [{
        "symbol": symbols[c], "entry_date": dates[ps["t"]].date().isoformat(), "entry_price": round(ps["entry"], 2),
        "qty": ps["qty"], "last_price": round(C_ffill[last, c], 2),
        "ret_pct": round((C_ffill[last, c] / ps["entry"] - 1) * 100, 2),
        "stop": round(ps["stop"], 2) if ps["stop"] is not None else None,
        "days": last - ps["t"],
    } for c, ps in pos.items()]
    next_orders = ([{"action": "SELL", "symbol": symbols[c], "reason": r} for c, r in pending_sell.items()] +
                   [{"action": "BUY", "symbol": symbols[c], "reason": "entry signal" if is_event else "enters top ranks"}
                    for c in pending_buy])
    return SimResult(strategy.key, pd.Series(equity[t0:], index=idx[t0:]),
                     pd.Series(invested[t0:], index=idx[t0:]), trades, open_positions, next_orders, t0, cash_income)


# ------------------------------------------------------------------------------------- metrics
def _curve_stats(eq: pd.Series, rf: pd.Series | None = None) -> dict:
    """Return, CAGR (over calendar years: NSE has ~248 sessions a year, not 252), max drawdown, volatility and
    Sharpe ratio. `rf`: daily cash returns - the Sharpe ratio is then of the return over cash. A curve with
    almost no volatility (a window spent in cash) has no meaningful Sharpe ratio: None."""
    eq = eq.dropna()
    if len(eq) < 2 or eq.iloc[0] <= 0:
        return {"return_pct": None, "cagr_pct": None, "max_dd_pct": None, "sharpe": None, "vol_pct": None}
    years = (eq.index[-1] - eq.index[0]).days / 365.25
    total = eq.iloc[-1] / eq.iloc[0] - 1
    daily = eq.pct_change().dropna()
    sd = daily.std()
    vol = sd * np.sqrt(TRADING_DAYS)
    excess = daily - rf.reindex(daily.index).fillna(0.0) if rf is not None else daily
    return {
        "return_pct": total * 100,
        "cagr_pct": ((1 + total) ** (1 / years) - 1) * 100 if years >= 0.45 and total > -1 else None,
        "max_dd_pct": float((eq / eq.cummax() - 1).min() * 100),
        "sharpe": float(excess.mean() / sd * np.sqrt(TRADING_DAYS)) if sd > 0 and vol >= 0.01 else None,
        "vol_pct": float(vol * 100),
    }


def _trade_stats(trades: list[Trade]) -> dict:
    if not trades:
        return {"trades": 0, "win_rate": None, "avg_win_pct": None, "avg_loss_pct": None,
                "expectancy_pct": None, "profit_factor": None, "avg_days": None}
    r = np.array([t.ret_pct for t in trades])
    pnl = np.array([t.pnl for t in trades])
    wins, losses = r[r > 0], r[r <= 0]
    gross_loss = -pnl[pnl <= 0].sum()
    return {
        "trades": len(trades),
        "win_rate": float((r > 0).mean() * 100),
        "avg_win_pct": float(wins.mean()) if len(wins) else None,
        "avg_loss_pct": float(losses.mean()) if len(losses) else None,
        "expectancy_pct": float(r.mean()),
        "profit_factor": float(pnl[pnl > 0].sum() / gross_loss) if gross_loss > 0 else None,
        "avg_days": float(np.mean([t.days for t in trades])),
    }


def after_tax_equity(res: SimResult, tax: TaxModel, stt_pct: float = 0.0) -> pd.Series:
    """Equity curve after paying capital-gains tax on each financial year's realised gains
    (paid on the first trading day of the next April; the current year's accrued tax is deducted at
    the last date). Short-term losses offset short- and long-term gains, long-term losses only
    long-term gains, and unused losses carry forward. Paying tax shrinks the portfolio, so later
    gains - and taxes - are scaled down with it.

    Like the buy-and-hold benchmarks, positions still open at the last date are taxed as if sold then.
    STT (`stt_pct` of each side's value) is not deductible from the gain (s.48), so it is added back to
    each trade's P&L for the tax base. Income on idle cash (res.cash_income) is taxed at the slab rate."""
    eq = res.equity.dropna()
    if eq.empty:
        return eq
    by_fy: dict[int, list[float]] = {}
    for t in res.trades:
        fy = t.exit_date.year if t.exit_date.month >= 4 else t.exit_date.year - 1
        is_long = (t.exit_date - t.entry_date).days > 365
        gain = t.pnl + t.qty * (t.entry_price + t.exit_price) * stt_pct / 100
        by_fy.setdefault(fy, [0.0, 0.0])[1 if is_long else 0] += gain
    last = eq.index[-1]
    fy_last = last.year if last.month >= 4 else last.year - 1
    for ps in res.open_positions:
        gain = ps["qty"] * (ps["last_price"] - ps["entry_price"])
        if math.isfinite(gain):
            is_long = (last - pd.Timestamp(ps["entry_date"])).days > 365
            by_fy.setdefault(fy_last, [0.0, 0.0])[1 if is_long else 0] += gain
    factor = pd.Series(1.0, index=eq.index)
    scale, st_pool, lt_pool = 1.0, 0.0, 0.0
    for fy in sorted(set(by_fy) | set(res.cash_income)):
        st, lt = (g * scale for g in by_fy.get(fy, (0.0, 0.0)))
        if st < 0:
            st_pool, st = st_pool - st, 0.0
        if lt < 0:
            lt_pool, lt = lt_pool - lt, 0.0
        used = min(st, st_pool); st -= used; st_pool -= used
        used = min(lt, lt_pool); lt -= used; lt_pool -= used
        used = min(lt, st_pool); lt -= used; st_pool -= used
        due = st * tax.stcg_pct / 100 + max(0.0, lt - tax.ltcg_exempt) * tax.ltcg_pct / 100
        due += max(0.0, res.cash_income.get(fy, 0.0) * scale) * tax.interest_pct / 100
        if due <= 0:
            continue
        later = eq.index[eq.index >= pd.Timestamp(fy + 1, 4, 1)]
        pay = later[0] if len(later) else eq.index[-1]
        value = float(eq.loc[pay]) * scale
        scale *= max(0.0, 1 - due / value)
        factor.loc[pay:] = scale
    return eq * factor


def evaluate(res: SimResult, benchmark: pd.Series, ew_benchmark: pd.Series | None = None,
             windows: dict[str, int] | None = None, tax: TaxModel | None = None,
             n500_benchmark: pd.Series | None = None, factor_benchmark: pd.Series | None = None,
             cash_rate: pd.Series | None = None, stt_pct: float = 0.0) -> dict:
    """Metrics for the full period and for recent windows (by trading days). `cash_rate`: the cash-return
    index the simulation used - Sharpe ratios are then of the return over cash. `stt_pct`: see after_tax_equity.
    A benchmark whose data starts later than the strategy is measured from its own start ('start', 'days'),
    with the strategy's CAGR over that same period ('strategy_cagr_same_period_pct')."""
    windows = windows or {"12m": 252, "6m": 126, "3m": 63}
    eq = res.equity.dropna()
    rf = (cash_rate.reindex(eq.index).ffill().pct_change().fillna(0.0).clip(-0.01, 0.01)
          if cash_rate is not None else None)   # the same daily cash return as engine.simulate
    out = {"full": {**_curve_stats(eq, rf), **_trade_stats(res.trades),
                    "exposure_pct": float(res.invested.mean() * 100),
                    "start": eq.index[0].date().isoformat(), "end": eq.index[-1].date().isoformat()}}

    def bench(series: pd.Series | None, idx) -> dict:
        if series is None:
            return {}
        b = series.reindex(idx).ffill().dropna()
        if len(b) <= 1:
            return {}
        r = {**_curve_stats(b, rf), "start": b.index[0].date().isoformat(), "days": len(b)}
        if b.index[0] > idx[0] + pd.Timedelta(days=7):   # e.g. an NSE index whose history starts later
            r["strategy_cagr_same_period_pct"] = _curve_stats(eq.loc[b.index[0]:], rf)["cagr_pct"]
        return r

    out["full"]["benchmark"] = bench(benchmark, eq.index)
    out["full"]["ew_benchmark"] = bench(ew_benchmark, eq.index)
    out["full"]["n500_benchmark"] = bench(n500_benchmark, eq.index)
    out["full"]["factor_benchmark"] = bench(factor_benchmark, eq.index)
    if tax is not None:
        at = _curve_stats(after_tax_equity(res, tax, stt_pct), rf)
        out["full"]["after_tax_cagr_pct"] = at["cagr_pct"]
        out["full"]["after_tax_return_pct"] = at["return_pct"]
        for key in ("benchmark", "ew_benchmark", "n500_benchmark", "factor_benchmark"):  # buy & hold: taxed at the end
            b = out["full"][key]
            if b.get("return_pct") is not None:
                years = (eq.index[-1] - pd.Timestamp(b.get("start") or eq.index[0])).days / 365.25   # its own span
                net = b["return_pct"] / 100 * (1 - tax.ltcg_pct / 100) if b["return_pct"] > 0 else b["return_pct"] / 100
                b["after_tax_cagr_pct"] = ((1 + net) ** (1 / years) - 1) * 100 if years >= 0.45 else None
    for name, n in windows.items():
        if len(eq) <= n:
            continue
        w = eq.iloc[-n - 1:]
        start = w.index[0]
        tw = [t for t in res.trades if t.exit_date > start]
        out[name] = {**_curve_stats(w, rf), **_trade_stats(tw),
                     "exposure_pct": float(res.invested.reindex(w.index).mean() * 100),
                     "benchmark": bench(benchmark, w.index), "ew_benchmark": bench(ew_benchmark, w.index),
                     "n500_benchmark": bench(n500_benchmark, w.index),
                     "factor_benchmark": bench(factor_benchmark, w.index)}
    return out


IDLE_EXPOSURE_PCT = 25.0   # invested less than this on average: a window's result is mostly the cash yield


def working_status(metrics: dict) -> tuple[str, str]:
    """Is the strategy working *now*? Compares the last 12 and 6 months with the Nifty 50 index and the
    average stock. A strategy that lost money over the whole backtest is never 'working'; one that was mostly
    in cash in a recent window (regime filter, no signals) is 'unknown': that result is the cash yield, not
    evidence about its rules."""
    full_cagr = (metrics.get("full") or {}).get("cagr_pct")
    if full_cagr is not None and full_cagr < 0:
        return "not-working", f"Lost money over the whole backtest after costs ({full_cagr:+.1f}%/yr)."
    checks, idle = [], []
    for w in ("12m", "6m"):
        m = metrics.get(w)
        if not m or m.get("return_pct") is None:
            continue
        if m.get("exposure_pct") is not None and m["exposure_pct"] < IDLE_EXPOSURE_PCT:
            idle.append(w)
            continue
        b = (m.get("benchmark") or {}).get("return_pct")
        ew = (m.get("ew_benchmark") or {}).get("return_pct")
        ref = max(x for x in (b, ew) if x is not None) if (b is not None or ew is not None) else 0
        checks.append(m["return_pct"] - ref)
    if idle:
        return "unknown", (f"Mostly in cash over the last {' and '.join(idle)} (regime filter or no signals): "
                           "recent results say nothing about the rules.")
    if not checks:
        return "unknown", "Not enough history yet."
    if all(c > 0 for c in checks):
        return "working", "Beat both the Nifty 50 and the average stock over the last 12 and 6 months."
    if any(c > 0 for c in checks):
        return "mixed", "Beat the market in one recent window but not the other."
    return "not-working", "Did worse than the Nifty 50 / the average stock over the last 12 and 6 months."


def equal_weight_index(f: Factors, tradable: pd.DataFrame) -> pd.Series:
    """Daily-rebalanced equal-weight average of all tradable stocks (the 'average stock')."""
    r = f.daily_ret.where(tradable.shift(1).fillna(False).astype(bool))
    return (1 + r.mean(axis=1).fillna(0)).cumprod()
