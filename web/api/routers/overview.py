"""2. overview + 4. signals (+ their strength and the signal track record)."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Query

from ..models import Horizon, OverviewResponse, SignalsResponse, TrackRecordResponse
from ..services import alerts, clock, data, fyers_svc, intraday_view, market_derived, paper_svc, scan_runner
from ..services import results as results_svc, signal_quality, sizing, strategies as st, track_svc
from ..util import fmt_date, num, today_ist

router = APIRouter(prefix="/api", tags=["overview"])


def market_snapshot(lt: dict) -> dict:
    m = lt.get("market") or {}
    n500 = next((r for r in (lt.get("indices") or {}).get("factors", []) if r.get("name") == "Nifty 500"), {})
    nifty = num(m.get("nifty"))
    sma = num(m.get("nifty_sma200"))
    if sma is None:
        try:
            sma = market_derived.nifty_sma200()
        except Exception:
            sma = None
    vix = num(m.get("vix"))
    label = m.get("label") if m.get("label") in ("Bullish", "Mixed", "Bearish") else "Mixed"
    level = m.get("level") if m.get("level") in ("good", "neutral", "bad") else "neutral"
    return {"label": label, "level": level, "advice": str(m.get("advice") or ""),
            "regime_up": bool(m.get("regime_up", True)), "nifty": nifty, "nifty_change_pct": num(m.get("nifty_change_pct")),
            "nifty_sma200": sma, "nifty_vs_sma200_pct": round((nifty / sma - 1) * 100, 2) if nifty and sma else None,
            "nifty500": num(n500.get("last")), "nifty500_change_pct": num(n500.get("chg_1d")),
            "vix": vix, "vix_change_pct": num(m.get("vix_change_pct")), "high_vix": bool(vix is not None and vix >= 20),
            "breadth_50": num(m.get("breadth_50")), "advances": int(m.get("advances") or 0),
            "declines": int(m.get("declines") or 0)}


def mover(r: dict, meta: dict) -> dict:
    mm = meta.get(r.get("symbol"), {})
    return {"symbol": r.get("symbol"), "company": r.get("company") or mm.get("company"),
            "industry": r.get("industry") or mm.get("industry"), "price": num(r.get("price")),
            "change_pct": num(r.get("change_pct")), "vol_ratio": num(r.get("vol_ratio"))}


def movers(lt: dict, n: int | None = None) -> dict:
    meta = data.symbol_meta()
    return {k: [mover(r, meta) for r in (lt.get(k) or [])[:n]] for k in ("gainers", "losers", "volume_spikes")}


@router.get("/overview", response_model=OverviewResponse)
def overview():
    lt = st.require_latest()
    clk = clock.market_clock()
    as_of = st.as_of(lt, clk)
    today = today_ist()
    papers = paper_svc.summaries()
    allst = st.all_strategies(lt)
    active = [s for s in allst if s["lifecycle"] == "active"]
    summaries = {s["key"]: st.summary(s, lt, papers) for s in active}
    alloc, _, _ = sizing.resolve(None, [s["key"] for s in active])
    held = data.holdings_qty()
    orders = [o for s in active for o in sizing.orders_for(s, lt, alloc, held, today)]
    signal_quality.attach(orders, lt, active, track_svc.stats_by_strategy())
    empty: dict = {}
    for h in ("longterm", "swing"):
        mine = [s for s in active if s["horizon"] == h and not st.comparison_only(s)]
        if any(o["horizon"] == h and not o["comparison_only"] for o in orders):
            empty[h] = None
        elif not mine:
            empty[h] = "No working strategy in this horizon."
        elif all(summaries[s["key"]]["blocked_by_regime"] for s in mine):
            empty[h] = "Regime filter on: no new buys while Nifty is below its 200-DMA."
        else:
            reviews = sorted(summaries[s["key"]]["next_rebalance"] for s in mine if summaries[s["key"]]["next_rebalance"])
            empty[h] = "No entry signals today." + (f" Next review {fmt_date(reviews[0], year=False)}." if reviews else "")
    empty["intraday"] = intraday_view.signals_payload()["note"]
    prev = alerts.previous_scan(lt)
    paper_list = list(papers.values())
    al = alerts.build(lt, as_of, clk, fyers_svc.status(lt=lt), scan_runner.status(), list(summaries.values()),
                      orders, paper_list, prev)
    try:
        tiles = market_derived.index_tiles(lt)
    except Exception:
        tiles = []
    return {"as_of": as_of, "market": market_snapshot(lt), "index_tiles": tiles, "orders": orders,
            "empty_reasons": empty, "alerts": al, "changes": alerts.changes(lt, prev),
            "strategy_pulse": [summaries[s["key"]] for s in active][:6], "movers": movers(lt, 5),
            "results_soon": results_svc.events(lt, days=7, relevant=True)["events"], "paper": paper_list}


@router.get("/signals", response_model=SignalsResponse)
def signals(horizon: Horizon | None = None, allocations: str | None = None):
    lt = st.require_latest()
    today = today_ist()
    papers = paper_svc.summaries()
    active = [s for s in st.all_strategies(lt) if s["lifecycle"] == "active"]
    alloc, source, warning = sizing.resolve(allocations, [s["key"] for s in active])
    held = data.holdings_qty()
    capital = num(lt.get("capital")) or 0.0
    groups = []
    for s in active:
        if horizon and s["horizon"] != horizon:
            continue
        summ = st.summary(s, lt, papers)
        r, _ = st.rules(s)
        a_cap = sizing.alloc_capital(capital, alloc, s["key"])
        orders = sizing.orders_for(s, lt, alloc, held, today)
        groups.append({"strategy": summ,
                       "sizing": {"capital": round(a_cap, 2), "per_position": round(a_cap / summ["max_positions"], 2),
                                  "max_positions": summ["max_positions"],
                                  "sizing": "risk" if r.get("sizing") == "risk" else "equal",
                                  "risk_pct": num(r.get("risk_pct")) if r.get("sizing") == "risk" else None},
                       "orders": orders, "empty_reason": None if orders else sizing.empty_reason(summ)})
    groups.sort(key=lambda g: g["strategy"]["comparison_only"])        # stable: daily.py order within each
    track = track_svc.stats_by_strategy()
    every = [s for s in st.all_strategies(lt) if s["lifecycle"] == "active"]   # agreement ignores ?horizon=
    for g in groups:
        signal_quality.attach(g["orders"], lt, every, track)
    acting = [o for g in groups if not g["strategy"]["comparison_only"] for o in g["orders"]]
    buys = [o for o in acting if o["action"] == "BUY"]
    sells = [o for o in acting if o["action"] == "SELL"]
    # two followed strategies selling a stock you hold both size on your whole holding: count it once
    seen: set = set()
    sell_amts = []
    for o in sells:
        if o["qty_basis"] == "your_holding":
            if o["symbol"] in seen:
                continue
            seen.add(o["symbol"])
        sell_amts.append(o["amount"])
    regime_up = bool((lt.get("market") or {}).get("regime_up", True))
    return {
        "as_of": st.as_of(lt), "capital": capital, "min_position": st.min_position(lt),
        "allocations": [{"strategy_key": k, "pct": v, "capital": round(capital * v / 100, 2)} for k, v in (alloc or {}).items()],
        "allocation_source": source, "allocation_warning": warning, "sized_like_scan": source == "none",
        "regime": {"regime_up": regime_up,
                   "note": None if regime_up else "Nifty is below its 200-day average: strategies with the regime "
                                                  "filter make no new buys and only manage existing positions."},
        "groups": groups,
        "totals": {"buy_count": len(buys), "sell_count": len(sells),
                   "buy_amount": round(sum(o["amount"] or 0 for o in buys), 2),
                   "sell_amount": (round(sum(sell_amts), 2)
                                   if sell_amts and all(v is not None for v in sell_amts) else (0.0 if not sells else None)),
                   "risk_amount": round(sum(o["risk_amount"] or 0 for o in buys), 2),
                   "results_warnings": sum(1 for o in acting if o["results_warning"])},
    }


@router.get("/signals/track-record", response_model=TrackRecordResponse)
def signals_track_record(strategy: str | None = Query(None, max_length=64),
                         state: Literal["pending", "not_filled", "open", "closed"] | None = None):
    """Every BUY signal the scanner gave (journal), followed on real prices by the strategy's own rules."""
    return track_svc.payload(strategy, state)
