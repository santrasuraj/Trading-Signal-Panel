"""Strategy library: well-known, real-world strategies for every horizon.

Every strategy is backtested after each scan on ~8 years of NSE data with full Indian costs, so the
platform shows which ones actually work - including the famous ones that don't. Parameters can be
overridden per strategy under `strategies:` in config.yaml (`enabled: false` hides one).

Evidence grades (see README):
  STRONG       - decades of academic + out-of-sample evidence, incl. India (momentum, low volatility)
  MODERATE     - solid evidence in other markets / practitioner track record, mixed in India
  WEAK         - popular, but evidence is thin or results depend on the period
  EXPERIMENTAL - our own tests are inconclusive; shown for comparison
Intraday strategies live in scanner/intraday/ (they need 5-minute bars).
"""
from __future__ import annotations

import pandas as pd

from .engine import EventStrategy, RankStrategy
from .panel import Factors


def tradable_mask(f: Factors, min_price: float, min_turnover_cr: float) -> pd.DataFrame:
    """Instruments liquid enough to trade: price and average daily traded value filters."""
    return (f.p.close >= min_price) & (f.turnover_avg20_cr >= min_turnover_cr) & f.p.close.notna()


def _uptrend(f: Factors) -> pd.DataFrame:
    return (f.p.close > f.sma200) & (f.sma50 > f.sma200)


def _stage2(f: Factors) -> pd.DataFrame:
    """Price above rising 50/200-day averages (a 'stage 2' uptrend)."""
    return (f.p.close > f.sma50) & (f.sma50 > f.sma200) & f.sma200_rising


def _trend_template(f: Factors, rs_min: float) -> pd.DataFrame:
    """Minervini-style trend template."""
    c = f.p.close
    return ((c > f.sma50) & (f.sma50 > f.sma150) & (f.sma150 > f.sma200) & f.sma200_rising
            & (f.pct_above_52w_low >= 30) & (f.pct_from_52w_high >= -25) & (f.rs_rating >= rs_min))


def _only(f: Factors, names) -> pd.DataFrame:
    """True in the columns of the given instruments (e.g. a list of ETFs), on every date."""
    names = set(names)
    row = [c in names for c in f.p.close.columns]
    return pd.DataFrame([row] * len(f.p.dates), index=f.p.dates, columns=f.p.close.columns)


