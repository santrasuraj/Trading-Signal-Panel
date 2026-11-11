"""One answer per stock (GET /api/action/{symbol}) and today's actions (GET /api/today): services/action_svc.py."""
from __future__ import annotations

from typing import Literal

from .common import AsOf, Horizon, Model, Side, StrategyStatus

ActionState = Literal["BUY", "SELL", "HOLD", "NO_EDGE"]


class ActionOrder(Model):
    strategy_key: str
    strategy_name: str
    status: StrategyStatus
    horizon: Horizon
    cagr_pct: float | None = None                 # the strategy's backtest, after costs (point-in-time if set up)
    after_tax_cagr_pct: float | None = None
    max_dd_pct: float | None = None
    trades: int | None = None
    timing_low_pct: float | None = None           # the same rules started on other days
    timing_high_pct: float | None = None
    live_level: Literal["good", "bad", "unknown"]
    live_verdict: str                             # the strategy's live signal record
    action: Side
    price: float | None = None                    # reference price (next open is the fill)
    qty: int | None = None
    amount: float | None = None
    stop: float | None = None
    stop_distance_pct: float | None = None
    risk_amount: float | None = None
    reason: str
    provisional: bool
    below_min_position: bool
    strength_score: int | None = None
    strength_grade: str | None = None
    late_days: int | None = None                  # a late-entry BUY: trading days since the model's own buy
    late_lag: int | None = None                   # ... and the tested delay that covers it (5 / 10 / 21)


class ActionHolding(Model):
    qty: float | None = None
    buy_price: float | None = None
    price: float | None = None
    pnl_pct: float | None = None
    pnl_amount: float | None = None
    stop_price: float | None = None
    target_price: float | None = None
    level: str | None = None
    alerts: list[str]


class ActionRisk(Model):
    kind: Literal["results", "ban", "regime", "provisional"]
    text: str


class ActionCard(Model):
    symbol: str
    company: str | None = None
    industry: str | None = None
    state: ActionState
    headline: str
    provisional: bool
    primary: ActionOrder | None = None            # the order behind BUY / SELL (or the buy alongside a HOLD)
    others: list[ActionOrder]                     # other working strategies saying the same
    unproven: list[ActionOrder]                   # buys of mixed / too-new strategies: never the answer
    exits: list[ActionOrder]                      # working strategies' exits not behind the answer
    holding: ActionHolding | None = None
    near: list[str]                               # how close each working strategy is to acting
    risks: list[ActionRisk]                       # facts that never change the answer
    as_of: AsOf
    note: str


class ActionHistory(Model):
    sessions: int                                 # journalled sessions looked at (at most 30)
    with_actions: int                             # of them, sessions with at least one tested order


class TodayCounts(Model):
    buy: int
    sell: int
    hold: int


class TodayResponse(Model):
    as_of: AsOf
    actions: list[ActionCard]                     # every BUY and SELL, exits first
    holds: list[ActionCard]
    counts: TodayCounts
    unproven_strategies: list[str]
    history: ActionHistory
    empty_note: str | None = None
    note: str


__all__ = ["ActionState", "ActionOrder", "ActionHolding", "ActionRisk", "ActionCard", "ActionHistory", "TodayCounts",
           "TodayResponse"]
