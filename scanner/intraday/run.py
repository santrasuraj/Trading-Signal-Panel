"""Intraday pipeline: universe -> 5-minute bars -> per-day context -> backtests + today's live setups.

Data: Yahoo gives the last ~60 sessions of 5-minute bars (no login). With a FYERS login,
`intraday_sync.py --backfill` (fyers_sync.sync) extends history to ~1 year, and the daily 15:45
`--archive` keeps it growing, because FYERS only keeps a rolling year. Today's bars come from the
FYERS live WebSocket service (live.py) for the symbols it streams, from Yahoo for the rest.
Results go to data/results/intraday.json.
"""
from __future__ import annotations

import io
import json
import math
import os
import time
from dataclasses import asdict
from datetime import date, timedelta
from statistics import NormalDist

import numpy as np
import pandas as pd

from ..events import results_history
from ..nse import _get
from ..providers import get_fyers
from ..settings import DATA_DIR, RESULTS_DIR, ist_now, ist_today
from ..store import load_store
from ..universe import get_universe
from . import data as idata
from . import fyers_sync
from . import live as live_feed
from .engine import FLAT_FNO, FLAT_OTHER, SLOTS, Day, IntradayCosts, run_intraday
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
    try:
        df = pd.read_csv(io.StringIO(text))
    except Exception:
        df = pd.DataFrame()
    col = next((c for c in df.columns if str(c).strip().upper() == "SYMBOL"), None)
    syms = sorted({str(s).strip() for s in df[col].dropna()} - {"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY",
                                                                "NIFTYNXT50", "NIFTYFPI", "SYMBOL"}) \
        if col is not None else []
    if len(syms) < 100:            # format change or a blocked answer: keep the last good list, never cache this
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else syms
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
    info = {"fno": set(fno), "turnover": turnover.to_dict(), "top30": set(liquid[:30]) | set(etfs),
            "etfs": set(etfs), "min_turnover_cr": float(ic.get("min_turnover_cr", 100))}
    return liquid + etfs, info


def update_bars(symbols: list[str], cfg: dict | None = None, log=print) -> tuple[pd.DataFrame, list[str]]:
    """FYERS first, Yahoo only as fallback. Returns (all 5-minute bars incl. today's, sources used).
      1. Completed days: top up from FYERS through the shared rate limiter (0 calls when up to date;
         a big first-time backfill is left to `intraday_sync.py --backfill` so a scan never burns budget).
      2. Today: bars from the FYERS live WebSocket service for the (up to 100) symbols it streams, as long
         as its ticks are fresh (real-time, no REST calls).
      3. Yahoo (~15 min delayed): today's bars for every other symbol (or all of them when the live feed
         stopped), and the last ~60 sessions only when FYERS hasn't covered them.
    Where sources overlap the better one wins (fyers > fyers_ws > yahoo), so tick-built bars never replace
    the official FYERS bars archived at 15:45."""
    ic = (cfg or {}).get("intraday") or {}
    store = idata.IntradayStore(INTRADAY_DIR / "bars")
    days = int(ic.get("history_days", 365))
    sources: list[str] = []
    fy = None
    if cfg is not None:
        try:
            fy, _ = get_fyers(cfg)
        except Exception:
            fy = None
    if fy is not None:
        est = fyers_sync.plan_calls(symbols, INTRADAY_DIR, days)
        if 0 < est["calls"] <= int(ic.get("max_sync_calls_per_scan", 200)):
            fyers_sync.sync(fy, symbols, INTRADAY_DIR, days, log=log)
        elif est["calls"] > 0:
            log(f"FYERS intraday history needs {est['calls']} calls (~{est['minutes']} min): run "
                "5_intraday_backfill.bat (or intraday_sync.py --backfill). Using what is stored + Yahoo for now.")
    # per symbol: FYERS history ending more than 4 days before the last complete session is stale
    have = fyers_sync.load_state(INTRADAY_DIR)["symbols"]
    cutoff = (fyers_sync.last_complete_day() - timedelta(days=4)).isoformat()
    stale = {s for s in symbols
             if str((have.get(s) if isinstance(have.get(s), dict) else {}).get("to") or "") < cutoff}
    if symbols and len(symbols) - len(stale) >= len(symbols) / 2:
        sources.append("fyers")
    live_today = idata.clean_bars(live_feed.load_live(INTRADAY_DIR), "5m")   # a bad tick must not reach the setups
    now = ist_now().replace(tzinfo=None)
    covered: set[str] = set()                         # symbols whose today's bars come from the live feed
    if len(live_today):
        if live_feed.feed_fresh(INTRADAY_DIR):
            first = live_today.groupby(live_today["symbol"].astype(str))["ts"].min()
            # only symbols streamed since the open; a feed started late (login after 09:15) lacks their morning
            covered = set(first[first.dt.hour * 60 + first.dt.minute <= 9 * 60 + 20].index.astype(str))
            sources.append("fyers live")
        else:
            log("The FYERS live feed stopped receiving ticks today - Yahoo fills in today's bars")
    need = [s for s in symbols if s not in covered]
    today_parts = [live_today] if len(live_today) else []   # even stale live bars beat Yahoo's (priority)
    full = [s for s in symbols if s in stale]               # ~60 sessions of Yahoo history
    short = [s for s in need if s not in stale]             # today's bars only
    if full or short:
        raw = pd.concat([idata.fetch_yahoo_intraday(syms, "5m", days=n, log=log)
                         for syms, n in ((full, None), (short, 1)) if syms], ignore_index=True)
        clean = idata.clean_bars(raw.assign(source="yahoo"), "5m", drop_synthetic_close=True, now=now)
        store.save(clean, "5m")                       # forming bars are never stored; FYERS bars win on overlap
        forming = clean[((clean["flags"] & idata.FLAG_FORMING) != 0) & clean["symbol"].isin(need)]
        if len(forming):
            today_parts.append(forming)
        sources.append("yahoo")
    bars = store.load("5m")
    if today_parts:
        bars = idata.merge_by_priority(bars, *today_parts)
    return bars, sources


