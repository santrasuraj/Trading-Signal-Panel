"""Options signals: the app's directional signals turned into concrete option trades, and volatility (IV rank) trades -
each with its contract, entry premium, stop and target in premium, lot, capital, maximum loss and exact charges,
labelled with its evidence, journalled and scored on real option prices.

Sources
  intraday    every open intraday signal on an F&O stock (Signals > Intraday) -> buy the CE (LONG) or PE (SHORT) of the
              nearest expiry with MIN_DAYS_NEAR+ days left, the strike nearest DELTA_NEAR; same day, squared off by 15:00
  stock       every BUY of a daily strategy whose backtest is 'working' (the last scan) on an F&O stock -> buy a call
              with MIN_DAYS_MONTH+ days left (next month when the current one is too close), the strike nearest
              DELTA_MONTH (in the money: less time decay per rupee); exits with the strategy, its stop, or near expiry
  volatility  F&O underlyings whose ~30-day IV rank and percentile (scanner/iv_history.py) are both IV_HIGH+ -> sell a
              defined-risk iron condor (shorts near CONDOR_DELTA, wings about WING_PCT of the price further, credit at
              least MIN_CREDIT_OF_WIDTH of the width) on the monthly expiry nearest 30 days; take profit at half the credit, stop at a loss of one credit, close VOL_CLOSE_DAYS before
              expiry. Both IV_LOW- -> buy the at-the-money straddle (no evidence; labelled untested)
  index       the daily BUY CALL / BUY PUT verdicts for the NSE indices (scanner/option_verdict.py) - shown with their
              own record; a NO TRADE is shown with its reasons
Prices come from NSE's live option chain (option-chain-v3, ~a minute old at worst); a buy fills at the ask, a sell at the
bid. Stop and target premiums are the option re-priced (Black-76, the strike's implied volatility) at the underlying's stop
and target, a little time later (HOLD_DAYS): a guide, since volatility moves too. Charges: FYERS' brokerage, NSE / SEBI
fees, stamp duty, GST and STT per leg (scanner/options_backtest.py, the same as the options backtester).

Evidence: each signal carries its underlying strategy's backtest label, and its source's own forward record. The
directional option sources cannot be backtested here (no stored intraday option prices); the volatility source is
backtested on NSE's daily option history of NIFTY and BANKNIFTY (vol_backtest). Journal: data/results/option_signals.json;
the nightly F&O download closes and scores what is left at NSE's official closing price (settle_day). Practice only:
nothing here sends an order.
"""
from __future__ import annotations

import json
import math
import time
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd

from . import option_verdict as ov
from . import options as opt
from .options_backtest import _charges
from .settings import RESULTS_DIR, ist_now

FILE = RESULTS_DIR / "option_signals.json"
LOCK = RESULTS_DIR / ".option_signals.lock"
R = 0.065
DELTA_NEAR, DELTA_MONTH = 0.55, 0.70
MIN_DAYS_NEAR, MIN_DAYS_MONTH = 2, 25
HOLD_DAYS = {"intraday": 0.1, "stock": 10.0}         # time assumed to pass before the stop / target is reached
IV_HIGH, IV_LOW = 70.0, 15.0
CONDOR_DELTA, WING_STEPS = 0.16, 2           # shorts near 0.16 delta; wings at least WING_STEPS strikes further
WING_PCT = {"index": 1.5, "stock": 4.0}       # ... and about this % of the price further (a defined, useful width)
MIN_CREDIT_OF_WIDTH = 0.15                    # a condor collecting less than 15% of its width is not worth the risk
VOL_TARGET_PCT, VOL_STOP_PCT, VOL_CLOSE_DAYS = 50.0, 100.0, 5
VOL_MIN_DAYS = 10            # a volatility trade's expiry is at least this far (it is closed VOL_CLOSE_DAYS before)
STRADDLE_TARGET_PCT, STRADDLE_STOP_PCT = 50.0, 35.0
OI_MIN, SPREAD_MAX_PCT = 200, 10.0
MAX_NEW = {"intraday": 10, "stock": 10, "volatility": 6}
SQUARE_OFF = (15, 0)
MAX_LATE_MIN = 15.0         # an intraday signal becomes an option only this soon after its entry bar starts (the
                            # 5-minute task's signals arrive up to ~10 min after it; later, the price has moved on)
CHAIN_TTL_S = 60
SOURCES = {"intraday": "From intraday signals", "stock": "From stock strategies", "volatility": "Volatility (IV rank)",
           "index": "Index verdicts"}
_chains: dict = {}


