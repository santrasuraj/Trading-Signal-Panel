"""Outlook for one symbol: setup, base rates of similar setups, expected ranges, levels, signals, derivatives.

Files only (price store, latest.json, data/results/outlook_study.json, levels, stored option chains and F&O
bhavcopy). Every number is either measured on the past or read from NSE's own data - none is a forecast.
"""
from __future__ import annotations

import json
import math
import threading

import numpy as np
import pandas as pd

from scanner import big_money as bm
from scanner import option_verdict as ov
from scanner import outlook as ol

from ..caches import FileCache, KeyedCache, file_key, register
from ..paths import P
from ..util import num, today_ist
from . import chart_data, data, levels_svc, strategies as st

NOTE = ("Base rates, not a forecast: nobody knows the next move. 'Similar setups' are every day since 2018 on which a "
        "stock of that day's 500 most-traded NSE stocks (including the ones that later collapsed) looked like this "
        "one does now; the numbers are what happened next, measured from the next day's open. A setup that did "
        "'better' than the average stock did so before costs and over many cases - any single stock can do anything. "
        "This app's own tests found no candle or chart pattern that beat the average stock after costs.")
COST_PCT = 0.45                   # round trip, as in pattern_study.py
OPTION_NAMES = {"NIFTY50": "NIFTY"}
INDEX_OPTIONS = {"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50"}
MAX_LEVELS = 6
MERGE_PCT = 0.4                   # levels closer than this (in % of price) are shown once

_study = register(FileCache(lambda p: json.loads(p.read_text(encoding="utf-8")), missing=None))
_fno_list = register(FileCache(lambda p: set(json.loads(p.read_text(encoding="utf-8"))), missing=set()))
_feat = register(KeyedCache(2))
_out = register(KeyedCache(32))


def study() -> dict | None:
    s = _study.get(P.results / ol.STUDY_FILE.name)
    return s if s and s.get("version") == ol.VERSION else None


def _features() -> dict:
    """Feature codes for every stored symbol on every day, momentum ranked among today's universe."""
    def compute() -> dict:
        frames = data.store()
        cols = frames["close"].columns
        uni = set(data.universe()["symbol"])
        member = pd.DataFrame(np.broadcast_to(cols.isin(list(uni)), frames["close"].shape),
                              index=frames["close"].index, columns=cols)
        f = ol.features({k: frames[k] for k in ("open", "high", "low", "close", "volume")}, member)
        ret126 = frames["close"] / frames["close"].shift(126) - 1
        return {"f": f, "ret126": ret126, "uni": [c for c in cols if c in uni]}
    return _feat.get(data.store_version(), compute)


def _codes(sym: str, day: pd.Timestamp) -> dict:
    fx = _features()
    codes = {}
    for k in ol.FEATURES:
        df = fx["f"][k]
        v = df.at[day, sym] if sym in df.columns and day in df.index else np.nan
        codes[k] = int(v) if np.isfinite(v) else None
    if codes["mom"] is None and sym in fx["ret126"].columns:   # not a universe member: rank it against them
        row = fx["ret126"].loc[day, fx["uni"]].dropna()
        mine = fx["ret126"].at[day, sym]
        if np.isfinite(mine) and len(row) > 50:
            p = float((row < mine).mean())
            codes["mom"] = 0 if p < 1 / 3 else 1 if p < 2 / 3 else 2
    return codes


def _pct_move(close: float | None, pct: float | None) -> float | None:
    return num(close * (1 + pct / 100), 2) if close is not None and pct is not None else None


def _dist(h: dict | None) -> dict | None:
    if not h:
        return None
    return {k: h.get(k) for k in ("n", "mean_pct", "median_pct", "up_pct", "p10_pct", "p25_pct", "p75_pct", "p90_pct",
                                  "excess_pct", "beat_pct", "t")}


