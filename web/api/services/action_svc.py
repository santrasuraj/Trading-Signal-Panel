"""One answer per stock: BUY, SELL (exit), HOLD or NO EDGE - taken only from tested rules.

  BUY      a strategy whose own backtest is working (active, not comparison-only) buys it at the next open in the
           latest scan, and no working strategy exits it. If you already hold it, the answer is HOLD.
  SELL     you hold it, and a working strategy exits it at the next open, or your own stop-loss is hit.
  HOLD     you hold it and no exit fired.
  NO EDGE  anything else, with how close each working strategy is to acting on it.

Buys of strategies whose backtest is mixed or too new appear as "unproven buy" lines, never as the answer.
Strategies that are not working never appear. Risk facts (results soon, F&O ban, regime filter, a provisional
intraday scan) are chips that never change the answer. Claude, patterns, option positioning and F&O build-ups
never decide it: none of them shows an edge after costs in this app's own tests.

A model exit for a stock you don't hold is irrelevant to you (NO EDGE). This is the scan's research for your own
use; you decide.
"""
from __future__ import annotations

from datetime import date

from scanner import big_money, late_entry

from . import data, holdings_svc, paper_svc, signal_quality, sizing, strategies as st, track_svc
from . import results as results_svc
from ..util import fmt_date, num, today_ist

STATES = ("BUY", "SELL", "HOLD", "NO_EDGE")
NOTE = ("BUY and SELL come only from strategies whose own survivorship-free backtest, after Indian costs and tax, is "
        "working. Everything else is NO EDGE: no tested rule acts on this stock today. Research for your own "
        "decisions, not advice.")


def _record(tr: dict | None) -> tuple[str, str]:
    tr = tr or {}
    level = tr.get("level") if tr.get("level") in ("good", "bad") else "unknown"
    return level, str(tr.get("verdict") or "No live signals recorded yet")


def _evidence(s: dict, summ: dict, track: dict) -> dict:
    h = summ["headline"]
    tm = summ.get("timing") or {}
    level, verdict = _record(track.get(s["key"]))
    return {"strategy_key": s["key"], "strategy_name": summ["name"], "status": s["status"], "horizon": s["horizon"],
            "cagr_pct": h.get("cagr_pct"), "after_tax_cagr_pct": h.get("after_tax_cagr_pct"),
            "max_dd_pct": h.get("max_dd_pct"), "trades": h.get("trades"),
            "timing_low_pct": tm.get("low"), "timing_high_pct": tm.get("high"),
            "live_level": level, "live_verdict": verdict}


def _order_view(o: dict, ev: dict) -> dict:
    stg = o.get("strength") or {}
    return {**ev, "action": o["action"], "price": o["price"], "qty": o["qty"], "amount": o["amount"], "stop": o["stop"],
            "stop_distance_pct": o["stop_distance_pct"], "risk_amount": o["risk_amount"], "reason": o["reason"],
            "provisional": o["provisional"], "below_min_position": o["below_min_position"],
            "strength_score": stg.get("score"), "strength_grade": stg.get("grade"), "late_days": None, "late_lag": None}


class Context:
    """Everything one scan says, loaded once for all symbols (the Today page asks for many)."""

    def __init__(self):
        self.lt = st.require_latest()
        self.today = today_ist()
        papers = paper_svc.summaries()
        self.active = [s for s in st.all_strategies(self.lt) if s["lifecycle"] == "active"]
        self.summ = {s["key"]: st.summary(s, self.lt, papers) for s in self.active}
        alloc, _, _ = sizing.resolve(None, [s["key"] for s in self.active])
        held = data.holdings_qty()
        self.track = track_svc.stats_by_strategy()
        self.orders: dict[str, list[dict]] = {}
        all_orders = []
        for s in self.active:
            for o in sizing.orders_for(s, self.lt, alloc, held, self.today):
                all_orders.append(o)
                self.orders.setdefault(o["symbol"], []).append(o)
        signal_quality.attach(all_orders, self.lt, self.active, self.track)
        rows, _ = holdings_svc.rows(self.lt)
        self.holdings: dict[str, dict] = {}
        for r in rows:                                   # several lots of one symbol: the first lot's health
            self.holdings.setdefault(r["symbol"], r)
        self.by_key = {s["key"]: s for s in self.active}
        try:
            self.results = {e["symbol"]: e["date"] for e in results_svc.events(self.lt, days=14)["events"]}
        except Exception:
            self.results = {}
        try:
            self.ban = set((big_money.load_ban() or {}).get("symbols") or [])
        except Exception:
            self.ban = set()
        self.warn_days = sizing.warn_days()
        from . import late_entry_svc
        self.late = late_entry_svc.report(wait=False)      # None until computed (in the background, a few seconds)

    def working(self, s: dict) -> bool:
        return s["status"] == "working" and not st.comparison_only(s)


