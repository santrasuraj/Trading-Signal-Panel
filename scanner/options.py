"""Option chains: open interest, PCR, max pain, implied volatility, the move the market prices, OI levels and what
changed at each strike - for index and stock options, during the session and after it.

Source: NSE's public option chain (www.nseindia.com/api/option-chain-v3): the exchange's own figures for every strike
of one expiry - last price, change, open interest and its change since yesterday, volume, best bid/ask, pending
buy/sell quantity. NSE stamps each chain with its time; a chain is stored only when that time is new, so polling more
often than NSE updates stores nothing twice. OI and volume are in contracts, as NSE reports them.
FYERS (real time) is not used yet: its option-chain response has not been checked against a real one.

Everything here describes positioning. None of it is a signal: no backtest in this app shows that PCR, max pain or OI
levels predict prices. Every stored chain (data/options/YYYYMMDD/) is kept so that can be tested once enough days
exist.

  python -m scanner.options            fetch the configured chains once
  python intraday_sync.py --options    every `options.interval_seconds` during the session (09:14 scheduled task)
"""
from __future__ import annotations

import json
import math
import os
import re
import time
from contextlib import contextmanager
from datetime import date, datetime
from datetime import time as dtime

import numpy as np
import pandas as pd

from . import smart_money as sm
from .lock import _try_lock, _unlock
from .settings import DATA_DIR, IST, ist_now, load_config
from .store import _replace

API = "https://www.nseindia.com/api/"
REFERER = "https://www.nseindia.com/option-chain"
OPTIONS_DIR = DATA_DIR / "options"
LATEST_NAME = "latest.json"
SUMMARY_NAME = "summary.parquet"
LIVE_LOCK_NAME = ".live.lock"
WRITE_LOCK_NAME = ".write.lock"

INDICES = frozenset({"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50"})
DEFAULTS = {"underlyings": ["NIFTY", "BANKNIFTY"], "expiries": 2, "interval_seconds": 60, "risk_free_pct": 6.5}
MIN_INTERVAL_S = 30          # NSE is asked politely: never more often than this per chain
BLOCK_PAUSE_S = 300          # NSE refused (403/429): no NSE call for 5 minutes
EXPIRY_CLOSE = dtime(15, 30)
MIN_T_YEARS = 15 / (365 * 24 * 60)     # 15 minutes: an expiring chain still gets finite numbers
BUILDUP_MIN_PCT = 5.0        # an OI change under 5% of yesterday's OI is noise, not a build-up
LEVELS = 3                   # strikes listed per level / addition list
PARITY_STRIKES = 5           # strikes nearest the spot that estimate the forward (put-call parity)

SIDES = ("ce", "pe")
NSE_FIELDS = {"ltp": "lastPrice", "chg": "change", "oi": "openInterest", "oi_chg": "changeinOpenInterest",
              "volume": "totalTradedVolume", "iv_nse": "impliedVolatility", "bid": "buyPrice1", "ask": "sellPrice1",
              "buy_qty": "totalBuyQuantity", "sell_qty": "totalSellQuantity"}
CHAIN_COLS = ["strike"] + [f"{s}_{f}" for s in SIDES for f in NSE_FIELDS]
SUMMARY_COLS = ["time", "symbol", "expiry", "spot", "forward", "atm", "atm_iv", "straddle", "expected_move_pct",
                "pcr_oi", "pcr_volume", "max_pain", "ce_oi", "pe_oi", "ce_oi_chg", "pe_oi_chg", "support",
                "resistance", "skew_25d"]
BUILDUPS = ("long_buildup", "short_buildup", "short_covering", "long_unwinding")


def folder() -> "os.PathLike":
    """data/options (a module global, so the web API's tests can repoint it)."""
    return OPTIONS_DIR


def settings(cfg: dict | None = None) -> dict:
    """config.yaml `options:` merged over DEFAULTS, validated (a bad value falls back to its default)."""
    raw = (cfg or {}).get("options") or {}
    out = dict(DEFAULTS)
    syms = raw.get("underlyings")
    if isinstance(syms, (list, tuple)):
        clean = [s for s in (str(x).strip().upper() for x in syms) if valid_symbol(s)]
        out["underlyings"] = [s for i, s in enumerate(clean) if s not in clean[:i]] or DEFAULTS["underlyings"]
    for key, lo, hi in (("expiries", 1, 6), ("interval_seconds", MIN_INTERVAL_S, 3600)):
        try:
            out[key] = min(max(int(raw.get(key, out[key])), lo), hi)
        except (TypeError, ValueError):
            pass
    try:
        r = float(raw.get("risk_free_pct", out["risk_free_pct"]))
        out["risk_free_pct"] = r if 0 <= r <= 20 else DEFAULTS["risk_free_pct"]
    except (TypeError, ValueError):
        pass
    return out


