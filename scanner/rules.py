"""Buy / sell signal rules.

Each rule returns a True/False series over the whole history, so the same code drives both
the daily scan (last value) and the backtest (every past value).
Parameters can be overridden per rule in config.yaml.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import pandas as pd


def cross_above(a: pd.Series, b: pd.Series) -> pd.Series:
    return (a > b) & (a.shift(1) <= b.shift(1))


def cross_below(a: pd.Series, b: pd.Series) -> pd.Series:
    return (a < b) & (a.shift(1) >= b.shift(1))


def _uptrend(df: pd.DataFrame, p: dict):
    return df["close"] > df["sma200"] if p.get("require_uptrend") else True


@dataclass(frozen=True)
class Rule:
    key: str
    side: str  # "BUY" or "SELL"
    name: str
    explain: str
    defaults: dict
    signal: Callable[[pd.DataFrame, dict], pd.Series]
    reason: Callable[[pd.Series, dict], str]

    def evaluate(self, df: pd.DataFrame, params: dict) -> pd.Series:
        s = self.signal(df, params)
        return s.fillna(False).astype(bool) if isinstance(s, pd.Series) else pd.Series(bool(s), index=df.index)


RULES: list[Rule] = [
    # ---------------------------------------------------------------- BUY
    Rule(
        "ma50_breakout", "BUY", "50-DMA breakout",
        "Price crossed above its 50-day average on heavy volume while above the 200-day average (long-term uptrend).",
        {"min_vol_ratio": 2.0, "require_uptrend": True},
        lambda df, p: cross_above(df["close"], df["sma50"]) & (df["vol_ratio"] >= p["min_vol_ratio"]) & _uptrend(df, p),
        lambda r, p: f"Crossed above 50-DMA ₹{r['sma50']:,.1f} on {r['vol_ratio']:.1f}× volume",
    ),
    Rule(
        "high52_breakout", "BUY", "52-week high breakout",
        "Closed above its highest price of the last year, with above-normal volume.",
        {"min_vol_ratio": 1.5},
        lambda df, p: (df["close"] > df["high_52w"]) & (df["vol_ratio"] >= p["min_vol_ratio"]),
        lambda r, p: f"New 52-week high (prev ₹{r['high_52w']:,.1f}) on {r['vol_ratio']:.1f}× volume",
    ),
    Rule(
        "rsi_bounce", "BUY", "RSI oversold bounce",
        "RSI climbed back above the oversold level - selling pressure may be ending.",
        {"level": 30, "require_uptrend": False},
        lambda df, p: (df["rsi"].shift(1) < p["level"]) & (df["rsi"] >= p["level"]) & _uptrend(df, p),
        lambda r, p: f"RSI recovered above {p['level']} (now {r['rsi']:.0f})",
    ),
    Rule(
        "macd_bull_cross", "BUY", "MACD bullish crossover",
        "MACD line crossed above its signal line while the stock is in a long-term uptrend.",
        {"require_uptrend": True},
        lambda df, p: cross_above(df["macd"], df["macd_signal"]) & _uptrend(df, p),
        lambda r, p: "MACD crossed above signal line",
    ),
    Rule(
        "ema_bull_cross", "BUY", "EMA 9/21 bullish crossover",
        "Short-term 9-day EMA crossed above the 21-day EMA, price above 50-DMA, volume above normal.",
        {"min_vol_ratio": 1.2},
        lambda df, p: cross_above(df["ema9"], df["ema21"]) & (df["close"] > df["sma50"]) & (df["vol_ratio"] >= p["min_vol_ratio"]),
        lambda r, p: f"9-EMA crossed above 21-EMA, {r['vol_ratio']:.1f}× volume",
    ),
    # ---------------------------------------------------------------- SELL
    Rule(
        "ma50_breakdown", "SELL", "50-DMA breakdown",
        "Price fell below its 50-day average on above-normal volume.",
        {"min_vol_ratio": 1.5},
        lambda df, p: cross_below(df["close"], df["sma50"]) & (df["vol_ratio"] >= p["min_vol_ratio"]),
        lambda r, p: f"Fell below 50-DMA ₹{r['sma50']:,.1f} on {r['vol_ratio']:.1f}× volume",
    ),
    Rule(
        "low52_breakdown", "SELL", "52-week low breakdown",
        "Closed below its lowest price of the last year, with above-normal volume.",
        {"min_vol_ratio": 1.5},
        lambda df, p: (df["close"] < df["low_52w"]) & (df["vol_ratio"] >= p["min_vol_ratio"]),
        lambda r, p: f"New 52-week low (prev ₹{r['low_52w']:,.1f}) on {r['vol_ratio']:.1f}× volume",
    ),
    Rule(
        "rsi_overbought_exit", "SELL", "RSI overbought reversal",
        "RSI dropped back below the overbought level - the rally may be running out of steam.",
        {"level": 70},
        lambda df, p: (df["rsi"].shift(1) >= p["level"]) & (df["rsi"] < p["level"]),
        lambda r, p: f"RSI fell back below {p['level']} (now {r['rsi']:.0f})",
    ),
    Rule(
        "macd_bear_cross", "SELL", "MACD bearish crossover",
        "MACD line crossed below its signal line while price is under the 50-day average.",
        {},
        lambda df, p: cross_below(df["macd"], df["macd_signal"]) & (df["close"] < df["sma50"]),
        lambda r, p: "MACD crossed below signal line, price under 50-DMA",
    ),
    Rule(
        "ema_bear_cross", "SELL", "EMA 9/21 bearish crossover",
        "Short-term 9-day EMA crossed below the 21-day EMA on above-normal volume.",
        {"min_vol_ratio": 1.2},
        lambda df, p: cross_below(df["ema9"], df["ema21"]) & (df["vol_ratio"] >= p["min_vol_ratio"]),
        lambda r, p: f"9-EMA crossed below 21-EMA, {r['vol_ratio']:.1f}× volume",
    ),
]
RULES_BY_KEY = {r.key: r for r in RULES}


def active_rules(cfg: dict) -> list[tuple[Rule, dict]]:
    """Enabled rules with their parameters merged from config.yaml."""
    conf = cfg.get("rules") or {}
    out = []
    for rule in RULES:
        rc = conf.get(rule.key) or {}
        if rc.get("enabled", True):
            params = {**rule.defaults, **{k: v for k, v in rc.items() if k != "enabled"}}
            out.append((rule, params))
    return out