# ------------------------------------------------------------------ journal
def load() -> list[dict]:
    try:
        rows = json.loads(FILE.read_text(encoding="utf-8"))
        return rows if isinstance(rows, list) else []
    except (OSError, ValueError):
        return []


def _save(rows: list[dict]) -> None:
    FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(rows[-5000:], default=str), encoding="utf-8")
    tmp.replace(FILE)


def _lock():
    from .intraday.data import FileLock
    return FileLock(LOCK, timeout=20.0)


# ------------------------------------------------------------------ option chains
def _pick_expiry(exps: list[date], today: date, rule: str) -> date | None:
    days = [(e, (e - today).days) for e in exps]
    if rule == "near":
        ok = [e for e, d in days if d >= MIN_DAYS_NEAR]
        return ok[0] if ok else None
    if rule == "month":
        ok = [e for e, d in days if d >= MIN_DAYS_MONTH]
        return ok[0] if ok else None
    ok = vol_expiries(exps, today)
    return ok[0] if ok else None


def vol_expiries(exps: list[date], today: date) -> list[date]:
    """The MONTHLY expiries at least VOL_MIN_DAYS out, nearest 30 days first (an index's far weekly expiries and a
    stock's next month have little open interest, so the next one is the fallback)."""
    monthly: dict = {}
    for e in exps:
        monthly[(e.year, e.month)] = max(monthly.get((e.year, e.month), e), e)
    ok = [e for e in monthly.values() if (e - today).days >= VOL_MIN_DAYS]
    return sorted(ok, key=lambda e: abs((e - today).days - 30))


def _vol_chains(symbol: str, now: datetime):
    """The chains a volatility trade may use, preferred first: the monthly expiry nearest 30 days, then the other."""
    exps, _code = opt.expiries(symbol.upper())
    for e in vol_expiries(exps or [], now.date())[:2]:
        c = get_chain(symbol, expiry=e, now=now)
        if c is not None:
            yield c


def get_chain(symbol: str, rule: str | None = None, expiry: date | None = None, now: datetime | None = None) -> dict | None:
    """NSE's live chain of `symbol` for `expiry` (or the one `rule` picks), with the forward and time to expiry; cached
    CHAIN_TTL_S. None when NSE has no such chain or refused."""
    now = now or ist_now()
    sym = symbol.upper()
    if expiry is None:
        exps, _code = opt.expiries(sym)
        expiry = _pick_expiry(exps, now.date(), rule or "near") if exps else None
        if expiry is None:
            return None
    key = (sym, expiry)
    hit = _chains.get(key)
    if hit and time.time() - hit[0] < CHAIN_TTL_S:
        return hit[1]
    code, payload = opt._get("option-chain-v3", {"type": opt.instrument_type(sym), "symbol": sym,
                                                 "expiry": expiry.strftime("%d-%b-%Y")})
    c = None
    if payload is not None:
        df, meta = opt.parse_nse(payload, sym, expiry)
        if not df.empty and meta.get("spot"):
            T = opt.years_to_expiry(expiry, now)
            c = {"symbol": sym, "expiry": expiry, "df": df, "spot": float(meta["spot"]), "T": T,
                 "F": float(opt.forward(df, float(meta["spot"]), T, R)),
                 "time": (meta.get("time") or now).isoformat(timespec="seconds")}
    _chains[key] = (time.time(), c)
    return c


def legs_frame(c: dict, side: str) -> pd.DataFrame:
    """One side of a chain: strike, bid, ask, mid, OI, implied volatility (NSE's, else from the price) and delta."""
    df = c["df"]
    call = 1.0 if side == "ce" else 0.0
    out = pd.DataFrame({"strike": df["strike"].astype(float), "bid": df[f"{side}_bid"], "ask": df[f"{side}_ask"],
                        "ltp": df[f"{side}_ltp"], "oi": df[f"{side}_oi"].fillna(0)})
    out["mid"] = opt.option_price(df, side)
    iv = df[f"{side}_iv_nse"] / 100
    solved = pd.Series(opt.implied_vol(out["mid"].to_numpy(float), c["F"], out["strike"].to_numpy(float), c["T"], R,
                                       np.full(len(out), call)), index=out.index)
    out["iv"] = iv.where(iv > 0, solved)
    g = opt.greeks(c["F"], out["strike"].to_numpy(float), c["T"], R, out["iv"].fillna(0.3).to_numpy(float),
                   np.full(len(out), call))
    out["delta"] = np.where(out["iv"].notna(), g["delta"], np.nan)
    spread = (out["ask"] - out["bid"]) / out["mid"]
    out["liquid"] = (out["oi"] >= OI_MIN) & (out["bid"] > 0) & (out["ask"] > 0) & (spread <= SPREAD_MAX_PCT / 100)
    return out


