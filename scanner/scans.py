"""Your own scans: rules over whole-market factors, run on today's market and back-tested on 8 years.

A scan is a list of rules joined by "all" (every rule) or "any" (at least one):

    {"name": "Breakout on volume", "match": "all", "direction": "long", "rules": [
        {"left": "close", "op": ">", "right": {"field": "high_20_prev"}},
        {"left": "vol_ratio", "op": ">=", "right": {"value": 2}},
        {"left": "close", "op": ">", "right": {"field": "sma200"}}]}

  left      a field (FIELDS)
  op        >  >=  <  <=  crosses_above  crosses_below
  right     {"value": number} or {"field": name, "mult": 1.0} (e.g. close > 1.05 x sma50)

Fields are computed for every stock at once (scanner/panel.py, no look-ahead: row t uses data up to day t).

Today: the scan's universe (config.yaml `universe`) on the price store, the last scan's prices.
Backtest: the survivorship-free point-in-time top 500 (scanner/pit.py), Aug 2018 on - companies that later
crashed or were delisted included. An event is the first day a stock matches (it matched no rule set the day
before), only while it is a universe member. Buy at the next day's open, hold 5 / 10 / 20 days, compared with the
average member over the same days, round-trip costs of ~0.45% subtracted, t-statistic on monthly averages
(scanner/pattern_study.py): the same test every candle and chart pattern in this app went through. A scan has an
edge only with t >= 2 and a positive excess after costs over 100+ events in 24+ months; most don't.
"""
from __future__ import annotations

import json
import math
import re
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Callable

import numpy as np
import pandas as pd

from . import pattern_study as ps
from . import watch
from .panel import Factors, Panel, panel_from_wide
from .settings import ist_now

OPS = (">", ">=", "<", "<=", "crosses_above", "crosses_below")
MAX_RULES = 8
SCANS_FILE_NAME = "scans.json"
NAME = re.compile(r"^[\w .,&()+%/-]{1,60}$")


@dataclass(frozen=True)
class Field:
    label: str
    group: str
    unit: str          # "₹", "%", "x", "", "₹ cr"
    fn: Callable[["Ctx"], pd.DataFrame]


class Ctx:
    def __init__(self, panel: Panel, extra: dict[str, pd.DataFrame] | None = None):
        self.p = panel
        self.f = Factors(panel)
        self.extra = extra or {}
        self._cache: dict[str, pd.DataFrame] = {}

    def get(self, key: str) -> pd.DataFrame:
        if key not in self._cache:
            if len(self._cache) >= 16:                 # ~20 MB a field on the 8-year panel: keep the 16 newest
                self._cache.pop(next(iter(self._cache)))
            self._cache[key] = FIELDS[key].fn(self)
        return self._cache[key]


def _pct(df: pd.DataFrame) -> pd.DataFrame:
    return df * 100


