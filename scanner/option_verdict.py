"""Options verdict: BUY CALL, BUY PUT or NO TRADE - a buy only when the evidence says so.

Two gates, both from data, never from untested readings (PCR, max pain, OI walls and candle patterns never decide):

  1 direction  only tested sources: the outlook study's similar setups at the horizon nearest the expiry ('better'
               than the average stock with a positive median = bullish, 'worse' with a negative median = bearish),
               and today's BUY / SELL order of a strategy whose own backtest is 'working'. Both must not disagree.
  2 price      each candidate (at the money, one and two strikes out, in that direction) is valued on this stock's own
               history: every past move over the same number of trading days as the time to expiry, re-scaled to
               today's volatility and shifted by the tested drift. A buy needs that history-fair value to beat the
               price paid (the ask) plus costs by EDGE_MIN_PCT, a PROB_MIN_PCT chance of ending above the breakeven,
               a bid-ask spread under SPREAD_MAX_PCT, open interest of OI_MIN contracts and DAYS_MIN days left.

Anything else is NO TRADE, with the reasons. This has not been tested on options yet: every verdict is written to a
journal (data/results/option_verdicts.json) once a day by the scan, and scored at expiry from the stored closes, so
its real record builds up. Buying options loses money for most traders (SEBI, 2024: 93% of individual F&O traders
lost money over three years); a NO TRADE is the normal answer.
"""
from __future__ import annotations

import json
import math
from datetime import date

import numpy as np
import pandas as pd

from . import outlook as ol
from .settings import RESULTS_DIR, ist_now, ist_today

JOURNAL_FILE = RESULTS_DIR / "option_verdicts.json"
EDGE_MIN_PCT = 10.0          # history-fair value at least 10% above the price paid plus costs
PROB_MIN_PCT = 35.0          # at least a 35% chance of ending above the breakeven
SPREAD_MAX_PCT = 10.0        # bid-ask spread at most 10% of the mid price
OI_MIN = 200                 # open interest of at least 200 contracts
DAYS_MIN = 2.0               # at least two calendar days to expiry (expiry-day options are lottery tickets)
COST_PCT = 3.0               # brokerage (Rs 20 x 2 per lot), exchange, SEBI, stamp and GST: ~3% of a typical premium
EXERCISE_STT_PCT = 0.125     # STT on the settlement value of an option held to expiry in the money
STRIKES_OUT = 2
STORE_SYMBOL = {"NIFTY": "NIFTY50"}      # option underlying -> the price-store column that settles it
NOTE = ("A verdict needs a tested direction and an option that this stock's own history says is worth more than it "
        "costs; otherwise NO TRADE. Not yet tested on options: each verdict is journalled and scored at expiry. "
        "Options can lose 100% of the premium. Research, not advice: you decide.")


def _r(x, nd=2):
    return None if x is None or not np.isfinite(x) else round(float(x), nd)


def trading_days(days_cal: float) -> int:
    return max(1, int(round(days_cal * 252 / 365)))


def vols(close: pd.Series) -> dict:
    lr = np.log(close.dropna()).diff().dropna()
    f = lambda n: float(lr.iloc[-n:].std(ddof=1) * math.sqrt(252) * 100) if len(lr) >= n * 0.75 else None  # noqa: E731
    hv20, hv60, hv252 = f(20), f(60), f(252)
    parts = [v for v in (hv60, hv252) if v]
    return {"hv20_pct": hv20, "hv60_pct": hv60, "hv252_pct": hv252, "used_pct": float(np.mean(parts)) if parts else hv20}


def moves(close: pd.Series, n: int, vol_pct: float, drift_log: float) -> np.ndarray:
    """Every past n-day log move of this stock, demeaned, re-scaled to today's volatility, plus the drift."""
    c = close.dropna()
    r = np.log(c.shift(-n) / c).dropna().to_numpy()
    if len(r) < 250 or not vol_pct:
        return np.array([])
    sd = r.std(ddof=1)
    if not sd > 0:
        return np.array([])
    return (r - r.mean()) * (vol_pct / 100 * math.sqrt(n / 252) / sd) + drift_log