def _pick(legs: pd.DataFrame, target: float) -> pd.Series | None:
    ok = legs[legs["liquid"] & legs["delta"].notna()]
    if ok.empty:
        return None
    return ok.loc[(ok["delta"].abs() - target).abs().idxmin()]


def _reprice(c: dict, strike: float, iv: float, call: bool, spot_new: float, days: float) -> float:
    F_new = c["F"] * spot_new / c["spot"]
    T_new = max(c["T"] - days / 365, opt.MIN_T_YEARS)
    return float(opt.black76(F_new, strike, T_new, R, iv, 1.0 if call else 0.0))


def _r(x, nd=2):
    return None if x is None or (isinstance(x, float) and not math.isfinite(x)) else round(float(x), nd)


# ------------------------------------------------------------------ building signals
def build_buy(source: str, uid: str, symbol: str, direction: str, und_stop: float | None, und_target: float | None,
              rule: str, target_delta: float, strategy: dict, now: datetime, lot: int) -> dict | None:
    """Buy the CE (LONG) / PE (SHORT) nearest `target_delta`, with premium stop / target from the underlying's levels."""
    c = get_chain(symbol, rule, now=now)
    if c is None:
        return None
    side = "ce" if direction == "LONG" else "pe"
    p = _pick(legs_frame(c, side), target_delta)
    if p is None:
        return None
    k, iv, entry = float(p["strike"]), float(p["iv"]), float(p["ask"])
    days = HOLD_DAYS.get(source, 1.0)
    stop = _reprice(c, k, iv, side == "ce", float(und_stop), days) if und_stop else None
    target = _reprice(c, k, iv, side == "ce", float(und_target), days) if und_target else None
    if stop is not None and stop >= entry:
        stop = None                                              # the stop would not cost anything: no premium stop
    if target is not None and target <= entry:
        target = None
    ch_in = _charges(entry * lot, "buy", now.date())
    ch_stop = _charges((stop or 0.0) * lot, "sell", now.date()) if stop else 0.0
    max_loss = ((entry - stop) * lot + ch_in + ch_stop) if stop else entry * lot + ch_in
    ch_tgt = _charges((target or 0.0) * lot, "sell", now.date()) if target else 0.0
    max_gain = ((target - entry) * lot - ch_in - ch_tgt) if target else None
    return {"id": f"{source}|{uid}", "source": source, "symbol": symbol, "direction": direction, "kind": "debit",
            "structure": f"Buy {side.upper()}", "legs": [{"action": "buy", "type": side.upper(), "strike": k,
                                                          "expiry": c["expiry"].isoformat(), "premium": _r(entry),
                                                          "iv": _r(iv * 100, 1), "delta": _r(float(p["delta"]), 2)}],
            "expiry": c["expiry"].isoformat(), "lot": int(lot), "entry": _r(entry), "stop": _r(stop), "target": _r(target),
            "capital": _r(entry * lot + ch_in), "max_loss": _r(max_loss), "max_gain": _r(max_gain),
            "charges_in": _r(ch_in), "underlying": {"price": _r(c["spot"]), "stop": _r(und_stop), "target": _r(und_target)},
            "strategy": strategy, "day": now.date().isoformat(), "opened_at": now.isoformat(timespec="seconds"),
            "chain_time": c["time"], "state": "open", "mark": _r(entry), "marked_at": c["time"]}


def build_condor(symbol: str, rank: dict, now: datetime, lot: int) -> dict | None:
    """Sell a defined-risk iron condor: short call and put near CONDOR_DELTA, long wings WING_STEPS strikes further,
    on the first of the volatility expiries liquid enough for it."""
    for c in _vol_chains(symbol, now):
        r = _condor(c, symbol, rank, now, lot)
        if r is not None:
            return r
    return None


