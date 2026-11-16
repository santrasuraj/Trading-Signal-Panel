"""Options strategy builder (POST /api/options/payoff): the profit and loss of a multi-leg position on a stored option
chain, at expiry and today, with breakevens, the maximum profit and loss, the position's Greeks and the chance of
ending in profit.

Pricing is Black-76 on the chain's forward (scanner/options.py), each leg at its own implied volatility from the chain
(or one you type). "Today" moves the underlying with the forward / spot basis kept, `days` later and with every
volatility shifted by `iv_shift` points. The chance of profit assumes a lognormal price at expiry with the
at-the-money volatility: a model, not a forecast. Margin is not computed (SPAN + exposure come from your broker; an
option you sell needs margin, a bought one only its premium).
"""
from __future__ import annotations

import math
from datetime import date, datetime

import numpy as np

from scanner import options as opt

from . import options_svc
from ..errors import ApiException
from ..util import now_ist

POINTS = 241
MAX_LEGS = 8


def _norm_cdf(x):
    from math import erf
    return 0.5 * (1 + np.vectorize(erf)(np.asarray(x, dtype=float) / math.sqrt(2)))


def _leg_value(leg: dict, F: np.ndarray, T: float, r: float, iv_shift: float) -> np.ndarray:
    """Value of one unit of the leg's contract at forward levels F with T years left (T=0: intrinsic)."""
    if leg["kind"] == "FUT":
        return F.copy()
    call = 1.0 if leg["kind"] == "CE" else 0.0
    if T <= 0:
        return np.maximum(F - leg["strike"], 0) if call else np.maximum(leg["strike"] - F, 0)
    sigma = max(leg["iv"] + iv_shift / 100, 0.005)
    return np.asarray(opt.black76(F, np.full_like(F, leg["strike"]), T, r, np.full_like(F, sigma),
                                  np.full_like(F, call)), dtype=float)


def _crossings(x: np.ndarray, y: np.ndarray) -> list[float]:
    out = []
    for i in range(len(x) - 1):
        a, b = y[i], y[i + 1]
        if a == 0 and (i == 0 or y[i - 1] != 0):
            out.append(float(x[i]))
        elif a * b < 0:
            out.append(float(x[i] + (x[i + 1] - x[i]) * (-a) / (b - a)))
    return out


