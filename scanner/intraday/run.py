"""Intraday pipeline: universe -> 5-minute bars -> per-day context -> backtests + today's live setups.

Data: Yahoo gives the last ~60 sessions of 5-minute bars (no login). With a FYERS login,
`backfill_fyers` extends history to ~1 year (and should be run daily to archive, because FYERS only
keeps a rolling year). Results go to data/results/intraday.json.
"""
from __future__ import annotations

import io
import json
import math
import time
from datetime import date, timedelta

import numpy as np
import pandas as pd

from ..events import results_history
from ..nse import _get
from ..settings import DATA_DIR, RESULTS_DIR, ist_now, ist_today
from ..store import load_store
from ..universe import get_universe
from . import data as idata
from .engine import SLOTS, Day, IntradayCosts, run_intraday
from .strategies import S_0945, build_intraday_strategies

INTRADAY_DIR = DATA_DIR / "intraday"
RESULT_FILE = RESULTS_DIR / "intraday.json"
FNO_URL = "https://nsearchives.nseindia.com/content/fo/fo_mktlots.csv"
SEBI_FACTS = {
    "source": "SEBI, Analysis of Intraday Trading by Individuals in Equity Cash Segment (July 2024)",
    "url": "https://www.sebi.gov.in/sebi_data/attachdocs/jul-2024/1721818140715.pdf",
    "points": ["71% of individual intraday traders made net losses in FY23 (65% in FY19).",
               "80% of those making more than 500 trades a year lost money.",
               "Trading costs made loss-makers' losses 57% larger and took 19% of profit-makers' profits.",
               "In F&O, 93% of individual traders lost money in FY22-FY24 (SEBI, Sep 2024)."],
}


def fno_symbols() -> list[str]:
    """NSE F&O stock list (cached for a week)."""
    path = INTRADAY_DIR / "fno.json"
    INTRADAY_DIR.mkdir(parents=True, exist_ok=True)
    if path.exists() and time.time() - path.stat().st_mtime < 7 * 86400:
        return json.loads(path.read_text(encoding="utf-8"))
    code, text = _get(FNO_URL)
    if code != 200:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    df = pd.read_csv(io.StringIO(text))
    syms = sorted({str(s).strip() for s in df.iloc[:, 1]} - {"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY",
                                                              "NIFTYNXT50", "NIFTYFPI", "SYMBOL"})
    path.write_text(json.dumps(syms), encoding="utf-8")
    return syms


def intraday_universe(cfg: dict, frames: dict) -> tuple[list[str], dict]:
    """Liquid F&O stocks (price >= Rs 100, 20-day traded value >= Rs 100 crore) + NIFTYBEES."""
    ic = cfg.get("intraday") or {}
    close, vol = frames["close"], frames["volume"]
    turnover = (close * vol).iloc[-20:].mean() / 1e7
    fno = [s for s in fno_symbols() if s in close.columns]
    liquid = [s for s in fno if close[s].iloc[-1] >= float(ic.get("min_price", 100))
              and turnover.get(s, 0) >= float(ic.get("min_turnover_cr", 100))]
    liquid.sort(key=lambda s: -turnover.get(s, 0))
    liquid = liquid[: int(ic.get("max_symbols", 150))]
    etfs = [e for e in ic.get("etfs", ["NIFTYBEES"]) if e in close.columns]
    info = {"fno": set(fno), "turnover": turnover.to_dict(), "top30": set(liquid[:30]) | set(etfs)}
    return liquid + etfs, info


def update_bars(symbols: list[str], log=print) -> pd.DataFrame:
    """Refresh the 5-minute store from Yahoo (last ~60 sessions) and return all stored 5m bars."""
    store = idata.IntradayStore(INTRADAY_DIR / "bars")
    raw = idata.fetch_yahoo_intraday(symbols, "5m", log=log)
    now = ist_now().replace(tzinfo=None)
    clean = idata.clean_bars(raw.assign(source="yahoo"), "5m", drop_synthetic_close=True, now=now)
    store.save(clean, "5m")                       # forming bars are never stored
    live = clean[(clean["flags"] & idata.FLAG_FORMING) != 0]
    bars = store.load("5m")
    return pd.concat([bars, live], ignore_index=True) if len(live) else bars


def backfill_fyers(provider, symbols: list[str], days: int = 365, log=print) -> int:
    """Extend 5-minute history to ~1 year with FYERS (Standard plan: ~50 requests/minute)."""
    store = idata.IntradayStore(INTRADAY_DIR / "bars")
    end = ist_today()
    got = idata.fetch_fyers_intraday(provider, symbols, end - timedelta(days=days), end, resolution="5")
    clean = idata.clean_bars(got.assign(source="fyers"), "5m")
    store.save(clean, "5m")
    return len(clean)


