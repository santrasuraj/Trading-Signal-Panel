"""3. strategies: list, detail, curve, trades."""
from __future__ import annotations

from typing import Literal

import numpy as np
import pandas as pd
from fastapi import APIRouter, Query

from ..errors import SafeJSONResponse, ApiException
from ..models import CurveResponse, Horizon, StrategyDetail, StrategyListResponse, TradesPage
from ..services import catalog, data, intraday_view, paper_svc, sizing, strategies as st
from ..util import num, ser_list, today_ist

router = APIRouter(prefix="/api/strategies", tags=["strategies"])


@router.get("", response_model=StrategyListResponse)
def list_strategies(horizon: Horizon | None = None):
    lt = st.require_latest()
    papers = paper_svc.summaries()
    allst = st.all_strategies(lt)
    active = [s for s in allst if s["lifecycle"] == "active"]
    rejected = [s for s in allst if s["lifecycle"] != "active"]
    counts = {"longterm": 0, "swing": 0, "intraday": intraday_view.count()}
    for s in active:
        if s["horizon"] in ("longterm", "swing"):
            counts[s["horizon"]] += 1
    if horizon:
        active = [s for s in active if s["horizon"] == horizon]
        rejected = [s for s in rejected if s["horizon"] == horizon]
    period, bench = st.benchmark_strip(lt)
    tested = {s["key"] for s in allst}
    cat = [] if lt.get("rejected_strategies") else [
        {**r, "source": "catalogue"} for r in catalog.REJECTED_CATALOGUE
        if r["key"] not in tested and (not horizon or r["horizon"] == horizon)]
    return {"as_of": st.as_of(lt), "period": period, "benchmarks": bench, "counts": counts,
            "strategies": [st.summary(s, lt, papers) for s in active],
            "rejected": [st.summary(s, lt, papers) for s in rejected], "rejected_catalogue": cat}


@router.get("/{key}", response_model=StrategyDetail)
def detail(key: str):
    lt = st.require_latest()
    s = st.find(lt, key)
    papers = paper_svc.summaries()
    summ = st.summary(s, lt, papers)
    today = today_ist()
    alloc, _, _ = sizing.resolve(None, [x["key"] for x in st.all_strategies(lt) if x["lifecycle"] == "active"])
    orders = sizing.orders_for(s, lt, alloc, data.holdings_qty(), today)
    return {"as_of": st.as_of(lt), "strategy": summ, "metrics": st.metrics(s), "yearly": st.yearly(s),
            "monthly": st.monthly(key), "rules": st.rules_view(s),
            "evidence": catalog.evidence_card(key, s["evidence"]), "positions": st.positions(s, lt, today),
            "orders": orders, "ranking": st.ranking(s, today) if s["kind"] == "rank" else [],
            "recent_trades": st.recent_trades(s), "trades_available": st.artifact_trades(key) is not None,
            "regime_note": st.regime_note(summ, lt), "paper": papers.get(key)}


RANGE_ROWS = {"1y": 252, "3y": 756, "all": None}


@router.get("/{key}/curve", response_model=None, response_class=SafeJSONResponse,
            responses={200: {"model": CurveResponse}})
def curve(key: str, range: Literal["1y", "3y", "all"] = "all"):  # noqa: A002
    lt = st.require_latest()
    s = st.find(lt, key)
    c = data.curves()
    if c is None or key not in c.columns:
        raise ApiException("FEATURE_UNAVAILABLE", "No equity curve for this strategy yet.", "Run a scan.",
                           {"feature": "curve"})
    eq = c[key].dropna()
    n = RANGE_ROWS[range]
    idx = eq.index[-(n + 1):] if n else eq.index
    cols = [(key, s.get("name") or key, "strategy")]
    for col, label in (("NIFTY 500", "NIFTY 500"), ("Average stock", "Average stock"), ("NIFTY 50", "NIFTY 50")):
        if col in c.columns:
            cols.append((col, label, "benchmark"))
    frame = c.reindex(idx)[[x[0] for x in cols]].ffill()
    fname = st.metrics(s)["full"].get("factor_benchmark_name")
    hist = data.index_history()
    if fname and hist is not None and fname in hist.columns:
        f = hist[fname].reindex(hist.index.union(idx)).ffill().reindex(idx)
        if f.notna().any():
            frame[fname] = f
            cols.append((fname, fname, "factor"))
    t = [d.date().isoformat() for d in frame.index]
    series, dds = [], []
    for col, label, role in cols:
        v = frame[col]
        first = v.dropna()
        base = first.iloc[0] if len(first) else np.nan
        rebased = v / base
        series.append({"id": col, "label": label, "role": role, "v": ser_list(rebased, 5)})
        if col in (key, "NIFTY 500"):
            dd = (rebased / rebased.cummax() - 1) * 100
            dds.append({"id": col, "label": label, "role": role, "v": ser_list(dd, 3)})
    return {"as_of": st.as_of(lt), "key": key, "range": range, "curve": {"t": t, "series": series},
            "drawdown": {"t": t, "series": dds}, "capital": num(lt.get("capital")) or 0.0}


