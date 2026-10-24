"""5. screener, symbols, sparklines and 6. chart, stock."""
from __future__ import annotations

from typing import Literal

import pandas as pd
from fastapi import APIRouter, Query

from scanner.providers import INDEX_SYMBOLS

from ..errors import ApiException, SafeJSONResponse, feature_unavailable, not_found
from ..models import ChartResponse, ScreenerResponse, SparklinesResponse, StockSnapshot, SymbolsResponse
from ..services import chart_data, data, holdings_svc, market_derived, strategies as st
from ..util import fmt_date, inum, num, ser_list, spct, today_ist

router = APIRouter(prefix="/api", tags=["lookup"])

PRESETS = ("momentum", "rs", "near_high", "low_vol", "volume", "uptrend", "all")
COLS = {"ret_1w": "ret_1w_pct", "ret_1m": "ret_1m_pct", "ret_3m": "ret_3m_pct", "ret_6m": "ret_6m_pct",
        "ret_12m": "ret_12m_pct"}


def _models_by_symbol(lt: dict) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for s in lt.get("strategies") or []:
        for p in s.get("positions") or []:
            out.setdefault(p.get("symbol"), []).append(s.get("key"))
    return out


def _results_by_symbol(lt: dict) -> dict[str, str]:
    from ..services import results
    return {e["symbol"]: e["date"] for e in results.events(lt, days=30)["events"]}


@router.get("/screener", response_model=ScreenerResponse)
def screener(preset: Literal["momentum", "rs", "near_high", "low_vol", "volume", "uptrend", "all"] = "momentum",
             industry: str | None = None, min_turnover_cr: float | None = Query(None, ge=0),
             in_models: bool = False, results_within: int | None = Query(None, ge=0, le=60),
             sort: str | None = None):
    lt = st.require_latest()
    df = data.screener()
    if df is None:
        raise feature_unavailable("screener", "The screener appears after the next scan.",
                                  "Run a scan (or a re-check without download, ~15 s) to build it.")
    df = df.copy()
    models = _models_by_symbol(lt)
    held = set(data.holdings_df()["symbol"])
    res = _results_by_symbol(lt)
    df["in_models"] = [models.get(s, []) for s in df["symbol"]]
    df["you_hold"] = [s in held for s in df["symbol"]]
    df["results_on"] = [res.get(s) for s in df["symbol"]]
    flt = (data.config().get("filters") or {})
    mt = min_turnover_cr if min_turnover_cr is not None else float(flt.get("min_turnover_cr", 5) or 0)
    df = df[df["turnover_cr"].fillna(0) >= mt]
    industries = sorted({str(x) for x in df["industry"].dropna() if str(x).strip()})
    if industry:
        wanted = {x.strip() for x in industry.split(",") if x.strip()}
        df = df[df["industry"].isin(wanted)]
    if in_models:
        df = df[df["in_models"].map(bool)]
    if results_within is not None:
        lim = (today_ist() + pd.Timedelta(days=results_within)).isoformat()
        # a missing date is NaN (float) in a pyarrow-backed string column, not None: compare strings only
        df = df[df["results_on"].map(lambda d: isinstance(d, str) and d <= lim)]
    up200 = df["above_sma200"].fillna(False).astype(bool)
    if preset == "momentum":
        df = df[up200 & df["momentum_score"].notna()].sort_values("momentum_score", ascending=False)
    elif preset == "rs":
        df = df.sort_values("rs", ascending=False)
    elif preset == "near_high":
        df = df[up200 & df["sma50_above_sma200"].fillna(False).astype(bool)].sort_values("pct_from_52w_high", ascending=False)
    elif preset == "low_vol":
        top = df["turnover_cr"].rank(ascending=False) <= 150
        df = df[top].sort_values("vol_ann_pct", ascending=True)
    elif preset == "volume":
        df = df[df["vol_ratio"] >= 3].sort_values("vol_ratio", ascending=False)
    elif preset == "uptrend":
        df = df[up200 & df["sma50_above_sma200"].fillna(False).astype(bool)].sort_values("rs", ascending=False)
    else:
        df = df.sort_values("symbol")
    if sort:
        field = COLS_REV.get(sort.lstrip("-+"), sort.lstrip("-+"))
        if field not in df.columns:
            raise ApiException("VALIDATION", f"Cannot sort by '{sort.lstrip('-+')}'.", details={"param": "sort"})
        df = df.sort_values(field, ascending=not sort.startswith("-"), kind="stable", na_position="last")
    rows = []
    for r in df.to_dict("records"):
        row = {COLS.get(k, k): v for k, v in r.items()}
        for k in ("above_sma50", "above_sma200", "sma50_above_sma200"):
            row[k] = None if pd.isna(row.get(k)) else bool(row[k])
        for k, v in list(row.items()):
            if isinstance(v, float):
                row[k] = num(v, 2)
        row["momentum_rank"] = inum(row.get("momentum_rank"))
        row["company"] = row.get("company") or None
        row["industry"] = row.get("industry") or None
        rows.append(row)
    return {"as_of": st.as_of(lt), "source_date": str(lt.get("data_date")), "preset": preset, "total": len(rows),
            "rows": rows, "industries": industries}