FIELDS: dict[str, Field] = {
    # price
    "close": Field("Close", "Price", "₹", lambda c: c.p.close),
    "open": Field("Open", "Price", "₹", lambda c: c.p.open),
    "high": Field("High", "Price", "₹", lambda c: c.p.high),
    "low": Field("Low", "Price", "₹", lambda c: c.p.low),
    "change_pct": Field("Day change %", "Price", "%", lambda c: _pct(c.f.daily_ret)),
    "gap_pct": Field("Gap at the open %", "Price", "%", lambda c: (c.p.open / c.p.close.shift(1) - 1) * 100),
    # trend
    "sma20": Field("SMA 20", "Trend", "₹", lambda c: c.f.sma20),
    "sma50": Field("SMA 50", "Trend", "₹", lambda c: c.f.sma50),
    "sma150": Field("SMA 150", "Trend", "₹", lambda c: c.f.sma150),
    "sma200": Field("SMA 200", "Trend", "₹", lambda c: c.f.sma200),
    "ema9": Field("EMA 9", "Trend", "₹", lambda c: c.f.ema9),
    "ema21": Field("EMA 21", "Trend", "₹", lambda c: c.f.ema21),
    "macd": Field("MACD (12, 26)", "Trend", "", lambda c: c.f.macd),
    "macd_signal": Field("MACD signal (9)", "Trend", "", lambda c: c.f.macd_signal),
    # momentum
    "ret_1w": Field("Return 1 week %", "Momentum", "%", lambda c: _pct(c.f.ret(5))),
    "ret_1m": Field("Return 1 month %", "Momentum", "%", lambda c: _pct(c.f.ret(21))),
    "ret_3m": Field("Return 3 months %", "Momentum", "%", lambda c: _pct(c.f.ret_3m)),
    "ret_6m": Field("Return 6 months %", "Momentum", "%", lambda c: _pct(c.f.ret_6m)),
    "ret_12m": Field("Return 12 months %", "Momentum", "%", lambda c: _pct(c.f.ret_12m)),
    "rs_rating": Field("Relative strength (1-99)", "Momentum", "", lambda c: c.f.rs_rating),
    "rsi14": Field("RSI 14", "Momentum", "", lambda c: c.f.rsi14),
    "rsi2": Field("RSI 2", "Momentum", "", lambda c: c.f.rsi2),
    # range
    "high_20_prev": Field("20-day high (before today)", "Range", "₹", lambda c: c.f.high_20_prev),
    "low_20_prev": Field("20-day low (before today)", "Range", "₹", lambda c: c.f.low_n(20)),
    "high_52w_prev": Field("52-week high (before today)", "Range", "₹", lambda c: c.f.high_52w_prev),
    "low_52w_prev": Field("52-week low (before today)", "Range", "₹", lambda c: c.f.low_52w_prev),
    "pct_from_52w_high": Field("% from 52-week high (0 = at it)", "Range", "%", lambda c: c.f.pct_from_52w_high),
    "pct_above_52w_low": Field("% above 52-week low", "Range", "%", lambda c: c.f.pct_above_52w_low),
    # volatility / volume
    "atr_pct": Field("ATR 14 % of price", "Volatility", "%", lambda c: c.f.atr_pct),
    "vol_ann_pct": Field("Volatility 1y % (annualised)", "Volatility", "%", lambda c: _pct(c.f.vol_ann)),
    "volume": Field("Volume (shares)", "Volume", "", lambda c: c.p.volume),
    "vol_ratio": Field("Volume vs 20-day average", "Volume", "x", lambda c: c.f.vol_ratio),
    "turnover_cr": Field("Traded value 20-day avg", "Volume", "₹ cr", lambda c: c.f.turnover_avg20_cr),
    "deliv_pct": Field("Delivery %", "Volume", "%", lambda c: c.extra["deliv_pct"].reindex(index=c.p.dates, columns=c.p.close.columns)
                       if "deliv_pct" in c.extra else pd.DataFrame(np.nan, index=c.p.dates, columns=c.p.close.columns)),
}

def _fund(c: "Ctx", key: str) -> pd.DataFrame:
    """Company numbers, point in time (scanner/fundamentals.py): each quarter's value from the day it was filed."""
    if "_fund" not in c.extra:
        from . import fundamentals
        c.extra["_fund"] = fundamentals.frames(list(c.p.close.columns), c.p.dates)
    f = c.extra["_fund"]
    if key == "pe":
        eps = f["eps_ttm"]
        return c.p.close / eps.where(eps > 0)
    return f[key]


def _weekly(c: "Ctx", key: str) -> pd.DataFrame:
    """Weekly-chart fields on daily rows: each completed week's value from the week's last day on (no look-ahead:
    the current, unfinished week never counts)."""
    if "_weekly" not in c.extra:
        close = c.p.close
        wk = close.index.to_period("W-FRI")
        last_day = pd.Series(close.index, index=close.index).groupby(wk).transform("max")
        wclose = close.groupby(wk).last()
        d = wclose.diff()
        up, dn = d.clip(lower=0), -d.clip(upper=0)
        rs = up.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean() / dn.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean().replace(0, np.nan)
        wf = {"w_sma10": wclose.rolling(10, min_periods=10).mean(), "w_sma30": wclose.rolling(30, min_periods=30).mean(),
              "w_rsi14": 100 - 100 / (1 + rs), "w_ret_4": (wclose / wclose.shift(4) - 1) * 100}
        complete = (close.index == last_day.to_numpy())             # a week's value appears on its last trading day
        out = {}
        for k, v in wf.items():
            daily = v.reindex(wk).set_axis(close.index)
            out[k] = daily.where(pd.Series(complete, index=close.index), axis=0).ffill()
        c.extra["_weekly"] = out
    return c.extra["_weekly"][key]