def _near(ctx: Context, sym: str) -> list[str]:
    """How close each working strategy is to acting on `sym` (only facts the scan already computed)."""
    out = []
    for s in ctx.active:
        if not ctx.working(s):
            continue
        summ = ctx.summ[s["key"]]
        r, _ = st.rules(s)
        pos = next((p for p in s.get("positions") or [] if p.get("symbol") == sym), None)
        if pos:
            out.append(f"{summ['name']} holds it in its model portfolio since {fmt_date(pos.get('entry_date'))}: it "
                       f"was bought on an earlier signal; the strategy does not add to it today.")
            continue
        rk = next((x for x in s.get("ranking") or [] if x.get("symbol") == sym), None)
        if rk and s["kind"] == "rank":
            top = r.get("top_n") or summ["max_positions"]
            nxt = summ.get("next_rebalance")
            out.append(f"{summ['name']}: ranked #{int(rk.get('rank') or 0)}; it buys the top {top} "
                       + (f"at its next review on {fmt_date(nxt, year=False)}." if nxt else "at its next review."))
        if summ.get("blocked_by_regime"):
            out.append(f"{summ['name']}: regime filter on (Nifty below its 200-day average): no new buys.")
    return out[:6]


def _late_buy(ctx: Context, sym: str) -> dict | None:
    """A working strategy holds `sym` in its model (bought on an earlier day) and its late-entry test at that delay
    shows an edge after costs (scanner/late_entry.py): an order to join it now, else None."""
    if ctx.late is None:
        return None
    best = None
    for s in ctx.active:
        if not ctx.working(s):
            continue
        p = next((x for x in s.get("positions") or [] if x.get("symbol") == sym), None)
        if p is None or p.get("days") is None:
            continue
        days = int(p["days"])
        lag = late_entry.lag_for(days)
        res = ((ctx.late.get("strategies") or {}).get(s["key"]) or {}).get("lags", {}).get(str(lag)) if lag else None
        if not res or res.get("verdict") != "edge":
            continue
        summ = ctx.summ[s["key"]]
        price = num(p.get("last_price"))
        per = num(summ.get("per_position")) or 0.0
        qty = int(per // price) if price and per else None
        stop = num(p.get("stop"))
        o = {**_evidence(s, summ, ctx.track), "action": "BUY", "price": price, "qty": qty,
             "amount": round(qty * price, 2) if qty and price else None, "stop": stop,
             "stop_distance_pct": round((stop / price - 1) * 100, 2) if stop and price else None,
             "risk_amount": round(qty * (price - stop), 2) if qty and price and stop else None,
             "reason": (f"Late entry: the model bought on {fmt_date(p.get('entry_date'))} ({days} trading days ago). "
                        f"Joining up to {lag} days late: {res['after_cost_pct']:+.2f}% vs the average stock after costs, "
                        f"t {res['t']:.1f}, {res['n']} late trades."),
             "provisional": bool(ctx.lt.get("live")), "below_min_position": bool(qty and price and qty * price < st.min_position(ctx.lt)),
             "strength_score": None, "strength_grade": None, "late_days": days, "late_lag": lag}
        if best is None or (res.get("t") or 0) > (best.get("_t") or 0):
            best = {**o, "_t": res.get("t") or 0}
    if best:
        best.pop("_t", None)
    return best


def _risks(ctx: Context, sym: str, provisional: bool) -> list[dict]:
    out = []
    ro = ctx.results.get(sym)
    if ro:
        try:
            d = (date.fromisoformat(ro) - ctx.today).days
        except ValueError:
            d = None
        if d is not None and 0 <= d <= ctx.warn_days:
            out.append({"kind": "results", "text": f"Results {'today' if d == 0 else f'in {d} day(s)'} ({fmt_date(ro, year=False)}): "
                                                   "the stock can gap either way."})
    if sym in ctx.ban:
        out.append({"kind": "ban", "text": "In the F&O ban period: no new F&O positions (cash trades allowed)."})
    if any(ctx.summ[s["key"]].get("blocked_by_regime") for s in ctx.active if ctx.working(s)):
        out.append({"kind": "regime", "text": "Regime filter on: Nifty is below its 200-day average."})
    if provisional:
        out.append({"kind": "provisional", "text": "Provisional: from an intraday scan on live prices; final after "
                                                    "NSE's official close (~18:00)."})
    return out


def card(ctx: Context, sym: str) -> dict:
    sym = sym.upper()
    meta = data.symbol_meta().get(sym, {})
    orders = ctx.orders.get(sym, [])
    working_buys, working_sells, unproven = [], [], []
    for o in orders:
        s = ctx.by_key.get(o["strategy_key"])
        if s is None or s["status"] == "not-working" or o["comparison_only"]:
            continue                                          # not working: never shown
        ev = _evidence(s, ctx.summ[s["key"]], ctx.track)
        if not ctx.working(s):
            if o["action"] == "BUY":
                unproven.append(_order_view(o, ev))
            continue
        (working_buys if o["action"] == "BUY" else working_sells).append(_order_view(o, ev))
    working_buys.sort(key=lambda x: -(x.get("strength_score") or 0))
    h = ctx.holdings.get(sym)
    held = bool(h and (h.get("qty") or 0) > 0)
    stop_hit = bool(held and h.get("level") == "danger")
    provisional = bool(any(o["provisional"] for o in orders) or ctx.lt.get("live"))
    if held and (working_sells or stop_hit):
        state = "SELL"
        why = working_sells[0]["strategy_name"] + " exits it at the next open" if working_sells else "your stop-loss is hit"
        headline = f"SELL (exit): {why}."
        primary = working_sells[0] if working_sells else None
    elif held:
        state = "HOLD"
        primary = working_buys[0] if working_buys else None
        stop = h.get("stop_price")
        headline = ("HOLD: you own it and no exit has fired"
                    + (f"; your stop-loss is {num(stop):,.2f}" if num(stop) else "") + "."
                    + (f" {working_buys[0]['strategy_name']} (working) also buys it." if working_buys else ""))
    elif working_buys and not working_sells:
        state = "BUY"
        primary = working_buys[0]
        stop = primary.get("stop")
        headline = (f"BUY at the next open: {primary['strategy_name']} (backtest working"
                    + (f", {primary['cagr_pct']:+.1f}%/yr after costs" if isinstance(primary.get("cagr_pct"), (int, float)) else "")
                    + ")" + (f", stop {stop:,.2f}" if isinstance(stop, (int, float)) else "") + ".")
    elif not working_sells and (late := _late_buy(ctx, sym)) is not None:
        state, primary = "BUY", late
        stop = late.get("stop")
        headline = (f"BUY (late entry): {late['strategy_name']} bought it {late['late_days']} trading days ago and still "
                    f"holds it; joining up to {late['late_lag']} days late still beat the average stock after costs in its "
                    f"backtest" + (f". Stop {stop:,.2f}" if isinstance(stop, (int, float)) else "") + ".")
    else:
        state = "NO_EDGE"
        primary = None
        if working_buys and working_sells:
            headline = "NO EDGE: working strategies disagree (one buys, one exits)."
        elif unproven:
            headline = (f"NO EDGE: only {'an unproven strategy' if len(unproven) == 1 else 'unproven strategies'} "
                        "buy it today (backtest mixed or too new).")
        else:
            headline = "NO EDGE: no tested rule acts on this stock today."
    others = [x for x in (working_buys if state in ("BUY", "HOLD") else working_sells) if x is not primary]
    return {
        "symbol": sym, "company": meta.get("company"), "industry": meta.get("industry"),
        "state": state, "headline": headline, "provisional": provisional,
        "primary": primary, "others": others, "unproven": unproven,
        "exits": working_sells if state != "SELL" else working_sells[1:],
        "holding": ({"qty": h.get("qty"), "buy_price": h.get("buy_price"), "price": h.get("price"),
                     "pnl_pct": h.get("pnl_pct"), "pnl_amount": h.get("pnl_amount"), "stop_price": h.get("stop_price"),
                     "target_price": h.get("target_price"), "level": h.get("level"), "alerts": list(h.get("alerts") or [])}
                    if held else None),
        "near": _near(ctx, sym) if state == "NO_EDGE" or not primary else [],
        "risks": _risks(ctx, sym, provisional),
        "as_of": st.as_of(ctx.lt), "note": NOTE, "pending": _pending(ctx),
    }


def _pending(ctx: Context) -> list[str]:
    """Checks still computing in the background whose answer could change a card (the page polls until done)."""
    holds = any(ctx.working(s) and s.get("positions") for s in ctx.active)
    return ["late_entry"] if ctx.late is None and holds else []


def one(sym: str) -> dict:
    return card(Context(), sym)


def _journal_days() -> dict:
    """How many of the last 30 journalled sessions had at least one tested BUY or SELL (paper journal)."""
    try:
        import sqlite3

        from ..paths import P
        if not P.journal.exists():
            return {"sessions": 0, "with_actions": 0}
        con = sqlite3.connect(f"file:{P.journal}?mode=ro", uri=True)
        try:
            days = [r[0] for r in con.execute("select distinct date from scans order by date desc limit 30")]
            acted = {r[0] for r in con.execute("select distinct date from orders")} if days else set()
        finally:
            con.close()
        return {"sessions": len(days), "with_actions": sum(1 for d in days if d in acted)}
    except Exception:
        return {"sessions": 0, "with_actions": 0}


def today() -> dict:
    """Every BUY and SELL for today (holdings first), every HOLD, and how often tested actions happen."""
    ctx = Context()
    syms: list[str] = list(ctx.holdings)
    for sym, os_ in ctx.orders.items():
        if sym not in syms and any(ctx.working(ctx.by_key[o["strategy_key"]]) for o in os_ if o["strategy_key"] in ctx.by_key):
            syms.append(sym)
    if ctx.late is not None:                        # stocks a working strategy holds: candidates for a late-entry BUY
        for s in ctx.active:
            if ctx.working(s):
                for p in s.get("positions") or []:
                    if p.get("symbol") and p["symbol"] not in syms:
                        syms.append(p["symbol"])
    cards = [card(ctx, s) for s in syms]
    acts = [c for c in cards if c["state"] in ("BUY", "SELL")]
    acts.sort(key=lambda c: (c["state"] != "SELL", -((c["primary"] or {}).get("strength_score") or 0)))
    holds = [c for c in cards if c["state"] == "HOLD"]
    unproven = sorted({u["strategy_name"] for c in cards for u in c["unproven"]})
    hist = _journal_days()
    if acts:
        empty = None
    elif _pending(ctx):
        empty = "Checking which held stocks can still be joined late (late-entry test, a few seconds)..."
    else:
        empty = ("No tested BUY or SELL today: no working strategy acts at the next open."
                 + (f" For comparison, the paper journal has model orders (any strategy) on {hist['with_actions']} of "
                    f"its last {hist['sessions']} sessions." if hist["sessions"] else ""))
    return {"as_of": st.as_of(ctx.lt), "actions": acts, "holds": holds,
            "counts": {"buy": sum(c["state"] == "BUY" for c in acts), "sell": sum(c["state"] == "SELL" for c in acts),
                       "hold": len(holds)},
            "unproven_strategies": unproven, "history": hist, "empty_note": empty, "note": NOTE,
            "pending": _pending(ctx)}
