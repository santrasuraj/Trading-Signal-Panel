"""latest.json -> contract shapes: AsOf, metrics, strategy summaries, rules, positions, rankings, trades.

Normalisation rules (docs/ui_spec_review.md A2-A5, B13):
- windows '12m'/'6m'/'3m' -> m12/m6/m3; a window or benchmark encoded as {} -> null; '' benchmark -> null;
- evidence '' -> EXPERIMENTAL; missing horizon -> rank: longterm, event: swing; missing lifecycle -> active;
- results_in_days is recomputed against today's IST date (the scan stored days from the scan day);
- the backtest compounds, so model share counts are never exposed (weight_pct instead).
"""
from __future__ import annotations

import json
from datetime import date

import pandas as pd

from . import catalog, clock, data, paper_svc
from ..caches import KeyedCache, file_key, register
from ..errors import no_scan, not_found
from ..paths import P
from ..util import days_until, inum, num, sample_even, sub

EVIDENCE = {"STRONG", "MODERATE", "WEAK", "FOLKLORE", "EXPERIMENTAL"}
PERF_KEYS = ("return_pct", "cagr_pct", "max_dd_pct", "sharpe", "vol_pct", "after_tax_cagr_pct")
TRADE_KEYS = ("win_rate", "avg_win_pct", "avg_loss_pct", "expectancy_pct", "profit_factor", "avg_days")
BENCH_KEYS = ("benchmark", "ew_benchmark", "n500_benchmark", "factor_benchmark")


# ------------------------------------------------------------------ latest / as_of
def require_latest() -> dict:
    lt = data.latest()
    if lt is None:
        raise no_scan()
    return lt


def is_legacy(lt: dict) -> bool:
    """latest.json written by a checkout without the strategy library (older schema)."""
    return "indices" not in lt or any("horizon" not in s for s in lt.get("strategies", []))


def min_position(lt: dict) -> float:
    v = num(lt.get("min_position"))
    if v is None:
        v = num((data.config().get("account") or {}).get("min_position"))
    return v or 0.0


def as_of(lt: dict | None = None, clk: dict | None = None) -> dict:
    lt = lt or require_latest()
    clk = clk or clock.market_clock()
    data_date = str(lt.get("data_date") or "")[:10]
    return {
        "scan_id": str(lt.get("generated_at")), "generated_at": str(lt.get("generated_at")),
        "elapsed_s": num(lt.get("elapsed_s")) or 0.0, "data_date": data_date, "live": bool(lt.get("live")),
        "live_source": lt.get("live_source"), "complete_upto": lt.get("complete_upto"),
        "stale": bool(data_date) and data_date < clk["last_completed_day"],
        "legacy_producer": is_legacy(lt),
        "backtest_universe": lt.get("backtest_universe") if lt.get("backtest_universe") in ("current_list", "point_in_time") else "current_list",
        "universe_note": str(lt.get("universe") or ""), "tradable": int(lt.get("stocks") or 0),
        "capital": num(lt.get("capital")) or 0.0, "min_position": min_position(lt),
        "costs_round_trip_pct": num(lt.get("costs_round_trip_pct")) or 0.0,
    }


# ------------------------------------------------------------------ metrics
def perf(d) -> dict | None:
    if not isinstance(d, dict) or not d or all(d.get(k) is None for k in PERF_KEYS[:5]):
        return None
    return {k: num(d.get(k)) for k in PERF_KEYS}


def window(d, full: bool = False) -> dict | None:
    if not isinstance(d, dict) or not d:
        return None
    out = {k: num(d.get(k)) for k in PERF_KEYS + TRADE_KEYS}
    out["trades"] = int(d.get("trades") or 0)
    for b in BENCH_KEYS:
        out[b] = perf(d.get(b))
    if full:
        rng = d.get("cagr_range")
        out.update({"exposure_pct": num(d.get("exposure_pct")), "start": str(d.get("start") or ""),
                    "end": str(d.get("end") or ""), "after_tax_return_pct": num(d.get("after_tax_return_pct")),
                    "cagr_range": [num(rng[0]), num(rng[1])] if isinstance(rng, list) and len(rng) == 2
                    and num(rng[0]) is not None and num(rng[1]) is not None else None,
                    "te_n500_pct": num(d.get("te_n500_pct")),
                    "factor_benchmark_name": d.get("factor_benchmark_name") or None})
    return out