def build_days(bars: pd.DataFrame, frames: dict, info: dict, large: set[str], results: dict,
               missing_prev: set[str] | None = None) -> dict[str, list[Day]]:
    """Day objects per symbol with context from the daily store (previous day's official high/low/close,
    daily ATR, narrow-CPR flag, 20-day turnover) and from earlier intraday days (relative early volume,
    09:45 move size). A stock-day is kept only when the stock was liquid as of that day (20-day turnover
    to the previous day >= min_turnover_cr; ETFs always). Symbols whose daily store lacks the previous
    session are added to `missing_prev`. Vectorised with numpy: bars are sorted once and each day is a
    contiguous slice."""
    out: dict[str, list[Day]] = {}
    dh, dl, dc, dv = frames["high"], frames["low"], frames["close"], frames["volume"]
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
        # 20-day traded value in Rs crore up to each day (close x volume does not depend on the price scale)
        vol = dv[sym].reindex(C.index) if sym in dv.columns else pd.Series(np.nan, index=C.index)
        tv = ((C * vol).rolling(20, min_periods=15).mean() / 1e7).to_numpy()
        res = {np.datetime64(x, "D") for x in results.get(sym, [])}
        is_fno, is_large, is_etf = sym in info["fno"], sym in large, sym in info["etfs"]
        days, early_vol, r1_hist = [], [], []
        dvals = day_all[s0:s1]
        cuts = np.flatnonzero(dvals[1:] != dvals[:-1]) + 1
        prev_day = None
        for a, z in zip(np.r_[0, cuts], np.r_[cuts, len(dvals)]):
            a, z = s0 + a, s0 + z
            d0 = day_all[a]
            last_day, prev_day = prev_day, d0
            pi = np.searchsorted(c_dates, d0) - 1        # previous trading day in the daily store
            if pi < 0:
                continue
            if last_day is not None and c_dates[pi] < last_day:
                # the store misses the previous session: prev close/high/low, ATR and CPR would be stale
                if missing_prev is not None:
                    missing_prev.add(sym)
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
            j = pi + 1
            if j < len(c_dates) and c_dates[j] == d0:
                # before an ex-date the adjusted store is off by the action's factor (misses < 25% for the check below)
                f = np.median([h_vals[j] / np.nanmax(h), l_vals[j] / np.nanmin(l), c_vals[j] / c[~np.isnan(c)][-1]])
                if not abs(f - 1) <= 0.03:
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
            if is_etf or tv[pi] >= info["min_turnover_cr"]:   # liquid as of that day (NaN = unknown = skip)
                days.append(Day(
                    symbol=sym, date=pd.Timestamp(d0), o=o, h=h, l=l, c=c, v=v,
                    prev_close=prev_close, prev_high=float(h_vals[pi]), prev_low=float(l_vals[pi]), atr_d=atr_d,
                    is_fno=is_fno, large=is_large, results_day=(d0 in res) or (c_dates[pi] in res),
                    ctx={"relvol": relvol, "r1_sd": r1_sd, "cpr_narrow": bool(narrow[pi]),
                         "liquidity": float(np.nan_to_num(tv[pi]))}))
            early_vol.append(ev)                         # early volume / 09:45 history from every clean day
            if r1 is not None:
                r1_hist.append(r1)
        out[sym] = days
    return out