SORTS = {"exit_date", "entry_date", "ret_pct", "days", "symbol"}


@router.get("/{key}/trades", response_model=TradesPage)
def trades(key: str, page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=500),
           outcome: Literal["all", "win", "loss"] = "all", reason: str | None = None, symbol: str | None = None,
           sort: str = "-exit_date"):
    lt = st.require_latest()
    s = st.find(lt, key)
    art = st.artifact_trades(key)
    if art is not None:
        df = art[["symbol", "entry_date", "exit_date", "entry_price", "exit_price", "ret_pct", "days", "reason", "pnl"]].copy()
        source = "artifact"
    else:
        df = pd.DataFrame(st.recent_trades(s), columns=["symbol", "entry_date", "exit_date", "entry_price",
                                                        "exit_price", "ret_pct", "days", "reason"])
        df["pnl"] = np.nan
        source = "recent_only"
    if outcome == "win":
        df = df[df["ret_pct"] > 0]
    elif outcome == "loss":
        df = df[df["ret_pct"] <= 0]
    if reason:
        df = df[df["reason"] == reason]
    if symbol:
        df = df[df["symbol"].str.upper().str.startswith(symbol.strip().upper())]
    field = sort.lstrip("-+")
    if field not in SORTS:
        raise ApiException("VALIDATION", f"Cannot sort by '{field}'.", f"Use one of: {', '.join(sorted(SORTS))}.",
                           {"param": "sort"})
    df = df.sort_values(field, ascending=not sort.startswith("-"), kind="stable")
    total = len(df)
    rows = df.iloc[(page - 1) * page_size: page * page_size]
    r = df["ret_pct"].astype(float).dropna()
    wins, losses = r[r > 0], r[r <= 0]
    pnl = df["pnl"].astype(float)
    if source == "artifact" and pnl.notna().any():
        gl = -pnl[pnl <= 0].sum()
        pf = float(pnl[pnl > 0].sum() / gl) if gl > 0 else None
    else:
        gl = -losses.sum()
        pf = float(wins.sum() / gl) if gl > 0 else None
    # 3 dp like the scan's metrics: 2 dp double-rounds (47.2477 -> 47.25 -> "47.3%" vs the KPI's 47.2%).
    stats = {"trades": int(total), "win_rate": num((r > 0).mean() * 100, 3) if len(r) else None,
             "avg_win_pct": num(wins.mean(), 2) if len(wins) else None,
             "avg_loss_pct": num(losses.mean(), 2) if len(losses) else None,
             "expectancy_pct": num(r.mean(), 2) if len(r) else None, "profit_factor": num(pf, 3),
             "avg_days": num(df["days"].astype(float).mean(), 1) if total else None}
    edges = np.arange(-30, 102, 2)
    counts = np.histogram(np.clip(r.to_numpy(), -30, 99.999), bins=edges)[0] if len(r) else np.zeros(len(edges) - 1)
    hist = [{"bin_lo": float(edges[i]), "bin_hi": float(edges[i + 1]), "count": int(counts[i])} for i in range(len(edges) - 1)]
    reasons = [{"reason": str(k), "count": int(len(g)), "avg_ret_pct": num(g["ret_pct"].astype(float).mean(), 2)}
               for k, g in df.groupby("reason")]
    reasons.sort(key=lambda x: -x["count"])
    out_rows = [{"symbol": x.symbol, "entry_date": str(x.entry_date), "exit_date": str(x.exit_date),
                 "entry_price": num(x.entry_price, 2), "exit_price": num(x.exit_price, 2),
                 "ret_pct": num(x.ret_pct, 2), "days": int(x.days), "reason": str(x.reason)}
                for x in rows.itertuples(index=False)]
    return {"as_of": st.as_of(lt), "key": key, "source": source, "total": total, "page": page,
            "page_size": page_size, "rows": out_rows, "stats": stats, "histogram": hist, "reasons": reasons}