COLS_REV = {v: k for k, v in COLS.items()}


@router.get("/symbols", response_model=SymbolsResponse)
def symbols():
    lt = data.latest()
    meta = data.symbol_meta()
    uni = set(data.universe()["symbol"])
    etfs = data.etfs()
    names = list(dict.fromkeys(list(data.universe()["symbol"]) + list((lt or {}).get("symbols") or []) + etfs
                               + list(INDEX_SYMBOLS)))
    out = []
    for s in names:
        kind = data.symbol_kind(s)
        m = meta.get(s, {})
        company = data.INDEX_NAMES.get(s) if kind == "index" else m.get("company")
        out.append({"symbol": s, "company": company, "industry": m.get("industry"), "kind": kind,
                    "in_universe": s in uni})
    return {"as_of": st.as_of(lt) if lt else None, "symbols": out}


@router.get("/sparklines", response_model=None, response_class=SafeJSONResponse,
            responses={200: {"model": SparklinesResponse}})
def sparklines(symbols: str, days: int = Query(60, ge=5, le=400)):
    syms = list(dict.fromkeys(s.strip().upper() for s in symbols.split(",") if s.strip()))
    if len(syms) > 500:
        raise ApiException("VALIDATION", "At most 500 symbols per call.", details={"param": "symbols"})
    c = data.store_close()
    if c.empty:
        raise feature_unavailable("store", "No stored prices yet.", "Run a scan.")
    have = [s for s in syms if s in c.columns]
    part = c[have].iloc[-days:]
    series = {s: ser_list(part[s], 2) for s in have}
    return {"source_date": c.index[-1].date().isoformat(), "days": days, "series": series}


@router.get("/chart/{symbol}", response_model=None, response_class=SafeJSONResponse,
            responses={200: {"model": ChartResponse}})
def chart(symbol: str, tf: Literal["1d", "1w"] = "1d",
          range: Literal["3m", "6m", "1y", "2y", "5y", "max"] = "1y",  # noqa: A002
          indicators: str | None = None):
    sym = symbol.strip().upper()
    wanted = ([x.strip() for x in indicators.split(",") if x.strip()] if indicators is not None
              else list(chart_data.DEFAULT_INDICATORS))
    bad = [x for x in wanted if x not in chart_data.INDICATORS]
    if bad:
        raise ApiException("VALIDATION", f"Unknown indicator(s): {', '.join(bad)}.",
                           f"Available: {', '.join(chart_data.INDICATORS)}.", {"param": "indicators"})
    return chart_data.build(sym, tf, range, wanted)