def _analogs(stu: dict, codes: dict, daily: pd.DataFrame, close: float | None) -> dict | None:
    m = ol.match(stu, codes)
    if m is None:
        return None
    s, base = m["stats"], stu["base"]
    own = ol.own_history(daily, codes, m["level"])
    rows = []
    for n in ol.HORIZONS:
        h = s.get(str(n)) or {}
        o = (own or {}).get(str(n)) or {}
        x = h.get("excess_pct")
        rows.append({
            "days": n, "setup": _dist(h), "base": _dist(base.get(str(n))), "verdict": ol.verdict(s, n),
            "after_cost_excess_pct": num(x - COST_PCT, 2) if x is not None else None,
            "price_p10": _pct_move(close, h.get("p10_pct")), "price_p25": _pct_move(close, h.get("p25_pct")),
            "price_median": _pct_move(close, h.get("median_pct")), "price_p75": _pct_move(close, h.get("p75_pct")),
            "price_p90": _pct_move(close, h.get("p90_pct")),
            "own_n": o.get("n"), "own_median_pct": o.get("median_pct"), "own_up_pct": o.get("up_pct"),
        })
    return {"level": m["level"], "dropped": m["dropped"], "n": s["n"], "months": s["months"],
            "first_day": stu.get("first_day"), "last_day": stu.get("last_day"), "universe": stu.get("universe", ""),
            "horizons": rows, "touch": s["touch"], "base_touch": base["touch"], "cost_pct": COST_PCT,
            "generated_at": stu.get("generated_at")}


def _headline(setup: list[dict], an: dict | None, kind: str) -> str:
    what = " · ".join(f["short"] for f in setup) or "Not enough history to describe the setup"
    if an is None:
        return what + "."
    h = next((r for r in an["horizons"] if r["days"] == 20), an["horizons"][-1])
    s = h["setup"] or {}
    word = {"better": "better than the average stock", "worse": "worse than the average stock",
            "same": "no different from the average stock (within luck)", "unknown": "not measurable"}[h["verdict"]]
    med, up, exc = s.get("median_pct") or 0.0, s.get("up_pct") or 0.0, s.get("excess_pct")
    vs = f", {exc:+.1f}% vs it before costs" if h["verdict"] in ("better", "worse") and exc is not None else ""
    out = (f"{what}. In {an['n']:,} similar cases, {h['days']} trading days later the median move was "
           f"{med:+.1f}% and {up:.0f}% ended higher - {word}{vs}.")
    if kind != "stock":
        out += " (Measured on stocks; an index or ETF moves less.)"
    return out


def _realized_vol(daily: pd.DataFrame) -> float | None:
    r = np.log(daily["close"]).diff().iloc[-20:]
    v = r.std(ddof=1)
    return float(v * math.sqrt(252) * 100) if np.isfinite(v) and len(r.dropna()) >= 15 else None


def _ranges(close: float | None, rv: float | None, chain: dict | None, an: dict | None) -> list[dict]:
    out = []
    if close is None:
        return out
    for n in (1, 5, 20):
        if chain and chain.get("atm_iv_pct"):
            w = chain["atm_iv_pct"] / 100 * math.sqrt(n / 252) * 100
            out.append({"source": "options", "label": f"Options-implied, {n} day{'s' if n > 1 else ''} (1 SD)", "days": n,
                        "low": num(close * (1 - w / 100), 2), "high": num(close * (1 + w / 100), 2), "pct": num(w, 2),
                        "prob_pct": 68.0})
        if rv:
            w = rv / 100 * math.sqrt(n / 252) * 100
            out.append({"source": "realized", "label": f"Recent volatility, {n} day{'s' if n > 1 else ''} (1 SD)", "days": n,
                        "low": num(close * (1 - w / 100), 2), "high": num(close * (1 + w / 100), 2), "pct": num(w, 2),
                        "prob_pct": 68.0})
    for h in (an or {}).get("horizons") or []:
        s = h["setup"] or {}
        if s.get("p10_pct") is not None:
            out.append({"source": "analogs", "label": f"Similar setups, {h['days']} days (10th-90th percentile)",
                        "days": h["days"], "low": h["price_p10"], "high": h["price_p90"],
                        "pct": num((s["p90_pct"] - s["p10_pct"]) / 2, 2), "prob_pct": 80.0})
    return out


def _merge(levels: list[dict], close: float, above: bool) -> list[dict]:
    pts = sorted((x for x in levels if x["price"] is not None and (x["price"] > close if above else x["price"] < close)),
                 key=lambda x: x["price"], reverse=not above)
    out: list[dict] = []
    for x in pts:
        if out and abs(x["price"] / out[-1]["price"] - 1) * 100 < MERGE_PCT:
            out[-1]["label"] += f" · {x['label']}"
            out[-1]["strength"] = max(out[-1]["strength"] or 0, x["strength"] or 0) or None
            continue
        out.append({**x, "dist_pct": num((x["price"] / close - 1) * 100, 2)})
    return out[:MAX_LEVELS]


