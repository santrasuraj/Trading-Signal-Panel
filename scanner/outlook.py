"""Outlook: what usually happened next when a stock looked like this one does today.

No one knows tomorrow's price. What can be measured is how often, and by how much, stocks in the same setup moved
afterwards. This module measures that on the survivorship-free point-in-time universe (pit.py: each day's 500
most-traded NSE stocks since 2018, including the ones that later collapsed or were delisted).

Setup (five features, each only from data up to that day)
  trend    close vs its 50- and 200-day averages: above both / above 200 only / above 50 only / below both
  mom      6-month return ranked against that day's universe: weak / middle / strong third
  rsi      RSI 14: under 35 / 35-65 / over 65
  high52   distance from the 52-week high: within 5% / 5-15% / 15-30% / more than 30% below
  vol      day's volume vs the previous 20 days' average: under 0.8x / 0.8-1.5x / 1.5x or more

Outcome (like pattern_study.py)
  buy at the next day's open, measure to the close 5, 10 and 20 trading days later; "excess" is that return minus
  the average universe stock's return over exactly the same stretch; touch = the high / low of the next 20 days
  reached +5% / -5% from the entry open. t-statistics on monthly averages (days of one month move together).

A setup with too few cases (MIN_EVENTS events over MIN_MONTHS months) falls back to a coarser one: the last
features are dropped one by one (vol, then rsi, then high52, then mom).

  python -m scanner.outlook       (~1 minute; writes data/results/outlook_study.json; every scan also runs it)
"""
from __future__ import annotations

import json
import math
import time

import numpy as np
import pandas as pd

from .settings import RESULTS_DIR, ist_now

STUDY_FILE = RESULTS_DIR / "outlook_study.json"
VERSION = 1
HORIZONS = (5, 10, 20)
TOUCH_DAYS, TOUCH_PCT = 20, 5.0
MIN_EVENTS, MIN_MONTHS = 200, 24
FEATURES = ("trend", "mom", "rsi", "high52", "vol")
LEVELS = [FEATURES[:k] for k in range(len(FEATURES), 0, -1)]       # full setup first, then coarser ones
LABELS = {
    "trend": ["above the 50- and 200-day averages", "above the 200-day, below the 50-day average",
              "below the 200-day, above the 50-day average", "below the 50- and 200-day averages"],
    "mom": ["weak 6-month momentum (bottom third)", "middling 6-month momentum", "strong 6-month momentum (top third)"],
    "rsi": ["RSI under 35 (oversold)", "RSI 35-65", "RSI over 65 (overbought)"],
    "high52": ["within 5% of the 52-week high", "5-15% below the 52-week high", "15-30% below the 52-week high",
               "more than 30% below the 52-week high"],
    "vol": ["quiet volume (under 0.8x average)", "normal volume", "heavy volume (1.5x average or more)"],
}
SHORT = {
    "trend": ["Uptrend", "Pullback in uptrend", "Recovery attempt", "Downtrend"],
    "mom": ["Weak momentum", "Mid momentum", "Strong momentum"],
    "rsi": ["Oversold", "RSI neutral", "Overbought"],
    "high52": ["Near 52w high", "5-15% off high", "15-30% off high", ">30% off high"],
    "vol": ["Quiet volume", "Normal volume", "Heavy volume"],
}


# --------------------------------------------------------------------------- features (no look-ahead)
def rsi14(close: pd.DataFrame | pd.Series) -> pd.DataFrame | pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    rs = gain / loss.where(loss != 0)
    return (100 - 100 / (1 + rs)).where(loss != 0, 100.0).where(gain.notna())


def _cut(x: pd.DataFrame, edges: list[float]) -> pd.DataFrame:
    """Codes 0..len(edges) by ascending edges; NaN stays NaN."""
    v = x.to_numpy(dtype=float)
    codes = np.searchsorted(np.asarray(edges, dtype=float), v, side="right").astype(float)
    codes[~np.isfinite(v)] = np.nan
    return pd.DataFrame(codes, index=x.index, columns=x.columns)


