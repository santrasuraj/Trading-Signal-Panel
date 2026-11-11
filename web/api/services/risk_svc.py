"""Portfolio risk (GET /api/risk): how much your holdings can lose, and how concentrated they are.

  * Money at risk to your stops: (price - stop) x quantity per lot, the stop from holdings.csv's stop-loss % (or the
    default). A gap through the stop loses more: this is the planned loss, not the worst case.
  * Concentration: weights by value, the largest holding and industry, and the "effective number of stocks"
    (1 / sum of squared weights: 10 equal holdings = 10, one big one among small ones = close to 1).
  * Beta to the Nifty 50 (last year's daily returns): 1.2 = moves 12% when the Nifty moves 10%.
  * One-day loss estimate (value at risk): today's holdings replayed over the last two years of daily returns; on 1
    day in 20 (95%) or 1 in 100 (99%) the loss was at least this much. Expected shortfall = the average of those bad
    days. The worst day in the store for today's holdings, and what -5/-10/-20% on the Nifty would do through beta.
  * Correlation between holdings (last year's daily returns): pairs that move together above 0.7 give less
    diversification than their count suggests.
History-based numbers assume the next year looks like the last ones: a crash worse than any in the window isn't in them.
"""
from __future__ import annotations

import math
from datetime import date

import numpy as np
import pandas as pd

from scanner.providers import INDEX_NIFTY

from . import data, quotes_svc
from ..util import num, today_ist

BETA_DAYS = 250
VAR_DAYS = 500
CORR_DAYS = 250
MAX_CORR = 25
HIGH_CORR = 0.7
BIG_STOCK_PCT = 20.0
BIG_INDUSTRY_PCT = 35.0
SHOCKS = (-5.0, -10.0, -20.0)


def positions(holdings: pd.DataFrame, prices: dict[str, float], default_sl: float) -> tuple[list[dict], list[dict]]:
    """(per-symbol positions, per-lot stop rows) from holdings.csv rows and current prices."""
    lots, pos = [], {}
    for r in holdings.itertuples(index=False):
        qty, buy, px = num(r.qty), num(r.buy_price), prices.get(r.symbol)
        if not qty or px is None:
            continue
        sl = num(r.stop_loss_pct) or default_sl
        stop = buy * (1 - sl / 100) if buy else px * (1 - sl / 100)
        hit = px <= stop
        lots.append({"symbol": r.symbol, "qty": qty, "price": px, "stop": round(stop, 2), "stop_pct": sl,
                     "stop_hit": hit, "at_risk": 0.0 if hit else round((px - stop) * qty, 2),
                     "loss_if_hit": round((stop - buy) * qty, 2) if buy else None})
        p = pos.setdefault(r.symbol, {"symbol": r.symbol, "qty": 0.0, "price": px, "value": 0.0, "at_risk": 0.0})
        p["qty"] += qty
        p["value"] += qty * px
        p["at_risk"] += lots[-1]["at_risk"]
    return list(pos.values()), lots


def _returns(close: pd.DataFrame, syms: list[str], days: int) -> pd.DataFrame:
    c = close[[s for s in syms if s in close.columns]].iloc[-(days + 1):]
    return c.pct_change(fill_method=None).iloc[1:]


def beta(stock: pd.Series, index: pd.Series) -> float | None:
    both = pd.concat([stock, index], axis=1).dropna()
    if len(both) < 60 or both.iloc[:, 1].var() == 0:
        return None
    return float(both.cov().iloc[0, 1] / both.iloc[:, 1].var())


def var_es(port: pd.Series, value: float) -> dict:
    """Historical one-day value at risk and expected shortfall (rupees, positive = a loss)."""
    r = port.dropna()
    if len(r) < 100:
        return {}
    out = {"days": int(len(r))}
    for lvl in (95, 99):
        q = float(np.percentile(r, 100 - lvl))
        tail = r[r <= q]
        out[f"var{lvl}"] = round(-q * value, 2)
        out[f"var{lvl}_pct"] = round(-q * 100, 2)
        out[f"es{lvl}"] = round(-float(tail.mean()) * value, 2) if len(tail) else None
    out["vol_pct"] = round(float(r.std() * math.sqrt(252) * 100), 2)
    return out