def _scenarios(d: dict | None, close: float | None, chain: dict | None) -> dict:
    if not d or close is None:
        return {"above": [], "below": [], "flips": []}
    lv = []
    for x in d["levels"]["resistance"]:
        lv.append({"price": x["price"], "label": "Resistance (swing highs)", "kind": "resistance", "strength": x["touches"]})
    for x in d["levels"]["support"]:
        lv.append({"price": x["price"], "label": "Support (swing lows)", "kind": "support", "strength": x["touches"]})
    pv = d["pivots"]
    for k in ("r1", "r2", "s1", "s2", "p"):
        lv.append({"price": pv.get(k), "label": f"Pivot {k.upper()}" if k != "p" else "Pivot", "kind": "pivot", "strength": None})
    t = d["trend"]
    for k, lab in (("sma50", "50-day average"), ("sma200", "200-day average")):
        lv.append({"price": t.get(k), "label": lab, "kind": "sma", "strength": None})
    lv.append({"price": d.get("high_52w"), "label": "52-week high", "kind": "high_52w", "strength": None})
    lv.append({"price": d.get("low_52w"), "label": "52-week low", "kind": "low_52w", "strength": None})
    for p in d.get("chart_patterns") or []:
        if p["status"] == "forming" and p.get("breakout") is not None:
            lv.append({"price": p["breakout"], "label": f"{p['name']} breakout", "kind": "pattern", "strength": None})
        if p.get("invalidation") is not None:
            lv.append({"price": p["invalidation"], "label": f"{p['name']} void beyond", "kind": "pattern", "strength": None})
    if chain:
        if chain.get("call_wall"):
            lv.append({"price": chain["call_wall"], "label": "Call wall (most call OI)", "kind": "option", "strength": None})
        if chain.get("put_wall"):
            lv.append({"price": chain["put_wall"], "label": "Put wall (most put OI)", "kind": "option", "strength": None})
        if chain.get("max_pain"):
            lv.append({"price": chain["max_pain"], "label": "Max pain", "kind": "option", "strength": None})
    flips = []
    if t.get("sma50") is not None:
        flips.append(f"A close {'below' if close > t['sma50'] else 'above'} the 50-day average ({t['sma50']:,.2f}) "
                     f"turns the short-term trend {'down' if close > t['sma50'] else 'up'}.")
    if t.get("sma200") is not None:
        flips.append(f"A close {'below' if close > t['sma200'] else 'above'} the 200-day average ({t['sma200']:,.2f}) "
                     f"changes the long-term trend; most momentum strategies here only buy above it.")
    if t.get("supertrend") is not None and t.get("supertrend_dir"):
        flips.append(f"Supertrend (10, 3) is {t['supertrend_dir']}; it flips on a close "
                     f"{'below' if t['supertrend_dir'] == 'up' else 'above'} {t['supertrend']:,.2f}.")
    return {"above": _merge(lv, close, True), "below": _merge(lv, close, False), "flips": flips}


VERDICT_TEXT = {"edge": ("tested: edge after costs", "good"), "edge_before_costs": ("tested: edge before costs only", "neutral"),
                "no_edge": ("tested: no edge", "neutral"), "opposite": ("tested: worked in reverse", "bad"),
                "no_direction": ("tested: no direction", "neutral"), "too_few": ("too few cases to test", None)}


