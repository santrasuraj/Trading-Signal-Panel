"""Strategies added on 25 Oct 2026 (momentum_n200, residual_momentum, alpha_low_vol, etf_trend): the CAPM factors
behind them, no look-ahead, and that each one builds, scores and trades on synthetic data."""
from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from scanner.costs import CostModel
from scanner.engine import simulate
from scanner.panel import TRADING_DAYS, Factors, panel_from_wide
from scanner.settings import load_config
from scanner.strategies import build_strategies, strategy_lifecycle

NEW_KEYS = ("momentum_n200", "residual_momentum", "alpha_low_vol", "etf_trend")
ETFS = {"NIFTYBEES", "JUNIORBEES", "GOLDBEES", "MON100"}
N = 420          # rows: a year of warm-up plus about 8 months of trading
CUT = 380        # the no-look-ahead test changes every row from here on


def _closes(seed: int = 0) -> dict[str, np.ndarray]:
    """Close paths from daily log returns: Nifty 50, stocks with a known beta and alpha, and four ETFs."""
    rng = np.random.default_rng(seed)
    mkt = 0.001 + rng.normal(0, 0.008, N)
    rets = {
        "NIFTY50": mkt,
        "ALPHA": 1.0 * mkt + 0.003 + rng.normal(0, 0.005, N),   # earns more than its beta explains
        "BETA": 2.0 * mkt + rng.normal(0, 0.005, N),            # its return comes only from beta
        "PLAIN": 1.0 * mkt + rng.normal(0, 0.01, N),
        "LAGGARD": 0.5 * mkt - 0.002 + rng.normal(0, 0.01, N),
        "NIFTYBEES": mkt + rng.normal(0, 0.001, N),
        "JUNIORBEES": 1.2 * mkt + rng.normal(0, 0.003, N),
        "GOLDBEES": -0.004 + rng.normal(0, 0.006, N),           # falls all along: always below its 200-day average
        "MON100": 0.0015 + rng.normal(0, 0.01, N),
    }
    return {k: (10_000.0 if k == "NIFTY50" else 100.0) * np.exp(np.cumsum(r)) for k, r in rets.items()}


def _factors(frames_factory, closes: dict[str, np.ndarray] | None = None, universe=None) -> Factors:
    p = panel_from_wide(frames_factory(closes or _closes()), universe=universe)
    return Factors(p, etfs=ETFS)


def _new(cfg: dict | None = None) -> dict:
    return {s.key: s for s in build_strategies(cfg or {}) if s.key in NEW_KEYS}


# ------------------------------------------------------------------ factors
def test_capm_matches_ordinary_least_squares(frames_factory):
    f = _factors(frames_factory)
    r = f.daily_ret["ALPHA"].to_numpy()
    m = f.p.index_close.pct_change().to_numpy()
    slope, icpt = np.polyfit(m[-TRADING_DAYS:], r[-TRADING_DAYS:], 1)
    _, beta, _ = f.capm(TRADING_DAYS)
    assert beta["ALPHA"].iloc[-1] == pytest.approx(slope, rel=1e-6)
    assert f.alpha_1y["ALPHA"].iloc[-1] == pytest.approx(icpt * TRADING_DAYS, rel=1e-6)
    w = slice(N - TRADING_DAYS, N - 21)          # months 12-1: the 231 days ending a month before the last day
    slope, icpt = np.polyfit(m[w], r[w], 1)
    resid = r[w] - (icpt + slope * m[w])
    assert f.resid_mom["ALPHA"].iloc[-1] == pytest.approx(icpt / np.sqrt(np.mean(resid ** 2)), rel=1e-6)


def test_residual_momentum_and_alpha_strip_out_beta(frames_factory):
    f = _factors(frames_factory)
    _, beta, _ = f.capm(TRADING_DAYS)
    assert abs(beta["BETA"].iloc[-1] - 2.0) < 0.2 and abs(beta["ALPHA"].iloc[-1] - 1.0) < 0.2
    assert f.resid_mom["ALPHA"].iloc[-1] > f.resid_mom["BETA"].iloc[-1]
    assert f.alpha_1y["ALPHA"].iloc[-1] > f.alpha_1y["BETA"].iloc[-1]
    assert f.alpha_1y["ALPHA"].iloc[-1] == pytest.approx(0.003 * TRADING_DAYS, abs=0.25)
    # ETFs are never ranked with stocks; a year of history is needed first
    assert f.resid_mom["NIFTYBEES"].isna().all() and f.alpha_1y["GOLDBEES"].isna().all()
    assert f.resid_mom["ALPHA"].iloc[:200].isna().all() and f.alpha_1y["ALPHA"].iloc[:199].isna().all()


def test_capm_factors_blank_non_members(frames_factory):
    closes = _closes()
    idx = frames_factory(closes)["close"].index
    uni = pd.DataFrame(True, index=idx, columns=[c for c in closes if c != "NIFTY50"])
    uni["PLAIN"] = False
    f = _factors(frames_factory, closes, universe=uni)
    assert f.resid_mom["PLAIN"].isna().all() and f.alpha_1y["PLAIN"].isna().all()
    assert f.resid_mom["ALPHA"].notna().iloc[-1]