def direction(match: dict | None, n: int, strategies: list[dict], symbol: str) -> dict:
    """bullish / bearish / none from tested sources only, with the reasons."""
    votes, reasons = [], []
    drift, horizon = 0.0, None
    if match:
        horizon = min(ol.HORIZONS, key=lambda h: abs(h - n))
        s = match["stats"].get(str(horizon)) or {}
        v = ol.verdict(match["stats"], horizon)
        med = s.get("median_pct")
        if med is not None:
            drift = math.log(1 + med / 100) * n / horizon
        bench = match.get("benchmark") or "the average stock"
        own = f" in its own history ({match.get('setup_text')})" if match.get("source") == "index" else ""
        if v == "better" and (med or 0) > 0:
            votes.append(1)
            reasons.append(f"Similar setups{own} beat {bench} over {horizon} days ({s.get('excess_pct'):+.2f}%, "
                           f"t {s.get('t'):.1f}) with a median move of {med:+.1f}%.")
        elif v == "worse" and (med or 0) < 0:
            votes.append(-1)
            reasons.append(f"Similar setups{own} lagged {bench} over {horizon} days ({s.get('excess_pct'):+.2f}%, "
                           f"t {s.get('t'):.1f}) with a median move of {med:+.1f}%.")
        else:
            m = f"median {med:+.1f}%, " if med is not None else ""
            reasons.append(f"Similar setups{own} over {horizon} days: {m}"
                           f"{'no different from ' + bench if v == 'same' else 'no usable direction'}.")
    else:
        reasons.append("No similar-setup statistics for this symbol.")
    for s in strategies or []:
        if s.get("status") != "working" or (s.get("lifecycle") or "active") != "active":
            continue
        for a in s.get("actions") or []:
            if a.get("symbol") != symbol:
                continue
            if a.get("action") != "BUY":
                # a long-only strategy's SELL only closes its own position (stop, rebalance, trend exit): it is not
                # a forecast that the price falls, so it never counts as a bearish vote
                reasons.append(f"{s.get('name')} (backtest: working) exits its position at the next open "
                               "(an exit, not a bearish forecast: not counted).")
                continue
            votes.append(1)
            reasons.append(f"{s.get('name')} (backtest: working) buys it at the next open.")
    bias = "none"
    if votes and all(v > 0 for v in votes):
        bias = "bullish"
    elif votes and all(v < 0 for v in votes):
        bias = "bearish"
    elif votes:
        reasons.append("The tested sources disagree.")
    return {"bias": bias, "reasons": reasons, "drift_log": drift, "horizon": horizon}


def _candidates(c: dict, side: str, mv: np.ndarray, spot: float) -> list[dict]:
    rows = [r for r in c.get("rows") or [] if r.get("strike") is not None]
    if not rows or not len(mv):
        return []
    k_atm = c.get("atm") or min(rows, key=lambda r: abs(r["strike"] - spot))["strike"]
    strikes = sorted(r["strike"] for r in rows)
    i = strikes.index(min(strikes, key=lambda k: abs(k - k_atm)))
    picks = strikes[i:i + STRIKES_OUT + 1] if side == "ce" else strikes[max(0, i - STRIKES_OUT):i + 1][::-1]
    by = {r["strike"]: r for r in rows}
    st = spot * np.exp(mv)
    out = []
    for j, k in enumerate(picks):
        leg = by[k][side]
        ltp, bid, ask = leg.get("ltp"), leg.get("bid"), leg.get("ask")
        quoted = bool(ask and ask > 0 and bid and bid > 0)
        prem = ask if quoted else ltp
        if not prem or prem <= 0:
            continue
        pay = np.maximum(st - k, 0) if side == "ce" else np.maximum(k - st, 0)
        net = pay * (1 - EXERCISE_STT_PCT / 100)
        cost = prem * (1 + COST_PCT / 100)
        fair = float(net.mean())
        be = k + cost if side == "ce" else k - cost
        spread = (ask - bid) / ((ask + bid) / 2) * 100 if quoted else None
        fails = []
        edge = (fair / cost - 1) * 100
        prob = float((net > cost).mean() * 100)
        if edge < EDGE_MIN_PCT:
            fails.append(f"history-fair value {'only ' if edge > 0 else ''}{edge:+.0f}% vs the price paid (needs +{EDGE_MIN_PCT:g}%)")
        if prob < PROB_MIN_PCT:
            fails.append(f"{prob:.0f}% chance to end above the breakeven (needs {PROB_MIN_PCT:g}%)")
        if spread is not None and spread > SPREAD_MAX_PCT:
            fails.append(f"bid-ask spread {spread:.0f}% of the price (max {SPREAD_MAX_PCT:g}%)")
        if (leg.get("oi") or 0) < OI_MIN:
            fails.append(f"open interest {leg.get('oi') or 0:,} contracts (needs {OI_MIN})")
        out.append({
            "side": side, "strike": _r(k), "moneyness": "ATM" if j == 0 else f"{j} strike{'s' if j > 1 else ''} out",
            "premium": _r(prem), "bid": _r(bid), "ask": _r(ask), "quoted": quoted, "spread_pct": _r(spread, 1),
            "oi": leg.get("oi"), "iv_pct": leg.get("iv_pct"), "delta": leg.get("delta"),
            "breakeven": _r(be), "breakeven_pct": _r((be / spot - 1) * 100),
            "fair": _r(fair), "edge_pct": _r(edge, 1), "prob_profit_pct": _r(prob, 1),
            "prob_itm_pct": _r(float((pay > 0).mean() * 100), 1),
            "exp_return_pct": _r((fair / cost - 1) * 100, 1), "ok": not fails, "fails": fails,
        })
    return out