def _is_nifty50(name) -> bool:
    return str(name or "").replace(" ", "").upper() in ("NIFTY50", "NIFTY")


def factor_name(s: dict, full: dict | None = None) -> str | None:
    """The strategy's matching NSE factor index, or None when that is Nifty 50: Nifty 50 is already the
    benchmark (and the ETF strategies' primary edge), so a second 'factor' copy of it would only repeat it."""
    name = s.get("benchmark") or (full or {}).get("factor_benchmark_name") or None
    return None if _is_nifty50(name) else name


def metrics(s: dict) -> dict:
    m = s.get("metrics") or {}
    out = {"full": window(m.get("full") or {"start": "", "end": ""}, full=True) or {},
           "m12": window(m.get("12m")), "m6": window(m.get("6m")), "m3": window(m.get("3m"))}
    if factor_name(s, out["full"]) is None:
        out["full"]["factor_benchmark_name"] = None
        for w in out.values():
            if w:
                w["factor_benchmark"] = None
    return out


def _ret(w, bench: str | None = None):
    if not w:
        return None
    if bench:
        b = w.get(bench)
        return b.get("return_pct") if b else None
    return w.get("return_pct")


def edges(s: dict, m: dict) -> dict:
    full = m["full"]

    def cagr(b):
        x = full.get(b)
        return x.get("cagr_pct") if x else None
    c = full.get("cagr_pct")
    return {"primary": "nifty" if s.get("universe") == "etfs" else "ew",
            "vs_ew_cagr_pct": sub(c, cagr("ew_benchmark")), "vs_n500_cagr_pct": sub(c, cagr("n500_benchmark")),
            "vs_nifty_cagr_pct": sub(c, cagr("benchmark")), "vs_factor_cagr_pct": sub(c, cagr("factor_benchmark")),
            "r12m_vs_n500_pct": sub(_ret(m["m12"]), _ret(m["m12"], "n500_benchmark")),
            "r6m_vs_n500_pct": sub(_ret(m["m6"]), _ret(m["m6"], "n500_benchmark"))}


def timing(s: dict, m: dict) -> dict | None:
    full = m["full"]
    rng = full.get("cagr_range")
    base = full.get("cagr_pct")
    if not rng:
        return None
    lo, hi = rng
    ok = base is not None and lo - 0.05 <= base <= hi + 0.05
    return {"base_cagr_pct": base, "low": round(lo, 4), "high": round(hi, 4), "consistent": bool(ok),
            "method": "rebalance_offsets" if s.get("kind") == "rank" else "start_offsets"}


def headline(m: dict) -> dict:
    f = m["full"]
    return {"cagr_pct": f.get("cagr_pct"), "after_tax_cagr_pct": f.get("after_tax_cagr_pct"),
            "max_dd_pct": f.get("max_dd_pct"), "sharpe": f.get("sharpe"), "vol_pct": f.get("vol_pct"),
            "win_rate": f.get("win_rate"), "trades": int(f.get("trades") or 0), "exposure_pct": f.get("exposure_pct"),
            "avg_days": f.get("avg_days"), "ret_12m_pct": _ret(m["m12"]), "ret_6m_pct": _ret(m["m6"]),
            "ret_3m_pct": _ret(m["m3"]), "n500_12m_pct": _ret(m["m12"], "n500_benchmark")}


# ------------------------------------------------------------------ rules (B5, with config fallback)
_cfg_strats = register(KeyedCache(2))


def _config_strategies() -> dict:
    """{key: strategy object} from build_strategies(current config) - only for scans without B5 rules."""
    def build():
        from scanner.strategies import build_strategies
        try:
            return {s.key: s for s in build_strategies(data.config(), include_disabled=True)}
        except Exception:
            return {}
    return _cfg_strats.get(file_key(P.config), build)