def build_strategies(cfg: dict) -> list:
    conf = cfg.get("strategies") or {}

    def opt(key: str, name: str, default):
        return (conf.get(key) or {}).get(name, default)

    def enabled(key: str, default: bool = True) -> bool:
        return bool((conf.get(key) or {}).get("enabled", default))

    out: list = []

    # ============================================================== LONG-TERM (months to years)
    k = "momentum"
    if enabled(k):
        need_trend = opt(k, "require_uptrend", True)
        out.append(RankStrategy(
            key=k, name="Momentum leaders", horizon="longterm", evidence="STRONG", benchmark="Nifty200 Momentum 30",
            description=("Holds the 15 strongest stocks by risk-adjusted 6- and 12-month return (the method behind "
                         "NSE's Nifty200 Momentum 30 index), reviewed monthly; a holding is kept while it stays in "
                         "the top 30. Momentum is the most consistently documented stock-selection effect worldwide "
                         "and in India (IIM-A factor data: ~10%/yr long-short since 1994). Crashes hard in sharp "
                         "reversals (2008-09)."),
            score=lambda f: f.momentum,
            eligible=(lambda f: f.p.close > f.sma200) if need_trend else None,
            top_n=int(opt(k, "top_n", 15)), keep_rank=int(opt(k, "keep_rank", 30)),
            rebalance=opt(k, "rebalance", "monthly"), use_regime=opt(k, "use_regime", True),
            regime_action=opt(k, "regime_action", "hold"), stop_pct=opt(k, "stop_pct", None),
        ))

    k = "low_vol"
    if enabled(k):
        big = int(opt(k, "universe_size", 150))
        out.append(RankStrategy(
            key=k, name="Low volatility", horizon="longterm", evidence="STRONG",
            benchmark="Nifty100 Low Volatility 30",
            description=("Holds the 20 steadiest large, liquid stocks (lowest 1-year volatility), reviewed quarterly "
                         "- the method behind NSE's Nifty100 Low Vol 30 index (17.7% vs 13.7%/yr for Nifty 100, "
                         "2005-18, and much smaller crash losses). Defensive: lags in strong rallies."),
            score=lambda f: -f.vol_ann,
            eligible=lambda f: (f.turnover_avg20_cr.rank(axis=1, ascending=False) <= big) & f.vol_ann.notna(),
            top_n=int(opt(k, "top_n", 20)), keep_rank=int(opt(k, "keep_rank", 40)),
            rebalance=opt(k, "rebalance", "quarterly"), use_regime=opt(k, "use_regime", False),
        ))

    k = "sector_rotation"
    if enabled(k):
        top_ind = int(opt(k, "top_industries", 3))
        out.append(RankStrategy(
            key=k, name="Sector rotation", horizon="longterm", evidence="MODERATE", benchmark="Nifty Alpha 50",
            description=(f"Each month finds the {top_ind} strongest industries (average 6-month return of their "
                         "stocks) and holds the strongest stocks inside them. Industry momentum is documented "
                         "(Moskowitz & Grinblatt 1999) and partly explains stock momentum."),
            score=lambda f: f.rs_rating,
            eligible=lambda f: (f.industry_rank <= top_ind) & (f.p.close > f.sma200),
            top_n=int(opt(k, "top_n", 12)), keep_rank=int(opt(k, "keep_rank", 24)),
            rebalance=opt(k, "rebalance", "monthly"), use_regime=opt(k, "use_regime", True),
        ))

    k = "golden_cross"
    if enabled(k):
        out.append(EventStrategy(
            key=k, name="Golden cross trend", horizon="longterm", evidence="WEAK",
            description=("Buys when the 50-day average crosses above the 200-day average (a 'golden cross') in a "
                         "strong stock, and holds until the 'death cross' (50-day back below 200-day). Classic "
                         "long-term trend following; slow, many small losses, a few big winners."),
            entries=lambda f: f.golden_cross & (f.rs_rating >= float(opt(k, "rs_min", 60))),
            priority=lambda f: f.rs_rating,
            exit_signal=lambda f: f.sma50 < f.sma200,
            stop_pct=float(opt(k, "stop_pct", 15)), max_positions=int(opt(k, "max_positions", 15)),
            use_regime=opt(k, "use_regime", False),
        ))

    k = "index_trend"
    if enabled(k):
        etf = str(opt(k, "etf", "NIFTYBEES"))
        out.append(RankStrategy(
            key=k, name="Nifty trend timing (ETF)", horizon="longterm", evidence="MODERATE", benchmark="Nifty 50",
            description=(f"Holds the {etf} index ETF while Nifty is above its 200-day average and moves to cash "
                         "when it falls below (checked monthly). Faber's market-timing rule: similar long-run return "
                         "to buy-and-hold with much smaller crashes; whipsaws in sideways markets."),
            score=lambda f: f.p.close * 0 + 1,
            eligible=lambda f: _only(f, [etf]) & pd.DataFrame({c: f.regime_up for c in f.p.close.columns}),
            top_n=1, keep_rank=1, rebalance=opt(k, "rebalance", "monthly"), use_regime=False,
            universe="etfs",
        ))

    k = "dual_momentum"
    if enabled(k):
        assets = list(opt(k, "etfs", ["NIFTYBEES", "JUNIORBEES", "BANKBEES", "GOLDBEES", "MON100"]))
        hold = int(opt(k, "hold", 2))
        out.append(RankStrategy(
            key=k, name="Dual momentum (ETF rotation)", horizon="longterm", evidence="MODERATE", benchmark="Nifty 50",
            description=(f"Each month holds the {hold} ETFs with the best 12-month return among Nifty, Nifty Next 50, "
                         "Bank, Gold and Nasdaq-100 - but only if that return is positive, otherwise cash "
                         "(Antonacci's dual momentum: relative + absolute momentum across asset classes)."),
            score=lambda f: f.ret_12m,
            eligible=lambda f: (f.ret_12m > 0) & _only(f, assets),
            top_n=hold, keep_rank=hold, rebalance=opt(k, "rebalance", "monthly"), use_regime=False,
            universe="etfs",
        ))

    # ============================================================== SWING (days to weeks)
    k = "trend_breakout"
    if enabled(k):
        rs_min = float(opt(k, "rs_min", 90))
        vol_min = float(opt(k, "min_vol_ratio", 2.0))
        out.append(EventStrategy(
            key=k, name="Trend-template breakout", horizon="swing", evidence="EXPERIMENTAL",
            description=("Minervini SEPA-style: a stock in a strong uptrend (above rising 50/150/200-day averages, "
                         "near its high, relative strength in the top 10%) breaking its 20-day high on 2x volume. "
                         "8% stop, exit on a close below the 50-day average. Out of sample it only matched the "
                         "average stock."),
            entries=lambda f: _trend_template(f, rs_min) & (f.p.close > f.high_20_prev) & (f.vol_ratio >= vol_min),
            priority=lambda f: f.rs_rating, exit_signal=lambda f: f.p.close < f.sma50,
            stop_pct=float(opt(k, "stop_pct", 8)), trail_pct=opt(k, "trail_pct", None) or None,
            max_positions=int(opt(k, "max_positions", 10)), use_regime=opt(k, "use_regime", True),
        ))

    k = "vcp_breakout"
    if enabled(k):
        out.append(EventStrategy(
            key=k, name="Volatility contraction (VCP) breakout", horizon="swing", evidence="WEAK",
            description=("A leader near its 52-week high goes quiet - a tight 15-day box (under 12% high-to-low) "
                         "with shrinking volatility - then breaks out of the box on 1.5x volume (Minervini's VCP / "
                         "Darvas box). Stop 7%, exit on a close below the 50-day average."),
            entries=lambda f: (_trend_template(f, float(opt(k, "rs_min", 80)))
                               & (f.pct_from_52w_high >= -10) & (f.range_15_pct.shift(1) <= float(opt(k, "max_box_pct", 12)))
                               & (f.atr_contraction.shift(1) <= 0.85) & (f.p.close > f.high_15_prev)
                               & (f.vol_ratio >= float(opt(k, "min_vol_ratio", 1.5)))),
            priority=lambda f: f.rs_rating, exit_signal=lambda f: f.p.close < f.sma50,
            stop_pct=float(opt(k, "stop_pct", 7)), max_positions=int(opt(k, "max_positions", 10)),
            use_regime=opt(k, "use_regime", True),
        ))

    k = "donchian"
    if enabled(k):
        out.append(EventStrategy(
            key=k, name="Turtle / Donchian 55-day breakout", horizon="swing", evidence="MODERATE",
            description=("The Turtle Traders' System 2: buy a new 55-day high, exit on a new 20-day low, with a "
                         "2-ATR initial stop. Only stocks above their 200-day average. Trend following has strong "
                         "evidence in futures; on single stocks it is weaker and whipsaws in sideways markets."),
            entries=lambda f: (f.p.close > f.high_55_prev) & (f.p.close > f.sma200),
            priority=lambda f: f.rs_rating, exit_signal=lambda f: f.p.close < f.low_20_prev,
            stop_pct=None, stop_atr=float(opt(k, "stop_atr", 2.0)),
            max_positions=int(opt(k, "max_positions", 10)), use_regime=opt(k, "use_regime", True),
        ))

    k = "pullback_leaders"
    if enabled(k):
        out.append(EventStrategy(
            key=k, name="Pullback in leaders (21-EMA)", horizon="swing", evidence="WEAK",
            description=("Buys a relative-strength leader (RS 80+) in a stage-2 uptrend when it pulls back to its "
                         "21-day EMA and bounces (low touches the EMA, close above it). Exit: close below the "
                         "50-day average or after 20 days; 7% stop. 'Buy the dip in strong stocks'."),
            entries=lambda f: (_stage2(f) & (f.rs_rating >= float(opt(k, "rs_min", 80)))
                               & (f.p.low <= f.ema21) & (f.p.close > f.ema21) & (f.rsi14 < 65)),
            priority=lambda f: f.rs_rating, exit_signal=lambda f: f.p.close < f.sma50,
            stop_pct=float(opt(k, "stop_pct", 7)), max_hold=int(opt(k, "max_hold", 20)),
            max_positions=int(opt(k, "max_positions", 10)), use_regime=opt(k, "use_regime", True),
        ))

    k = "earnings_gap"
    if enabled(k):
        out.append(EventStrategy(
            key=k, name="Earnings gap-up (PEAD)", horizon="swing", evidence="MODERATE",
            description=("Post-earnings-announcement drift: after quarterly results, a stock that gaps up 4%+ on 3x "
                         "volume and holds the gap tends to keep rising for weeks (Ball & Brown 1968; mixed but "
                         "positive Indian evidence). Results dates from NSE's event calendar. 8% stop, 40-day "
                         "holding limit, exit on a close below the 50-day average."),
            entries=lambda f: (f.results_window & (f.gap_pct >= float(opt(k, "min_gap_pct", 4)))
                               & (f.p.close >= f.p.open) & (f.vol_ratio >= float(opt(k, "min_vol_ratio", 3)))
                               & (f.p.close > f.sma200)),
            priority=lambda f: f.gap_pct, exit_signal=lambda f: f.p.close < f.sma50,
            stop_pct=float(opt(k, "stop_pct", 8)), max_hold=int(opt(k, "max_hold", 40)),
            max_positions=int(opt(k, "max_positions", 10)), use_regime=opt(k, "use_regime", False),
        ))

    k = "bb_squeeze"
    if enabled(k):
        out.append(EventStrategy(
            key=k, name="Bollinger squeeze breakout", horizon="swing", evidence="WEAK",
            description=("When Bollinger Bands are at their narrowest in 6 months (a volatility squeeze) and price "
                         "closes above the upper band in an uptrend, volatility tends to expand in that direction. "
                         "Exit on a close below the 20-day average; 8% stop."),
            entries=lambda f: f.bb_squeeze.shift(1).fillna(False).astype(bool) & (f.p.close > f.bb_upper) & _uptrend(f),
            priority=lambda f: f.rs_rating, exit_signal=lambda f: f.p.close < f.sma20,
            stop_pct=float(opt(k, "stop_pct", 8)), max_positions=int(opt(k, "max_positions", 10)),
            use_regime=opt(k, "use_regime", True),
        ))

    k = "nr7_breakout"
    if enabled(k):
        out.append(EventStrategy(
            key=k, name="NR7 breakout", horizon="swing", evidence="WEAK",
            description=("Toby Crabel's narrow-range pattern: after the quietest day in 7 sessions, a close above "
                         "that day's high in an uptrending leader. Short holding (exit below the 10-day average or "
                         "after 7 days), 5% stop."),
            entries=lambda f: (f.nr7.shift(1).fillna(False).astype(bool) & (f.p.close > f.p.high.shift(1))
                               & _uptrend(f) & (f.rs_rating >= 70)),
            priority=lambda f: f.rs_rating, exit_signal=lambda f: f.p.close < f.sma10,
            stop_pct=float(opt(k, "stop_pct", 5)), max_hold=int(opt(k, "max_hold", 7)),
            max_positions=int(opt(k, "max_positions", 10)), use_regime=opt(k, "use_regime", True),
        ))

    k = "rsi2_pullback"
    if enabled(k, default=False):
        level = float(opt(k, "rsi2_below", 10))
        out.append(EventStrategy(
            key=k, name="RSI-2 pullback (Connors)", horizon="swing", evidence="WEAK",
            description=("Larry Connors' short-term mean reversion: buy a 1-3 day plunge (RSI-2 under 10) in a "
                         "stock above its 200-day average, sell on the bounce. Works in US large caps; here it lost "
                         "money after realistic costs (reversal mostly works in illiquid stocks)."),
            entries=lambda f: (f.p.close > f.sma200) & (f.rsi2 < level),
            priority=lambda f: -f.rsi2, exit_signal=lambda f: f.p.close > f.sma5,
            stop_pct=float(opt(k, "stop_pct", 10)), max_hold=int(opt(k, "max_hold", 10)),
            max_positions=int(opt(k, "max_positions", 10)), use_regime=opt(k, "use_regime", True),
        ))

    k = "near_high"
    if enabled(k, default=False):
        out.append(RankStrategy(
            key=k, name="Near 52-week high", horizon="longterm", evidence="MODERATE",
            description=("Holds uptrending stocks trading closest to their 52-week high (George & Hwang 2004). "
                         "In our tests it never beat the average stock."),
            score=lambda f: f.pct_from_52w_high, eligible=_uptrend,
            top_n=int(opt(k, "top_n", 15)), keep_rank=int(opt(k, "keep_rank", 30)),
            rebalance=opt(k, "rebalance", "monthly"), use_regime=opt(k, "use_regime", True),
        ))

    k = "legacy_rules"
    if enabled(k, default=False):
        out.append(EventStrategy(
            key=k, name="Old textbook rules (baseline)", horizon="swing", evidence="EXPERIMENTAL",
            description=("The v1 rules (50-DMA volume breakout, 52-week-high breakout) with 5% stop / 10% target / "
                         "15 days. Kept only as a 'what not to do' comparison (-12%/yr in testing)."),
            entries=lambda f: (((f.p.close > f.sma50) & (f.p.close.shift(1) <= f.sma50.shift(1))
                                & (f.vol_ratio >= 2) & (f.p.close > f.sma200))
                               | ((f.p.close > f.high_52w_prev) & (f.vol_ratio >= 1.5))),
            priority=lambda f: f.vol_ratio, stop_pct=5, target_pct=10, max_hold=15, max_positions=10,
            use_regime=False,
        ))
    return out