def assess(c: dict, close: pd.Series, match: dict | None, strategies: list[dict], symbol: str, *,
           last_day: str, results_on: str | None = None, support: float | None = None,
           resistance: float | None = None) -> dict:
    """The verdict for one stored chain `c` (scanner.options.analyze output) of the store symbol `symbol`."""
    spot = c.get("spot")
    days = float(c.get("days_to_expiry") or 0)
    n = trading_days(days)
    v = vols(close)
    iv = (c.get("summary") or {}).get("atm_iv_pct")
    d = direction(match, n, strategies, symbol)
    checks = []
    base = {"symbol": c.get("symbol"), "expiry": c.get("expiry"), "chain_time": c.get("time"), "spot": spot,
            "days_to_expiry": _r(days, 1), "trading_days": n, "iv_pct": iv, "hv20_pct": _r(v["hv20_pct"], 1),
            "hv252_pct": _r(v["hv252_pct"], 1), "vol_used_pct": _r(v["used_pct"], 1),
            "iv_vs_hv": _r(iv / v["used_pct"], 2) if iv and v["used_pct"] else None,
            "direction": {"bias": d["bias"], "reasons": d["reasons"]}, "edge_min_pct": EDGE_MIN_PCT,
            "prob_min_pct": PROB_MIN_PCT, "cost_pct": COST_PCT, "note": NOTE}
    old = str(c.get("time", ""))[:10] < last_day
    checks.append({"name": "Current option chain", "ok": not old,
                   "detail": f"stored {str(c.get('time', ''))[:16].replace('T', ' ')}" + (" - before the last price bar: refresh it" if old else "")})
    checks.append({"name": f"At least {DAYS_MIN:g} days to expiry", "ok": days >= DAYS_MIN, "detail": f"{days:.1f} days"})
    checks.append({"name": "Tested direction", "ok": d["bias"] != "none",
                   "detail": d["bias"] if d["bias"] != "none" else "none of the tested sources points one way"})
    mv = moves(close, n, v["used_pct"] or 0, d["drift_log"]) if spot else np.array([])
    calls, puts = _candidates(c, "ce", mv, spot), _candidates(c, "pe", mv, spot)
    if results_on and last_day <= results_on <= str(c.get("expiry")):
        checks.append({"name": "No results before expiry", "ok": False,
                       "detail": f"results on {results_on}: implied volatility usually drops right after them"})
    want = calls if d["bias"] == "bullish" else puts if d["bias"] == "bearish" else []
    good = [x for x in want if x["ok"]]
    pick = max(good, key=lambda x: x["edge_pct"]) if good else None
    if want:
        best = max(want, key=lambda x: x["edge_pct"])
        checks.append({"name": f"An option worth more than it costs (+{EDGE_MIN_PCT:g}%)", "ok": pick is not None,
                       "detail": f"best {best['strike']:,.0f} {best['side'].upper()}: " + ("; ".join(best["fails"]) or "passes")})
    blocking = [x for x in checks if not x["ok"] and not x["name"].startswith("No results")]
    if not len(mv) or not (calls or puts):
        verdict, head = "NO_DATA", "No verdict: not enough price history or option prices to value the options."
    elif old:
        verdict, head = "NO_DATA", f"No verdict: the option chain is from {str(c.get('time', ''))[:10]}. Refresh it."
    elif pick and not blocking:
        verdict = "BUY_CALL" if pick["side"] == "ce" else "BUY_PUT"
        head = (f"{'BUY CALL' if pick['side'] == 'ce' else 'BUY PUT'} {pick['strike']:,.0f} {pick['side'].upper()} at "
                f"{pick['premium']:,.2f} (expiry {c.get('expiry')}): history values it at {pick['fair']:,.2f} "
                f"({pick['edge_pct']:+.0f}% after costs) with a {pick['prob_profit_pct']:.0f}% chance of ending above "
                f"the breakeven {pick['breakeven']:,.2f}.")
    else:
        first = next((x for x in blocking), None)
        why = f"{first['name'].lower()} failed - {first['detail']}" if first else "no candidate passes"
        verdict, head = "NO_TRADE", f"No options edge: {why}."
    exit_ = None
    if verdict in ("BUY_CALL", "BUY_PUT"):
        h = (match or {}).get("stats", {}).get(str(d["horizon"])) if d["horizon"] else None
        tgt = spot * (1 + (h.get("p75_pct") if verdict == "BUY_CALL" else h.get("p25_pct")) / 100) if h else None
        exit_ = {"stop_underlying": _r(support if verdict == "BUY_CALL" else resistance),
                 "target_underlying": _r(tgt),
                 "note": ("Exit if the stock closes below the nearest support; similar setups' upper quartile is the "
                          "target" if verdict == "BUY_CALL" else "Exit if the stock closes above the nearest "
                          "resistance; similar setups' lower quartile is the target") + ". Never risk more than you "
                         "can lose in full."}
    return {**base, "verdict": verdict, "headline": head, "pick": pick, "calls": calls, "puts": puts,
            "checks": checks, "exit": exit_}