def _condor(c: dict, symbol: str, rank: dict, now: datetime, lot: int) -> dict | None:
    ce, pe = legs_frame(c, "ce"), legs_frame(c, "pe")
    sc, sp = _pick(ce[ce["strike"] > c["spot"]], CONDOR_DELTA), _pick(pe[pe["strike"] < c["spot"]], CONDOR_DELTA)
    if sc is None or sp is None:
        return None
    want = c["spot"] * WING_PCT["index" if symbol in opt.INDICES else "stock"] / 100
    lc = ce[(ce["strike"] >= float(sc["strike"]) + want) & (ce["ask"] > 0)]
    lp = pe[(pe["strike"] <= float(sp["strike"]) - want) & (pe["ask"] > 0)]
    ks = sorted(set(c["df"]["strike"].astype(float)))
    i_c, i_p = ks.index(float(sc["strike"])), ks.index(float(sp["strike"]))
    if lc.empty or lp.empty or i_c + WING_STEPS >= len(ks) or i_p - WING_STEPS < 0:
        return None
    wc = lc.loc[lc["strike"].idxmin()]                         # the nearest strike at least `want` beyond the short
    wp = lp.loc[lp["strike"].idxmax()]
    if wc["strike"] < ks[i_c + WING_STEPS] or wp["strike"] > ks[i_p - WING_STEPS]:
        return None
    credit = float(sc["bid"] + sp["bid"] - wc["ask"] - wp["ask"])
    width = max(float(wc["strike"]) - float(sc["strike"]), float(sp["strike"]) - float(wp["strike"]))
    if credit < MIN_CREDIT_OF_WIDTH * width or credit >= width:
        return None
    day = now.date()
    legs = [("sell", "CE", sc, sc["bid"]), ("buy", "CE", wc, wc["ask"]), ("sell", "PE", sp, sp["bid"]), ("buy", "PE", wp, wp["ask"])]
    ch_in = sum(_charges(float(px) * lot, a, day) for a, _t, _x, px in legs)
    ch_out = sum(_charges(float(px) * lot, "buy" if a == "sell" else "sell", day) for a, _t, _x, px in legs)
    return {"id": f"volatility|{day.isoformat()}|{symbol}|condor", "source": "volatility", "symbol": symbol,
            "direction": "NEUTRAL", "kind": "credit", "structure": "Iron condor (sell premium)",
            "legs": [{"action": a, "type": t, "strike": float(x["strike"]), "expiry": c["expiry"].isoformat(),
                      "premium": _r(float(px)), "iv": _r(float(x["iv"]) * 100, 1), "delta": _r(float(x["delta"]), 2)}
                     for a, t, x, px in legs],
            "expiry": c["expiry"].isoformat(), "lot": int(lot), "entry": _r(credit),
            "stop": _r(credit * (1 + VOL_STOP_PCT / 100)), "target": _r(credit * (1 - VOL_TARGET_PCT / 100)),
            "capital": _r((width - credit) * lot + ch_in), "max_loss": _r((width - credit) * lot + ch_in + ch_out),
            "max_gain": _r(credit * lot - ch_in - ch_out), "charges_in": _r(ch_in),
            "breakevens": [_r(float(sp["strike"]) - credit), _r(float(sc["strike"]) + credit)],
            "underlying": {"price": _r(c["spot"]), "stop": None, "target": None},
            "strategy": {"key": "iv_high_condor", "name": f"IV rank {rank.get('rank'):.0f} / percentile {rank.get('percentile'):.0f}",
                         "status": "untested", "proven": False},
            "iv_rank": rank, "day": day.isoformat(), "opened_at": now.isoformat(timespec="seconds"), "chain_time": c["time"],
            "state": "open", "mark": _r(credit), "marked_at": c["time"]}


def build_straddle(symbol: str, rank: dict, now: datetime, lot: int) -> dict | None:
    """Buy the at-the-money straddle when implied volatility is low against its own year (no evidence: untested), on
    the first of the volatility expiries where both options are liquid."""
    for c in _vol_chains(symbol, now):
        r = _straddle(c, symbol, rank, now, lot)
        if r is not None:
            return r
    return None


def _straddle(c: dict, symbol: str, rank: dict, now: datetime, lot: int) -> dict | None:
    ce, pe = legs_frame(c, "ce"), legs_frame(c, "pe")
    atm = float(ce.loc[(ce["strike"] - c["F"]).abs().idxmin(), "strike"])
    a, b = ce[ce["strike"] == atm].iloc[0], pe[pe["strike"] == atm].iloc[0]
    if not (a["liquid"] and b["liquid"]):
        return None
    debit = float(a["ask"] + b["ask"])
    day = now.date()
    ch_in = _charges(float(a["ask"]) * lot, "buy", day) + _charges(float(b["ask"]) * lot, "buy", day)
    return {"id": f"volatility|{day.isoformat()}|{symbol}|straddle", "source": "volatility", "symbol": symbol,
            "direction": "NEUTRAL", "kind": "debit", "structure": "Long straddle (buy premium)",
            "legs": [{"action": "buy", "type": t, "strike": atm, "expiry": c["expiry"].isoformat(), "premium": _r(float(x["ask"])),
                      "iv": _r(float(x["iv"]) * 100, 1), "delta": _r(float(x["delta"]), 2)} for t, x in (("CE", a), ("PE", b))],
            "expiry": c["expiry"].isoformat(), "lot": int(lot), "entry": _r(debit),
            "stop": _r(debit * (1 - STRADDLE_STOP_PCT / 100)), "target": _r(debit * (1 + STRADDLE_TARGET_PCT / 100)),
            "capital": _r(debit * lot + ch_in), "max_loss": _r(debit * lot * STRADDLE_STOP_PCT / 100 + ch_in * 2),
            "max_gain": None, "charges_in": _r(ch_in), "breakevens": [_r(atm - debit), _r(atm + debit)],
            "underlying": {"price": _r(c["spot"]), "stop": None, "target": None},
            "strategy": {"key": "iv_low_straddle", "name": f"IV rank {rank.get('rank'):.0f} / percentile {rank.get('percentile'):.0f}",
                         "status": "untested", "proven": False},
            "iv_rank": rank, "day": day.isoformat(), "opened_at": now.isoformat(timespec="seconds"), "chain_time": c["time"],
            "state": "open", "mark": _r(debit), "marked_at": c["time"]}


