"""Market statistics derived from the completed-day price store (no network).

Breadth uses the same symbol list and ETF exclusion as daily.py (universe + holdings + config ETFs, ETFs
excluded via Factors(etfs=...)), so the last completed point equals latest.market.breadth_50 when the scan
was not live.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from scanner.panel import Factors, panel_from_wide
from scanner.providers import INDEX_N500, INDEX_NIFTY, INDEX_VIX
from scanner.strategies import tradable_mask

from . import data
from ..caches import KeyedCache, file_key, register
from ..paths import P
from ..util import num, ser_list

_factors = register(KeyedCache(1))
_breadth = register(KeyedCache(2))
_industries = register(KeyedCache(1))


def symbols() -> list[str]:
    uni = list(data.universe()["symbol"])
    held = list(data.holdings_df()["symbol"])
    return list(dict.fromkeys(uni + held + data.etfs()))


def factors() -> Factors | None:
    """Factors over the store, cached per store generation + symbol list."""
    syms = symbols()
    key = (data.store_version(), file_key(P.universe(data.universe_name())), file_key(P.holdings),
           tuple(data.etfs()))

    def build():
        frames = data.store()
        if frames["close"].empty:
            return None
        try:
            p = panel_from_wide(frames, syms)
        except ValueError:
            return None
        meta = data.symbol_meta()
        industry = {s: m["industry"] for s, m in meta.items() if m.get("industry")}
        return Factors(p, etfs=set(data.etfs()), industry=industry)
    return _factors.get(key, build)


def source_date() -> str | None:
    c = data.store_close()
    return c.index[-1].date().isoformat() if len(c) else None


def nifty_sma200() -> float | None:
    """Store NIFTY50.rolling(200, min_periods=180) (fallback when the scan has no B3 field)."""
    c = data.store_close()
    if INDEX_NIFTY not in c.columns:
        return None
    s = c[INDEX_NIFTY].rolling(200, min_periods=180).mean().dropna()
    return num(s.iloc[-1], 2) if len(s) else None


RANGES = {"1y": 252, "3y": 756, "all": None}


def breadth(rng: str) -> dict | None:
    def build():
        f = factors()
        if f is None:
            return None
        close = data.store_close()
        idx = f.p.dates
        stocks = [c for c in f.p.close.columns if c not in f.etfs]
        chg = f.daily_ret[stocks]
        adv = (chg > 0).sum(axis=1)
        dec = (chg < 0).sum(axis=1)
        ad = (adv - dec).cumsum()
        out = pd.DataFrame({
            "breadth_50": f.breadth_50, "nifty": f.p.index_close, "nifty_sma200": f.index_sma200,
            "nifty500": close[INDEX_N500].reindex(idx) if INDEX_N500 in close.columns else np.nan,
            "vix": close[INDEX_VIX].reindex(idx) if INDEX_VIX in close.columns else np.nan,
            "ad_line": ad.astype(float),
        }, index=idx)
        n = RANGES[rng]
        if n:
            out = out.iloc[-n:]
        return {"source_date": idx[-1].date().isoformat(), "t": [d.date().isoformat() for d in out.index],
                "breadth_50": ser_list(out["breadth_50"], 2), "nifty": ser_list(out["nifty"], 2),
                "nifty_sma200": ser_list(out["nifty_sma200"], 2), "nifty500": ser_list(out["nifty500"], 2),
                "vix": ser_list(out["vix"], 2), "ad_line": ser_list(out["ad_line"], 0)}
    return _breadth.get((data.store_version(), rng, tuple(symbols())), build)


def industries() -> dict | None:
    def build():
        f = factors()
        if f is None:
            return None
        meta = data.symbol_meta()
        c = f.p.close
        stocks = [s for s in c.columns if s not in f.etfs and (meta.get(s) or {}).get("industry")]
        if not stocks:
            return {"rows": [], "source_date": c.index[-1].date().isoformat()}
        last = c[stocks].iloc[-1]
        # the same stocks as the top bar's advance/decline and the status bar's "liquid" count: fresh price today
        # AND liquid enough to trade (daily.py's tradable mask with the config filters)
        flt = data.config().get("filters") or {}
        liquid = tradable_mask(f, float(flt.get("min_price", 50)), float(flt.get("min_turnover_cr", 5)))
        valid = last.notna() & f.p.observed[stocks].iloc[-1] & liquid[stocks].iloc[-1].fillna(False).astype(bool)

        def ret(n):
            return (c[stocks].iloc[-1] / c[stocks].iloc[-1 - n] - 1) * 100 if len(c) > n else pd.Series(np.nan, index=stocks)
        r = {"1d": ret(1), "1w": ret(5), "1m": ret(21), "3m": ret(63), "6m": ret(126)}
        above = (c[stocks].iloc[-1] > f.sma50[stocks].iloc[-1])
        has50 = f.sma50[stocks].iloc[-1].notna()
        ind = pd.Series({s: meta[s]["industry"] for s in stocks})
        rows = []
        for name, members in ind.groupby(ind).groups.items():
            mem = [m for m in members if valid.get(m, False)]
            if not mem:
                continue
            d1 = r["1d"][mem]
            b = has50[mem]
            leaders = r["3m"][mem].dropna().sort_values(ascending=False).head(3)
            rows.append({"industry": str(name), "members": len(mem), "advances": int((d1 > 0).sum()),
                         "declines": int((d1 < 0).sum()),
                         "breadth_50": num(above[mem][b].mean() * 100, 1) if b.any() else None,
                         **{f"ret_{k}_pct": num(v[mem].mean(), 2) for k, v in r.items()},
                         "leaders": [{"symbol": s, "ret_3m_pct": num(v, 2)} for s, v in leaders.items()]})
        rows.sort(key=lambda x: -(x["ret_3m_pct"] if x["ret_3m_pct"] is not None else -1e9))
        return {"rows": rows, "source_date": c.index[-1].date().isoformat()}
    return _industries.get((data.store_version(), tuple(symbols()), file_key(P.config)), build)


TILES = ["Nifty 50", "Nifty 500", "India VIX", "Nifty200 Momentum 30"]


def index_tiles(lt: dict) -> list[dict]:
    hist = data.index_history()
    factors_rows = {r["name"]: r for r in (lt.get("indices") or {}).get("factors", [])}
    m = lt.get("market") or {}
    out = []
    for name in TILES:
        row = factors_rows.get(name) or {}
        last, chg = num(row.get("last")), num(row.get("chg_1d"))
        if name == "India VIX":
            last, chg = num(m.get("vix")), num(m.get("vix_change_pct"))
        elif name == "Nifty 50" and m.get("nifty") is not None:
            last, chg = num(m.get("nifty")), num(m.get("nifty_change_pct"))
        spark = []
        if hist is not None and name in hist.columns:
            spark = ser_list(hist[name].dropna().iloc[-63:], 2)
        if last is None and not spark:
            continue
        out.append({"name": name, "last": last, "chg_1d_pct": chg, "spark": spark, "href": "/market/factors"})
    return out


def stock_stats(symbol: str) -> dict:
    """Per-symbol indicators straight from the store (for symbols without a screener row)."""
    frames = data.store()
    c = frames["close"]
    if symbol not in c.columns:
        return {}
    close = c[symbol].dropna()
    if close.empty:
        return {}
    hi = frames["high"][symbol].reindex(close.index)
    lo = frames["low"][symbol].reindex(close.index)
    vol = frames["volume"][symbol].reindex(close.index)

    def ret(n):
        return num((close.iloc[-1] / close.iloc[-1 - n] - 1) * 100, 2) if len(close) > n else None
    h52, l52 = hi.iloc[-252:].max(), lo.iloc[-252:].min()
    va = vol.iloc[-21:-1].mean()
    dv = frames.get("deliv_pct")
    deliv = dv[symbol].reindex(close.index).dropna() if dv is not None and symbol in dv.columns else pd.Series(dtype=float)
    return {
        "price": num(close.iloc[-1], 2), "change_pct": ret(1), "data_date": close.index[-1].date().isoformat(),
        "high_52w": num(h52, 2), "low_52w": num(l52, 2),
        "pct_from_52w_high": num((close.iloc[-1] / h52 - 1) * 100, 2) if h52 and h52 > 0 else None,
        "ret_1m_pct": ret(21), "ret_3m_pct": ret(63), "ret_6m_pct": ret(126), "ret_12m_pct": ret(252),
        "sma50": num(close.iloc[-50:].mean(), 2) if len(close) >= 45 else None,
        "sma200": num(close.iloc[-200:].mean(), 2) if len(close) >= 180 else None,
        "vol_ratio": num(vol.iloc[-1] / va, 2) if va and va > 0 else None,
        "turnover_cr": num((close * vol).iloc[-20:].mean() / 1e7, 2),
        "deliv_pct": num(deliv.iloc[-1], 2) if len(deliv) else None,
    }