def _signals(sym: str, lt: dict, d: dict | None, daily: pd.DataFrame, chain: dict | None, fut: dict | None) -> list[dict]:
    out: list[dict] = []
    last = daily.index[-1].date().isoformat()
    for s in st.all_strategies(lt) if lt else []:
        if s["lifecycle"] != "active":
            continue
        full = ((s.get("metrics") or {}).get("full") or {})
        cagr = full.get("cagr_pct")
        tested = f"strategy {s['status']}" + (f", backtest {cagr:+.1f}%/yr" if isinstance(cagr, (int, float)) else "")
        tone = "good" if s["status"] == "working" else "bad" if s["status"] == "not-working" else "neutral"
        for a in s.get("actions") or []:
            if a.get("symbol") == sym:
                buy = a.get("action") == "BUY"
                stop = f"; stop {a['stop']:,.2f}" if isinstance(a.get("stop"), (int, float)) else ""
                # a long-only strategy's SELL closes its own position: an exit, not a bearish forecast
                out.append({"source": "strategy", "bias": "bullish" if buy else "neutral",
                            "title": f"{s.get('name')}: {'BUY' if buy else 'exits'} at the next open",
                            "detail": f"{a.get('reason') or ''}{stop}".strip("; "), "tested": tested, "tone": tone, "when": last})
        for p in s.get("positions") or []:
            if p.get("symbol") == sym:
                ret = p.get("ret_pct")
                out.append({"source": "strategy", "bias": "bullish", "title": f"Held by {s.get('name')}",
                            "detail": f"since {p.get('entry_date')}" + (f" ({ret:+.1f}%)" if isinstance(ret, (int, float)) else "")
                            + (f"; model stop {p['stop']:,.2f}" if isinstance(p.get("stop"), (int, float)) else ""),
                            "tested": tested, "tone": tone, "when": str(p.get("entry_date") or "") or None})
        busy = any(p.get("symbol") == sym for p in (s.get("positions") or []) + (s.get("actions") or []))
        for r in s.get("ranking") or []:
            if not busy and r.get("symbol") == sym and int(r.get("rank") or 999) <= 30:
                out.append({"source": "strategy", "bias": "neutral", "title": f"Ranked #{r.get('rank')} by {s.get('name')}",
                            "detail": "in the strategy's ranking, not (yet) bought", "tested": tested, "tone": tone, "when": last})
    for p in (d or {}).get("patterns") or []:
        ev = (p.get("evidence") or {}).get("verdict")
        txt, tone = VERDICT_TEXT.get(ev, ("untested", None))
        # a pattern counts as bullish / bearish only when its own test found an edge after costs
        out.append({"source": "pattern", "bias": p["bias"] if ev == "edge" else "neutral", "title": p["name"],
                    "detail": f"{p['what']} ({_ago(p['bars_ago'])})",
                    "tested": txt, "tone": tone, "when": str(p["at"])[:10]})
    for p in (d or {}).get("chart_patterns") or []:
        ev = (p.get("evidence") or {}).get("verdict")
        txt, tone = VERDICT_TEXT.get(ev, ("untested", None))
        state = f"confirmed {p.get('direction') or ''}".strip() if p["status"] == "confirmed" else "forming"
        lvl = f"breakout {p['breakout']:,.2f}" if p.get("breakout") is not None else ""
        out.append({"source": "chart_pattern", "bias": p["bias"] if ev == "edge" else "neutral", "title": f"{p['name']} ({state})",
                    "detail": f"{lvl}{'; void beyond ' + format(p['invalidation'], ',.2f') if p.get('invalidation') is not None else ''}",
                    "tested": txt, "tone": tone, "when": p.get("end")})
    out += _trend_events(daily)
    if chain:
        for line in chain.get("readings") or []:
            out.append({"source": "options", "bias": "neutral", "title": "Option positioning", "detail": line,
                        "tested": "not tested (positioning, not a signal)", "tone": None, "when": str(chain["time"])[:10]})
    if fut and fut.get("buildup"):
        label = str(fut["buildup"]).replace("_", " ")
        # positioning, never tested as a signal here: shown, but it never votes bullish or bearish
        out.append({"source": "futures", "bias": "neutral", "title": f"Futures: {label}",
                    "detail": f"price {fut.get('chg_pct') or 0:+.1f}%, open interest {fut.get('oi_chg_pct') or 0:+.1f}%",
                    "tested": "not tested (positioning, not a signal)", "tone": None, "when": fut.get("date")})
    sig = data.intraday_signals() or {}
    for x in sig.get("signals") or []:
        if str(x.get("symbol", "")).upper() == sym:
            out.append({"source": "intraday", "bias": "bullish" if str(x.get("side", "")).upper() == "BUY" else "bearish",
                        "title": f"Intraday: {x.get('strategy') or x.get('name') or 'signal'} {x.get('side') or ''}".strip(),
                        "detail": str(x.get("reason") or x.get("detail") or ""), "tested": "proven intraday strategy",
                        "tone": "good", "when": str(x.get("time") or x.get("at") or "")[:10] or None})
    return out