FIELDS.update({
    "w_sma10": Field("Weekly SMA 10 (completed weeks)", "Weekly", "₹", lambda c: _weekly(c, "w_sma10")),
    "w_sma30": Field("Weekly SMA 30 (completed weeks)", "Weekly", "₹", lambda c: _weekly(c, "w_sma30")),
    "w_rsi14": Field("Weekly RSI 14 (completed weeks)", "Weekly", "", lambda c: _weekly(c, "w_rsi14")),
    "w_ret_4": Field("Return over the last 4 weeks %", "Weekly", "%", lambda c: _weekly(c, "w_ret_4")),
})

FIELDS.update({
    "pe": Field("P/E (last 4 quarters' EPS)", "Company", "x", lambda c: _fund(c, "pe")),
    "eps_ttm": Field("EPS, last 4 quarters", "Company", "₹", lambda c: _fund(c, "eps_ttm")),
    "sales_growth": Field("Revenue growth vs a year ago %", "Company", "%", lambda c: _fund(c, "sales_growth")),
    "profit_growth": Field("Profit growth vs a year ago %", "Company", "%", lambda c: _fund(c, "profit_growth")),
    "net_margin": Field("Net profit margin %", "Company", "%", lambda c: _fund(c, "net_margin")),
})

PRESETS = [
    {"name": "20-day breakout on 2x volume (uptrend)", "match": "all", "direction": "long", "rules": [
        {"left": "close", "op": ">", "right": {"field": "high_20_prev"}},
        {"left": "vol_ratio", "op": ">=", "right": {"value": 2}},
        {"left": "close", "op": ">", "right": {"field": "sma200"}}]},
    {"name": "New 52-week high", "match": "all", "direction": "long", "rules": [
        {"left": "close", "op": ">", "right": {"field": "high_52w_prev"}}]},
    {"name": "Golden cross (50 over 200)", "match": "all", "direction": "long", "rules": [
        {"left": "sma50", "op": "crosses_above", "right": {"field": "sma200"}}]},
    {"name": "RSI(2) oversold in an uptrend", "match": "all", "direction": "long", "rules": [
        {"left": "rsi2", "op": "<", "right": {"value": 10}},
        {"left": "close", "op": ">", "right": {"field": "sma200"}}]},
    {"name": "Pullback to the 50-day in a leader", "match": "all", "direction": "long", "rules": [
        {"left": "rs_rating", "op": ">=", "right": {"value": 80}},
        {"left": "low", "op": "<=", "right": {"field": "sma50", "mult": 1.01}},
        {"left": "close", "op": ">", "right": {"field": "sma50"}}]},
    {"name": "MACD crosses above signal", "match": "all", "direction": "long", "rules": [
        {"left": "macd", "op": "crosses_above", "right": {"field": "macd_signal"}}]},
    {"name": "Weekly uptrend, daily pullback (two timeframes)", "match": "all", "direction": "long", "rules": [
        {"left": "close", "op": ">", "right": {"field": "w_sma30"}},
        {"left": "w_rsi14", "op": ">", "right": {"value": 50}},
        {"left": "rsi14", "op": "<", "right": {"value": 40}}]},
    {"name": "Growing profits, reasonable P/E, uptrend", "match": "all", "direction": "long", "rules": [
        {"left": "profit_growth", "op": ">=", "right": {"value": 20}},
        {"left": "sales_growth", "op": ">=", "right": {"value": 10}},
        {"left": "pe", "op": "<=", "right": {"value": 40}},
        {"left": "close", "op": ">", "right": {"field": "sma200"}}]},
]


# ---- validation -------------------------------------------------------------------------------------------------

def validate(scan: dict) -> dict:
    name = str(scan.get("name") or "My scan").strip()[:60] or "My scan"
    match = scan.get("match") or "all"
    if match not in ("all", "any"):
        raise ValueError("match must be all or any.")
    direction = scan.get("direction") or "long"
    if direction not in ("long", "short"):
        raise ValueError("direction must be long or short.")
    rules = scan.get("rules") or []
    if not rules:
        raise ValueError("Add at least one rule.")
    if len(rules) > MAX_RULES:
        raise ValueError(f"At most {MAX_RULES} rules.")
    out = []
    for i, r in enumerate(rules, 1):
        left, op, right = r.get("left"), r.get("op"), r.get("right") or {}
        if left not in FIELDS:
            raise ValueError(f"Rule {i}: unknown field {left!r}.")
        if op not in OPS:
            raise ValueError(f"Rule {i}: unknown comparison {op!r}.")
        if "field" in right and right["field"] is not None:
            if right["field"] not in FIELDS:
                raise ValueError(f"Rule {i}: unknown field {right['field']!r}.")
            mult = float(right.get("mult") if right.get("mult") is not None else 1.0)
            if not math.isfinite(mult) or mult <= 0 or mult > 100:
                raise ValueError(f"Rule {i}: the multiplier must be between 0 and 100.")
            rr = {"field": right["field"], "mult": mult}
        else:
            try:
                v = float(right.get("value"))
            except (TypeError, ValueError):
                raise ValueError(f"Rule {i}: give a number or a field to compare with.") from None
            if not math.isfinite(v):
                raise ValueError(f"Rule {i}: the number is not finite.")
            rr = {"value": v}
        out.append({"left": left, "op": op, "right": rr})
    return {"name": name, "match": match, "direction": direction, "rules": out}