def analyse(holdings: pd.DataFrame, prices: dict[str, float], close: pd.DataFrame, industries: dict[str, str],
            default_sl: float) -> dict:
    pos, lots = positions(holdings, prices, default_sl)
    total = sum(p["value"] for p in pos)
    if not pos or total <= 0:
        return {"empty": True, "positions": [], "lots": [], "notes": ["No holdings with a quantity and a price yet: add "
                                                                       "them on Portfolio."]}
    for p in pos:
        p["weight_pct"] = round(p["value"] / total * 100, 2)
        p["industry"] = industries.get(p["symbol"]) or "Unknown"
        p["value"] = round(p["value"], 2)
        p["at_risk"] = round(p["at_risk"], 2)
    pos.sort(key=lambda p: -p["value"])
    w = {p["symbol"]: p["value"] / total for p in pos}
    hhi = sum(x * x for x in w.values())
    by_ind: dict[str, float] = {}
    for p in pos:
        by_ind[p["industry"]] = by_ind.get(p["industry"], 0.0) + p["weight_pct"]
    industries_out = [{"industry": k, "weight_pct": round(v, 2)} for k, v in sorted(by_ind.items(), key=lambda x: -x[1])]

    syms = [p["symbol"] for p in pos]
    nifty = close[INDEX_NIFTY].pct_change(fill_method=None) if INDEX_NIFTY in close.columns else None
    rets_b = _returns(close, syms, BETA_DAYS)
    for p in pos:
        p["beta"] = (round(b, 2) if nifty is not None and p["symbol"] in rets_b.columns
                     and (b := beta(rets_b[p["symbol"]], nifty.reindex(rets_b.index))) is not None else None)
    have_beta = [p for p in pos if p["beta"] is not None]
    wb = sum(p["weight_pct"] for p in have_beta)
    port_beta = round(sum(p["beta"] * p["weight_pct"] for p in have_beta) / wb, 2) if wb > 0 else None

    rets_v = _returns(close, syms, VAR_DAYS)
    cover = sum(w[s] for s in rets_v.columns)
    risk: dict = {}
    worst = None
    if len(rets_v.columns):
        ww = pd.Series({s: w[s] for s in rets_v.columns}) / cover
        port = (rets_v.fillna(0.0) * ww).sum(axis=1)
        risk = var_es(port, total)
        if risk:
            risk["covered_pct"] = round(cover * 100, 1)
        full = close[list(rets_v.columns)].pct_change(fill_method=None).fillna(0.0)
        hist = (full * ww).sum(axis=1).iloc[1:]
        if len(hist):
            d = hist.idxmin()
            worst = {"date": d.date().isoformat(), "pct": round(float(hist.min()) * 100, 2),
                     "amount": round(float(hist.min()) * total, 2),
                     "nifty_pct": (round(float(nifty.get(d)) * 100, 2) if nifty is not None and pd.notna(nifty.get(d))
                                   else None)}
        eq = (1 + port).cumprod()
        dd = float((eq / eq.cummax() - 1).min()) if len(eq) else None
        risk["max_drawdown_pct"] = round(dd * 100, 2) if dd is not None else None
    if nifty is not None:
        nv = nifty.iloc[-VAR_DAYS:].dropna()
        risk["nifty_vol_pct"] = round(float(nv.std() * math.sqrt(252) * 100), 2) if len(nv) > 50 else None

    corr_syms = syms[:MAX_CORR]
    rets_c = _returns(close, corr_syms, CORR_DAYS)
    rets_c = rets_c.loc[:, rets_c.notna().sum() >= 60]
    corr = rets_c.corr() if rets_c.shape[1] >= 2 else pd.DataFrame()
    pairs = []
    if len(corr):
        cols = list(corr.columns)
        for i in range(len(cols)):
            for j in range(i + 1, len(cols)):
                v = corr.iat[i, j]
                if pd.notna(v) and v >= HIGH_CORR:
                    pairs.append({"a": cols[i], "b": cols[j], "corr": round(float(v), 2)})
        tri = corr.where(np.triu(np.ones(corr.shape, dtype=bool), 1)).stack()
        avg_corr = round(float(tri.mean()), 2) if len(tri) else None
    else:
        avg_corr = None
    pairs.sort(key=lambda x: -x["corr"])

    at_risk = round(sum(lt["at_risk"] for lt in lots), 2)
    flags = []
    top = pos[0]
    if top["weight_pct"] > BIG_STOCK_PCT:
        flags.append(f"{top['symbol']} is {top['weight_pct']:.0f}% of the portfolio: one stock's bad news is a big hit.")
    if industries_out and industries_out[0]["weight_pct"] > BIG_INDUSTRY_PCT and len(pos) > 1:
        flags.append(f"{industries_out[0]['industry']} is {industries_out[0]['weight_pct']:.0f}% of the portfolio.")
    hit = [lt["symbol"] for lt in lots if lt["stop_hit"]]
    if hit:
        flags.append(f"Below the stop already: {', '.join(sorted(set(hit)))}.")
    if pairs:
        flags.append(f"{len(pairs)} pair(s) of holdings move together (correlation >= {HIGH_CORR}).")
    if port_beta is not None and port_beta > 1.2:
        flags.append(f"Beta {port_beta:.2f}: the portfolio moves more than the Nifty, both ways.")
    return {
        "empty": False, "value": round(total, 2), "count": len(pos), "positions": pos, "lots": lots,
        "at_risk": at_risk, "at_risk_pct": round(at_risk / total * 100, 2),
        "concentration": {"top_pct": top["weight_pct"], "top_symbol": top["symbol"],
                          "top5_pct": round(sum(p["weight_pct"] for p in pos[:5]), 2),
                          "effective_n": round(1 / hhi, 1) if hhi > 0 else None, "industries": industries_out},
        "beta": port_beta, "risk": risk, "worst_day": worst,
        "shocks": [{"nifty_pct": s, "pct": round(port_beta * s, 2), "amount": round(port_beta * s / 100 * total, 2)}
                   for s in SHOCKS] if port_beta is not None else [],
        "correlation": {"symbols": list(corr.columns) if len(corr) else [],
                        "matrix": [[round(float(v), 2) if pd.notna(v) else None for v in row] for row in corr.to_numpy()]
                        if len(corr) else [], "high_pairs": pairs, "average": avg_corr},
        "flags": flags, "notes": [],
    }