def rules(s: dict) -> tuple[dict, str]:
    r = dict(s.get("rules") or {})
    if "kind" in r and "params" in r:
        return r, "scan"
    obj = _config_strategies().get(s["key"])
    if obj is not None:
        from scanner.daily import _rules
        base = _rules(obj, (data.config().get("strategies") or {}).get(s["key"]))
        base.update({k: v for k, v in r.items() if k in ("stop_pct", "target_pct", "trail_pct", "sizing", "risk_pct")})
        return base, "config"
    kind = s.get("kind") if s.get("kind") in ("rank", "event") else "event"
    return {"kind": kind, "rebalance": None, "top_n": None, "keep_rank": None,
            "max_positions": int(s.get("max_positions") or 1), "stop_pct": r.get("stop_pct"), "stop_atr": None,
            "target_pct": r.get("target_pct"), "trail_pct": r.get("trail_pct"), "max_hold": None,
            "sizing": r.get("sizing") or "equal", "risk_pct": r.get("risk_pct"), "use_regime": False,
            "regime_action": None, "params": {}}, "config"


def rules_view(s: dict) -> dict:
    r, source = rules(s)
    out = {
        "kind": r.get("kind") if r.get("kind") in ("rank", "event") else "event",
        "rebalance": r.get("rebalance"), "top_n": inum(r.get("top_n")), "keep_rank": inum(r.get("keep_rank")),
        "max_positions": int(r.get("max_positions") or s.get("max_positions") or 1),
        "stop_pct": num(r.get("stop_pct")) or None, "stop_atr": num(r.get("stop_atr")),
        "target_pct": num(r.get("target_pct")) or None, "trail_pct": num(r.get("trail_pct")) or None,
        "max_hold": inum(r.get("max_hold")), "sizing": "risk" if r.get("sizing") == "risk" else "equal",
        "risk_pct": num(r.get("risk_pct")), "use_regime": bool(r.get("use_regime")),
        "regime_action": r.get("regime_action") if r.get("regime_action") in ("hold", "cash") else None,
        "params": json.loads(json.dumps(r.get("params") or {}, default=str)), "source": source,
    }
    out["plain_rules"] = catalog.plain_rules(s["key"], out)
    return out


# ------------------------------------------------------------------ strategy list
def all_strategies(lt: dict) -> list[dict]:
    """Active strategies (daily.py order) then B4 rejected/disabled ones, normalised."""
    out = []
    for s in lt.get("strategies", []):
        out.append(_norm(s, default_lifecycle="active"))
    for s in lt.get("rejected_strategies", []) or []:
        out.append(_norm(s, default_lifecycle="rejected"))
    return out


def _norm(s: dict, default_lifecycle: str) -> dict:
    s = dict(s)
    s["kind"] = s.get("kind") if s.get("kind") in ("rank", "event") else "event"
    s["horizon"] = s.get("horizon") or ("longterm" if s["kind"] == "rank" else "swing")
    s["evidence"] = s.get("evidence") if s.get("evidence") in EVIDENCE else "EXPERIMENTAL"
    s["universe"] = s.get("universe") if s.get("universe") in ("stocks", "etfs") else "stocks"
    s["lifecycle"] = s.get("lifecycle") if s.get("lifecycle") in ("active", "disabled", "rejected") else default_lifecycle
    s["status"] = s.get("status") if s.get("status") in ("working", "mixed", "not-working", "unknown") else "unknown"
    return s


def find(lt: dict, key: str) -> dict:
    for s in all_strategies(lt):
        if s["key"] == key:
            return s
    raise not_found(f"Strategy '{key}'", "See /api/strategies for the available keys.")


def comparison_only(s: dict) -> bool:
    return s["status"] == "not-working" or s["lifecycle"] != "active"


def spark(key: str) -> list[float]:
    c = data.curves()
    if c is None or key not in c.columns:
        return []
    v = c[key].dropna()
    return [round(float(x), 4) for x in sample_even(v.tolist(), 120)]


def curve_last(key: str) -> float | None:
    c = data.curves()
    if c is None or key not in c.columns:
        return None
    v = c[key].dropna()
    return float(v.iloc[-1]) if len(v) else None