def features(frames: dict[str, pd.DataFrame], member: pd.DataFrame | None) -> dict[str, pd.DataFrame]:
    """Feature codes per (day, stock), each from data up to that day. `member`: who the momentum rank is taken
    among (that day's universe); None = every column."""
    c, h, v = frames["close"], frames["high"], frames["volume"]
    sma50 = c.rolling(50, min_periods=50).mean()
    sma200 = c.rolling(200, min_periods=200).mean()
    above50, above200 = c > sma50, c > sma200
    trend = pd.DataFrame(np.select([above50 & above200, above200 & ~above50, ~above200 & above50], [0, 1, 2], 3),
                         index=c.index, columns=c.columns).astype(float).where(sma200.notna() & c.notna())
    ret126 = c / c.shift(126) - 1
    ranked = ret126 if member is None else ret126.where(member.reindex_like(c).fillna(False).astype(bool))
    pct = ranked.rank(axis=1, pct=True)               # (0, 1]: the bottom third is pct <= 1/3
    mom = (np.ceil(pct * 3) - 1).clip(0, 2)
    rsi = _cut(rsi14(c), [35.0, 65.0])
    hi = h.rolling(252, min_periods=120).max()
    dist = (c / hi - 1) * 100
    high52 = 3 - _cut(dist, [-30.0, -15.0, -5.0])        # 0 = within 5% of the high ... 3 = more than 30% below
    avg = v.rolling(20, min_periods=20).mean().shift(1)
    vol = _cut(v / avg.where(avg > 0), [0.8, 1.5])
    return {"trend": trend, "mom": mom, "rsi": rsi, "high52": high52, "vol": vol}


def setup_now(frames: dict[str, pd.DataFrame], symbol: str, member: pd.DataFrame | None = None) -> dict | None:
    """The symbol's feature codes on the last bar (and the raw readings behind them)."""
    if symbol not in frames["close"].columns:
        return None
    f = features(frames, member)
    c = frames["close"][symbol].dropna()
    if c.empty:
        return None
    day = c.index[-1]
    codes = {}
    for k in FEATURES:
        x = f[k].at[day, symbol] if day in f[k].index else np.nan
        codes[k] = None if not np.isfinite(x) else int(x)
    return {"date": day.date().isoformat(), "codes": codes}