# --------------------------------------------------------------------------- journal (written by the scan)
def load_journal() -> list[dict]:
    try:
        return json.loads(JOURNAL_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def record(verdicts: list[dict], day: str) -> int:
    """Merge today's verdicts into the journal (one per underlying, expiry and day: a later scan replaces it)."""
    rows = {r["id"]: r for r in load_journal()}
    for v in verdicts:
        atm = lambda xs: (xs[0]["strike"], xs[0]["premium"]) if xs else (None, None)   # noqa: E731
        (kc, pc), (kp, pp) = atm(v.get("calls") or []), atm(v.get("puts") or [])
        rid = f"{v['symbol']}|{v['expiry']}|{day}"
        rows[rid] = {"id": rid, "day": day, "recorded_at": ist_now().isoformat(timespec="seconds"),
                     "symbol": v["symbol"], "store_symbol": v.get("store_symbol"), "expiry": v["expiry"],
                     "spot": v.get("spot"), "verdict": v["verdict"],
                     "side": (v.get("pick") or {}).get("side"), "strike": (v.get("pick") or {}).get("strike"),
                     "premium": (v.get("pick") or {}).get("premium"), "breakeven": (v.get("pick") or {}).get("breakeven"),
                     "atm_call": {"strike": kc, "premium": pc}, "atm_put": {"strike": kp, "premium": pp}}
    out = sorted(rows.values(), key=lambda r: (r["day"], r["symbol"], r["expiry"]))
    JOURNAL_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = JOURNAL_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(out, indent=0), encoding="utf-8")
    tmp.replace(JOURNAL_FILE)
    return len(verdicts)


def _payoff(side: str | None, k, prem, s_exp) -> float | None:
    if side not in ("ce", "pe") or k is None or not prem or s_exp is None:
        return None
    pay = max(s_exp - k, 0) if side == "ce" else max(k - s_exp, 0)
    return (pay * (1 - EXERCISE_STT_PCT / 100) - prem * (1 + COST_PCT / 100)) / (prem * (1 + COST_PCT / 100)) * 100


