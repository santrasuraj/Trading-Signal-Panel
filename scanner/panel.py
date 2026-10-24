"""Whole-market 'panel' data and vectorized factors.

A Panel holds one wide DataFrame per field (rows = trading dates, columns = symbols). Every factor
is computed for all stocks at once, which is far faster than looping stock by stock, and lets us
rank stocks against each other on each day (momentum, relative strength).

All factors at row t use only data up to and including day t (no look-ahead). Factors named
`*_prev` exclude day t itself (e.g. the 52-week high to beat for a breakout).
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property

import bottleneck as bn
import numpy as np
import pandas as pd

FIELDS = ("open", "high", "low", "close", "volume")
TRADING_DAYS = 252


@dataclass
class Panel:
    open: pd.DataFrame
    high: pd.DataFrame
    low: pd.DataFrame
    close: pd.DataFrame
    volume: pd.DataFrame
    index_close: pd.Series  # Nifty 50 close aligned to the same dates (may contain NaN)
    observed: pd.DataFrame  # True where the stock really traded/printed (False = gap-filled)
    # Optional point-in-time universe (True = member that day). When set, cross-sectional factors
    # (ranks, z-scores, breadth) compare a stock only with that day's members; None = all columns.
    universe: pd.DataFrame | None = None

    @property
    def dates(self) -> pd.DatetimeIndex:
        return self.close.index

    @property
    def symbols(self) -> list[str]:
        return list(self.close.columns)


INDEX_COLUMNS = ("NIFTY50", "INDIAVIX", "NIFTY500")


ETF_PRINT_TOL_PCT = 2.0


def clean_etf_prints(wide: dict[str, pd.DataFrame], etfs, tol_pct: float = ETF_PRINT_TOL_PCT) -> None:
    """NSE's daily file often has a stray odd-lot pre-open trade as an ETF's open (and so as its high or low),
    far from what the fund traded at all day: JUNIORBEES on 3 Jan 2022 'opened' at 386 between closes of 444 and
    447. A backtest that fills at the next open would book a phantom +15% (or -15%). For ETF columns only, an
    open beyond BOTH the previous and today's close by more than tol_pct is moved to the nearest edge of that
    band, and high / low are capped at it (real ETF moves - gaps included - stay inside the band because the
    band contains today's close). Stocks are never touched: their gaps are real. In place."""
    cols = [c for c in wide["close"].columns if c in set(etfs or ())]
    if not cols:
        return
    c = wide["close"][cols]
    pc = c.shift(1).fillna(c)
    lo = np.minimum(pc, c) * (1 - tol_pct / 100)
    hi = np.maximum(pc, c) * (1 + tol_pct / 100)
    o = wide["open"][cols].clip(lower=lo, upper=hi)
    wide["open"][cols] = o
    wide["high"][cols] = np.maximum(wide["high"][cols].clip(upper=hi), np.maximum(o, c))
    wide["low"][cols] = np.minimum(wide["low"][cols].clip(lower=lo), np.minimum(o, c))


def panel_from_wide(frames: dict[str, pd.DataFrame], symbols: list[str] | None = None,
                    index_symbol: str = "NIFTY50", max_gap_fill: int = 5, etfs=None,
                    universe: pd.DataFrame | None = None) -> Panel:
    """Build a Panel from wide per-field frames (see store.py). Short gaps inside a stock's history
    (suspended day, missing live quote) are bridged with the last close so rolling indicators don't
    break; `observed` records where real data existed. `etfs`: columns whose stray open prints are
    cleaned (clean_etf_prints). `universe`: see Panel.universe."""
    close_all = frames["close"]
    cols = [c for c in (symbols if symbols is not None else close_all.columns)
            if c in close_all.columns and c not in INDEX_COLUMNS]
    if not cols:
        raise ValueError("no stock data to build a panel from")
    wide = {f: frames[f].reindex(columns=cols).astype(float).sort_index() for f in FIELDS}
    close = wide["close"]
    dates = close.index
    observed = close.notna()
    first_valid = close.ffill().notna()
    filled_close = close.ffill(limit=max_gap_fill).where(first_valid)
    gap = close.isna() & filled_close.notna()
    for f in ("open", "high", "low"):
        wide[f] = wide[f].where(~gap, filled_close)
    wide["close"] = filled_close
    wide["volume"] = wide["volume"].where(~gap, 0.0)
    if etfs:
        clean_etf_prints(wide, etfs)
    index_close = (close_all[index_symbol].reindex(dates).astype(float) if index_symbol in close_all.columns
                   else pd.Series(np.nan, index=dates))
    if universe is not None:
        universe = universe.reindex(index=dates, columns=cols, fill_value=False).fillna(False).astype(bool)
    return Panel(index_close=index_close, observed=observed, universe=universe, **wide)


def build_panel(histories: dict[str, pd.DataFrame], index_symbol: str = "NIFTY50", max_gap_fill: int = 5) -> Panel:
    """Turn {symbol: OHLCV frame} into a Panel (convenience for per-symbol data)."""
    usable = {s: df for s, df in histories.items() if len(df)}
    frames = {f: pd.DataFrame({s: df[f] for s, df in usable.items()}).sort_index() for f in FIELDS}
    return panel_from_wide(frames, index_symbol=index_symbol, max_gap_fill=max_gap_fill)


def _min_periods(n: int) -> int:
    return max(1, n - n // 10)


_MOVE = {"mean": bn.move_mean, "max": bn.move_max, "min": bn.move_min, "std": bn.move_std}


def rolling(df: pd.DataFrame, how: str, n: int, min_count: int) -> pd.DataFrame:
    """Rolling window over every column at once (bottleneck, C speed - ~30x faster than pandas'
    column-by-column rolling). NaNs are skipped; a value needs at least `min_count` observations."""
    kw = {"ddof": 1} if how == "std" else {}
    arr = _MOVE[how](df.to_numpy(dtype=float), n, min_count=min_count, axis=0, **kw)
    return pd.DataFrame(arr, index=df.index, columns=df.columns)


class Factors:
    """Lazily computed, cached indicators over a Panel. Access like attributes: f.sma200, f.rsi2 ..."""

    def __init__(self, panel: Panel, etfs: set[str] | None = None, industry: dict[str, str] | None = None,
                 results_dates: dict[str, list[str]] | None = None):
        self.p = panel
        self.etfs = set(etfs or ()) & set(panel.symbols)              # ETFs: excluded from stock rankings
        self.industry = industry or {}                                 # symbol -> industry (for sector rotation)
        self.results_dates = results_dates or {}                       # symbol -> ['YYYY-MM-DD', ...]

    def _stocks_only(self, df: pd.DataFrame) -> pd.DataFrame:
        """Blank out ETF columns before cross-sectional statistics (ranks, z-scores, breadth)."""
        return df.drop(columns=[c for c in df.columns if c in self.etfs]).reindex(columns=df.columns) if self.etfs else df

    @cached_property
    def etf_mask(self) -> pd.DataFrame:
        cols = self.p.close.columns
        return pd.DataFrame(np.broadcast_to([c in self.etfs for c in cols], self.p.close.shape),
                            index=self.p.dates, columns=cols)

    # ---------------------------------------------------------------- helpers
    def members(self, df: pd.DataFrame) -> pd.DataFrame:
        """`df` with non-members of that day's universe blanked out (before ranking across stocks)."""
        return df if self.p.universe is None else df.where(self.p.universe)

    def sma(self, n: int) -> pd.DataFrame:
        return rolling(self.p.close, "mean", n, _min_periods(n))

    def ema(self, n: int) -> pd.DataFrame:
        return self.p.close.ewm(span=n, adjust=False, min_periods=n).mean()

    def ret(self, n: int) -> pd.DataFrame:
        return self.p.close / self.p.close.shift(n) - 1

    def rsi(self, n: int) -> pd.DataFrame:
        delta = self.p.close.diff()
        gain = delta.clip(lower=0).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
        loss = (-delta.clip(upper=0)).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
        rsi = 100 - 100 / (1 + gain / loss.replace(0, np.nan))
        rsi = rsi.where(~((loss == 0) & (gain > 0)), 100.0)     # only gains: 100
        return rsi.where(~((loss == 0) & (gain == 0)), 50.0)    # flat / suspended: neutral 50

    def high_n(self, n: int, include_today: bool = False) -> pd.DataFrame:
        h = rolling(self.p.high, "max", n, min(n, 60))
        return h if include_today else h.shift(1)

    def low_n(self, n: int, include_today: bool = False) -> pd.DataFrame:
        lo = rolling(self.p.low, "min", n, min(n, 60))
        return lo if include_today else lo.shift(1)

    # ---------------------------------------------------------------- trend
    @cached_property
    def sma5(self): return self.sma(5)
    @cached_property
    def sma10(self): return self.sma(10)
    @cached_property
    def sma20(self): return self.sma(20)
    @cached_property
    def sma50(self): return self.sma(50)
    @cached_property
    def sma150(self): return self.sma(150)
    @cached_property
    def sma200(self): return self.sma(200)
    @cached_property
    def ema9(self): return self.ema(9)
    @cached_property
    def ema21(self): return self.ema(21)

    @cached_property
    def sma200_rising(self) -> pd.DataFrame:
        """200-DMA higher than it was a month (21 days) ago."""
        return self.sma200 > self.sma200.shift(21)

    @cached_property
    def macd(self) -> pd.DataFrame:
        c = self.p.close
        return c.ewm(span=12, adjust=False).mean() - c.ewm(span=26, adjust=False).mean()

    @cached_property
    def macd_signal(self) -> pd.DataFrame:
        return self.macd.ewm(span=9, adjust=False).mean()

    # ---------------------------------------------------------------- oscillators / volatility
    @cached_property
    def rsi14(self): return self.rsi(14)
    @cached_property
    def rsi2(self): return self.rsi(2)

    @cached_property
    def atr14(self) -> pd.DataFrame:
        prev = self.p.close.shift(1)
        tr = np.maximum(self.p.high - self.p.low,
                        np.maximum((self.p.high - prev).abs(), (self.p.low - prev).abs()))
        return tr.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()

    @cached_property
    def atr_pct(self): return self.atr14 / self.p.close * 100

    @cached_property
    def daily_ret(self): return self.p.close.pct_change()

    @cached_property
    def vol_ann(self) -> pd.DataFrame:
        """Annualised volatility of daily log returns over the past year."""
        lr = np.log(self.p.close).diff()
        return rolling(lr, "std", TRADING_DAYS, 200) * np.sqrt(TRADING_DAYS)

    # ---------------------------------------------------------------- volume / liquidity
    @cached_property
    def vol_avg20(self):
        return rolling(self.p.volume, "mean", 20, 15).shift(1)

    @cached_property
    def vol_ratio(self):
        return self.p.volume / self.vol_avg20.replace(0, np.nan)

    @cached_property
    def turnover_avg20_cr(self):
        """Average daily traded value over the past 20 days, in Rs crore."""
        return rolling(self.p.close * self.p.volume, "mean", 20, 15) / 1e7

    @cached_property
    def turnover_rank(self):
        """1 = most traded stock that day (by 20-day average traded value; ETFs and non-members excluded)."""
        return self.members(self._stocks_only(self.turnover_avg20_cr)).rank(axis=1, ascending=False)

    # ---------------------------------------------------------------- 52-week range
    @cached_property
    def high_52w_prev(self): return self.high_n(TRADING_DAYS)
    @cached_property
    def low_52w_prev(self): return self.low_n(TRADING_DAYS)
    @cached_property
    def high_52w(self): return self.high_n(TRADING_DAYS, include_today=True)
    @cached_property
    def low_52w(self): return self.low_n(TRADING_DAYS, include_today=True)
    @cached_property
    def high_20_prev(self): return self.high_n(20)

    @cached_property
    def pct_from_52w_high(self):
        """0 = at the 52-week high, -10 = 10% below it."""
        return (self.p.close / self.high_52w - 1) * 100

    @cached_property
    def pct_above_52w_low(self):
        return (self.p.close / self.low_52w - 1) * 100

    # ---------------------------------------------------------------- momentum / relative strength
    @cached_property
    def ret_3m(self): return self.ret(63)
    @cached_property
    def ret_6m(self): return self.ret(126)
    @cached_property
    def ret_9m(self): return self.ret(189)
    @cached_property
    def ret_12m(self): return self.ret(TRADING_DAYS)

    @cached_property
    def rs_rating(self) -> pd.DataFrame:
        """IBD-style relative strength: weighted 3/6/9/12-month return, ranked 1-99 across stocks each day."""
        raw = self._stocks_only(0.4 * self.ret_3m + 0.2 * self.ret_6m + 0.2 * self.ret_9m + 0.2 * self.ret_12m)
        return (self.members(raw).rank(axis=1, pct=True) * 98 + 1).round()

    def momentum_score(self, skip_days: int = 0) -> pd.DataFrame:
        """NSE momentum-index style score: 6m and 12m returns each divided by annualised volatility,
        z-scored across stocks, averaged, then normalised (z>=0 -> 1+z, z<0 -> 1/(1-z))."""
        c = self.p.close.shift(skip_days) if skip_days else self.p.close
        vol = self.vol_ann.replace(0, np.nan)
        zs = []
        for n in (126, TRADING_DAYS):
            ratio = self.members(self._stocks_only((c / c.shift(n) - 1) / vol))
            mu, sd = ratio.mean(axis=1), ratio.std(axis=1)
            zs.append(ratio.sub(mu, axis=0).div(sd.replace(0, np.nan), axis=0))
        z = (zs[0] + zs[1]) / 2
        return z.where(z < 0, 1 + z).where(z >= 0, 1 / (1 - z))

    @cached_property
    def momentum(self): return self.momentum_score()

    # ---------------------------------------------------------------- market regime (Nifty)
    @cached_property
    def index_sma200(self) -> pd.Series:
        return self.p.index_close.rolling(200, min_periods=180).mean()

    @cached_property
    def regime_up(self) -> pd.Series:
        """True when Nifty 50 is above its 200-day average (missing data counts as up)."""
        ic = self.p.index_close.ffill()
        up = ic > self.index_sma200
        return up.where(self.index_sma200.notna(), True).astype(bool)

    @cached_property
    def breadth_50(self) -> pd.Series:
        """% of stocks above their 50-DMA each day."""
        valid = self.members(self.sma50).notna() & ~self.etf_mask
        return ((self.p.close > self.sma50) & valid).sum(axis=1) / valid.sum(axis=1).replace(0, np.nan) * 100

    # ---------------------------------------------------------------- swing-trading patterns
    @cached_property
    def high_55_prev(self): return self.high_n(55)
    @cached_property
    def low_20_prev(self): return self.low_n(20)
    @cached_property
    def low_10_prev(self): return self.low_n(10)
    @cached_property
    def high_15_prev(self): return self.high_n(15)

    @cached_property
    def range_15_pct(self) -> pd.DataFrame:
        """Height of the last 15 days' box (high-low) as % of its low: tight boxes precede breakouts."""
        return (rolling(self.p.high, "max", 15, 12) / rolling(self.p.low, "min", 15, 12) - 1) * 100

    @cached_property
    def atr_contraction(self) -> pd.DataFrame:
        """Recent volatility vs longer-term volatility (<1 = contracting, as in a VCP)."""
        return rolling(self.atr_pct, "mean", 10, 8) / rolling(self.atr_pct, "mean", 50, 40)

    @cached_property
    def bb_width(self) -> pd.DataFrame:
        """Bollinger Band width: 4 x 20-day std / 20-day average."""
        return 4 * rolling(self.p.close, "std", 20, 18) / self.sma20

    @cached_property
    def bb_upper(self) -> pd.DataFrame:
        return self.sma20 + 2 * rolling(self.p.close, "std", 20, 18)

    @cached_property
    def bb_squeeze(self) -> pd.DataFrame:
        """Band width in the lowest 10% of its last 6 months (a volatility squeeze)."""
        lo = rolling(self.bb_width, "min", 126, 100)
        hi = rolling(self.bb_width, "max", 126, 100)
        return self.bb_width <= lo + 0.1 * (hi - lo)

    @cached_property
    def nr7(self) -> pd.DataFrame:
        """Today's high-low range is the narrowest of the last 7 days."""
        rng = self.p.high - self.p.low
        return rng <= rolling(rng, "min", 7, 7)

    @cached_property
    def gap_pct(self) -> pd.DataFrame:
        return (self.p.open / self.p.close.shift(1) - 1) * 100

    @cached_property
    def golden_cross(self) -> pd.DataFrame:
        return (self.sma50 > self.sma200) & (self.sma50.shift(1) <= self.sma200.shift(1))

    @cached_property
    def results_window(self) -> pd.DataFrame:
        """True on a stock's results day and the next 2 trading days (from NSE's event calendar)."""
        out = pd.DataFrame(False, index=self.p.dates, columns=self.p.close.columns)
        arr = out.to_numpy(copy=True)
        col = {c: j for j, c in enumerate(out.columns)}
        for sym, days in self.results_dates.items():
            j = col.get(sym)
            if j is None:
                continue
            for d in days:
                i = self.p.dates.searchsorted(pd.Timestamp(d))
                if i < len(self.p.dates):
                    arr[i:i + 3, j] = True
        return pd.DataFrame(arr, index=out.index, columns=out.columns)

    @cached_property
    def industry_rank(self) -> pd.DataFrame:
        """Rank (1 = strongest) of each stock's industry by its members' average 6-month return."""
        ind = pd.Series(self.industry).reindex(self.p.close.columns)
        ret = self.members(self._stocks_only(self.ret_6m))
        valid = ind.dropna()
        if valid.empty:
            return pd.DataFrame(np.nan, index=self.p.dates, columns=self.p.close.columns)
        grp = ret[valid.index].T.groupby(valid.values).mean().T            # dates x industries
        counts = ret[valid.index].notna().T.groupby(valid.values).sum().T
        grp = grp.where(counts >= 3)                                         # ignore tiny industries
        rank = grp.rank(axis=1, ascending=False)
        out = rank.reindex(columns=ind.values)
        out.columns = ind.index
        return out