def describe_rule(r: dict) -> str:
    left = FIELDS[r["left"]].label
    op = {">": ">", ">=": "≥", "<": "<", "<=": "≤", "crosses_above": "crosses above", "crosses_below": "crosses below"}[r["op"]]
    rt = r["right"]
    if "field" in rt:
        m = rt.get("mult", 1.0)
        right = (f"{m:g} × " if m != 1 else "") + FIELDS[rt["field"]].label
    else:
        right = f"{rt['value']:g}"
    return f"{left} {op} {right}"


# ---- evaluation --------------------------------------------------------------------------------------------------

def _rhs(ctx: Ctx, rt: dict, like: pd.DataFrame) -> pd.DataFrame | float:
    if "field" in rt:
        return ctx.get(rt["field"]) * float(rt.get("mult", 1.0))
    return float(rt["value"])


def _rule_mask(ctx: Ctx, r: dict) -> pd.DataFrame:
    a = ctx.get(r["left"])
    b = _rhs(ctx, r["right"], a)
    op = r["op"]
    if op == ">":
        m = a > b
    elif op == ">=":
        m = a >= b
    elif op == "<":
        m = a < b
    elif op == "<=":
        m = a <= b
    else:
        b_prev = b.shift(1) if isinstance(b, pd.DataFrame) else b
        if op == "crosses_above":
            m = (a > b) & (a.shift(1) <= b_prev)
        else:
            m = (a < b) & (a.shift(1) >= b_prev)
    return m.fillna(False) if hasattr(m, "fillna") else m


def evaluate(scan: dict, ctx: Ctx) -> pd.DataFrame:
    """Boolean frame (dates x symbols): where the scan matches."""
    masks = [_rule_mask(ctx, r) for r in scan["rules"]]
    out = masks[0].copy()
    for m in masks[1:]:
        out = (out & m) if scan["match"] == "all" else (out | m)
    return out.astype(bool)


def _num(x) -> float | None:
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    return round(f, 2) if math.isfinite(f) else None


# ---- today -------------------------------------------------------------------------------------------------------

def run_today(scan: dict, frames: dict[str, pd.DataFrame], symbols: list[str], meta: dict[str, dict] | None = None,
              lookback: int = 400, limit: int = 300) -> dict:
    """The stocks matching on the last day of `frames` (the price store, the scan's prices)."""
    scan = validate(scan)
    t0 = time.monotonic()
    cut = {k: v.iloc[-lookback:] for k, v in frames.items() if isinstance(v, pd.DataFrame)}
    panel = panel_from_wide(cut, symbols)
    ctx = Ctx(panel, {"deliv_pct": cut["deliv_pct"]} if "deliv_pct" in cut else None)
    m = evaluate(scan, ctx)
    last = m.iloc[-1]
    hits = [s for s in m.columns if bool(last.get(s))]
    started = set()
    if len(m) > 1:
        prev = m.iloc[-2]
        started = {s for s in hits if not bool(prev.get(s))}
    show = sorted({r["left"] for r in scan["rules"]} | {r["right"]["field"] for r in scan["rules"] if "field" in r["right"]})
    meta = meta or {}
    rows = []
    for s in hits:
        vals = {k: _num(ctx.get(k)[s].iloc[-1]) for k in show}
        rows.append({"symbol": s, "company": (meta.get(s) or {}).get("company"), "industry": (meta.get(s) or {}).get("industry"),
                     "close": _num(panel.close[s].iloc[-1]), "change_pct": _num(ctx.get("change_pct")[s].iloc[-1]),
                     "rs_rating": _num(ctx.get("rs_rating")[s].iloc[-1]), "new_today": s in started, "values": vals})
    rows.sort(key=lambda r: (not r["new_today"], -(r["rs_rating"] or 0)))
    return {"scan": scan, "date": panel.dates[-1].date().isoformat(), "universe_size": len(panel.symbols),
            "count": len(rows), "rows": rows[:limit], "fields": show,
            "rules_text": [describe_rule(r) for r in scan["rules"]], "elapsed_s": round(time.monotonic() - t0, 2)}