def summary(s: dict, lt: dict, papers: dict | None = None) -> dict:
    m = metrics(s)
    r, _ = rules(s)
    regime_up = bool((lt.get("market") or {}).get("regime_up", True))
    uses_regime = bool(r.get("use_regime"))
    actions = s.get("actions") or []
    papers = paper_svc.summaries() if papers is None else papers
    return {
        "key": s["key"], "name": s.get("name") or s["key"], "description": s.get("description") or "",
        "kind": s["kind"], "horizon": s["horizon"], "evidence": s["evidence"], "universe": s["universe"],
        "lifecycle": s["lifecycle"], "status": s["status"], "status_reason": s.get("status_reason") or "",
        "rejected_reason": s.get("rejected_reason"), "comparison_only": comparison_only(s),
        "headline": headline(m), "edges": edges(s, m), "timing": timing(s, m),
        "factor_benchmark_name": factor_name(s, m["full"]),
        "max_positions": int(s.get("max_positions") or 1), "per_position": num(s.get("per_position")) or 0.0,
        "positions": len(s.get("positions") or []),
        "orders_buy": sum(1 for a in actions if a.get("action") == "BUY"),
        "orders_sell": sum(1 for a in actions if a.get("action") == "SELL"),
        "rebalance": r.get("rebalance") if s["kind"] == "rank" else None,
        "next_rebalance": s.get("next_rebalance") if s["kind"] == "rank" else None,
        "uses_regime_filter": uses_regime, "blocked_by_regime": uses_regime and not regime_up,
        "spark": spark(s["key"]), "paper": paper_svc.pulse(papers.get(s["key"])),
    }


def benchmark_strip(lt: dict) -> tuple[dict, dict]:
    """Same-period benchmarks from the first active strategy's full window."""
    strats = lt.get("strategies") or []
    full = (strats[0].get("metrics") or {}).get("full") if strats else {}
    full = full or {}
    ew, n500 = perf(full.get("ew_benchmark")), perf(full.get("n500_benchmark"))
    gap = sub((ew or {}).get("cagr_pct"), (n500 or {}).get("cagr_pct"))
    return ({"start": str(full.get("start") or lt.get("data_date") or ""), "end": str(full.get("end") or lt.get("data_date") or "")},
            {"nifty50": perf(full.get("benchmark")), "nifty500": n500, "average_stock": ew, "survivorship_gap_pct": gap})


# ------------------------------------------------------------------ positions / ranking / trades
def model_weight(pos: dict, key: str, capital: float) -> float | None:
    """qty * last / (capital * curves[key].last) * 100: the position's share of the model portfolio."""
    cl = curve_last(key)
    qty, last = num(pos.get("qty")), num(pos.get("last_price"))
    if not cl or not capital or qty is None or last is None:
        return None
    return round(qty * last / (capital * cl) * 100, 2)


def positions(s: dict, lt: dict, today: date | None = None) -> list[dict]:
    meta = data.symbol_meta()
    capital = num(lt.get("capital")) or 0.0
    out = []
    for p in s.get("positions") or []:
        sym = p.get("symbol")
        m = meta.get(sym, {})
        out.append({"symbol": sym, "company": p.get("company") or m.get("company"),
                    "industry": p.get("industry") or m.get("industry"),
                    "entry_date": str(p.get("entry_date") or ""), "entry_price": num(p.get("entry_price")) or 0.0,
                    "last_price": num(p.get("last_price")), "ret_pct": num(p.get("ret_pct")), "stop": num(p.get("stop")),
                    "days": int(p.get("days") or 0), "weight_pct": model_weight(p, s["key"], capital),
                    "results_on": p.get("results_on"), "results_in_days": days_until(p.get("results_on"), today)})
    return out


def ranking(s: dict, today: date | None = None) -> list[dict]:
    meta = data.symbol_meta()
    out = []
    for r in s.get("ranking") or []:
        sym = r.get("symbol")
        m = meta.get(sym, {})
        out.append({"rank": int(r.get("rank") or 0), "symbol": sym, "company": r.get("company") or m.get("company"),
                    "industry": r.get("industry") or m.get("industry"), "score": num(r.get("score")),
                    "price": num(r.get("price")), "ret_6m_pct": num(r.get("ret_6m")), "ret_12m_pct": num(r.get("ret_12m")),
                    "rs": num(r.get("rs")), "in_portfolio": bool(r.get("in_portfolio")),
                    "results_on": r.get("results_on"), "results_in_days": days_until(r.get("results_on"), today)})
    return out


