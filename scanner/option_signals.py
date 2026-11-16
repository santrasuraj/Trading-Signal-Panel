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
import statistics
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
NO_NEW_INTRADAY = (14, 30)  # no new intraday option in the last 30 minutes: too little time to reach a target, while
                            # the spread and charges are paid in full
MAX_LATE_MIN = 15.0         # an intraday signal becomes an option only this soon after its entry bar starts (the
                            # 5-minute task's signals arrive up to ~10 min after it; later, the price has moved on)
CHAIN_TTL_S = 60
# Which signals may open an option, by their strategy's backtest (config.yaml option_signals.evidence):
#   not_lost  every strategy except those that LOST money in their backtest ("Lost in test") - the default: losing on the
#             shares means losing more on options (premium decay, spreads); untested ones run as a labelled live test
#   proven    only strategies whose backtest beat costs beyond luck ("working")
#   all       everything (practice / research)
EVIDENCE = {"not_lost": {"working", "mixed", "unknown", "untested"}, "proven": {"working"}, "all": None}
DEFAULT_EVIDENCE = "not_lost"
LOST = "not-working"
# ... and by its own live record: a strategy whose bought options clearly lose (at least LIVE_MIN_TRADES closed in the
# last LIVE_DAYS days, losing on average with a t-stat at or below LIVE_T) is paused - an untested strategy's only test,
# and a backtest that stopped holding. Older trades drop out of the window: after LIVE_DAYS it gets a new trial.
LIVE_DAYS, LIVE_MIN_TRADES, LIVE_T = 30, 10, -1.0
SKIP_REASONS = {"lost": "their strategy lost money in its backtest", "evidence": "below the evidence rule",
                "lost_live": "their strategy's live option record is losing",
                "repeat": "a repeat of a trade already taken today", "stacked": "another option on the stock was open",
                "closing": "in the last 30 minutes before the 15:00 square-off",
                "late": "too late after the signal's bar", "no_option": "no liquid option near the target delta"}
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


def skips_file():
    return FILE.with_name("option_signals_skips.json")


def evidence_rule(cfg: dict | None = None) -> str:
    """config.yaml option_signals.evidence (not_lost / proven / all); not_lost when missing or unknown."""
    try:
        if cfg is None:
            from .settings import load_config
            cfg = load_config()
        v = str(((cfg or {}).get("option_signals") or {}).get("evidence") or DEFAULT_EVIDENCE).strip().lower()
    except Exception:
        v = DEFAULT_EVIDENCE
    return v if v in EVIDENCE else DEFAULT_EVIDENCE