def score(rows: list[dict], closes: dict[str, pd.Series], today: date | None = None) -> list[dict]:
    """Outcome of each expired verdict (settled at the store's close on the expiry day, or the last one before it)."""
    today = today or ist_today()
    out = []
    for r in rows:
        s = closes.get(r.get("store_symbol") or STORE_SYMBOL.get(r["symbol"], r["symbol"]))
        exp = pd.Timestamp(r["expiry"])
        done = s is not None and exp.date() < today and len(s.loc[:exp].dropna())
        s_exp = float(s.loc[:exp].dropna().iloc[-1]) if done else None
        out.append({**r, "settled": bool(done), "settle_price": _r(s_exp),
                    "pick_return_pct": _r(_payoff(r.get("side"), r.get("strike"), r.get("premium"), s_exp), 1),
                    "atm_call_return_pct": _r(_payoff("ce", r["atm_call"]["strike"], r["atm_call"]["premium"], s_exp), 1),
                    "atm_put_return_pct": _r(_payoff("pe", r["atm_put"]["strike"], r["atm_put"]["premium"], s_exp), 1)})
    return out


def track(scored: list[dict]) -> dict:
    """The verdicts' record so far, and the plain 'always buy the ATM call / put' baselines for comparison."""
    done = [r for r in scored if r["settled"]]
    buys = [r for r in done if r["verdict"] in ("BUY_CALL", "BUY_PUT") and r["pick_return_pct"] is not None]
    mean = lambda xs: _r(float(np.mean(xs)), 1) if xs else None    # noqa: E731
    calls = [r["atm_call_return_pct"] for r in done if r["atm_call_return_pct"] is not None]
    puts = [r["atm_put_return_pct"] for r in done if r["atm_put_return_pct"] is not None]
    return {"recorded": len(scored), "settled": len(done), "open": len(scored) - len(done),
            "buys": len(buys), "buy_wins": sum(1 for r in buys if r["pick_return_pct"] > 0),
            "buy_avg_return_pct": mean([r["pick_return_pct"] for r in buys]),
            "no_trades": sum(1 for r in done if r["verdict"] == "NO_TRADE"),
            "atm_call_avg_return_pct": mean(calls), "atm_put_avg_return_pct": mean(puts),
            "first_day": scored[0]["day"] if scored else None}


def record_stored_chains(frames: dict[str, pd.DataFrame], latest: dict, log=print) -> int:
    """The scan's hook: today's verdict for every stored, unexpired chain of today (latest chain of each)."""
    from . import options as opt
    study = ol.load()
    lt = opt.load_latest()
    day = ist_today().isoformat()
    refs = [x for x in (lt.get("chains") or {}).values() if isinstance(x, dict) and str(x.get("day")) == day
            and str(x.get("expiry", "")) >= day]
    if not refs:
        return 0
    close = frames["close"]
    uni = [s for s in close.columns if s in set(latest.get("symbols") or close.columns)]
    member = pd.DataFrame(np.broadcast_to(close.columns.isin(uni), close.shape), index=close.index, columns=close.columns)
    feats = ol.features({k: frames[k] for k in ("open", "high", "low", "close", "volume")}, member)
    out = []
    for ref in refs:
        sym = STORE_SYMBOL.get(ref["symbol"], ref["symbol"])
        if sym not in close.columns:
            continue
        try:
            snaps = pd.read_parquet(opt.snap_file(date.fromisoformat(ref["day"]), ref["symbol"], date.fromisoformat(ref["expiry"])))
            cur, when = opt.chain_at(snaps)
            spot = float(snaps.loc[pd.to_datetime(snaps["time"]) == when, "spot"].iloc[0])
            a = opt.analyze(cur, {"symbol": ref["symbol"], "expiry": date.fromisoformat(ref["expiry"]), "spot": spot,
                                  "time": when.to_pydatetime()}, opt.settings()["risk_free_pct"])
        except Exception as e:     # a damaged snapshot file: skip that chain
            log(f"Options verdict: {ref['symbol']} {ref['expiry']} skipped ({type(e).__name__})")
            continue
        s = close[sym].dropna()
        codes = {k: (None if not np.isfinite(feats[k].at[s.index[-1], sym]) else int(feats[k].at[s.index[-1], sym]))
                 for k in ol.FEATURES}
        m = ol.match(study, codes) if study else None
        v = assess(a, s, m, latest.get("strategies") or [], sym, last_day=s.index[-1].date().isoformat())
        out.append({**v, "store_symbol": sym})
    n = record(out, day)
    log(f"Options verdicts journalled: {n} chain(s) ({', '.join(f'{v['symbol']} {v['verdict']}' for v in out)})")
    return n