def recent_trades(s: dict) -> list[dict]:
    return [{"symbol": t.get("symbol"), "entry_date": str(t.get("entry") or t.get("entry_date") or ""),
             "exit_date": str(t.get("exit") or t.get("exit_date") or ""),
             "entry_price": num(t.get("entry_price")), "exit_price": num(t.get("exit_price")),
             "ret_pct": num(t.get("ret_pct")), "days": int(t.get("days") or 0), "reason": str(t.get("reason") or "")}
            for t in s.get("recent_trades") or []]


def artifact_trades(key: str) -> pd.DataFrame | None:
    df = data.trades()
    if df is None:
        return None
    return df[df["strategy"] == key]


# ------------------------------------------------------------------ yearly / monthly (curves.parquet)
def _calendar_years(v: pd.Series) -> dict[int, float]:
    """Calendar-year returns in %: year-end over the PREVIOUS year-end (the first year over the first value), so a
    year includes its first trading day and equals the monthly table's year total. latest.yearly uses the year's
    first close as the base instead, which drops each first trading day (dual_momentum 2022: -20.2% vs -13.8%)."""
    v = v.dropna()
    if len(v) < 2:
        return {}
    year_end = v.groupby(v.index.year).last()
    base = year_end.shift(1)
    base.iloc[0] = v.iloc[0]
    return ((year_end / base - 1) * 100).round(1).to_dict()


def yearly(s: dict) -> list[dict]:
    c = data.curves()
    key = s["key"]
    strat = {int(k): num(v) for k, v in (s.get("yearly") or {}).items() if str(k).isdigit()}
    bench = {}
    first_day = last_day = None
    if c is not None and key in c.columns:
        eq = c[key].dropna()
        if len(eq):
            first_day, last_day = eq.index[0], eq.index[-1]
            strat = {int(y): num(v) for y, v in _calendar_years(eq).items()} or strat
            for col, name in (("NIFTY 500", "nifty500"), ("Average stock", "average_stock"), ("NIFTY 50", "nifty50")):
                if col in c.columns:
                    bench[name] = _calendar_years(c[col].reindex(eq.index).ffill())
    years = sorted(set(strat) | {y for d in bench.values() for y in d})
    out = []
    for y in years:
        partial = bool((first_day is not None and y == first_day.year and (first_day.month, first_day.day) > (1, 10))
                       or (last_day is not None and y == last_day.year and (last_day.month, last_day.day) < (12, 20)))
        out.append({"year": int(y), "partial": partial, "strategy": strat.get(y),
                    **{n: num(bench.get(n, {}).get(y)) for n in ("nifty500", "average_stock", "nifty50")}})
    return out


def monthly(key: str) -> list[dict]:
    c = data.curves()
    if c is None or key not in c.columns:
        return []
    eq = c[key].dropna()
    if len(eq) < 2:
        return []
    month_end = eq.groupby([eq.index.year, eq.index.month]).last()
    prev = month_end.shift(1)
    prev.iloc[0] = eq.iloc[0]
    ret = (month_end / prev - 1) * 100
    year_end = eq.groupby(eq.index.year).last()
    prev_y = year_end.shift(1)
    prev_y.iloc[0] = eq.iloc[0]
    total = (year_end / prev_y - 1) * 100
    out = []
    for y in sorted({k[0] for k in ret.index}):
        months = [num(ret.get((y, mth)), 2) for mth in range(1, 13)]
        out.append({"year": int(y), "months": months, "total": num(total.get(y), 2)})
    return out


def regime_note(summ: dict, lt: dict) -> str | None:
    if not summ["uses_regime_filter"]:
        return None
    if summ["blocked_by_regime"]:
        return (f"No new buys: Nifty is below its 200-day average (regime filter on). "
                f"Holding {summ['positions']} of {summ['max_positions']}.")
    return "Regime filter on: new buys stop while Nifty is below its 200-day average."