def _ago(n: int) -> str:
    return "last bar" if n == 0 else f"{n} bar{'s' if n > 1 else ''} ago"


def _trend_events(daily: pd.DataFrame) -> list[dict]:
    """Recent moving-average crosses, a new 52-week high / low and a volume spike on the last bars."""
    c, v = daily["close"], daily["volume"]
    out = []
    if len(c) < 210:
        return out
    last = daily.index[-1]
    for n in (50, 200):
        sma = c.rolling(n, min_periods=n).mean()
        above = c > sma
        flips = above.ne(above.shift(1)) & sma.notna() & sma.shift(1).notna()
        recent = flips.iloc[-5:]
        if recent.any():
            day = recent[recent].index[-1]
            up = bool(above.loc[day])
            out.append({"source": "trend", "bias": "bullish" if up else "bearish",
                        "title": f"Crossed {'above' if up else 'below'} the {n}-day average",
                        "detail": f"close {c.loc[day]:,.2f} vs average {sma.loc[day]:,.2f}", "tested": None, "tone": None,
                        "when": day.date().isoformat()})
    hi = daily["high"].rolling(252, min_periods=120).max().shift(1)
    lo = daily["low"].rolling(252, min_periods=120).min().shift(1)
    if np.isfinite(hi.iloc[-1]) and c.iloc[-1] > hi.iloc[-1]:
        out.append({"source": "trend", "bias": "bullish", "title": "New 52-week high",
                    "detail": f"close {c.iloc[-1]:,.2f} above the previous high {hi.iloc[-1]:,.2f}", "tested": None,
                    "tone": None, "when": last.date().isoformat()})
    if np.isfinite(lo.iloc[-1]) and c.iloc[-1] < lo.iloc[-1]:
        out.append({"source": "trend", "bias": "bearish", "title": "New 52-week low",
                    "detail": f"close {c.iloc[-1]:,.2f} below the previous low {lo.iloc[-1]:,.2f}", "tested": None,
                    "tone": None, "when": last.date().isoformat()})
    avg = v.rolling(20, min_periods=20).mean().shift(1)
    ratio = v.iloc[-1] / avg.iloc[-1] if np.isfinite(avg.iloc[-1]) and avg.iloc[-1] > 0 else None
    if ratio and ratio >= 2:
        up = c.iloc[-1] >= c.iloc[-2]
        out.append({"source": "volume", "bias": "bullish" if up else "bearish",
                    "title": f"Volume {ratio:.1f}x the 20-day average", "detail": f"on a {'up' if up else 'down'} day",
                    "tested": None, "tone": None, "when": last.date().isoformat()})
    return out


def option_symbol(sym: str) -> str | None:
    s = OPTION_NAMES.get(sym, sym)
    if s in INDEX_OPTIONS or s in _fno_list.get(P.data / "intraday" / "fno.json"):
        return s
    return None


def _chain(osym: str | None, last_day: str) -> tuple[dict | None, dict | None]:
    """The nearest stored chain; `old` when it was stored before the chart's last bar (its levels are then stale)."""
    if not osym:
        return None, None
    from . import options_svc
    try:
        c = options_svc.chain(osym, None, 15)
    except Exception:            # no stored chain (or it expired): the panel offers a refresh
        return None, None
    lv = c.get("levels") or {}
    sm = c.get("summary") or {}
    top = lambda xs: xs[0]["strike"] if xs else None      # noqa: E731
    return {"symbol": c["symbol"], "expiry": str(c["expiry"]), "time": str(c["time"]), "stale": bool(c.get("stale")),
            "day": str(c["time"])[:10], "old": str(c["time"])[:10] < last_day,
            "spot": c.get("spot"), "forward": c.get("forward"), "days_to_expiry": c.get("days_to_expiry"),
            "pcr_oi": sm.get("pcr_oi"), "max_pain": sm.get("max_pain"), "max_pain_gap_pct": sm.get("max_pain_gap_pct"),
            "atm_iv_pct": sm.get("atm_iv_pct"), "expected_move_pct": sm.get("expected_move_pct"),
            "range_low": sm.get("range_low"), "range_high": sm.get("range_high"),
            "call_wall": top(lv.get("resistance") or []), "put_wall": top(lv.get("support") or []),
            "readings": [str(x) for x in c.get("readings") or []]}, c