def view() -> dict:
    h = data.holdings_df()
    syms = sorted({str(s) for s in h["symbol"]}) if len(h) else []
    prices, source = {}, "close"
    if syms:
        q = quotes_svc.quotes(syms)
        prices = {x["symbol"]: float(x["price"]) for x in q["quotes"] if x.get("price")}
        source = q.get("source", "close")
    uni = data.universe()
    industries = dict(zip(uni["symbol"], uni["industry"])) if len(uni) else {}
    hd = data.config().get("holdings_defaults") or {}
    try:
        close = data.store_close()
    except Exception:
        close = pd.DataFrame()
    out = analyse(h, prices, close, industries, num(hd.get("stop_loss_pct")) or 8.0)
    out["price_source"] = source
    out["as_of"] = today_ist().isoformat()
    return out


def trail_suggestion(symbol: str, pct: float = 8.0) -> dict:
    """A trailing stop for a real holding: `pct` under the highest close since it was bought (holdings.csv buy date,
    else Quant Desk's recorded fills, else the last 20 sessions). Information only: the Orders page's Protect places
    it after you confirm (cancel the old GTT first)."""
    from scanner import fills
    sym = symbol.upper()
    since = None
    try:
        h = data.holdings_df()
        ds = [d for d in h.loc[h["symbol"] == sym, "buy_date"] if isinstance(d, date) and not pd.isna(d)]
        since = min(ds) if ds else None
    except Exception:
        pass
    if since is None:
        try:
            _, still = fills.round_trips(fills.read())
            ts = [pd.Timestamp(x["time"]).date() for x in still if x.get("symbol") == sym and x.get("time")]
            since = min(ts) if ts else None
        except Exception:
            pass
    try:
        c = data.store_close()[sym].dropna()
    except Exception:
        c = pd.Series(dtype=float)
    basis = "since you bought" if since else "over the last 20 sessions"
    c = c[c.index >= pd.Timestamp(since)] if since else c.iloc[-20:]
    q = quotes_svc.quotes([sym]).get("quotes") or []
    live = float(q[0]["price"]) if q and q[0].get("price") else None
    if c.empty and live is None:
        return {"symbol": sym, "stop": None, "note": "No prices for this stock."}
    high, when = (float(c.max()), c.idxmax().date().isoformat()) if len(c) else (live, today_ist().isoformat())
    if live is not None and live > high:
        high, when = live, today_ist().isoformat()
    stop = round(round(high * (1 - pct / 100) / 0.05) * 0.05, 2)
    return {"symbol": sym, "since": since.isoformat() if since else None, "high": round(high, 2), "high_date": when,
            "pct": pct, "stop": stop, "price": live,
            "note": f"{pct:g}% under the highest close {basis} (₹{high:,.2f} on {when}). Cancel the old GTT before "
                    "protecting with the new stop."}