def valid_symbol(s: str) -> bool:
    """An NSE symbol (it becomes part of a file name): letters, digits, '&' and '-'."""
    return bool(re.fullmatch(r"[A-Z0-9&-]{1,20}", s or ""))


def instrument_type(symbol: str) -> str:
    return "Indices" if symbol.upper() in INDICES else "Equity"


# --------------------------------------------------------------------------- NSE
def _get(path: str, params: dict) -> tuple[int, dict | None]:
    """(status, JSON) from NSE's API through smart_money's session (cookies, spacing, never raises).
    -2 = NSE calls stopped for now (refused earlier), -3 = not JSON."""
    code, body = sm._fetch(API + path, params, api=True, referer=REFERER)
    if code != 200:
        return code, None
    try:
        return 200, json.loads(body)
    except ValueError:
        return -3, None


def _refused(code: int) -> bool:
    return code in (-2, 401, 403, 429)


_expiry_cache: dict[tuple[str, date], list[date]] = {}


def expiries(symbol: str) -> tuple[list[date], int]:
    """The symbol's option expiries, nearest first (NSE's contract list, cached for the day), and the HTTP status."""
    key = (symbol, ist_now().date())
    if key in _expiry_cache:
        return _expiry_cache[key], 200
    code, body = _get("option-chain-contract-info", {"symbol": symbol})
    if body is None:
        return [], code
    out = sorted({d for d in (_nse_date(x) for x in body.get("expiryDates") or []) if d is not None})
    if out:
        _expiry_cache[key] = out
    return out, code