# ------------------------------------------------------------------ marking and exits
def value_now(rec: dict, c: dict | None, mode: str = "mid") -> float | None:
    """Per-unit value of the position from a chain. mode "mid": marked at mid prices (marks and exit checks: crossing
    four spreads would 'stop out' a fresh condor at once); "close": what closing it now gets - a bought leg sells at
    the bid, a sold leg is bought back at the ask. None when a leg has no price."""
    if c is None:
        return None
    total = 0.0
    for leg in rec["legs"]:
        f = legs_frame(c, leg["type"].lower())
        row = f[f["strike"] == float(leg["strike"])]
        if row.empty:
            return None
        row = row.iloc[0]
        if mode == "mid":
            px = row["mid"]
        else:
            px = row["bid"] if leg["action"] == "buy" else row["ask"]
            if not (px > 0):
                px = row["mid"]
        if not (px > 0):
            return None
        total += float(px) if (leg["action"] == "buy") == (rec["kind"] == "debit") else -float(px)
    return total


def _close(rec: dict, value: float, reason: str, now: datetime, src: str = "chain") -> None:
    lot = rec["lot"]
    day = now.date()
    out_charges = 0.0
    for leg in rec["legs"]:
        leg_val = float(leg["premium"] or 0) * (value / rec["entry"]) if rec["entry"] else 0.0   # proportional estimate
        out_charges += _charges(abs(leg_val) * lot, "sell" if leg["action"] == "buy" else "buy", day)
    gross = (value - rec["entry"]) * lot if rec["kind"] == "debit" else (rec["entry"] - value) * lot
    rec.update(state="closed", exit=_r(value), exit_reason=reason, exit_src=src, closed_at=now.isoformat(timespec="seconds"),
               charges=_r((rec.get("charges_in") or 0) + out_charges),
               pnl=_r(gross - (rec.get("charges_in") or 0) - out_charges),
               ret_pct=_r((gross - (rec.get("charges_in") or 0) - out_charges) / (rec["capital"] or 1) * 100, 1),
               mark=_r(value))


def _exit_rule(rec: dict, value: float) -> str | None:
    if rec["kind"] == "debit":
        if rec.get("stop") is not None and value <= rec["stop"]:
            return "stop"
        if rec.get("target") is not None and value >= rec["target"]:
            return "target"
    else:
        if rec.get("stop") is not None and value >= rec["stop"]:
            return "stop"
        if rec.get("target") is not None and value <= rec["target"]:
            return "target"
    return None


# ------------------------------------------------------------------ the sources
def _intraday(signals: dict | None, lots: dict) -> list[dict]:
    out = []
    for x in (signals or {}).get("signals") or []:
        if x.get("state") == "open" and str(x.get("symbol")) in lots and x.get("side") in ("LONG", "SHORT"):
            out.append(x)
    return out


def _intraday_file() -> dict:
    try:
        f = json.loads((RESULTS_DIR / "intraday_signals.json").read_text(encoding="utf-8"))
        return f if str(f.get("generated_at") or "")[:10] == ist_now().date().isoformat() else {}
    except (OSError, ValueError):
        return {}