def _trade_dict(t, live_slot: int | None = None, flat: int = FLAT_OTHER) -> dict:
    def hhmm(slot):
        m = 555 + slot * 5
        return f"{m // 60:02d}:{m % 60:02d}"
    d = {"symbol": t.symbol, "date": t.date, "side": "LONG" if t.side > 0 else "SHORT",
         "entry_time": hhmm(t.entry_slot), "entry": round(t.entry_px, 2), "stop": round(t.stop, 2) if t.stop else None,
         "exit_time": hhmm(t.exit_slot), "exit": round(t.exit_px, 2), "reason": t.reason,
         "qty": t.qty, "pnl": round(t.pnl, 0), "ret_pct": round(t.ret_pct, 3)}
    if live_slot is not None:
        # today's bars end at the latest bar: walk_exit 'squares off' a running position there
        d["open_now"] = t.reason == "square-off" and live_slot < flat
        if d["open_now"]:
            d["reason"] = "open (marked at last bar)"
    return d


def run_intraday_all(cfg: dict, frames: dict | None = None, update: bool = True, log=print) -> dict:
    t0 = time.perf_counter()
    frames = frames or load_store()
    symbols, info = intraday_universe(cfg, frames)
    if len(info["fno"]) < 50:
        raise RuntimeError("NSE F&O list missing or incomplete - intraday results not updated")
    log(f"Intraday universe: {len(symbols)} liquid F&O stocks + ETFs")
    if update:
        bars, sources = update_bars(symbols, cfg, log=log)
    else:
        bars, sources = idata.IntradayStore(INTRADAY_DIR / "bars").load("5m"), ["stored"]
    if bars.empty:
        raise RuntimeError("No intraday bars available")
    bars = bars[bars["symbol"].isin(symbols)]
    large = set(get_universe("nifty50")[0]["symbol"])
    first = bars["ts"].min().date() - timedelta(days=7)
    results = results_history(first, ist_today(), log=log)
    missing_prev: set[str] = set()
    days = build_days(bars, frames, info, large, results, missing_prev)
    if missing_prev:
        log(f"Daily store misses the previous session for {len(missing_prev)} symbols on some days "
            f"(e.g. {sorted(missing_prev)[:5]}) - those days are skipped; run the daily scan to update it")
    # top-30 by turnover as of each day (vwap_trend / supertrend universe), plus the ETFs
    by_date: dict[pd.Timestamp, list[tuple[float, str]]] = {}
    for sym, ds in days.items():
        if sym in info["etfs"]:
            continue
        for d in ds:
            by_date.setdefault(d.date, []).append((d.ctx["liquidity"], sym))
    top30 = {dt: {sym for _, sym in sorted(v, reverse=True)[:30]} | info["etfs"] for dt, v in by_date.items()}
    costs = IntradayCosts.from_config((cfg.get("intraday") or {}).get("costs"))
    capital = float((cfg.get("account") or {}).get("capital", 500000))
    ic = cfg.get("intraday") or {}
    today = pd.Timestamp(ist_today())
    now = ist_now()
    live_slot = ((now.hour * 60 + now.minute) - 555) // 5
    out = []
    strategies = build_intraday_strategies(cfg)
    # Bonferroni: every enabled strategy on the same sessions - |t| >= 2 alone would flag one by luck too often
    t_crit = NormalDist().inv_cdf(1 - 0.025 / max(len(strategies), 1))
    for s in strategies:
        pool = [d for sym, ds in days.items() for d in ds
                if s.universe != "top30" or sym in top30.get(d.date, info["etfs"])]
        hist = [d for d in pool if d.date < today]
        res = run_intraday(s, hist, costs, capital, float(ic.get("risk_pct", 0.5)), float(ic.get("leverage", 2.0)))
        live_days = [d for d in pool if d.date == today]
        live = run_intraday(s, live_days, costs, capital, float(ic.get("risk_pct", 0.5)), float(ic.get("leverage", 2.0))) \
            if live_days else None
        m = res.metrics
        m["significant"] = m.get("t_stat") is not None and abs(m["t_stat"]) >= t_crit
        m["t_crit"] = round(t_crit, 2)
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
            "today": [_trade_dict(t, live_slot, FLAT_FNO if t.symbol in info["fno"] else FLAT_OTHER)
                      for t in (live.trades if live else [])],
        })
    order = {"working": 0, "mixed": 1, "unknown": 2, "not-working": 3}
    out.sort(key=lambda x: (order[x["status"]], -(x["metrics"].get("avg_day_pct") or -9)))
    span = (bars["ts"].min().date().isoformat(), bars["ts"].max().date().isoformat())
    result = {
        "generated_at": now.isoformat(timespec="seconds"), "elapsed_s": round(time.perf_counter() - t0, 1),
        "data": {"source": ", ".join(sorted(bars["source"].astype(str).unique())), "interval": "5m",
                 "from": span[0], "to": span[1], "sessions": int(bars["ts"].dt.normalize().nunique()),
                 "symbols": len(days), "sources_used": sources,
                 "fyers_coverage": fyers_sync.coverage(INTRADAY_DIR),
                 "note": _data_note(sources)},
        "rules": {"square_off": "15:00 for F&O stocks (FYERS MIS cut-off 15:05), 15:15 others",
                  "fills": "next bar open; stop orders at the level or the open if it gapped",
                  "costs": (f"FYERS intraday brokerage {costs.brokerage_pct:g}% (max Rs {costs.brokerage_max:g}/order), "
                            f"STT {costs.stt_sell_pct:g}% sell, stamp {costs.stamp_buy_pct:g}% buy, "
                            f"NSE {costs.exchange_pct:g}% + SEBI {costs.sebi_pct:g}% fees, GST {costs.gst_pct:g}%, "
                            f"slippage {costs.slippage_large_pct:g}% (Nifty 50) / {costs.slippage_other_pct:g}% per side, "
                            f"+{costs.stop_entry_extra_pct:g}% on stop orders"),
                  "selection": "each day the first trades by entry time (ties by priority), each sized on an equal "
                               "share of the leverage limit",
                  "significance": f"|t| >= {t_crit:.2f} (5% two-sided, Bonferroni-corrected for "
                                  f"{len(strategies)} strategies tested on the same sessions)",
                  "not_modelled": "Candidates = today's F&O list and today's most liquid stocks (the turnover filter "
                                  "and the top-30 list are applied as of each date within them, the list itself is "
                                  "not); no volume-participation cap; ex-dates not excluded; samples not split at "
                                  "the 3 Aug / 7 Sep 2026 auction changes",
                  "tax": f"speculative business income at {costs.tax_pct}%"},
        "cost_params": asdict(costs),   # the API states the round-trip cost these results were run with
        "sebi": SEBI_FACTS, "strategies": out,
    }
    # per-process tmp + retried replace: the web job and the 15:45 task can finish together, and on Windows
    # a replace fails while the API is reading the file
    tmp = RESULT_FILE.with_name(f"{RESULT_FILE.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(result, indent=1, default=str), encoding="utf-8")
    idata._replace(tmp, RESULT_FILE)
    log(f"Intraday done in {result['elapsed_s']}s: {len(out)} strategies on {result['data']['sessions']} sessions")
    return result


def _data_note(sources: list[str]) -> str:
    if "fyers live" in sources:
        return "FYERS history + live WebSocket bars" + (
            "; Yahoo (~15 min delayed) for the symbols the live feed doesn't stream" if "yahoo" in sources else "")
    if "fyers" in sources:
        return ("FYERS history; today's bars from Yahoo (~15 min delayed) - start the live feed for "
                "real-time bars")
    return ("Yahoo 5-minute data is ~15 min delayed and covers ~60 sessions; log in to FYERS and "
            "run the backfill for ~1 year of history")


def load_intraday() -> dict | None:
    try:
        return json.loads(RESULT_FILE.read_text(encoding="utf-8"))
    except Exception:
        return None