def build_days(bars: pd.DataFrame, frames: dict, info: dict, large: set[str], results: dict) -> dict[str, list[Day]]:
    """Day objects per symbol with context from the daily store (previous day's official high/low/close,
    daily ATR, narrow-CPR flag) and from earlier intraday days (relative early volume, 09:45 move size).
    Vectorised with numpy: bars are sorted once and each day is a contiguous slice."""
    out: dict[str, list[Day]] = {}
    dh, dl, dc = frames["high"], frames["low"], frames["close"]
    b = bars.sort_values(["symbol", "ts"], kind="stable")
    sym_codes, sym_names = pd.factorize(b["symbol"].astype(str))
    ts = b["ts"].to_numpy("datetime64[m]")
    day_all = ts.astype("datetime64[D]")
    slot_all = ((ts - day_all).astype(np.int64) - 555) // 5
    vals = {c: b[c].to_numpy(dtype=float) for c in ("open", "high", "low", "close", "volume")}
    bounds = np.flatnonzero(np.diff(sym_codes)) + 1
    for k, (s0, s1) in enumerate(zip(np.r_[0, bounds], np.r_[bounds, len(b)])):
        sym = sym_names[sym_codes[s0]]
        if sym not in dc.columns:
            continue
        H, L, C = dh[sym].dropna(), dl[sym].dropna(), dc[sym].dropna()
        prev_c = C.shift(1)
        tr = pd.concat([H - L, (H - prev_c).abs(), (L - prev_c).abs()], axis=1).max(axis=1)
        atr = tr.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean().reindex(C.index).to_numpy()
        P = (H + L + C) / 3
        width = (2 * P - (H + L)).abs() / P            # |TC - BC| / P
        narrow = (width <= width.rolling(20, min_periods=15).quantile(0.2)).reindex(C.index).fillna(False).to_numpy()
        c_dates = C.index.values.astype("datetime64[D]")
        c_vals, h_vals, l_vals = C.to_numpy(), H.reindex(C.index).to_numpy(), L.reindex(C.index).to_numpy()
        res = {np.datetime64(x, "D") for x in results.get(sym, [])}
        is_fno, is_large = sym in info["fno"], sym in large
        liq = float(info["turnover"].get(sym, 0))
        days, early_vol, r1_hist = [], [], []
        dvals = day_all[s0:s1]
        cuts = np.flatnonzero(dvals[1:] != dvals[:-1]) + 1
        for a, z in zip(np.r_[0, cuts], np.r_[cuts, len(dvals)]):
            a, z = s0 + a, s0 + z
            d0 = day_all[a]
            pi = np.searchsorted(c_dates, d0) - 1        # previous trading day in the daily store
            if pi < 0:
                continue
            sl = slot_all[a:z]
            ok = (sl >= 0) & (sl < SLOTS)
            arr = {}
            for col, src in vals.items():
                x = np.full(SLOTS, np.nan)
                x[sl[ok]] = src[a:z][ok]
                arr[col] = x
            o, h, l, c, v = arr["open"], arr["high"], arr["low"], arr["close"], arr["volume"]
            if np.isnan(c).all():
                continue
            prev_close = float(c_vals[pi])
            # skip days where intraday prices and the (adjusted) daily store disagree (corporate action)
            if abs(np.nanmean(c[:3]) / prev_close - 1) > 0.25:
                continue
            ev = float(np.nansum(v[1:3]))
            recent = early_vol[-14:]
            relvol = ev / np.mean(recent) if len(recent) >= 5 and np.mean(recent) > 0 else 1.0
            r1 = (c[S_0945] / prev_close - 1) if not math.isnan(c[S_0945]) else None
            r1_sd = float(np.std(r1_hist[-60:])) if len(r1_hist) >= 20 else None
            atr_d = float(atr[pi]) if not math.isnan(atr[pi]) else 0.0
            days.append(Day(
                symbol=sym, date=pd.Timestamp(d0), o=o, h=h, l=l, c=c, v=v,
                prev_close=prev_close, prev_high=float(h_vals[pi]), prev_low=float(l_vals[pi]), atr_d=atr_d,
                is_fno=is_fno, large=is_large, results_day=(d0 in res) or (c_dates[pi] in res),
                ctx={"relvol": relvol, "r1_sd": r1_sd, "cpr_narrow": bool(narrow[pi]), "liquidity": liq}))
            early_vol.append(ev)
            if r1 is not None:
                r1_hist.append(r1)
        out[sym] = days
    return out