def _latest_scan() -> dict:
    try:
        return json.loads((RESULTS_DIR / "latest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _stock(lt: dict, lots: dict) -> list[tuple[dict, dict]]:
    out = []
    for s in lt.get("strategies") or []:
        if s.get("status") != "working":
            continue
        for a in s.get("actions") or []:
            if a.get("action") == "BUY" and str(a.get("symbol")) in lots and not a.get("provisional"):
                out.append((s, a))
    return out


def late_min(now: datetime, entry_time: str | None) -> float | None:
    """Minutes since the signal's entry bar started (its "HH:MM" today); None without a time."""
    try:
        h, m = (int(x) for x in str(entry_time)[:5].split(":"))
    except (TypeError, ValueError):
        return None
    return (now - now.replace(hour=h, minute=m, second=0, microsecond=0)).total_seconds() / 60


def refresh(intraday: dict | None = None, now: datetime | None = None, sources=("intraday", "stock", "volatility"),
            log=lambda m: None) -> dict:
    """One pass: open new option signals from the sources (market hours only), mark the open ones on the live chains and
    apply their exits. Returns {"opened", "closed", "open"}. Never raises for NSE trouble."""
    now = now or ist_now()
    rep = {"opened": 0, "closed": 0, "open": 0, "errors": []}
    lk = _lock()
    if not lk.acquire(timeout=20):
        rep["errors"].append("journal busy")
        return rep
    try:
        rows = load()
        have = {r["id"] for r in rows}
        lots = ov.lot_sizes()
        mkt_open = _market_open(now)
        sig = intraday if intraday is not None else _intraday_file()
        if mkt_open and (now.hour, now.minute) < SQUARE_OFF:
            new: list[dict] = []
            if "intraday" in sources:
                for x in _intraday(sig, lots)[: MAX_NEW["intraday"] * 3]:
                    uid = f"{now.date().isoformat()}|{x.get('strategy_key')}|{x.get('symbol')}|{x.get('entry_time')}"
                    if f"intraday|{uid}" in have or sum(1 for r in new if r["source"] == "intraday") >= MAX_NEW["intraday"]:
                        continue
                    late = late_min(now, x.get("entry_time"))
                    if late is not None and late > MAX_LATE_MIN:
                        continue                   # too late to take at the signal's price
                    try:
                        r = build_buy("intraday", uid, str(x["symbol"]), x["side"], x.get("stop"), x.get("target"), "near",
                                      DELTA_NEAR, {"key": x.get("strategy_key"), "name": x.get("strategy_name"),
                                                   "status": x.get("strategy_status"), "proven": bool(x.get("proven")),
                                                   "entry_time": x.get("entry_time"),
                                                   "late_min": _r(late, 1)}, now, lots[str(x["symbol"])])
                    except Exception as e:
                        rep["errors"].append(f"{x.get('symbol')}: {type(e).__name__}: {e}")
                        r = None
                    if r:
                        new.append(r)
            if "stock" in sources:
                lt = _latest_scan()
                scan = str(lt.get("scan_id") or lt.get("generated_at") or "")[:16]
                for s, a in _stock(lt, lots):
                    uid = f"{scan}|{s['key']}|{a['symbol']}"
                    if f"stock|{uid}" in have or sum(1 for r in new if r["source"] == "stock") >= MAX_NEW["stock"]:
                        continue
                    stop = a.get("stop")
                    try:                           # no premium target: the strategy's own rules decide the exit
                        r = build_buy("stock", uid, str(a["symbol"]), "LONG", stop, None, "month", DELTA_MONTH,
                                      {"key": s["key"], "name": s.get("name"), "status": "working", "proven": True}, now,
                                      lots[str(a["symbol"])])
                    except Exception as e:
                        rep["errors"].append(f"{a.get('symbol')}: {type(e).__name__}: {e}")
                        r = None
                    if r:
                        new.append(r)
            if "volatility" in sources and (now.hour, now.minute) >= (9, 30):
                new += _volatility(now, lots, have, rep, rows + new)
            rows += new
            rep["opened"] = len(new)
        # mark and exit the open ones
        lt = None
        for rec in rows:
            if rec.get("state") != "open":
                continue
            exp = date.fromisoformat(rec["expiry"])
            if not mkt_open:
                continue
            c = get_chain(rec["symbol"], expiry=exp, now=now)
            v = value_now(rec, c)
            if v is None:
                continue
            rec.update(mark=_r(v), marked_at=c["time"],
                       unrealized=_r(((v - rec["entry"]) if rec["kind"] == "debit" else (rec["entry"] - v)) * rec["lot"]))
            reason = _exit_rule(rec, v)
            if rec["source"] == "intraday":
                if (now.hour, now.minute) >= SQUARE_OFF:
                    reason = reason or "square-off 15:00"
                elif sig:
                    _d, strat, symb, et = rec["id"].split("|", 1)[1].split("|")
                    closed = [x for x in sig.get("signals") or [] if x.get("strategy_key") == strat and x.get("symbol") == symb
                              and x.get("entry_time") == et and x.get("state") == "closed"]
                    if closed:
                        reason = reason or f"strategy exit ({closed[0].get('reason')})"
            elif rec["source"] == "stock":
                lt = lt if lt is not None else _latest_scan()
                reason = reason or _stock_exit(rec, lt)
                if (exp - now.date()).days <= 3:
                    reason = reason or "near expiry"
            elif rec["source"] == "volatility" and (exp - now.date()).days <= VOL_CLOSE_DAYS:
                reason = reason or f"{VOL_CLOSE_DAYS} days before expiry"
            if reason:
                fill = value_now(rec, c, "close")
                _close(rec, fill if fill is not None else v, reason, now)
                rep["closed"] += 1
        rep["open"] = sum(1 for r in rows if r.get("state") == "open")
        _save(rows)
    finally:
        lk.release()
    return rep


def _stock_exit(rec: dict, lt: dict) -> str | None:
    """The daily strategy left the stock: a SELL in a scan after the option was bought, or the stock is in neither its
    positions nor its BUY orders any more."""
    key, sym = (rec.get("strategy") or {}).get("key"), rec["symbol"]
    gen = str(lt.get("generated_at") or "")
    if not gen or gen <= rec["opened_at"][:19]:
        return None
    s = next((x for x in lt.get("strategies") or [] if x.get("key") == key), None)
    if s is None:
        return None
    if any(a.get("symbol") == sym and a.get("action") == "SELL" for a in s.get("actions") or []):
        return "strategy exit (sell)"
    held = {p.get("symbol") for p in s.get("positions") or []} | {a.get("symbol") for a in s.get("actions") or []
                                                                 if a.get("action") == "BUY"}
    return None if sym in held else "strategy exit (no longer held)"


def _volatility(now: datetime, lots: dict, have: set, rep: dict, rows: list[dict]) -> list[dict]:
    from . import iv_history as ivh
    t = ivh.ranks()
    if t is None or t.empty:
        return []
    t = t[t["symbol"].isin(list(lots)) & t["rank"].notna() & t["percentile"].notna()]
    hi = t[(t["rank"] >= IV_HIGH) & (t["percentile"] >= IV_HIGH)].sort_values("rank", ascending=False)
    lo = t[(t["rank"] <= IV_LOW) & (t["percentile"] <= IV_LOW)].sort_values("rank")
    out = []
    for frame, build, kind in ((hi, build_condor, "condor"), (lo, build_straddle, "straddle")):
        for r in frame.itertuples(index=False):
            if len(out) >= MAX_NEW["volatility"]:
                break
            if f"volatility|{now.date().isoformat()}|{r.symbol}|{kind}" in have:
                continue
            if any(x.get("source") == "volatility" and x.get("symbol") == r.symbol and x.get("state") == "open"
                   for x in rows + out):
                continue                                   # one open volatility trade per underlying
            try:
                rec = build(r.symbol, {"rank": float(r.rank), "percentile": float(r.percentile), "iv": float(r.iv)}, now,
                            lots[r.symbol])
            except Exception as e:
                rep["errors"].append(f"{r.symbol}: {type(e).__name__}: {e}")
                rec = None
            if rec:
                out.append(rec)
    return out


def _market_open(now: datetime) -> bool:
    from .intraday.fyers_sync import is_trading_day
    m = now.hour * 60 + now.minute
    return is_trading_day(now.date()) and 9 * 60 + 15 <= m < 15 * 60 + 30


# ------------------------------------------------------------------ nightly: NSE's official closes
def settle_day(content: bytes, day: date) -> int:
    """With the day's F&O bhavcopy: close intraday signals still open from that day at the official close, mark the others,
    and settle what expired at its intrinsic value. Returns how many were closed."""
    import io
    import zipfile
    with zipfile.ZipFile(io.BytesIO(content)) as z:
        raw = z.read(z.namelist()[0])
    bc = pd.read_csv(io.BytesIO(raw), usecols=["FinInstrmTp", "TckrSymb", "XpryDt", "StrkPric", "OptnTp", "ClsPric",
                                                "SttlmPric", "UndrlygPric"])
    bc = bc[bc["FinInstrmTp"].isin(["IDO", "STO"])].assign(expiry=lambda x: pd.to_datetime(x["XpryDt"]).dt.date.astype(str))
    px = {(r.TckrSymb, r.expiry, float(r.StrkPric), r.OptnTp): (float(r.ClsPric) if r.ClsPric > 0 else float(r.SttlmPric))
          for r in bc.itertuples(index=False)}
    under = bc.groupby("TckrSymb")["UndrlygPric"].first().to_dict()
    lk = _lock()
    if not lk.acquire(timeout=30):
        return 0
    n = 0
    try:
        rows = load()
        when = datetime.combine(day, datetime.min.time()).replace(hour=15, minute=30, tzinfo=ist_now().tzinfo)
        for rec in rows:
            if rec.get("state") != "open" or rec["day"] > day.isoformat():
                continue
            expired = rec["expiry"] <= day.isoformat()
            total, ok = 0.0, True
            for leg in rec["legs"]:
                if expired:
                    u = under.get(rec["symbol"])
                    if u is None:
                        ok = False
                        break
                    v = max(u - leg["strike"], 0.0) if leg["type"] == "CE" else max(leg["strike"] - u, 0.0)
                else:
                    v = px.get((rec["symbol"], leg["expiry"], float(leg["strike"]), leg["type"]))
                    if v is None:
                        ok = False
                        break
                total += v if (leg["action"] == "buy") == (rec["kind"] == "debit") else -v
            if not ok:
                continue
            if expired:
                _close(rec, total, "expiry", when, "nse close")
                n += 1
            elif rec["source"] == "intraday" and rec["day"] <= day.isoformat():
                _close(rec, total, "day's close (not closed live)", when, "nse close")
                n += 1
            else:
                reason = _exit_rule(rec, total)
                rec.update(mark=_r(total), marked_at=f"{day.isoformat()} close")
                if reason:
                    _close(rec, total, f"{reason} (at the close)", when, "nse close")
                    n += 1
        _save(rows)
    finally:
        lk.release()
    return n


# ------------------------------------------------------------------ record and view
def record(rows: list[dict]) -> list[dict]:
    """Closed signals per source: trades, win rate, average return on capital, total P&L after charges."""
    out = []
    for src in ("intraday", "stock", "volatility"):
        done = [r for r in rows if r.get("source") == src and r.get("state") == "closed" and r.get("pnl") is not None]
        pnl = [r["pnl"] for r in done]
        out.append({"source": src, "label": SOURCES[src], "trades": len(done),
                    "win_rate": _r(sum(1 for p in pnl if p > 0) / len(pnl) * 100, 1) if pnl else None,
                    "avg_ret_pct": _r(float(np.mean([r["ret_pct"] for r in done])), 1) if done else None,
                    "pnl": _r(sum(pnl)) if pnl else 0.0,
                    "open": sum(1 for r in rows if r.get("source") == src and r.get("state") == "open"),
                    "verdict": ("not enough trades yet" if len(done) < 20 else
                                "made money so far" if sum(pnl) > 0 else "lost money so far")})
    return out


# ------------------------------------------------------------------ the volatility backtest (NIFTY / BANKNIFTY)
def iv_rank_series(atm_iv: pd.Series, lookback: int = 252, min_days: int = 120) -> pd.DataFrame:
    """Rolling IV rank and percentile of a daily ATM IV series, each day against the days before it."""
    s = atm_iv.dropna().astype(float)
    lo = s.rolling(lookback, min_periods=min_days).min()
    hi = s.rolling(lookback, min_periods=min_days).max()
    rank = (s - lo) / (hi - lo) * 100
    pct = s.rolling(lookback, min_periods=min_days).apply(lambda w: (w[:-1] < w[-1]).mean() * 100, raw=True)
    return pd.DataFrame({"iv": s, "rank": rank, "percentile": pct})


def vol_backtest(symbol: str, hist: pd.DataFrame, atm_iv: pd.Series, spec: dict | None = None) -> dict:
    """The iron condor sold only when the IV rank and percentile were both IV_HIGH+ vs sold every cycle, on NSE's daily
    option history (scanner/options_backtest.py, same charges and fills)."""
    from . import options_backtest as ob
    spec = {"strategy": "iron_condor", "cycle": "monthly", "entry_dte": 35, "short_pct": 4.0, "wing_pct": 6.0,
            "stop_pct": VOL_STOP_PCT, "target_pct": VOL_TARGET_PCT, "lots": 1, "slippage_pct": 1.0, **(spec or {})}
    rk = iv_rank_series(atm_iv)
    high = {pd.Timestamp(d) for d, r in rk.iterrows() if r["rank"] >= IV_HIGH and r["percentile"] >= IV_HIGH}
    tested = {pd.Timestamp(d) for d in rk.dropna().index}
    always = ob.backtest(hist, spec, entry_days=tested)
    when_high = ob.backtest(hist, spec, entry_days=high)
    return {"symbol": symbol, "spec": spec, "days_with_rank": len(tested), "high_days": len(high),
            "always": always["stats"], "when_high": when_high["stats"], "trades_when_high": when_high["trades"][-20:],
            "first": min(tested).date().isoformat() if tested else None,
            "last": max(tested).date().isoformat() if tested else None}