# --------------------------------------------------------------------------- outcomes
def outcomes(frames: dict[str, pd.DataFrame], member: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """ret_h / excess_h: next open to the close h days later (fractions); touch_up / touch_down: the next
    TOUCH_DAYS bars reached +/- TOUCH_PCT from the entry open (1.0 / 0.0)."""
    o, h, l = frames["open"], frames["high"], frames["low"]
    c = frames["close"].ffill(limit=20)                 # a stock that stops trading is valued at its last close
    entry = o.shift(-1).where(o.shift(-1) > 0)
    m = member.reindex_like(c).fillna(False).astype(bool)
    out = {}
    for n in HORIZONS:
        r = c.shift(-n) / entry - 1
        bench = r.where(m).mean(axis=1)
        out[f"ret_{n}"] = r
        out[f"excess_{n}"] = r.sub(bench, axis=0)
    hi = h[::-1].rolling(TOUCH_DAYS, min_periods=1).max()[::-1].shift(-1)
    lo = l[::-1].rolling(TOUCH_DAYS, min_periods=1).min()[::-1].shift(-1)
    full = c.shift(-TOUCH_DAYS).notna()                 # only events with a full window ahead
    out["touch_up"] = ((hi / entry - 1) * 100 >= TOUCH_PCT).astype(float).where(full & entry.notna())
    out["touch_down"] = ((lo / entry - 1) * 100 <= -TOUCH_PCT).astype(float).where(full & entry.notna())
    return out


def events(frames: dict[str, pd.DataFrame], member: pd.DataFrame, y: dict | None = None) -> pd.DataFrame:
    """One row per universe member-day with every feature known: codes, month, outcomes."""
    f = features(frames, member)
    y = y if y is not None else outcomes(frames, member)
    m = member.reindex_like(frames["close"]).fillna(False).astype(bool).to_numpy()
    ok = m.copy()
    for k in FEATURES:
        ok &= np.isfinite(f[k].to_numpy())
    rows, cols = np.nonzero(ok)
    dates = frames["close"].index
    ev = pd.DataFrame({k: f[k].to_numpy()[rows, cols].astype(np.int8) for k in FEATURES})
    ev["month"] = dates[rows].to_period("M").astype(str)
    for k, df in y.items():
        ev[k] = df.to_numpy()[rows, cols].astype(np.float32)
    return ev


# --------------------------------------------------------------------------- statistics
def _r(v, nd: int = 2):
    return None if v is None or not np.isfinite(v) else round(float(v), nd)


def _tstat(x: pd.Series, month: pd.Series) -> float | None:
    mm = x.groupby(month).mean()
    if len(mm) < 3:
        return None
    sd = mm.std(ddof=1)
    return float(mm.mean() / (sd / math.sqrt(len(mm)))) if sd > 0 else None


def group_stats(g: pd.DataFrame) -> dict:
    out = {"n": int(len(g)), "months": int(g["month"].nunique())}
    for n in HORIZONS:
        r = g[f"ret_{n}"].dropna() * 100
        x = g[f"excess_{n}"].dropna() * 100
        if r.empty:
            out[str(n)] = None
            continue
        q = r.quantile([0.1, 0.25, 0.5, 0.75, 0.9]).to_numpy()
        out[str(n)] = {
            "n": int(len(r)), "mean_pct": _r(r.mean()), "median_pct": _r(q[2]), "up_pct": _r((r > 0).mean() * 100, 1),
            "p10_pct": _r(q[0]), "p25_pct": _r(q[1]), "p75_pct": _r(q[3]), "p90_pct": _r(q[4]),
            "excess_pct": _r(x.mean()), "beat_pct": _r((x > 0).mean() * 100, 1),
            "t": _r(_tstat(x, g.loc[x.index, "month"])),
        }
    up, down = g["touch_up"].dropna(), g["touch_down"].dropna()
    out["touch"] = {"days": TOUCH_DAYS, "pct": TOUCH_PCT, "up_pct": _r(up.mean() * 100, 1) if len(up) else None,
                    "down_pct": _r(down.mean() * 100, 1) if len(down) else None}
    return out


def key_of(level: tuple[str, ...], codes: dict) -> str:
    return f"{len(level)}|" + ",".join(str(codes[k]) for k in level)


def summarise(ev: pd.DataFrame, first_day: str, last_day: str) -> dict:
    groups = {}
    for level in LEVELS:
        for vals, g in ev.groupby(list(level), sort=False):
            vals = vals if isinstance(vals, tuple) else (vals,)
            groups[key_of(level, dict(zip(level, (int(v) for v in vals))))] = group_stats(g)
    return {"version": VERSION, "generated_at": ist_now().isoformat(timespec="seconds"),
            "universe": "point-in-time top 500 (pit.py)", "first_day": first_day, "last_day": last_day,
            "events": int(len(ev)), "horizons": list(HORIZONS), "min_events": MIN_EVENTS, "min_months": MIN_MONTHS,
            "levels": [list(lv) for lv in LEVELS], "base": group_stats(ev), "groups": groups}


COST_PCT = 0.45                  # round trip, as in pattern_study.py


def event_stats(hit: pd.DataFrame, member: pd.DataFrame, y: dict, side: int) -> dict:
    """Pattern-study style statistics for boolean events (member-days only), signed by `side`."""
    m = member.reindex_like(hit).fillna(False).astype(bool).to_numpy() & hit.fillna(False).astype(bool).to_numpy()
    rows, cols = np.nonzero(m)
    month = pd.Series(hit.index[rows].to_period("M").astype(str))
    out = {"n": int(len(rows)), "months": int(month.nunique())}
    for n in HORIZONS:
        x = pd.Series(y[f"excess_{n}"].to_numpy()[rows, cols] * 100 * side)
        ok = x.notna()
        x, mo = x[ok], month[ok]
        if x.empty:
            out[str(n)] = None
            continue
        t = _tstat(x, mo)
        out[str(n)] = {"n": int(len(x)), "excess_pct": _r(x.mean()), "median_pct": _r(x.median()),
                       "hit_pct": _r((x > 0).mean() * 100, 1), "t": _r(t), "after_cost_pct": _r(x.mean() - COST_PCT)}
    s = out.get("10") or {}
    if out["n"] < MIN_EVENTS or out["months"] < MIN_MONTHS or not s:
        out["verdict"] = "too_few"
    elif (s.get("t") or 0) >= 2 and (s.get("after_cost_pct") or 0) > 0:
        out["verdict"] = "edge"
    elif (s.get("t") or 0) >= 2 and (s.get("excess_pct") or 0) > 0:
        out["verdict"] = "edge_before_costs"
    elif (s.get("t") or 0) <= -2:
        out["verdict"] = "opposite"
    else:
        out["verdict"] = "no_edge"
    out["primary"] = 10
    return out


def run(log=print) -> dict:
    from . import big_money, pit
    t0 = time.monotonic()
    data = pit.load()
    if data is None:
        raise RuntimeError("point-in-time universe not built: run 4_build_universe.bat first")
    keep = data.members
    frames = {f: data.frames[f][keep] for f in ("open", "high", "low", "close", "volume")}
    member = data.universe[keep]
    y = outcomes(frames, member)
    ev = events(frames, member, y)
    cal = frames["close"].index
    log(f"Outlook study: {len(ev):,} member-days of {len(keep)} stocks...")
    rep = summarise(ev, cal[0].date().isoformat(), cal[-1].date().isoformat())
    if "deliv_pct" in data.frames:           # does a delivery spike (big buyers taking shares) say anything?
        dl = big_money.delivery_frames(frames["close"], frames["volume"], data.frames["deliv_pct"][keep])
        rep["delivery"] = {"rule": f"delivery quantity >= {big_money.DELIV_SPIKE:g}x its 20-day average and >= "
                                   f"{big_money.DELIV_MIN_PCT:g}% of the volume delivered; up day = accumulation, "
                                   "down day = distribution (signed: distribution works when the stock lags)",
                           "accumulation": event_stats(dl["accumulation"], member, y, 1),
                           "distribution": event_stats(dl["distribution"], member, y, -1),
                           "cost_pct": COST_PCT}
    rep["elapsed_s"] = round(time.monotonic() - t0, 1)
    STUDY_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STUDY_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(rep, separators=(",", ":")), encoding="utf-8")
    tmp.replace(STUDY_FILE)
    log(f"Outlook study done in {rep['elapsed_s']} s ({len(rep['groups'])} setups).")
    return rep