def _futures(osym: str | None) -> dict | None:
    if not osym:
        return None
    try:
        from scanner import fno
        from . import fno_svc
        d, rows = fno.day_futures(fno_svc._futures())
        rows = rows[rows["symbol"] == osym]
        if d is None or rows.empty:
            return None
        r = rows.iloc[0]
        return {"date": d.isoformat(), "close": num(r.get("close"), 2), "chg_pct": num(r.get("chg_pct"), 2),
                "oi_chg_pct": num(r.get("oi_chg_pct"), 2), "basis_pct": num(r.get("basis_pct"), 2),
                "buildup": r["buildup"] if isinstance(r.get("buildup"), str) else None, "pcr": num(r.get("pcr"), 2),
                "call_wall": num(r.get("call_wall"), 2), "put_wall": num(r.get("put_wall"), 2)}
    except Exception:            # no F&O bhavcopy fetched yet
        return None


def _events(sym: str, lt: dict, chain: dict | None) -> list[dict]:
    out = []
    from . import results
    try:
        for e in results.events(lt, days=45)["events"]:
            if e["symbol"] == sym:
                out.append({"date": e["date"], "kind": "results", "label": "Quarterly results"})
    except Exception:
        pass
    if chain:
        out.append({"date": chain["expiry"], "kind": "expiry", "label": f"{chain['symbol']} options expiry"})
    today = today_ist().isoformat()
    for ca in data.store_meta().get("corporate_actions") or []:
        if ca.get("symbol") == sym and str(ca.get("date", "")) >= (pd.Timestamp(today) - pd.Timedelta(days=30)).date().isoformat():
            out.append({"date": str(ca["date"])[:10], "kind": "corporate_action",
                        "label": f"{ca.get('reason') or 'Corporate action'} (x{num(ca.get('factor'), 4)})"})
    return sorted(out, key=lambda e: e["date"])


BM = P.data / "smart_money" / "big_money"
BM_NOTE = ("NSE's public disclosures only - there is no legal secret data: trading on unpublished price-sensitive "
           "information is insider trading (SEBI PIT Regulations). Filings arrive days after the trade, big buyers "
           "also lose money, and nothing here is a prediction. Each filing links to NSE.")
SAST_DAYS = 365


def _verdict(full: dict, daily: pd.DataFrame, stu: dict | None, codes: dict, lt: dict, sym: str, last_day: str,
             results_on: str | None, scen: dict) -> dict:
    m = ol.match(stu, codes) if stu else None
    sup = next((x["price"] for x in scen["below"] if x["kind"] in ("support", "sma", "low_52w")), None)
    res = next((x["price"] for x in scen["above"] if x["kind"] in ("resistance", "sma", "high_52w")), None)
    v = ov.assess(full, daily["close"], m, st.all_strategies(lt) if lt else [], sym, last_day=last_day,
                  results_on=results_on, support=sup, resistance=res)
    closes = data.store_close()
    rows = ov.score(_read(P.results / ov.JOURNAL_FILE.name, []), {c: closes[c] for c in closes.columns})
    return {**v, "track": ov.track(rows)}