def test_new_factors_and_rules_have_no_lookahead(frames_factory):
    """Changing the future (a stock, an ETF and the index itself) must not change any value in the past."""
    base = _closes()
    alt = {k: v.copy() for k, v in base.items()}
    alt["ALPHA"][CUT:] *= 3
    alt["NIFTY50"][CUT:] *= 0.5
    alt["MON100"][CUT:] *= 0.3
    fa, fb = _factors(frames_factory, base), _factors(frames_factory, alt)
    for name in ("resid_mom", "alpha_1y"):
        pd.testing.assert_frame_equal(getattr(fa, name).iloc[:CUT], getattr(fb, name).iloc[:CUT],
                                      check_exact=False, rtol=1e-9)
    pd.testing.assert_frame_equal(fa.capm(TRADING_DAYS)[1].iloc[:CUT], fb.capm(TRADING_DAYS)[1].iloc[:CUT],
                                  check_exact=False, rtol=1e-9)
    for key, s in _new().items():
        pd.testing.assert_frame_equal(s.score(fa).iloc[:CUT], s.score(fb).iloc[:CUT], check_exact=False, rtol=1e-9,
                                      obj=f"{key} score")
        if s.eligible:
            pd.testing.assert_frame_equal(s.eligible(fa).iloc[:CUT], s.eligible(fb).iloc[:CUT], obj=f"{key} eligible")


# ------------------------------------------------------------------ strategies
def test_new_strategies_are_on_with_their_published_rules():
    by_key = _new()
    assert set(by_key) == set(NEW_KEYS)
    assert all(strategy_lifecycle({}, k) == ("active", None) for k in NEW_KEYS)
    n200, alv, etf = by_key["momentum_n200"], by_key["alpha_low_vol"], by_key["etf_trend"]
    assert (n200.top_n, n200.keep_rank, n200.rebalance, n200.use_regime) == (30, 60, "semiannual", False)
    assert (alv.top_n, alv.keep_rank, alv.rebalance, alv.use_regime) == (30, 60, "semiannual", False)
    assert etf.universe == "etfs" and etf.top_n == etf.keep_rank == 4 and not etf.use_regime
    assert by_key["residual_momentum"].benchmark == "Nifty Alpha 50"
    assert all(s.description.startswith("New:") for s in by_key.values())


def test_new_strategies_score_and_trade_on_synthetic_data(frames_factory):
    f = _factors(frames_factory)
    trad = pd.DataFrame(True, index=f.p.dates, columns=f.p.close.columns)
    stocks = {"ALPHA", "BETA", "PLAIN", "LAGGARD"}
    by_key = _new({"strategies": {"residual_momentum": {"use_regime": False}}})
    for key, s in by_key.items():
        score = s.score(f)
        ok = s.eligible(f).fillna(False).astype(bool) if s.eligible else score.notna()
        assert score.where(ok).notna().to_numpy().any(), f"{key} never scores an eligible instrument"
        res = simulate(s, f, CostModel(), tradable=trad, capital=1_000_000, warmup=TRADING_DAYS)
        names = {t.symbol for t in res.trades} | {pp["symbol"] for pp in res.open_positions}
        assert names, f"{key} never traded"
        assert names <= (ETFS if s.universe == "etfs" else stocks), key
    alv = _new()["alpha_low_vol"].score(f).iloc[-1]
    assert alv[["NIFTYBEES", "GOLDBEES"]].isna().all() and alv[list(stocks)].between(0, 1).all()


def test_etf_trend_holds_only_etfs_above_their_200_day_average(frames_factory):
    f = _factors(frames_factory)
    trad = pd.DataFrame(True, index=f.p.dates, columns=f.p.close.columns)
    res = simulate(_new()["etf_trend"], f, CostModel(), tradable=trad, capital=1_000_000, warmup=TRADING_DAYS)
    names = {t.symbol for t in res.trades} | {pp["symbol"] for pp in res.open_positions}
    assert names and "GOLDBEES" not in names
    assert len(res.open_positions) <= 4


def test_rule_values_from_config_reach_the_rules():
    """A rule must use ITS strategy's config value, not the last strategy's (lambdas bind names late)."""
    df = lambda v: pd.DataFrame(v, index=range(3), columns=["A"])  # noqa: E731
    gc = SimpleNamespace(golden_cross=df(True), rs_rating=df(70.0))
    on = build_strategies({"strategies": {"golden_cross": {"rs_min": 60}}}, include_disabled=True)
    off = build_strategies({"strategies": {"golden_cross": {"rs_min": 80}}}, include_disabled=True)
    entries = lambda strats: next(s for s in strats if s.key == "golden_cross").entries(gc)  # noqa: E731
    assert entries(on).all().all() and not entries(off).any().any()
    eg = SimpleNamespace(results_window=df(True), gap_pct=df(5.0), vol_ratio=df(4.0), sma200=df(100.0),
                         p=SimpleNamespace(close=df(110.0), open=df(100.0)))
    strict = build_strategies({"strategies": {"earnings_gap": {"min_gap_pct": 6}}}, include_disabled=True)
    plain = build_strategies({}, include_disabled=True)
    pick = lambda strats: next(s for s in strats if s.key == "earnings_gap").entries(eg)  # noqa: E731
    assert pick(plain).all().all() and not pick(strict).any().any()


def test_config_retires_the_losing_swing_strategies_and_runs_the_new_ones():
    cfg = load_config()
    for key in ("nr7_breakout", "bb_squeeze", "pullback_leaders"):
        state, reason = strategy_lifecycle(cfg, key)
        assert state == "rejected" and reason, key
    assert all(strategy_lifecycle(cfg, k)[0] == "active" for k in NEW_KEYS)
    keys = {s.key for s in build_strategies(cfg, include_disabled=True)}
    assert set(NEW_KEYS) <= keys and {"nr7_breakout", "bb_squeeze", "pullback_leaders"} <= keys