def _trade_dict(t, live_slot: int | None = None) -> dict:
    def hhmm(slot):
        m = 555 + slot * 5
        return f"{m // 60:02d}:{m % 60:02d}"
    d = {"symbol": t.symbol, "date": t.date, "side": "LONG" if t.side > 0 else "SHORT",
         "entry_time": hhmm(t.entry_slot), "entry": round(t.entry_px, 2), "stop": round(t.stop, 2) if t.stop else None,
         "exit_time": hhmm(t.exit_slot), "exit": round(t.exit_px, 2), "reason": t.reason,
         "qty": t.qty, "pnl": round(t.pnl, 0), "ret_pct": round(t.ret_pct, 3)}
    if live_slot is not None:
        d["open_now"] = t.exit_slot >= live_slot
    return d


def run_intraday_all(cfg: dict, frames: dict | None = None, update: bool = True, log=print) -> dict:
    t0 = time.perf_counter()
    frames = frames or load_store()
    symbols, info = intraday_universe(cfg, frames)
    log(f"Intraday universe: {len(symbols)} liquid F&O stocks + ETFs")
    bars = update_bars(symbols, log=log) if update else idata.IntradayStore(INTRADAY_DIR / "bars").load("5m")
    if bars.empty:
        raise RuntimeError("No intraday bars available")
    bars = bars[bars["symbol"].isin(symbols)]
    large = set(get_universe("nifty50")[0]["symbol"])
    first = bars["ts"].min().date() - timedelta(days=7)
    results = results_history(first, ist_today(), log=log)
    days = build_days(bars, frames, info, large, results)
    costs = IntradayCosts.from_config((cfg.get("intraday") or {}).get("costs"))
    capital = float((cfg.get("account") or {}).get("capital", 500000))
    ic = cfg.get("intraday") or {}
    today = pd.Timestamp(ist_today())
    now = ist_now()
    live_slot = ((now.hour * 60 + now.minute) - 555) // 5
    out = []
    for s in build_intraday_strategies(cfg):
        pool = [d for sym, ds in days.items() for d in ds
                if s.universe != "top30" or sym in info["top30"]]
        hist = [d for d in pool if d.date < today]
        res = run_intraday(s, hist, costs, capital, float(ic.get("risk_pct", 0.5)), float(ic.get("leverage", 2.0)))
        live_days = [d for d in pool if d.date == today]
        live = run_intraday(s, live_days, costs, capital, float(ic.get("risk_pct", 0.5)), float(ic.get("leverage", 2.0))) \
            if live_days else None
        m = res.metrics
        if m.get("days", 0) < 40:
            status = "unknown"
        elif m.get("significant") and (m.get("avg_day_pct") or 0) > 0:
            status = "working"
        elif (m.get("avg_day_pct") or 0) > 0:
            status = "mixed"
        else:
            status = "not-working"
        out.append({
            "key": s.key, "name": s.name, "description": s.description, "evidence": s.evidence,
            "horizon": "intraday", "status": status, "metrics": m,
            "equity": [[d.date().isoformat(), round(v, 0)] for d, v in res.daily.items()],
            "recent_trades": [_trade_dict(t) for t in res.trades[-40:]][::-1],
            "today": [_trade_dict(t, live_slot) for t in (live.trades if live else [])],
        })
    order = {"working": 0, "mixed": 1, "unknown": 2, "not-working": 3}
    out.sort(key=lambda x: (order[x["status"]], -(x["metrics"].get("avg_day_pct") or -9)))
    span = (bars["ts"].min().date().isoformat(), bars["ts"].max().date().isoformat())
    result = {
        "generated_at": now.isoformat(timespec="seconds"), "elapsed_s": round(time.perf_counter() - t0, 1),
        "data": {"source": ", ".join(sorted(bars["source"].astype(str).unique())), "interval": "5m",
                 "from": span[0], "to": span[1], "sessions": int(bars["ts"].dt.normalize().nunique()),
                 "symbols": len(days), "note": "Yahoo 5-minute data is ~15 min delayed and covers ~60 sessions; "
                                               "log in to FYERS to backfill ~1 year."},
        "rules": {"square_off": "15:00 for F&O stocks (FYERS MIS cut-off 15:05), 15:15 others",
                  "fills": "next bar open; stop orders at the level or the open if it gapped",
                  "costs": "FYERS intraday brokerage, STT 0.025% sell, stamp 0.003% buy, NSE + SEBI fees, GST, slippage",
                  "tax": f"speculative business income at {costs.tax_pct}%"},
        "sebi": SEBI_FACTS, "strategies": out,
    }
    tmp = RESULT_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(result, indent=1, default=str), encoding="utf-8")
    tmp.replace(RESULT_FILE)
    log(f"Intraday done in {result['elapsed_s']}s: {len(out)} strategies on {result['data']['sessions']} sessions")
    return result


def load_intraday() -> dict | None:
    try:
        return json.loads(RESULT_FILE.read_text(encoding="utf-8"))
    except Exception:
        return None