def pit_last_day() -> str | None:
    """The last day of the current point-in-time build (its info.json only - no price arrays)."""
    from . import pit
    try:
        folder = pit.PIT_DIR / (pit.PIT_DIR / "CURRENT").read_text(encoding="utf-8").strip()
        return json.loads((folder / "info.json").read_text(encoding="utf-8")).get("last_day")
    except (OSError, ValueError):
        return None


def refresh_if_stale(log=print) -> bool:
    """Re-run the study when the point-in-time universe has a newer day than it (about once a day)."""
    last = pit_last_day()
    if last is None:
        return False
    rep = load()
    if rep is not None and str(rep.get("last_day")) >= str(last):
        return False
    run(log=log)
    return True


def load() -> dict | None:
    try:
        rep = json.loads(STUDY_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return rep if rep.get("version") == VERSION else None


# --------------------------------------------------------------------------- lookup
def match(study: dict, codes: dict) -> dict | None:
    """The finest setup with enough cases for these codes: {level, key, stats, dropped}."""
    for level in LEVELS:
        if any(codes.get(k) is None for k in level):
            continue
        s = study["groups"].get(key_of(level, codes))
        if s and s["n"] >= study.get("min_events", MIN_EVENTS) and s["months"] >= study.get("min_months", MIN_MONTHS):
            return {"level": list(level), "stats": s, "dropped": [k for k in FEATURES if k not in level]}
    return None


def verdict(stats: dict, horizon: int) -> str:
    """'better' / 'worse' when the setup's excess over the average stock is beyond luck (|t| >= 2), else 'same'."""
    s = stats.get(str(horizon)) or {}
    t, x = s.get("t"), s.get("excess_pct")
    if t is None or x is None:
        return "unknown"
    if t >= 2 and x > 0:
        return "better"
    if t <= -2 and x < 0:
        return "worse"
    return "same"


def own_history(df: pd.DataFrame, codes: dict, level: list[str]) -> dict | None:
    """The same setup in this stock's own past (daily bars of the main store): few cases, so only a footnote."""
    frames = {f: df[[f]].rename(columns={f: "x"}) for f in ("open", "high", "low", "close", "volume")}
    f = features(frames, None)
    mask = pd.Series(True, index=df.index)
    for k in level:
        if k == "mom":                  # a rank needs other stocks: not checked on one stock's own history
            continue
        mask &= f[k]["x"] == codes[k]
    mask.iloc[-1] = False               # today itself has no outcome yet
    c, o = df["close"], df["open"]
    entry = o.shift(-1).where(o.shift(-1) > 0)
    out = {"n": int(mask.sum())}
    for n in HORIZONS:
        r = ((c.shift(-n) / entry - 1) * 100)[mask].dropna()
        out[str(n)] = None if r.empty else {"n": int(len(r)), "median_pct": _r(r.median()),
                                           "up_pct": _r((r > 0).mean() * 100, 1)}
    return out


def describe(codes: dict) -> list[dict]:
    return [{"feature": k, "code": codes[k], "label": LABELS[k][codes[k]], "short": SHORT[k][codes[k]]}
            for k in FEATURES if codes.get(k) is not None]


if __name__ == "__main__":
    r = run(log=lambda m: print(m, flush=True))
    b = r["base"]["20"]
    print(f"All member-days, 20 days later: median {b['median_pct']}%, up {b['up_pct']}%, "
          f"p10 {b['p10_pct']}% .. p90 {b['p90_pct']}%")
