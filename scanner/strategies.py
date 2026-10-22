"""Strategy library. Parameters can be overridden per strategy under `strategies:` in config.yaml.

Each strategy is backed by published evidence (see README "Strategies"); every one is re-tested on
recent data after each scan so the dashboard shows which are working *now*.
"""
from __future__ import annotations

import pandas as pd

from .engine import EventStrategy, RankStrategy
from .panel import Factors


def tradable_mask(f: Factors, min_price: float, min_turnover_cr: float) -> pd.DataFrame:
    """Stocks liquid enough to trade: price and average daily traded value filters."""
    return (f.p.close >= min_price) & (f.turnover_avg20_cr >= min_turnover_cr) & f.p.close.notna()


def _uptrend(f: Factors) -> pd.DataFrame:
    return (f.p.close > f.sma200) & (f.sma50 > f.sma200)


def _trend_template(f: Factors, rs_min: float) -> pd.DataFrame:
    """Minervini-style stage-2 uptrend."""
    c = f.p.close
    return ((c > f.sma50) & (f.sma50 > f.sma150) & (f.sma150 > f.sma200) & f.sma200_rising
            & (f.pct_above_52w_low >= 30) & (f.pct_from_52w_high >= -25) & (f.rs_rating >= rs_min))


def build_strategies(cfg: dict) -> list:
    conf = cfg.get("strategies") or {}

    def opt(key: str, name: str, default):
        return (conf.get(key) or {}).get(name, default)

    def enabled(key: str, default: bool = True) -> bool:
        return bool((conf.get(key) or {}).get("enabled", default))

    out: list = []

    # 1. Cross-sectional momentum (NSE Momentum index methodology)
    k = "momentum"
    if enabled(k):
        need_trend = opt(k, "require_uptrend", True)
        out.append(RankStrategy(
            key=k, name="Momentum leaders",
            description=("Holds the strongest stocks by risk-adjusted 6- and 12-month return (the method behind "
                         "NSE's Nifty200 Momentum 30 index). Rebalanced monthly; a holding is kept while it stays "
                         "in the top ranks. Momentum is the most consistently documented stock-selection effect."),
            score=lambda f: f.momentum,
            eligible=(lambda f: f.p.close > f.sma200) if need_trend else None,
            top_n=int(opt(k, "top_n", 15)), keep_rank=int(opt(k, "keep_rank", 30)),
            rebalance=opt(k, "rebalance", "monthly"), use_regime=opt(k, "use_regime", True),
            regime_action=opt(k, "regime_action", "hold"), stop_pct=opt(k, "stop_pct", None),
        ))

    # 2. Near the 52-week high (George & Hwang)
    k = "near_high"
    if enabled(k):
        out.append(RankStrategy(
            key=k, name="Near 52-week high",
            description=("Holds uptrending stocks trading closest to their 52-week high. Stocks near their highs "
                         "tend to keep outperforming because investors under-react to good news."),
            score=lambda f: f.pct_from_52w_high,
            eligible=_uptrend,
            top_n=int(opt(k, "top_n", 15)), keep_rank=int(opt(k, "keep_rank", 30)),
            rebalance=opt(k, "rebalance", "monthly"), use_regime=opt(k, "use_regime", True),
            regime_action=opt(k, "regime_action", "hold"), stop_pct=opt(k, "stop_pct", None),
        ))

    # 3. Trend template + breakout (stage-2 breakouts)
    k = "trend_breakout"
    if enabled(k):
        rs_min = float(opt(k, "rs_min", 70))
        vol_min = float(opt(k, "min_vol_ratio", 1.5))
        out.append(EventStrategy(
            key=k, name="Trend-template breakout",
            description=("Buys a stock in a strong uptrend (price above rising 50/150/200-day averages, near its "
                         "high, top relative strength) when it breaks above its 20-day high on heavy volume. "
                         "Exits on stop-loss, trailing stop, or a close below the 50-day average."),
            entries=lambda f: _trend_template(f, rs_min) & (f.p.close > f.high_20_prev) & (f.vol_ratio >= vol_min),
            priority=lambda f: f.rs_rating,
            exit_signal=lambda f: f.p.close < f.sma50,
            stop_pct=float(opt(k, "stop_pct", 8)), trail_pct=opt(k, "trail_pct", 15),
            max_positions=int(opt(k, "max_positions", 10)),
            sizing=opt(k, "sizing", "equal"), risk_pct=float(opt(k, "risk_pct", 1.0)),
            use_regime=opt(k, "use_regime", True),
        ))

    # 4. RSI(2) pullback in uptrend (short-term mean reversion)
    k = "rsi2_pullback"
    if enabled(k):
        level = float(opt(k, "rsi2_below", 10))
        out.append(EventStrategy(
            key=k, name="RSI-2 pullback",
            description=("Buys a sharp 1-3 day dip in a stock that is in a long-term uptrend (above its 200-day "
                         "average), and sells on the bounce: close above the 5-day average, or after 10 days."),
            entries=lambda f: (f.p.close > f.sma200) & (f.rsi2 < level),
            priority=lambda f: -f.rsi2,
            exit_signal=lambda f: f.p.close > f.sma5,
            stop_pct=float(opt(k, "stop_pct", 10)), max_hold=int(opt(k, "max_hold", 10)),
            max_positions=int(opt(k, "max_positions", 10)),
            use_regime=opt(k, "use_regime", True),
        ))

    # 5. Old v1 rules, kept only as a comparison baseline
    k = "legacy_rules"
    if enabled(k, default=True):
        out.append(EventStrategy(
            key=k, name="Old textbook rules (baseline)",
            description=("The v1 rules (50-DMA volume breakout, 52-week-high breakout) with 5% stop / 10% target / "
                         "15 days. Kept only so you can see how much better the evidence-based strategies do."),
            entries=lambda f: (((f.p.close > f.sma50) & (f.p.close.shift(1) <= f.sma50.shift(1))
                                & (f.vol_ratio >= 2) & (f.p.close > f.sma200))
                               | ((f.p.close > f.high_52w_prev) & (f.vol_ratio >= 1.5))),
            priority=lambda f: f.vol_ratio,
            stop_pct=5, target_pct=10, max_hold=15, max_positions=10, use_regime=False,
        ))
    return out