LIVE_SOURCES = ("live", "fyers", "yahoo")


def live_frames(frames: dict[str, pd.DataFrame], quotes: dict[str, dict], day, lookback: int = 400) -> dict[str, pd.DataFrame]:
    """The last `lookback` days with today's row from live quotes (open, high, low, price as the close, volume),
    replacing a provisional row for today. Stocks without a live quote have no row today (they can't match)."""
    ts = pd.Timestamp(day)
    cut = {k: v.iloc[-lookback:].copy() for k, v in frames.items() if isinstance(v, pd.DataFrame)}
    if cut["close"].index[-1] < ts:
        for k, v in cut.items():
            cut[k] = pd.concat([v, pd.DataFrame(np.nan, index=[ts], columns=v.columns)])
    else:
        for k in cut:
            cut[k].loc[ts] = np.nan
    for field, key in (("open", "open"), ("high", "high"), ("low", "low"), ("close", "price"), ("volume", "volume")):
        if field not in cut:
            continue
        col = cut[field]
        for sym, q in quotes.items():
            v = q.get(key) if (q.get("source") or "live") in LIVE_SOURCES else None
            if v is None and field in ("open", "high", "low"):
                v = q.get("price") if (q.get("source") or "live") in LIVE_SOURCES else None
            if v is not None and sym in col.columns:
                col.at[ts, sym] = float(v)
    return cut


def run_live(scan: dict, frames: dict[str, pd.DataFrame], quotes: dict[str, dict], symbols: list[str],
             meta: dict[str, dict] | None = None, day=None, limit: int = 300) -> dict:
    """run_today on today's live prices: only stocks with a live quote can match ("quoted" says how many had one)."""
    from .settings import ist_now
    day = day or ist_now().date()
    live = {s for s, q in quotes.items() if q.get("price") is not None and (q.get("source") or "live") in LIVE_SOURCES}
    out = run_today(scan, live_frames(frames, quotes, day), symbols, meta, limit=10_000)
    rows = [r for r in out["rows"] if r["symbol"] in live]
    return {**out, "rows": rows[:limit], "count": len(rows), "live": True, "quoted": len(live & set(symbols))}


# ---- backtest ----------------------------------------------------------------------------------------------------

_pit_lock = threading.Lock()
_eval_lock = threading.Lock()
_pit: dict = {"at": 0.0, "data": None, "ctx": None}
PIT_KEEP_S = 900             # the 120 MB point-in-time panel stays in memory 15 minutes after its last use


def _pit_ctx():
    from . import pit
    with _pit_lock:
        now = time.monotonic()
        if _pit["ctx"] is None or now - _pit["at"] > PIT_KEEP_S:
            data = pit.load()
            if data is None:
                raise RuntimeError("The survivorship-free universe is not built yet: run 4_build_universe.bat once.")
            members = data.members
            panel = panel_from_wide(data.frames, members, universe=data.universe)
            _pit.update(data=data, ctx=Ctx(panel, {"deliv_pct": data.frames.get("deliv_pct")} if "deliv_pct" in data.frames else None))
        _pit["at"] = now
        t = _pit.get("timer")
        if t is not None:
            t.cancel()
        t = threading.Timer(PIT_KEEP_S + 5, release_pit)
        t.daemon = True
        t.start()
        _pit["timer"] = t
        return _pit["data"], _pit["ctx"]


def release_pit() -> None:
    with _pit_lock:
        if _pit["ctx"] is not None and time.monotonic() - _pit["at"] > PIT_KEEP_S:
            _pit.update(data=None, ctx=None)