def _nse_date(s) -> date | None:
    for fmt in ("%d-%b-%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(str(s), fmt).date()
        except ValueError:
            pass
    return None


def _num(x) -> float:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return math.nan
    return v if math.isfinite(v) else math.nan


def parse_nse(payload: dict, symbol: str, expiry: date) -> tuple[pd.DataFrame, dict]:
    """NSE option-chain-v3 JSON -> (one row per strike, CHAIN_COLS) and {symbol, expiry, spot, time, source}.
    A zero price or IV means "no figure" at NSE: NaN here. `time` is NSE's own stamp (IST), None if missing."""
    rec = (payload or {}).get("records") or {}
    rows = []
    for item in rec.get("data") or []:
        k = _num(item.get("strikePrice"))
        if not k > 0:
            continue
        row = {"strike": k}
        for side in SIDES:
            leg = item.get(side.upper()) or {}
            for f, src in NSE_FIELDS.items():
                v = _num(leg.get(src))
                row[f"{side}_{f}"] = math.nan if f in ("ltp", "iv_nse", "bid", "ask") and not v > 0 else v
        rows.append(row)
    chain = (pd.DataFrame(rows, columns=CHAIN_COLS).sort_values("strike").drop_duplicates("strike")
             .reset_index(drop=True))
    try:
        stamp = datetime.strptime(str(rec.get("timestamp")), "%d-%b-%Y %H:%M:%S").replace(tzinfo=IST)
    except ValueError:
        stamp = None
    spot = _num(rec.get("underlyingValue"))
    return chain, {"symbol": symbol.upper(), "expiry": expiry, "spot": spot if spot > 0 else None,
                   "time": stamp, "source": "nse"}


# --------------------------------------------------------------------------- pricing (Black-76 on the forward)
def _erfc(x):
    """Complementary error function, vectorised (Numerical Recipes' Chebyshev fit: relative error < 1.2e-7 everywhere,
    so deep out-of-the-money tails stay accurate). numpy has no erf and scipy is not a dependency."""
    z = np.abs(x)
    t = 1.0 / (1.0 + 0.5 * z)
    poly = -z * z - 1.26551223 + t * (1.00002368 + t * (0.37409196 + t * (0.09678418 + t * (-0.18628806 + t * (
        0.27886807 + t * (-1.13520398 + t * (1.48851587 + t * (-0.82215223 + t * 0.17087277))))))))
    ans = t * np.exp(poly)
    return np.where(x >= 0, ans, 2.0 - ans)


def _ncdf(x):
    return 0.5 * _erfc(-np.asarray(x, dtype=float) / math.sqrt(2.0))


def _npdf(x):
    x = np.asarray(x, dtype=float)
    return np.exp(-0.5 * x * x) / math.sqrt(2 * math.pi)


def black76(F, K, T, r, sigma, call):
    """Option price on a forward F (index options: the futures-implied level, so dividends are in F)."""
    F, K, sigma, call = (np.asarray(a, dtype=float) for a in (F, K, sigma, call))
    sq = sigma * math.sqrt(T)
    d1 = (np.log(F / K) + 0.5 * sq * sq) / sq
    d2 = d1 - sq
    df = math.exp(-r * T)
    return np.where(call > 0, df * (F * _ncdf(d1) - K * _ncdf(d2)), df * (K * _ncdf(-d2) - F * _ncdf(-d1)))


def implied_vol(price, F, K, T, r, call, lo=0.005, hi=5.0, iters=60):
    """Implied volatility (0.15 = 15%) by bisection, vectorised; NaN where the price is outside what any volatility
    can give (below intrinsic value, above the forward / strike) or missing."""
    price, K, call = (np.asarray(a, dtype=float) for a in (price, K, call))
    F = np.broadcast_to(np.asarray(F, dtype=float), K.shape)
    df = math.exp(-r * T)
    intrinsic = np.where(call > 0, np.maximum(F - K, 0), np.maximum(K - F, 0)) * df
    cap = np.where(call > 0, F, K) * df
    ok = np.isfinite(price) & (price > intrinsic + 1e-9) & (price < cap)
    a, b = np.full(K.shape, lo), np.full(K.shape, hi)
    for _ in range(iters):
        mid = 0.5 * (a + b)
        high = black76(F, K, T, r, mid, call) > price
        b, a = np.where(high, mid, b), np.where(high, a, mid)
    return np.where(ok, 0.5 * (a + b), np.nan)


def greeks(F, K, T, r, sigma, call) -> dict[str, np.ndarray]:
    """Black-76 delta, gamma (per point), theta (per calendar day) and vega (per volatility point)."""
    K, sigma, call = (np.asarray(a, dtype=float) for a in (K, sigma, call))
    sq = sigma * math.sqrt(T)
    with np.errstate(divide="ignore", invalid="ignore"):
        d1 = (np.log(F / K) + 0.5 * sq * sq) / sq
    df = math.exp(-r * T)
    pdf = _npdf(d1)
    price = black76(F, K, T, r, sigma, call)
    with np.errstate(divide="ignore", invalid="ignore"):
        delta = np.where(call > 0, df * _ncdf(d1), -df * _ncdf(-d1))
        gamma = df * pdf / (F * sq)
        theta = (-F * df * pdf * sigma / (2 * math.sqrt(T)) + r * price) / 365.0
        vega = df * F * pdf * math.sqrt(T) / 100.0
    return {"delta": delta, "gamma": gamma, "theta": theta, "vega": vega}


def years_to_expiry(expiry: date, at: datetime) -> float:
    """Calendar time from `at` to the expiry's 15:30 close, in years (at least 15 minutes)."""
    close = datetime.combine(expiry, EXPIRY_CLOSE, tzinfo=IST)
    return max((close - at).total_seconds() / (365 * 86400), MIN_T_YEARS)


def option_price(chain: pd.DataFrame, side: str) -> pd.Series:
    """The price an option is valued at: mid of the best bid and ask when both exist and the spread is under 20% of
    the mid, else the last traded price."""
    bid, ask, ltp = chain[f"{side}_bid"], chain[f"{side}_ask"], chain[f"{side}_ltp"]
    mid = (bid + ask) / 2
    good = (bid > 0) & (ask >= bid) & ((ask - bid) <= 0.2 * mid)
    return mid.where(good, ltp)


def forward(chain: pd.DataFrame, spot: float, T: float, r: float) -> float:
    """The level options are priced off: put-call parity (K + (C - P) e^rT) at the strikes nearest the spot, median.
    Falls back to spot x e^rT when parity is missing or more than 5% from the spot (stale prices)."""
    c, p = option_price(chain, "ce"), option_price(chain, "pe")
    both = chain[(c > 0) & (p > 0)]
    if len(both):
        near = both.loc[(both["strike"] - spot).abs().sort_values().index[:PARITY_STRIKES]]
        f = float(np.median(near["strike"] + (c[near.index] - p[near.index]) * math.exp(r * T)))
        if abs(f / spot - 1) <= 0.05:
            return f
    return spot * math.exp(r * T)


# --------------------------------------------------------------------------- analysis
def max_pain(chain: pd.DataFrame) -> float | None:
    """The expiry level at which option buyers as a whole would collect least (every strike tried)."""
    k = chain["strike"].to_numpy(dtype=float)
    ce, pe = (chain[f"{s}_oi"].fillna(0).to_numpy(dtype=float) for s in SIDES)
    if not len(k) or (ce.sum() + pe.sum()) <= 0:
        return None
    s = k[:, None]
    pain = (ce * np.maximum(s - k, 0)).sum(axis=1) + (pe * np.maximum(k - s, 0)).sum(axis=1)
    return float(k[int(np.argmin(pain))])


def buildup(price_chg: pd.Series, oi: pd.Series, oi_chg: pd.Series, min_pct: float = BUILDUP_MIN_PCT) -> pd.Series:
    """What the day's change says, per strike, from the contract's side: price up + OI up = long build-up, price down
    + OI up = short build-up, price up + OI down = short covering, price down + OI down = long unwinding. None when
    OI moved less than `min_pct` % of yesterday's or the price did not move."""
    prev = oi - oi_chg
    pct = (oi_chg / prev.where(prev > 0)) * 100
    pct = pct.where(prev > 0, np.where(oi > 0, np.inf, 0.0))      # new open interest: a build-up
    big = pct.abs() >= min_pct
    up, down = price_chg > 0, price_chg < 0
    oi_up, oi_down = oi_chg > 0, oi_chg < 0
    labels = np.select([big & up & oi_up, big & down & oi_up, big & up & oi_down, big & down & oi_down],
                       list(BUILDUPS), default=None)
    return pd.Series(labels, index=oi.index, dtype=object)


def _f(x, nd: int = 2):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return round(v, nd) if math.isfinite(v) else None


def _i(x):
    v = _f(x, 0)
    return int(v) if v is not None else None


def _top(chain: pd.DataFrame, col: str, where=None, n: int = LEVELS, positive: bool = False) -> list[dict]:
    side = col[:2]
    c = chain if where is None else chain[where]
    c = c[c[col].notna() & ((c[col] > 0) if positive else True)]
    return [{"strike": _f(r["strike"]), "oi": _i(r[f"{side}_oi"]), "oi_chg": _i(r[f"{side}_oi_chg"])}
            for _, r in c.nlargest(n, col).iterrows()]


def analyze(chain: pd.DataFrame, meta: dict, risk_free_pct: float = DEFAULTS["risk_free_pct"]) -> dict:
    """Everything the Options page shows for one chain (JSON-ready: NaN -> None)."""
    chain = chain.reset_index(drop=True)          # labels = positions below
    spot = meta["spot"]
    at = meta["time"] or ist_now()
    expiry = meta["expiry"]
    T, r = years_to_expiry(expiry, at), risk_free_pct / 100
    F = forward(chain, spot, T, r)
    k = chain["strike"]
    atm_i = int((k - F).abs().idxmin())
    atm = float(k[atm_i])

    sides = {}
    for side in SIDES:
        call = 1.0 if side == "ce" else 0.0
        px = option_price(chain, side)
        iv = pd.Series(implied_vol(px, F, k, T, r, np.full(len(k), call)), index=k.index)
        g = greeks(F, k, T, r, iv.fillna(0.2), np.full(len(k), call))
        sides[side] = {"price": px, "iv": iv, "g": {n: pd.Series(v, index=k.index).where(iv.notna()) for n, v in g.items()},
                       "buildup": buildup(chain[f"{side}_chg"], chain[f"{side}_oi"], chain[f"{side}_oi_chg"])}

    ce_iv, pe_iv = sides["ce"]["iv"], sides["pe"]["iv"]
    atm_iv = np.nanmean([ce_iv[atm_i], pe_iv[atm_i]]) if (ce_iv[atm_i] > 0 or pe_iv[atm_i] > 0) else math.nan
    straddle = sides["ce"]["price"][atm_i] + sides["pe"]["price"][atm_i]
    one_sd = F * atm_iv * math.sqrt(T) if atm_iv > 0 else math.nan
    # 25-delta skew: the put and the call whose delta is nearest 0.25, in volatility points
    cd, pd_ = sides["ce"]["g"]["delta"], sides["pe"]["g"]["delta"]
    skew = math.nan
    if cd.notna().any() and pd_.notna().any():
        ci, pi = (cd - 0.25).abs().idxmin(), (pd_ + 0.25).abs().idxmin()
        skew = (pe_iv[pi] - ce_iv[ci]) * 100

    tot = {f"{s}_{f}": float(chain[f"{s}_{f}"].fillna(0).sum()) for s in SIDES for f in ("oi", "oi_chg", "volume")}
    pcr_oi = tot["pe_oi"] / tot["ce_oi"] if tot["ce_oi"] > 0 else math.nan
    pcr_vol = tot["pe_volume"] / tot["ce_volume"] if tot["ce_volume"] > 0 else math.nan
    mp = max_pain(chain)
    levels = {
        "resistance": _top(chain, "ce_oi", k >= spot),
        "support": _top(chain, "pe_oi", k <= spot),
        "call_adds": _top(chain, "ce_oi_chg", positive=True),
        "put_adds": _top(chain, "pe_oi_chg", positive=True),
    }
    summary = {
        "pcr_oi": _f(pcr_oi), "pcr_volume": _f(pcr_vol), "max_pain": _f(mp),
        "max_pain_gap_pct": _f((mp / spot - 1) * 100) if mp else None,
        "atm_iv_pct": _f(atm_iv * 100), "straddle": _f(straddle), "expected_move_pct": _f(straddle / spot * 100),
        "one_sd_pts": _f(one_sd), "range_low": _f(spot - one_sd), "range_high": _f(spot + one_sd),
        "skew_25d": _f(skew), **{key: _i(v) for key, v in tot.items()},
    }
    # plain arrays for the per-strike rows (a pandas lookup per cell made this the slowest part by far)
    col = {c: chain[c].to_numpy(dtype=float) for c in CHAIN_COLS}
    arr = {side: {"iv": s["iv"].to_numpy(), "build": s["buildup"].to_numpy(),
                  **{n: g.to_numpy() for n, g in s["g"].items()}} for side, s in sides.items()}
    rows = []
    for i in range(len(chain)):
        row = {"strike": _f(col["strike"][i]), "atm": i == atm_i}
        for side in SIDES:
            a, v = arr[side], (lambda f, side=side: col[f"{side}_{f}"][i])       # noqa: E731
            oi, chg = v("oi"), v("oi_chg")
            prev = oi - chg if np.isfinite(oi) and np.isfinite(chg) else math.nan
            row[side] = {
                "ltp": _f(v("ltp")), "chg": _f(v("chg")), "oi": _i(oi), "oi_chg": _i(chg),
                "oi_chg_pct": _f(chg / prev * 100) if prev > 0 else None, "volume": _i(v("volume")),
                "iv_pct": _f(a["iv"][i] * 100), "iv_nse_pct": _f(v("iv_nse")), "bid": _f(v("bid")), "ask": _f(v("ask")),
                "buy_qty": _i(v("buy_qty")), "sell_qty": _i(v("sell_qty")),
                **{n: _f(a[n][i], 4) for n in ("delta", "gamma", "theta", "vega")},
                "buildup": a["build"][i] if isinstance(a["build"][i], str) else None,
            }
        rows.append(row)
    out = {
        "symbol": meta["symbol"], "expiry": expiry.isoformat(), "time": at.isoformat(timespec="seconds"),
        "source": meta.get("source", "nse"), "spot": _f(spot), "forward": _f(F), "atm": _f(atm),
        "days_to_expiry": _f(T * 365, 2), "summary": summary, "levels": levels, "rows": rows,
    }
    out["readings"] = readings(out)
    return out


def _n(x, nd: int = 0) -> str:
    return f"{x:,.{nd}f}" if x is not None else "?"


def readings(a: dict) -> list[str]:
    """Plain facts about one analysed chain, for the page (never a recommendation)."""
    s, lv, spot = a["summary"], a["levels"], a["spot"]
    out = []
    if lv["resistance"] and lv["support"]:
        out.append(f"Largest call open interest above the spot: {_n(lv['resistance'][0]['strike'])}; largest put open "
                   f"interest below it: {_n(lv['support'][0]['strike'])} (often read as resistance and support; "
                   "they move as positions change).")
    if s["expected_move_pct"] is not None and s["straddle"] is not None:
        exp = date.fromisoformat(a["expiry"]).strftime("%d %b")
        out.append(f"The at-the-money straddle costs {_n(s['straddle'], 1)}: options price a move of about "
                   f"±{s['expected_move_pct']:.1f}% (±{_n(s['straddle'])} points) by the {exp} expiry.")
    if s["pcr_oi"] is not None:
        more = "puts than calls" if s["pcr_oi"] >= 1 else "calls than puts"
        out.append(f"Put-call ratio {s['pcr_oi']:.2f}: more {more} are open.")
    if s["max_pain"] is not None and spot:
        gap = s["max_pain"] - spot
        where = "at" if abs(gap) < 0.5 else ("above" if gap > 0 else "below")
        out.append(f"Max pain {_n(s['max_pain'])}" + (f", {_n(abs(gap))} points {where} the spot." if where != "at"
                                                         else ", at the spot."))
    adds = [f"{label} at {_n(lst[0]['strike'])} (+{_n(lst[0]['oi_chg'])})"
            for label, lst in (("calls", lv["call_adds"]), ("puts", lv["put_adds"])) if lst]
    if adds:
        out.append("Biggest open-interest additions since yesterday: " + " and ".join(adds) + ".")
    return out


def window_change(snaps: pd.DataFrame, minutes: int) -> dict | None:
    """Open-interest change per strike over the last `minutes` of stored chains: {strike: (ce, pe)} plus the
    earlier chain's time, or None without a chain at least that old (first minutes of the day)."""
    if snaps is None or snaps.empty:
        return None
    t = pd.to_datetime(snaps["time"])
    last = t.max()
    older = t[t <= last - pd.Timedelta(minutes=int(minutes))]
    if older.empty:
        return None
    then = older.max()
    a = snaps[t == then].set_index("strike")
    b = snaps[t == last].set_index("strike")
    d = b[["ce_oi", "pe_oi"]].sub(a[["ce_oi", "pe_oi"]].reindex(b.index))
    return {"since": then.isoformat(),
            "rows": {float(k): (_i(r["ce_oi"]), _i(r["pe_oi"])) for k, r in d.iterrows()}}


UNUSUAL_N = 10
UNUSUAL_VOL_OI = 1.0         # traded today at least as many contracts as are open: fresh, heavy interest
UNUSUAL_WIN_PCT = 10.0       # or open interest changed this much within the window
UNUSUAL_MIN_SHARE = 0.005    # ... and the strike carries at least 0.5% of its side's volume (no illiquid noise)


def unusual(chain: pd.DataFrame, window: dict | None, lot: float | None, n: int = UNUSUAL_N) -> list[dict]:
    """Strikes with unusual activity: volume at or above their open interest, or an open-interest jump of
    UNUSUAL_WIN_PCT within the window (see window_change). Ranked by premium traded (contracts x lot x price, Rs crore)
    when the lot size is known, else by contracts. What happened, not who did it, nor which side started it."""
    parts = []
    wrows = (window or {}).get("rows") or {}
    for j, side in enumerate(SIDES):
        d = pd.DataFrame({"strike": chain["strike"].to_numpy(float), "side": side,
                          "ltp": chain[f"{side}_ltp"].to_numpy(float), "volume": chain[f"{side}_volume"].to_numpy(float),
                          "oi": chain[f"{side}_oi"].to_numpy(float)})
        d["win"] = [wrows.get(float(k), (None, None))[j] for k in d["strike"]]
        d["share"] = d["volume"] / max(float(d["volume"].sum()), 1.0)
        parts.append(d)
    d = pd.concat(parts, ignore_index=True)
    d["win"] = pd.to_numeric(d["win"], errors="coerce")
    d["vol_oi"] = d["volume"] / d["oi"].where(d["oi"] > 0)
    before = d["oi"] - d["win"]
    d["win_pct"] = d["win"] / before.where(before > 0) * 100
    d["value_cr"] = d["volume"] * d["ltp"] * lot / 1e7 if lot and lot > 0 else np.nan
    hot_vol = d["vol_oi"] >= UNUSUAL_VOL_OI
    hot_win = d["win_pct"].abs() >= UNUSUAL_WIN_PCT
    d = d[(hot_vol | hot_win) & (d["share"] >= UNUSUAL_MIN_SHARE)].copy()
    if d.empty:
        return []
    d["rank"] = d["value_cr"].fillna(-1.0) if lot else d["volume"]     # no price: ranked last
    out = []
    for r in d.sort_values("rank", ascending=False).head(n).itertuples(index=False):
        why = []
        if r.vol_oi >= UNUSUAL_VOL_OI:
            why.append(f"traded {r.vol_oi:.1f}x its open interest today")
        if pd.notna(r.win_pct) and abs(r.win_pct) >= UNUSUAL_WIN_PCT:
            why.append(f"open interest {'+' if r.win > 0 else ''}{r.win_pct:.0f}% in the window")
        out.append({"strike": _f(r.strike), "side": r.side, "ltp": _f(r.ltp), "volume": _i(r.volume), "oi": _i(r.oi),
                    "vol_oi": _f(r.vol_oi), "oi_chg_window": _i(r.win), "oi_chg_window_pct": _f(r.win_pct),
                    "value_cr": _f(r.value_cr), "why": why})
    return out


# --------------------------------------------------------------------------- storage
def day_dir(day: date):
    return folder() / f"{day:%Y%m%d}"


def snap_file(day: date, symbol: str, expiry: date):
    return day_dir(day) / f"{symbol}_{expiry:%Y%m%d}.parquet"


@contextmanager
def _write_lock(timeout: float = 30.0):
    """One writer at a time across processes (the live job and the web app's refresh)."""
    folder().mkdir(parents=True, exist_ok=True)
    fh = open(folder() / WRITE_LOCK_NAME, "a+")
    deadline = time.monotonic() + timeout
    try:
        while not _try_lock(fh):
            if time.monotonic() > deadline:
                raise TimeoutError("option-chain files are busy")
            time.sleep(0.05)
        try:
            yield
        finally:
            _unlock(fh)
    finally:
        fh.close()


def _write_parquet(df: pd.DataFrame, path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    df.to_parquet(tmp, index=False)
    _replace(tmp, path)


def write_json(obj: dict, path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(obj, indent=1, default=str), encoding="utf-8")
    _replace(tmp, path)


def load_latest() -> dict:
    try:
        return json.loads((folder() / LATEST_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"chains": {}}


def store(chain: pd.DataFrame, meta: dict, analysis: dict) -> bool:
    """Append one chain to its day file and the day's summary, and point latest.json at it. False (nothing written)
    when NSE's stamp is not newer than the stored chain's: the same chain fetched again."""
    stamp = meta["time"]
    day, sym, exp = stamp.date(), meta["symbol"], meta["expiry"]
    path = snap_file(day, sym, exp)
    ts = pd.Timestamp(stamp).tz_convert(IST)
    with _write_lock():
        old = pd.read_parquet(path) if path.exists() else None
        if old is not None and len(old) and pd.to_datetime(old["time"]).max() >= ts:
            return False
        new = chain.assign(time=ts, spot=meta["spot"])
        _write_parquet(new if old is None else pd.concat([old, new], ignore_index=True), path)
        s = analysis["summary"]
        row = {"time": ts, "symbol": sym, "expiry": exp.isoformat(), "spot": meta["spot"],
               "forward": analysis["forward"], "atm": analysis["atm"], "atm_iv": s["atm_iv_pct"],
               "straddle": s["straddle"], "expected_move_pct": s["expected_move_pct"], "pcr_oi": s["pcr_oi"],
               "pcr_volume": s["pcr_volume"], "max_pain": s["max_pain"], "ce_oi": s["ce_oi"], "pe_oi": s["pe_oi"],
               "ce_oi_chg": s["ce_oi_chg"], "pe_oi_chg": s["pe_oi_chg"],
               "support": (analysis["levels"]["support"] or [{}])[0].get("strike"),
               "resistance": (analysis["levels"]["resistance"] or [{}])[0].get("strike"), "skew_25d": s["skew_25d"]}
        spath = day_dir(day) / SUMMARY_NAME
        add = pd.DataFrame([row], columns=SUMMARY_COLS)
        _write_parquet(pd.concat([pd.read_parquet(spath), add], ignore_index=True) if spath.exists() else add, spath)
        latest = load_latest()
        latest.setdefault("chains", {})[f"{sym}|{exp.isoformat()}"] = {
            "symbol": sym, "expiry": exp.isoformat(), "day": day.isoformat(), "time": ts.isoformat(),
            "spot": meta["spot"], "source": meta.get("source", "nse"), "stored_at": ist_now().isoformat(timespec="seconds")}
        write_json(latest, folder() / LATEST_NAME)
    return True


def load_snapshots(day: date, symbol: str, expiry: date) -> pd.DataFrame | None:
    path = snap_file(day, symbol, expiry)
    return pd.read_parquet(path) if path.exists() else None


def chain_at(snaps: pd.DataFrame, at=None) -> tuple[pd.DataFrame, pd.Timestamp]:
    """The stored chain at time `at` (default: the newest) and its time."""
    t = pd.to_datetime(snaps["time"])
    when = t.max() if at is None else t[t <= pd.Timestamp(at)].max()
    rows = snaps[t == when]
    return rows[CHAIN_COLS].sort_values("strike").reset_index(drop=True), when


# --------------------------------------------------------------------------- refresh / live
_blocked_until = 0.0


def refresh(cfg: dict | None = None, symbols: list[str] | None = None, log=print, reset: bool = False) -> dict:
    """Fetch, analyse and store the nearest `expiries` chains of each underlying once. Never raises for NSE problems:
    they are listed in the report (and in latest.json's `last_refresh`)."""
    global _blocked_until
    cfg = cfg if cfg is not None else load_config()
    st = settings(cfg)
    t0 = time.monotonic()
    rep = {"started_at": ist_now().isoformat(timespec="seconds"), "chains": [], "errors": [], "refused": False}
    if reset or time.time() >= _blocked_until:
        sm._reset_api()
    if time.time() < _blocked_until and not reset:
        rep["refused"] = True
        rep["errors"].append("NSE refused requests a few minutes ago - waiting before asking again.")
    else:
        for sym in [s.upper() for s in (symbols or st["underlyings"])]:
            exps, code = expiries(sym)
            if not exps:
                rep["errors"].append(f"{sym}: no option expiries from NSE ({_why(code)})")
                if _refused(code):
                    rep["refused"] = True
                    break
                continue
            for exp in exps[: st["expiries"]]:
                code, payload = _get("option-chain-v3", {"type": instrument_type(sym), "symbol": sym,
                                                         "expiry": exp.strftime("%d-%b-%Y")})
                if payload is None:
                    rep["errors"].append(f"{sym} {exp:%d %b}: {_why(code)}")
                    if _refused(code):
                        rep["refused"] = True
                        break
                    continue
                chain, meta = parse_nse(payload, sym, exp)
                if chain.empty or meta["spot"] is None or meta["time"] is None:
                    rep["errors"].append(f"{sym} {exp:%d %b}: NSE sent an empty chain")
                    continue
                try:
                    a = analyze(chain, meta, st["risk_free_pct"])
                    new = store(chain, meta, a)
                except Exception as e:     # one bad chain must not stop the others
                    rep["errors"].append(f"{sym} {exp:%d %b}: {type(e).__name__}: {e}")
                    continue
                rep["chains"].append({"symbol": sym, "expiry": exp.isoformat(), "time": a["time"], "new": new})
                log(f"  {sym} {exp:%d %b}: {len(chain)} strikes, NSE time {meta['time']:%H:%M:%S}"
                    f"{'' if new else ' (unchanged)'}")
            if rep["refused"]:
                break
        if rep["refused"]:
            _blocked_until = time.time() + BLOCK_PAUSE_S
    rep["elapsed_s"] = round(time.monotonic() - t0, 1)
    try:
        with _write_lock():
            latest = load_latest()
            latest["last_refresh"] = {k: rep[k] for k in ("started_at", "errors", "refused", "elapsed_s")}
            latest["last_refresh"]["chains"] = len(rep["chains"])
            write_json(latest, folder() / LATEST_NAME)
    except (OSError, TimeoutError) as e:
        rep["errors"].append(f"status not saved: {type(e).__name__}")
    return rep


def _why(code: int) -> str:
    return {-1: "NSE did not answer", -2: "NSE calls paused after a refusal", -3: "NSE sent no JSON",
            401: "NSE refused (401)", 403: "NSE refused (403)", 404: "not found at NSE (no options?)",
            429: "NSE says too many requests"}.get(code, f"HTTP {code}")


def live_running() -> bool:
    """True while `intraday_sync.py --options` holds its lock."""
    path = folder() / LIVE_LOCK_NAME
    if not path.exists():
        return False
    with open(path, "a+") as fh:
        if _try_lock(fh):
            _unlock(fh)
            return False
    return True


def run_live(cfg: dict | None = None, log=print) -> int:
    """Every `interval_seconds` during the session (09:13-15:31 on trading days), then once after the close."""
    from .intraday.live import market_open_now

    cfg = cfg if cfg is not None else load_config()
    st = settings(cfg)
    folder().mkdir(parents=True, exist_ok=True)
    fh = open(folder() / LIVE_LOCK_NAME, "a+")
    if not _try_lock(fh):
        fh.close()
        log("The option-chain job is already running.")
        return 2
    try:
        log(f"Option chains every {st['interval_seconds']} s: {', '.join(st['underlyings'])} "
            f"({st['expiries']} expiries each), from NSE.")
        while market_open_now(lead_minutes=2):          # intraday_sync starts it at 09:13
            t0 = time.monotonic()
            rep = refresh(cfg, log=log)
            for e in rep["errors"]:
                log(f"  ! {e}")
            time.sleep(max(st["interval_seconds"] - (time.monotonic() - t0), 5))
        log("Session over - storing the closing chains.")
        rep = refresh(cfg, log=log)
        for e in rep["errors"]:
            log(f"  ! {e}")
        return 0
    finally:
        _unlock(fh)
        fh.close()


if __name__ == "__main__":
    r = refresh()
    print(json.dumps({k: v for k, v in r.items() if k != "chains"}, indent=1), f"\n{len(r['chains'])} chains")