def _read(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _tested(s: dict | None) -> dict | None:
    if not s:
        return None
    h = s.get(str(s.get("primary", 10))) or {}
    return {"n": s["n"], "months": s["months"], "verdict": s["verdict"], "excess_pct": h.get("excess_pct"),
            "hit_pct": h.get("hit_pct"), "t": h.get("t"), "after_cost_pct": h.get("after_cost_pct")}


def _clean(v):
    if isinstance(v, float) and not np.isfinite(v):
        return None
    if v is pd.NaT or (not isinstance(v, (str, bool, int, float)) and v is not None and pd.isna(v)):
        return None
    return v


def _big_money(sym: str, stu: dict | None) -> dict:
    pledges = _read(BM / "pledge.json", {})
    try:
        sast = pd.read_parquet(BM / "sast.parquet")
    except Exception:            # never fetched yet
        sast = bm.parse_sast([])
    since = (pd.Timestamp(today_ist()) - pd.Timedelta(days=SAST_DAYS)).date().isoformat()
    mine = sast[(sast["symbol"] == sym) & (sast["filed"].astype(str) >= since)].sort_values("filed", ascending=False)
    keep = ("filed", "period", "acquirer", "side", "mode", "security", "promoter", "regulation", "shares", "pct",
            "after_pct", "link")
    filings = []
    for r in mine.head(30).to_dict("records"):
        f = {k: _clean(r.get(k)) for k in keep}
        f["promoter"] = bool(f.get("promoter"))
        f["acquirer"] = str(f.get("acquirer") or "")
        f["side"] = "SELL" if f.get("side") == "SELL" else "BUY"
        filings.append(f)
    note = f"Latest 30 of {len(mine)} filings in the last year." if len(mine) > 30 else None
    ban = _read(BM / "fo_ban.json", None)
    frames = data.store()
    delivery = None
    if "deliv_pct" in frames and sym in frames["deliv_pct"].columns:
        df = pd.DataFrame({k: frames[k][sym] for k in ("close", "volume", "deliv_pct")}).dropna(subset=["close"])
        delivery = bm.delivery_now(df)
        if delivery:
            dl = (stu or {}).get("delivery") or {}
            delivery.update(tested_accumulation=_tested(dl.get("accumulation")),
                            tested_distribution=_tested(dl.get("distribution")), rule=dl.get("rule"))
    last = _read(BM / "last_refresh.json", {}) or {}
    return {"pledge": pledges.get(sym), "pledge_checked": sym in pledges, "filings": filings, "filings_note": note,
            "ban": {"trade_date": ban.get("trade_date"), "in_ban": sym in (ban.get("symbols") or []),
                    "symbols": ban.get("symbols") or [], "source": ban.get("source") or bm.BAN_URL} if ban else None,
            "delivery": delivery, "refreshed_at": last.get("refreshed_at"),
            "refreshing": _bm_running(), "note": BM_NOTE}


TESTED_WORD = {"edge": ("tested: edge after costs", "good"), "edge_before_costs": ("tested: edge before costs only", "neutral"),
               "no_edge": ("tested: no edge", "neutral"), "opposite": ("tested: worked in reverse", "bad"),
               "too_few": ("too few cases to test", None)}


def _bm_signals(b: dict) -> list[dict]:
    out = []
    for f in b["filings"][:5]:
        who = "Promoter" if f["promoter"] else "Large holder"
        did = "bought" if f["side"] == "BUY" else "sold"
        out.append({"source": "event", "bias": "bullish" if f["side"] == "BUY" else "bearish",
                    "title": f"{who} {did} {f.get('pct') or 0:.2f}% ({f['acquirer'][:40]})",
                    "detail": f"holds {f.get('after_pct') or 0:.2f}% after; {f.get('mode') or 'mode not stated'} (SEBI SAST filing)",
                    "tested": "not tested (one year of filings)", "tone": None, "when": str(f.get("filed") or "")[:10] or None})
    p = b.get("pledge") or {}
    if (p.get("promoter_pledged_pct") or 0) >= 10:
        out.append({"source": "event", "bias": "bearish",
                    "title": f"Promoters pledged {p['promoter_pledged_pct']:.1f}% of their shares",
                    "detail": f"{p.get('promoter_pledged_total_pct') or 0:.2f}% of the company, quarter {p.get('quarter')}: "
                              "a price fall can force lenders to sell",
                    "tested": "not tested (risk flag)", "tone": None, "when": p.get("quarter")})
    if b.get("ban") and b["ban"]["in_ban"]:
        out.append({"source": "event", "bias": "neutral", "title": "In the F&O ban period",
                    "detail": f"open interest above 95% of the market-wide limit ({b['ban']['trade_date']}): no new F&O positions",
                    "tested": None, "tone": None, "when": b["ban"]["trade_date"]})
    d = b.get("delivery") or {}
    for e in (d.get("events") or [])[:2]:
        t = d.get("tested_accumulation" if e["kind"] == "accumulation" else "tested_distribution") or {}
        word, tone = TESTED_WORD.get(t.get("verdict"), ("untested", None))
        out.append({"source": "volume", "bias": "bullish" if e["kind"] == "accumulation" else "bearish",
                    "title": f"Delivery spike: {e['kind']} ({e.get('ratio') or 0:.1f}x usual delivery, {e.get('deliv_pct') or 0:.0f}% delivered)",
                    "detail": f"on a {e.get('chg_pct') or 0:+.1f}% day", "tested": word, "tone": tone, "when": e["date"]})
    return out


_bm_lock = threading.Lock()
_bm_run: dict = {"thread": None, "symbol": None, "message": None}


def _bm_running() -> bool:
    return _bm_run["thread"] is not None and _bm_run["thread"].is_alive()


def start_big_money(symbol: str) -> dict:
    """POST: fetch this symbol's pledge data, the acquisition filings and the F&O ban list from NSE (background)."""
    sym = symbol.strip().upper()
    with _bm_lock:
        if not _bm_running():
            def work():
                try:
                    bm.refresh([sym], log=lambda m: _bm_run.update(message=str(m)[:200]))
                    _bm_run["message"] = "done"
                except Exception as e:      # refresh never raises for network problems; anything else ends here
                    _bm_run["message"] = f"{type(e).__name__}: {e}"[:200]
            t = threading.Thread(target=work, name="big-money-refresh", daemon=True)
            _bm_run.update(thread=t, symbol=sym, message="starting")
            t.start()
    return {"accepted": True, "running": True, "symbol": sym}


def outlook_for(symbol: str) -> dict:
    sym = symbol.strip().upper()
    daily = chart_data.bars_frame(sym)                    # NOT_FOUND when the store has no such symbol
    lt = data.latest() or {}
    osym = option_symbol(sym)
    key = (sym, data.store_version(), len(daily), float(daily["close"].iloc[-1]), file_key(P.latest),
           file_key(P.results / ol.STUDY_FILE.name), file_key(P.options / "latest.json"), file_key(P.fno / "futures.parquet"),
           file_key(P.intraday_signals), today_ist().isoformat(), file_key(BM / "sast.parquet"),
           file_key(BM / "pledge.json"), file_key(BM / "fo_ban.json"), file_key(P.results / ov.JOURNAL_FILE.name),
           _bm_running())

    def compute() -> dict:
        day = daily.index[-1]
        close = num(daily["close"].iloc[-1], 2)
        kind = data.symbol_kind(sym)
        codes = _codes(sym, day)
        setup = ol.describe(codes)
        stu = study()
        an = _analogs(stu, codes, daily, close) if stu else None
        hint = None
        if stu is None:
            hint = "The outlook study has not run yet: the next scan runs it (or python -m scanner.outlook, ~1 minute)."
        elif an is None:
            hint = "Not enough history to place this symbol in a setup (it needs about 200 trading days)."
        lv = levels_svc.levels_for(sym).get("daily")
        chain, full = _chain(osym, day.date().isoformat())
        fresh = chain if chain and not chain["old"] else None      # an old chain's walls / IV describe another day
        fut = _futures(osym)
        rv = _realized_vol(daily)
        live = bool(lt.get("live")) and str(lt.get("data_date")) == day.date().isoformat()
        scen = _scenarios(lv, close, fresh)
        events = _events(sym, lt, chain)
        results_on = next((e["date"] for e in events if e["kind"] == "results"), None)
        verdict = _verdict(full, daily, stu, codes, lt, sym, day.date().isoformat(), results_on, scen) if full else None
        big = _big_money(sym, stu)
        signals = _signals(sym, lt, lv, daily, fresh, fut) + _bm_signals(big)
        return {
            "symbol": sym, "kind": kind, "date": day.date().isoformat(), "close": close,
            "provisional": live and str(lt.get("complete_upto") or "") < day.date().isoformat(),
            "setup": setup, "headline": _headline(setup, an, kind), "analogs": an, "study_hint": hint,
            "expected": {"close": close, "atr": (lv or {}).get("atr"), "atr_pct": (lv or {}).get("atr_pct"),
                         "realized_vol_pct": num(rv, 1), "iv_pct": (fresh or {}).get("atm_iv_pct"),
                         "iv_expiry": (fresh or {}).get("expiry"), "ranges": _ranges(close, rv, fresh, an)},
            "scenarios": scen, "signals": signals,
            "derivatives": {"fno": osym is not None, "options_symbol": osym, "chain": chain, "futures": fut,
                            "verdict": verdict},
            "big_money": big, "events": events, "note": NOTE,
        }

    return _out.get(key, compute)