def backtest(scan: dict, log=print) -> dict:
    """The scan's event study on the point-in-time top 500 (see the module docstring)."""
    scan = validate(scan)
    t0 = time.monotonic()
    data, base = _pit_ctx()
    with _eval_lock:                               # one evaluation at a time on the shared (cached) panel
        m = evaluate(scan, base)
    uni = base.p.universe
    onset = m & ~m.shift(1, fill_value=False) & uni
    rows, cols = np.nonzero(onset.to_numpy())
    cal = base.p.dates
    if not len(rows):
        return {"scan": scan, "rules_text": [describe_rule(r) for r in scan["rules"]], "events": 0, "horizons": {},
                "verdict": "too_few", "primary": 10, "yearly": [], "recent": [], "first_day": cal[0].date().isoformat(),
                "last_day": cal[-1].date().isoformat(), "cost_pct": ps.COST_PCT, "elapsed_s": round(time.monotonic() - t0, 1),
                "note": NOTE}
    side = 1 if scan["direction"] == "long" else -1
    ev = pd.DataFrame({"symbol": base.p.close.columns[cols], "bar": rows, "date": cal[rows], "side": side})
    ev = ps.forward_excess({"open": base.p.open, "close": base.p.close}, uni, ev)
    hs = {str(h): ps.stats(ev, h) for h in ps.HORIZONS}
    primary = 10
    verdict = ps.verdict(hs[str(primary)], True)
    x = ev.dropna(subset=[f"excess_{primary}"]).copy()
    x["signed"] = x[f"excess_{primary}"] * side * 100
    x["raw"] = x[f"ret_{primary}"] * side * 100
    yearly = []
    for y, g in x.groupby(pd.to_datetime(x["date"]).dt.year):
        yearly.append({"year": int(y), "events": int(len(g)), "excess_pct": _num(g["signed"].mean()),
                       "hit_pct": _num((g["signed"] > 0).mean() * 100), "return_pct": _num(g["raw"].mean())})
    recent = []
    for _, r in x.sort_values("date").tail(25).iloc[::-1].iterrows():
        recent.append({"date": pd.Timestamp(r["date"]).date().isoformat(), "symbol": r["symbol"],
                       "return_pct": _num(r["raw"]), "excess_pct": _num(r["signed"])})
    return {"scan": scan, "rules_text": [describe_rule(r) for r in scan["rules"]], "events": int(len(ev)),
            "horizons": hs, "primary": primary, "verdict": verdict, "yearly": yearly, "recent": recent,
            "first_day": cal[0].date().isoformat(), "last_day": cal[-1].date().isoformat(), "cost_pct": ps.COST_PCT,
            "elapsed_s": round(time.monotonic() - t0, 1), "note": NOTE}


NOTE = ("Tested on the survivorship-free top 500 (companies that later crashed or were delisted included): each time a "
        "stock starts to match, buy at the next open and hold 5, 10 or 20 days, compared with the average member over "
        "the same days, ~0.45% round-trip costs subtracted. An edge needs t ≥ 2 and a positive excess after costs over "
        "100+ events in 24+ months. Past results only; most scans show no edge.")


# ---- saved scans -------------------------------------------------------------------------------------------------

def saved() -> list[dict]:
    return list(watch._read(watch.data_dir() / SCANS_FILE_NAME, {"scans": []}).get("scans") or [])


def save(scan: dict, scan_id: str | None = None) -> dict:
    s = validate(scan)
    with watch._lock("scans"):
        cur = saved()
        if scan_id:
            hit = next((x for x in cur if x.get("id") == scan_id), None)
            if hit is None:
                raise KeyError(scan_id)
            hit.update(s, updated=ist_now().isoformat(timespec="seconds"))
            out = hit
        else:
            if len(cur) >= 100:
                raise ValueError("At most 100 saved scans.")
            out = {**s, "id": uuid.uuid4().hex[:12], "updated": ist_now().isoformat(timespec="seconds")}
            cur.append(out)
        watch._write(watch.data_dir() / SCANS_FILE_NAME, {"scans": cur})
    return out


def delete(scan_id: str) -> None:
    with watch._lock("scans"):
        cur = [x for x in saved() if x.get("id") != scan_id]
        watch._write(watch.data_dir() / SCANS_FILE_NAME, {"scans": cur})


def catalog() -> dict:
    return {"fields": [{"key": k, "label": f.label, "group": f.group, "unit": f.unit} for k, f in FIELDS.items()],
            "ops": list(OPS), "presets": PRESETS, "max_rules": MAX_RULES}


def dumps(x) -> str:
    return json.dumps(x, default=str)


try:                                   # your saved formulas as scan fields (scanner/formula.py)
    from . import formula as _formula
    _formula.register_fields()
except Exception:                      # a broken formulas.json must never stop the scans
    pass