def payoff(legs: list[dict], spot: float, F: float, T: float, r: float, atm_iv: float, days: float = 0.0,
           iv_shift: float = 0.0, span_pct: float | None = None) -> dict:
    """legs: [{kind CE/PE/FUT, strike, side buy/sell, qty (units, lots x lot size), price (entry), iv (0.15)}]."""
    if not legs:
        raise ValueError("Add at least one leg")
    basis = F / spot if spot else 1.0
    sd = atm_iv * math.sqrt(max(T, 1e-6)) if atm_iv and atm_iv > 0 else 0.1
    strikes = [lg["strike"] for lg in legs if lg["kind"] != "FUT"]
    width = span_pct / 100 if span_pct else max(3.5 * sd, 0.06)
    lo = min([spot * (1 - width)] + [k * 0.97 for k in strikes])
    hi = max([spot * (1 + width)] + [k * 1.03 for k in strikes])
    S = np.unique(np.concatenate([np.linspace(max(lo, 0.01), hi, POINTS), np.array(strikes, dtype=float), [spot]]))
    S = S[(S >= lo) & (S <= hi)] if len(S) else S
    T_now = max(T - days / 365, 0.0)

    exp_pnl = np.zeros_like(S)
    now_pnl = np.zeros_like(S)
    premium = 0.0
    g = {"delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0}
    for lg in legs:
        sign = 1.0 if lg["side"] == "buy" else -1.0
        q = sign * lg["qty"]
        exp_pnl += q * (_leg_value(lg, S, 0.0, r, 0.0) - lg["price"])       # at expiry the forward is the spot
        now_pnl += q * (_leg_value(lg, S * basis, T_now, r, iv_shift) - lg["price"])
        if lg["kind"] == "FUT":
            g["delta"] += q
            continue
        premium += -q * lg["price"]
        if T > 0:
            gr = opt.greeks(F, np.array([lg["strike"]]), T, r, np.array([lg["iv"]]),
                            np.array([1.0 if lg["kind"] == "CE" else 0.0]))
            for n in g:
                g[n] += q * float(np.asarray(gr[n]).ravel()[0])

    # beyond the grid: below, every option's value is linear down to 0; above, calls (and futures) keep paying
    slope_up = sum((1 if lg["side"] == "buy" else -1) * lg["qty"] for lg in legs if lg["kind"] in ("CE", "FUT"))
    at_zero = sum((1 if lg["side"] == "buy" else -1) * lg["qty"] *
                  ((max(lg["strike"], 0) if lg["kind"] == "PE" else 0.0) - lg["price"]) for lg in legs)
    max_profit = None if slope_up > 0 else float(max(exp_pnl.max(), at_zero))
    max_loss = None if slope_up < 0 else float(min(exp_pnl.min(), at_zero))
    bes = _crossings(S, exp_pnl)

    pop = None
    if atm_iv and atm_iv > 0 and T > 0:
        # chance of ending in profit: lognormal around the forward, probability mass of each grid cell
        edges = np.concatenate([[0.0], (S[1:] + S[:-1]) / 2, [np.inf]])
        z = (np.log(np.maximum(edges, 1e-12) / F) + 0.5 * sd ** 2) / sd
        cdf = _norm_cdf(np.where(np.isinf(edges), 50, np.where(edges <= 0, -50, z)))
        mass = np.diff(cdf)
        p = float(mass[exp_pnl > 0].sum())
        pop = round(min(max(p, 0.0), 1.0) * 100, 1)

    return {
        "grid": [round(float(x), 2) for x in S],
        "at_expiry": [round(float(x), 2) for x in exp_pnl], "today": [round(float(x), 2) for x in now_pnl],
        "breakevens": [round(b, 2) for b in bes], "max_profit": None if max_profit is None else round(max_profit, 2),
        "max_loss": None if max_loss is None else round(max_loss, 2),
        "premium": round(premium, 2), "kind": "credit" if premium > 0 else "debit" if premium < 0 else "none",
        "greeks": {"delta": round(g["delta"], 2), "gamma": round(g["gamma"], 4), "theta": round(g["theta"], 2),
                   "vega": round(g["vega"], 2)},
        "pop_pct": pop, "one_sd": [round(spot * math.exp(-sd), 2), round(spot * math.exp(sd), 2)],
        "reward_risk": (round(max_profit / -max_loss, 2) if max_profit is not None and max_loss not in (None, 0)
                        and max_loss < 0 else None),
    }


def build(symbol: str, expiry: str | None, legs_in: list[dict], days: float = 0.0, iv_shift: float = 0.0,
          lot: int | None = None) -> dict:
    """Prices the legs on the stored chain (options_svc.chain) and returns the payoff."""
    if len(legs_in) > MAX_LEGS:
        raise ApiException("VALIDATION", f"At most {MAX_LEGS} legs.", None, {})
    c = options_svc.chain(symbol, expiry, 15)
    spot, F = c["spot"], c["forward"] or c["spot"]
    if not spot:
        raise ApiException("FEATURE_UNAVAILABLE", "The stored chain has no spot price.", None, {"feature": "payoff"})
    lot = int(lot or c.get("lot") or 1)
    at = datetime.fromisoformat(c["time"])
    exp = date.fromisoformat(c["expiry"])
    T = opt.years_to_expiry(exp, at)
    r = options_svc._cfg()["risk_free_pct"] / 100
    rows = {row["strike"]: row for row in c["rows"]}
    atm_iv = (c["summary"].get("atm_iv_pct") or 15.0) / 100
    legs, out_legs = [], []
    for lg in legs_in:
        kind = lg["kind"]
        strike = float(lg.get("strike") or 0)
        row = rows.get(strike)
        if kind != "FUT" and row is None:
            raise ApiException("VALIDATION", f"Strike {strike:g} is not in the stored {c['symbol']} chain.", None, {})
        side = row[kind.lower()] if kind != "FUT" else {}
        price = lg.get("price")
        if price is None:
            price = F if kind == "FUT" else side.get("ltp")
        if price is None:
            raise ApiException("VALIDATION", f"No price for the {strike:g} {kind}: type one.", None, {})
        iv = lg.get("iv_pct")
        iv = (iv if iv is not None else side.get("iv_pct") if kind != "FUT" else None)
        iv = (iv / 100) if iv else atm_iv
        q = int(lg.get("lots") or 1) * lot
        legs.append({"kind": kind, "strike": strike, "side": lg["side"], "qty": q, "price": float(price), "iv": iv})
        out_legs.append({**legs[-1], "lots": int(lg.get("lots") or 1), "iv_pct": round(iv * 100, 2),
                         "ltp": side.get("ltp") if kind != "FUT" else None, "bid": side.get("bid"), "ask": side.get("ask")})
    try:
        res = payoff(legs, spot, F, T, r, atm_iv, days=days, iv_shift=iv_shift)
    except ValueError as e:
        raise ApiException("VALIDATION", str(e), None, {}) from e
    return {"symbol": c["symbol"], "expiry": c["expiry"], "time": c["time"], "spot": spot, "forward": F, "lot": lot,
            "days_to_expiry": c["days_to_expiry"], "atm_iv_pct": round(atm_iv * 100, 2), "legs": out_legs,
            "days": days, "iv_shift": iv_shift, "as_of": now_ist().isoformat(timespec="seconds"), **res,
            "note": "Margin not included: an option you sell needs SPAN + exposure margin from your broker."}


# ---- your real F&O positions (FYERS) in the builder -----------------------------------------------------------------
import re as _re
from datetime import date as _date

_MONTHS = {m: i for i, m in enumerate(("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"), 1)}
_MONTHLY = _re.compile(r"^(?P<u>[A-Z&-]+?)(?P<yy>\d{2})(?P<mon>JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)"
                       r"(?:(?P<fut>FUT)|(?P<k>\d+(?:\.\d+)?)(?P<t>CE|PE))$")
_WEEKLY = _re.compile(r"^(?P<u>[A-Z&-]+?)(?P<yy>\d{2})(?P<m>[1-9OND])(?P<dd>\d{2})(?P<k>\d+(?:\.\d+)?)(?P<t>CE|PE)$")


def parse_fno_symbol(sym: str) -> dict | None:
    """A FYERS derivative symbol: NSE:NIFTY26NOV25200CE (monthly), NSE:NIFTY2611725200CE (weekly: year, month 1-9 /
    O / N / D, day), NSE:BANKNIFTY26DECFUT. Returns underlying, kind CE / PE / FUT, strike, and the expiry (a date
    for weekly contracts, (year, month) for monthly ones, whose day is the month's last expiry)."""
    s = str(sym).upper().removeprefix("NSE:").removeprefix("NFO:")
    m = _WEEKLY.match(s)
    if m:
        mon = {"O": 10, "N": 11, "D": 12}.get(m["m"]) or int(m["m"])
        try:
            exp = _date(2000 + int(m["yy"]), mon, int(m["dd"]))
        except ValueError:
            return None
        return {"underlying": m["u"], "kind": m["t"], "strike": float(m["k"]), "expiry": exp.isoformat(), "monthly": None}
    m = _MONTHLY.match(s)
    if m:
        return {"underlying": m["u"], "kind": "FUT" if m["fut"] else m["t"], "strike": float(m["k"]) if m["k"] else None,
                "expiry": None, "monthly": (2000 + int(m["yy"]), _MONTHS[m["mon"]])}
    return None


def my_positions() -> dict:
    """Open F&O positions on your FYERS account, grouped by underlying and expiry, as builder legs."""
    from . import orders_svc
    try:
        b = orders_svc.broker()
    except ApiException as e:
        return {"logged_in": False, "groups": [], "note": e.message}
    pos = b.positions()
    if pos.get("s") != "ok":
        return {"logged_in": True, "groups": [], "note": f"FYERS: {pos.get('message')}"}
    stored = {(r["symbol"], r["expiry"]) for r in options_svc._refs()}
    exps_by_sym: dict[str, list[str]] = {}
    for sym, e in stored:
        exps_by_sym.setdefault(sym, []).append(e)
    groups: dict[tuple, dict] = {}
    for x in pos.get("netPositions") or []:
        qty = int(float(x.get("netQty") or 0))
        p = parse_fno_symbol(x.get("symbol", ""))
        if not qty or not p:
            continue
        exp = p["expiry"]
        if exp is None and p["monthly"]:
            y, mo = p["monthly"]
            same = sorted(e for e in exps_by_sym.get(p["underlying"], []) if e.startswith(f"{y}-{mo:02d}"))
            exp = same[-1] if same else f"{y}-{mo:02d}"
        g = groups.setdefault((p["underlying"], exp), {"symbol": p["underlying"], "expiry": exp,
                                                         "stored": (p["underlying"], exp) in stored, "legs": []})
        g["legs"].append({"kind": p["kind"], "side": "buy" if qty > 0 else "sell", "strike": p["strike"], "qty": abs(qty),
                          "price": orders_svc._num(x.get("netAvg")), "ltp": orders_svc._num(x.get("ltp")),
                          "pl": orders_svc._num(x.get("pl")), "fyers_symbol": x.get("symbol")})
    return {"logged_in": True, "groups": list(groups.values()),
            "note": "Your open F&O positions from FYERS (read only). A group can be analysed when its option chain is "
                    "stored (Options page)."}