@router.get("/stock/{symbol}", response_model=StockSnapshot)
def stock(symbol: str):
    sym = symbol.strip().upper()
    lt = data.latest()
    meta = data.symbol_meta().get(sym, {})
    stats = market_derived.stock_stats(sym)
    in_lists = sym in set(data.universe()["symbol"]) or sym in set((lt or {}).get("symbols") or []) or sym in INDEX_SYMBOLS
    if not stats and not in_lists:
        raise not_found(f"Symbol '{sym}'", "Check the NSE symbol (e.g. RELIANCE, M&M).")
    row = {}
    sc = data.screener()
    if sc is not None:
        hit = sc[sc["symbol"] == sym]
        if len(hit):
            row = hit.iloc[0].to_dict()
    def pick(screen_key, stat_key=None, nd=2):
        v = row.get(screen_key) if row else None
        v = num(v, nd)
        return v if v is not None else stats.get(stat_key or screen_key)
    roles = []
    today = today_ist()
    results_on = None
    for s in st.all_strategies(lt) if lt else []:
        if s["lifecycle"] != "active":
            continue
        for p in s.get("positions") or []:
            if p.get("symbol") == sym:
                since = fmt_date(p.get("entry_date"))
                roles.append({"key": s["key"], "name": s.get("name"), "status": s["status"], "role": "holding",
                              "detail": f"Held since {since} ({spct(p.get('ret_pct'))})"
                              if num(p.get("ret_pct")) is not None else f"Held since {since}"})
                results_on = results_on or p.get("results_on")
        for a in s.get("actions") or []:
            if a.get("symbol") == sym:
                roles.append({"key": s["key"], "name": s.get("name"), "status": s["status"], "role": "order",
                              "detail": f"{a.get('action')} at the next open ({a.get('reason')})"})
                results_on = results_on or a.get("results_on")
        for r in s.get("ranking") or []:
            if r.get("symbol") == sym:
                roles.append({"key": s["key"], "name": s.get("name"), "status": s["status"], "role": "ranked",
                              "detail": f"Ranked #{r.get('rank')}"})
                results_on = results_on or r.get("results_on")
    from ..services import results
    if results_on is None:
        results_on = next((e["date"] for e in results.events(lt, days=30)["events"] if e["symbol"] == sym), None)
    hold_rows, _ = holdings_svc.rows(lt) if lt else ([], False)
    your = next((h for h in hold_rows if h["symbol"] == sym), None)
    cas = [{"date": str(c.get("date")), "factor": num(c.get("factor")) or 0.0, "reason": str(c.get("reason") or "")}
           for c in data.store_meta().get("corporate_actions") or [] if c.get("symbol") == sym]
    kind = data.symbol_kind(sym)
    index = kind == "index"        # an index has no traded value or delivery: its 'volume' is not real (often 0)
    return {
        "as_of": st.as_of(lt) if lt else None, "symbol": sym,
        "company": data.INDEX_NAMES.get(sym) if kind == "index" else meta.get("company"),
        "industry": meta.get("industry"), "kind": kind,
        "price": pick("price"), "change_pct": pick("change_pct"),
        "data_date": str(lt.get("data_date")) if row and lt else stats.get("data_date"),
        "high_52w": pick("high_52w"), "low_52w": pick("low_52w"), "pct_from_52w_high": pick("pct_from_52w_high"),
        "ret_1m_pct": pick("ret_1m", "ret_1m_pct"), "ret_3m_pct": pick("ret_3m", "ret_3m_pct"),
        "ret_6m_pct": pick("ret_6m", "ret_6m_pct"), "ret_12m_pct": pick("ret_12m", "ret_12m_pct"),
        "rs": num(row.get("rs")) if row else None, "momentum_rank": inum(row.get("momentum_rank")) if row else None,
        "sma50": pick("sma50"), "sma200": pick("sma200"), "vol_ratio": None if index else pick("vol_ratio"),
        "turnover_cr": None if index else pick("turnover_cr"), "deliv_pct": None if index else pick("deliv_pct"),
        "results_on": results_on,
        "strategies": roles, "your_holding": your, "corporate_actions": sorted(cas, key=lambda c: c["date"], reverse=True),
    }