def load_skips() -> dict:
    try:
        d = json.loads(skips_file().read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_skips(day: str, add: dict[str, set]) -> None:
    """Signals not taken, per day and reason ("strategy|symbol|direction"), the last 10 days kept."""
    d = load_skips()
    cur = d.get(day) or {}
    for reason, keys in add.items():
        if keys:
            cur[reason] = sorted(set(cur.get(reason) or []) | set(keys))
    d[day] = cur
    d = {k: d[k] for k in sorted(d)[-10:]}
    tmp = skips_file().with_suffix(".tmp")
    tmp.write_text(json.dumps(d), encoding="utf-8")
    tmp.replace(skips_file())


def tidy(rows: list[dict], day: str, allowed: set | None) -> int:
    """Apply the one-trade-per-signal and evidence rules to `day`'s intraday options already in the journal: a repeat of
    a trade already taken (same strategy, stock and direction), one opened while another option on the stock was
    still open, or one from a strategy below the evidence rule is marked cancelled - kept for the audit, left out of
    the record and the list. Returns how many were cancelled."""
    busy: dict[str, str | None] = {}                     # symbol -> closed_at of the kept trade (None while open)
    kept: set = set()
    n = 0
    mine = sorted((r for r in rows if r.get("source") == "intraday" and r.get("day") == day
                   and r.get("state") != "cancelled"), key=lambda r: r.get("opened_at") or "")
    for r in mine:
        st = str((r.get("strategy") or {}).get("status") or "untested")
        key = ((r.get("strategy") or {}).get("key"), r["symbol"], r.get("direction"))
        held = r["symbol"] in busy and (busy[r["symbol"]] is None or busy[r["symbol"]] > (r.get("opened_at") or ""))
        reason = ("lost" if st == LOST else "evidence") if allowed is not None and st not in allowed else \
                 "repeat" if key in kept else "stacked" if held else None
        if reason:
            r.update(state="cancelled", cancel_reason=reason, exit_reason=f"not taken: {SKIP_REASONS[reason]}",
                     unrealized=None, pnl=None, ret_pct=None)
            n += 1
        else:
            kept.add(key)
            busy[r["symbol"]] = r.get("closed_at")
    return n


def live_record(rows: list[dict], today: date) -> dict[str, dict]:
    """Each intraday strategy's closed options of the last LIVE_DAYS days (cancelled ones never count): trades, total
    P&L, t-stat of the average and whether that pauses it."""
    since = (today - timedelta(days=LIVE_DAYS)).isoformat()
    pnl: dict[str, list[float]] = {}
    for r in rows:
        if r.get("source") == "intraday" and r.get("state") == "closed" and r.get("pnl") is not None \
                and (r.get("day") or "") >= since:
            pnl.setdefault((r.get("strategy") or {}).get("key") or "?", []).append(float(r["pnl"]))
    out = {}
    for k, p in pnl.items():
        n, m = len(p), sum(p) / len(p)
        sd = statistics.stdev(p) if n > 1 else 0.0
        t = m / (sd / math.sqrt(n)) if sd > 0 else None
        out[k] = {"trades": n, "pnl": _r(sum(p)), "t": _r(t), "since": since,
                  "paused": n >= LIVE_MIN_TRADES and m < 0 and (t is None or t <= LIVE_T)}
    return out


def pnl_parts(rec: dict, spot: float | None, mid_exit: float | None, now: datetime) -> dict | None:
    """Where a closed bought option's P&L came from, in rupees (they add up to its P&L):
      move      the stock's move from entry to exit (the signal), at the entry's implied volatility
      decay     time decay over the hold
      vol       the change in implied volatility (and what the model misses)
      spread    paid crossing the bid-ask: bought at the ask, sold at the bid
      charges   brokerage, STT, exchange, GST, stamp
    None for spreads / condors or a trade without the prices needed (closed at NSE's official close)."""
    try:
        legs, u = rec.get("legs") or [], rec.get("underlying") or {}
        if rec.get("kind") != "debit" or len(legs) != 1 or not spot or mid_exit is None or not u.get("price") \
                or not legs[0].get("iv"):
            return None
        leg, lot = legs[0], rec["lot"]
        call, k, iv = leg["type"] == "CE", float(leg["strike"]), float(leg["iv"]) / 100
        exp = date.fromisoformat(rec["expiry"])
        t0 = opt.years_to_expiry(exp, datetime.fromisoformat(rec["opened_at"]))
        t1 = opt.years_to_expiry(exp, now)
        s0, s1 = float(u["price"]), float(spot)

        def val(s_, t_):
            return float(opt.black76(s_ * math.exp(R * t_), k, t_, R, iv, 1.0 if call else 0.0))
        mid0 = float(leg.get("mid") or val(s0, t0))      # older trades did not store the mid paid around
        move, decay = (val(s1, t1) - val(s0, t1)) * lot, (val(s0, t1) - val(s0, t0)) * lot
        spread = ((mid0 - rec["entry"]) + (rec["exit"] - mid_exit)) * lot
        vol = (mid_exit - mid0) * lot - move - decay
        return {"move": _r(move), "decay": _r(decay), "vol": _r(vol), "spread": _r(spread),
                "charges": _r(-(rec.get("charges") or 0.0))}
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        return None


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


TICK = 0.05


def _tick(x: float) -> float:
    """The nearest price on NSE's option tick (Rs 0.05)."""
    return round(round(x / TICK) * TICK, 2)


def _mid_iv(c: dict, strike: float, mid: float, call: bool) -> float | None:
    """The implied volatility that prices the option at its mid (None when it cannot be solved)."""
    if not (mid > 0):
        return None
    v = opt.implied_vol(np.array([mid]), c["F"], np.array([strike]), c["T"], R, np.array([1.0 if call else 0.0]))
    v = float(np.asarray(v).ravel()[0])
    return v if math.isfinite(v) and v > 0 else None


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
    k, entry = float(p["strike"]), float(p["ask"])
    call = side == "ce"
    # the IV that reproduces the option's own mid price (NSE's quoted IV can be stale or from another model, and then
    # an absolute model price at the stop can even exceed the ask); the stop / target are the modelled CHANGE from now
    # to the underlying's level - including the time decay of the hold - added to the price paid
    iv = _mid_iv(c, k, float(p["mid"]), call) or float(p["iv"])
    days = HOLD_DAYS.get(source, 1.0)
    base = _reprice(c, k, iv, call, c["spot"], 0.0)
    stop = entry + _reprice(c, k, iv, call, float(und_stop), days) - base if und_stop else None
    target = entry + _reprice(c, k, iv, call, float(und_target), days) - base if und_target else None
    stop = _tick(max(stop, TICK)) if stop is not None else None          # orders go in on NSE's 5-paise tick
    target = _tick(target) if target is not None else None
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
                                                          "mid": _r(float(p["mid"])), "iv": _r(iv * 100, 1),
                                                          "delta": _r(float(p["delta"]), 2)}],
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
    value = _r(value)                                    # the P&L from the exit price as shown (to the paisa)
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
        day = now.date().isoformat()
        rule = evidence_rule()
        allowed = EVIDENCE[rule]
        rep["cancelled"] = tidy(rows, day, allowed)
        paused = {k for k, v in live_record(rows, now.date()).items() if v["paused"]} if allowed is not None else set()
        skips: dict[str, set] = {k: set() for k in SKIP_REASONS}
        if mkt_open and (now.hour, now.minute) < SQUARE_OFF:
            new: list[dict] = []
            if "intraday" in sources:
                for x in _intraday(sig, lots)[: MAX_NEW["intraday"] * 6]:
                    uid = f"{day}|{x.get('strategy_key')}|{x.get('symbol')}|{x.get('entry_time')}"
                    if f"intraday|{uid}" in have or sum(1 for r in new if r["source"] == "intraday") >= MAX_NEW["intraday"]:
                        continue
                    sym, strat, status = str(x["symbol"]), x.get("strategy_key"), str(x.get("strategy_status") or "untested")
                    tag = f"{strat}|{sym}|{x.get('side')}"
                    live = [r for r in rows + new if r.get("source") == "intraday" and r.get("day") == day
                            and r.get("state") != "cancelled"]
                    if allowed is not None and status not in allowed:
                        skips["lost" if status == LOST else "evidence"].add(tag)
                        continue
                    if strat in paused:
                        skips["lost_live"].add(tag)  # its own bought options keep losing: paused (LIVE_DAYS window)
                        continue
                    if any(((r.get("strategy") or {}).get("key"), r["symbol"], r.get("direction")) == (strat, sym, x.get("side"))
                           for r in live):
                        skips["repeat"].add(tag)   # the same signal again (an OI build-up re-fires every bar)
                        continue
                    if any(r["symbol"] == sym and r.get("state") == "open" for r in live):
                        skips["stacked"].add(tag)
                        continue
                    if (now.hour, now.minute) >= NO_NEW_INTRADAY:
                        skips["closing"].add(tag)    # minutes before the square-off: costs in full, no time to work
                        continue
                    late = late_min(now, x.get("entry_time"))
                    if late is not None and late > MAX_LATE_MIN:
                        skips["late"].add(tag)     # too late to take at the signal's price
                        continue
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
                    else:
                        skips["no_option"].add(tag)
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
            v = _r(v)                                    # the open P&L from the mark as shown
            rec.update(mark=v, marked_at=c["time"],
                       unrealized=_r(((v - rec["entry"]) if rec["kind"] == "debit" else (rec["entry"] - v)) * rec["lot"]))
            reason = _exit_rule(rec, v)
            if rec["source"] == "intraday":
                if (now.hour, now.minute) >= SQUARE_OFF:
                    reason = reason or "square-off 15:00"
                elif sig:
                    st_ = rec.get("strategy") or {}
                    strat, symb, et = st_.get("key"), rec["symbol"], st_.get("entry_time")
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
                rec["parts"] = pnl_parts(rec, c.get("spot"), v, now)
                rep["closed"] += 1
        rep["open"] = sum(1 for r in rows if r.get("state") == "open")
        rep["skipped"] = {k: len(v) for k, v in skips.items() if v}
        _save(rows)
        if any(skips.values()):
            _save_skips(day, skips)
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
        tidy(rows, day.isoformat(), EVIDENCE[evidence_rule()])   # never settle a repeat or a lost strategy's trade
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
                m = _r(total)                                    # the open P&L moves with the mark it is shown with
                rec.update(mark=m, marked_at=f"{day.isoformat()} close",
                           unrealized=_r(((m - rec["entry"]) if rec["kind"] == "debit" else (rec["entry"] - m)) * rec["lot"]))
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
                                "made money so far" if sum(pnl) > 0 else "lost money so far"),
                    "by_strategy": _by_strategy([r for r in rows if r.get("source") == src],
                                                live_record(rows, ist_now().date()) if src == "intraday" else {},
                                                tested_status() if src == "intraday" else {})})
    return out


def tested_status() -> dict[str, str]:
    """Each intraday strategy's status in its newest backtest (intraday.json): a trade stores the status it was opened
    under, which a later backtest can change."""
    try:
        st = json.loads((RESULTS_DIR / "intraday.json").read_text(encoding="utf-8"))
        return {str(x["key"]): str(x.get("status") or "untested") for x in st.get("strategies") or [] if x.get("key")}
    except (OSError, ValueError, TypeError, KeyError):
        return {}


PARTS = ("move", "decay", "vol", "spread", "charges")


def _by_strategy(rows: list[dict], live: dict | None = None, tested: dict | None = None) -> list[dict]:
    """Each strategy's own record inside a source (cancelled trades never count): trades, wins, P&L, where that P&L
    came from (the trades whose breakdown is known) and, for intraday strategies, the live record that pauses one."""
    keys: dict[str, dict] = {}
    for r in rows:
        if r.get("state") == "cancelled":
            continue
        st = r.get("strategy") or {}
        k = st.get("key") or "?"
        e = keys.setdefault(k, {"key": k, "name": st.get("name") or k, "status": st.get("status"), "trades": 0,
                                "wins": 0, "pnl": 0.0, "open": 0, "parts": None, "parts_n": 0, "live": None})
        if r.get("state") == "open":
            e["open"] += 1
        elif r.get("state") == "closed" and r.get("pnl") is not None:
            e["trades"] += 1
            e["wins"] += int(r["pnl"] > 0)
            e["pnl"] = _r(e["pnl"] + r["pnl"])
            if r.get("parts"):
                e["parts"] = {p: _r((e["parts"] or {}).get(p, 0.0) + (r["parts"].get(p) or 0.0)) for p in PARTS}
                e["parts_n"] += 1
    for k, e in keys.items():
        e["live"] = (live or {}).get(k)
        e["status"] = (tested or {}).get(k, e["status"])    # its newest backtest, not the one it was opened under
    return sorted(keys.values(), key=lambda e: (-e["trades"], e["name"]))


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
