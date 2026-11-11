"""Market replay: practise on past sessions bar by bar, with no hindsight (GET /api/replay/...).

Intraday (5m / 15m): one past session from the intraday store (the ~150 most liquid F&O stocks, the last few months)
after the two sessions before it as context. Daily (1d): any date in the 8-year price store, after a year of context,
with the next 60 sessions to replay. The page reveals one bar at a time (web/ui/src/lib/replay.ts): a market order
fills at the last revealed close plus slippage, a stop or target on the bars that follow (at the open when the price
gaps past it), and an intraday position is squared off on the session's last bar. Blind mode hides the name and the
date until the end, so memory of what happened can't help.

Finished sessions are saved to data/replay_log.jsonl (POST /api/replay/results) with the P&L recomputed here from the
bars and the cost model, never taken from the browser: your practice record, which the trade coach reads.
"""
from __future__ import annotations

import dataclasses
import json
import random
import threading
import uuid
from datetime import timedelta

import pandas as pd

from scanner.costs import CostModel
from scanner.intraday import data as idata

from ..errors import ApiException, not_found
from ..paths import P
from ..util import now_ist, today_ist
from . import chart_data, data, intraday_chart

TFS = ("5m", "15m", "1d")
CONTEXT_SESSIONS = 2
DAILY_CONTEXT = 250
DAILY_REPLAY = 60
DAILY_MIN_CONTEXT = 60
PRICE_TOL = 0.006            # a saved fill may sit this far outside its bar's range (slippage, rounding)
LOG_NAME = "replay_log.jsonl"
NOTE = ("Practice on real past bars. Market orders fill at the last close plus slippage; stops and targets fill on "
        "the bars after, at the open if the price gaps past them (stop first when a bar touches both). Charges are "
        "FYERS' {product} charges. Nothing here is a real order.")

_lock = threading.Lock()
_cache: dict[tuple, object] = {}


def _manifest_key() -> float:
    try:
        return (P.intraday_bars / "5m" / "manifest.json").stat().st_mtime
    except OSError:
        return 0.0


def _cached(key: tuple, build):
    k = key + (_manifest_key(),)
    if k not in _cache:
        if len(_cache) > 400:
            _cache.clear()
        _cache[k] = build()
    return _cache[k]


def costs(tf: str) -> CostModel:
    """Delivery charges for daily replays, intraday ones (STT 0.025% on the sell, no DP charge) for 5m / 15m."""
    cm = CostModel.from_config(data.config().get("costs"))
    if tf == "1d":
        return cm
    # FYERS intraday: brokerage 0.03% capped at Rs 20, STT 0.025% on the sell only (spread over both sides here, as
    # the model charges STT per side), stamp 0.003% on the buy, no depository charge
    return dataclasses.replace(cm, brokerage_pct=0.03, stt_pct=0.0125, stamp_buy_pct=0.003, dp_per_sell=0.0)


def capital() -> float:
    try:
        return float((data.config().get("account") or {}).get("capital") or data.config().get("capital") or 500000)
    except (TypeError, ValueError):
        return 500000.0


def intraday_symbols() -> list[str]:
    def build():
        store = idata.IntradayStore(P.intraday_bars)
        months = store.months("5m")
        if not months:
            return []
        df = pd.read_parquet(store._dir("5m") / f"{months[-1]}.parquet", columns=["symbol"])
        return sorted(set(df["symbol"].astype(str)))
    return list(_cached(("symbols",), build))


def sessions(symbol: str) -> list[str]:
    """Past sessions with 5-minute bars for `symbol` (today's is still being written: not replayable)."""
    sym = symbol.upper()

    def build():
        df = idata.IntradayStore(P.intraday_bars).load("5m", [sym])
        if df.empty:
            return []
        days = sorted({d.date() for d in pd.to_datetime(df["ts"]).dt.normalize()})
        return [d.isoformat() for d in days if d < today_ist()]
    return list(_cached(("sessions", sym), build))


def _epoch(ts: pd.Series | pd.DatetimeIndex) -> list[int]:
    s = pd.Series(pd.to_datetime(ts))
    return ((s - pd.Timestamp("1970-01-01")) // pd.Timedelta(seconds=1)).astype("int64").tolist()


def _ohlcv(df: pd.DataFrame, t: list[int]) -> dict:
    r2 = lambda s: [round(float(x), 2) for x in s]  # noqa: E731
    return {"t": t, "o": r2(df["open"]), "h": r2(df["high"]), "l": r2(df["low"]), "c": r2(df["close"]),
            "v": [float(x) for x in df["volume"]]}


def _intraday(sym: str, tf: str, day: str) -> dict:
    have = sessions(sym)
    if day not in have:
        raise not_found(f"5-minute bars of {sym} on {day}",
                        f"Replay covers {len(have)} past sessions of {sym}" + (f", {have[0]} to {have[-1]}." if have else "."))
    d = pd.Timestamp(day)
    i = have.index(day)
    ctx = have[max(0, i - CONTEXT_SESSIONS):i]
    start = pd.Timestamp(ctx[0]) if ctx else d
    df = idata.IntradayStore(P.intraday_bars).load("5m", [sym], start=start, end=d)
    df = df.sort_values("ts").drop_duplicates("ts", keep="last").reset_index(drop=True)
    df["ts"] = pd.to_datetime(df["ts"])
    df = intraday_chart.resample(df, tf)
    first = int((df["ts"].dt.normalize() < d).sum())
    if first >= len(df):
        raise not_found(f"Bars of {sym} on {day}")
    return {"bars": _ohlcv(df, _epoch(df["ts"])), "vwap": intraday_chart.vwap(df), "start": first,
            "context": ctx, "square_off": len(df) - 1}


def _daily(sym: str, day: str) -> dict:
    df = chart_data.bars_frame(sym)
    idx = int(df.index.searchsorted(pd.Timestamp(day)))
    if idx < DAILY_MIN_CONTEXT:
        raise ApiException("VALIDATION", f"{sym} has too little history before {day} for a replay.",
                           f"Pick a date after {df.index[min(DAILY_MIN_CONTEXT, len(df) - 1)].date().isoformat()}.")
    if idx >= len(df) - 5:
        raise ApiException("VALIDATION", f"{day} is too recent for a daily replay of {sym}.",
                           "Pick a date at least a few weeks back: the replay needs bars after it.")
    lo, hi = max(0, idx - DAILY_CONTEXT), min(len(df), idx + DAILY_REPLAY)
    part = df.iloc[lo:hi]
    return {"bars": _ohlcv(part, _epoch(part.index)), "vwap": None, "start": idx - lo, "context": [],
            "square_off": None, "date": part.index[idx - lo].date().isoformat()}


def load(symbol: str, tf: str, day: str) -> dict:
    if tf not in TFS:
        raise ApiException("VALIDATION", "tf must be 5m, 15m or 1d.")
    sym = symbol.upper().strip()
    try:
        pd.Timestamp(day)
    except (ValueError, TypeError):
        raise ApiException("VALIDATION", "date must be YYYY-MM-DD.") from None
    out = _intraday(sym, tf, day) if tf != "1d" else _daily(sym, day)
    cm = costs(tf)
    first_close = out["bars"]["c"][out["start"]]
    cap = capital()
    value = cap * 0.10
    qty = max(1, int(value // first_close)) if first_close else 1
    side_charges = (cm.buy_cost(qty * first_close) + cm.sell_cost(qty * first_close)) / 2
    return {"symbol": sym, "tf": tf, "date": out.get("date", day), "start": out["start"], "bars": out["bars"],
            "vwap": out["vwap"], "context": out["context"], "square_off": out["square_off"],
            "costs": {"product": "CNC" if tf == "1d" else "INTRADAY", "slippage_pct": cm.slippage_pct,
                      "charges_pct": round(side_charges / max(qty * first_close, 1) * 100, 4)},
            "qty": qty, "capital": cap,
            "note": NOTE.format(product="delivery" if tf == "1d" else "intraday")}


def _daily_candidates() -> list[str]:
    def build():
        frames = data.store()
        c = frames["close"]
        try:
            n500 = set(pd.read_csv(P.data / "universe_nifty500.csv")["symbol"].astype(str).str.upper())
        except Exception:
            n500 = set()
        counts = c.notna().sum()
        return sorted(s for s in c.columns if counts[s] >= DAILY_MIN_CONTEXT + DAILY_REPLAY + 250 and (not n500 or s in n500))
    return list(_cached(("daily_candidates", data.store_version()), build))


def random_pick(tf: str, seed: int | None = None) -> dict:
    """A random symbol and date to replay (blind mode)."""
    if tf not in TFS:
        raise ApiException("VALIDATION", "tf must be 5m, 15m or 1d.")
    rng = random.Random(seed)
    if tf != "1d":
        syms = intraday_symbols()
        for _ in range(30):
            if not syms:
                break
            s = rng.choice(syms)
            have = sessions(s)[CONTEXT_SESSIONS:]
            if have:
                return {"symbol": s, "date": rng.choice(have), "tf": tf}
        raise ApiException("FEATURE_UNAVAILABLE", "No intraday sessions to replay yet.",
                           "Intraday bars come from the FYERS history sync and the live feed.", {"feature": "replay"})
    syms = _daily_candidates()
    if not syms:
        raise ApiException("FEATURE_UNAVAILABLE", "No price history to replay yet: run a scan first.", None,
                           {"feature": "replay"})
    for _ in range(30):
        s = rng.choice(syms)
        idx = chart_data.bars_frame(s).index
        lo, hi = max(DAILY_CONTEXT, DAILY_MIN_CONTEXT), len(idx) - DAILY_REPLAY
        if hi > lo:
            return {"symbol": s, "date": idx[rng.randrange(lo, hi)].date().isoformat(), "tf": tf}
    raise ApiException("FEATURE_UNAVAILABLE", "Could not find a stock with enough history to replay.", None,
                       {"feature": "replay"})


# ---- results: your practice record ----------------------------------------------------------------------------------

def _log_path():
    return P.data / LOG_NAME


def _recompute(sess: dict, trades: list[dict]) -> list[dict]:
    """Each trade's P&L from the bars and the cost model; a fill outside its bar's range is rejected."""
    b = sess["bars"]
    n = len(b["t"])
    cm = costs(sess["tf"])
    out = []
    for k, tr in enumerate(trades, 1):
        ei, xi = int(tr["entry_i"]), int(tr["exit_i"])
        if not (sess["start"] <= ei <= xi < n):
            raise ApiException("VALIDATION", f"Trade {k}: its bars are outside the replay.")
        for what, i, px in (("entry", ei, tr["entry"]), ("exit", xi, tr["exit"])):
            lo, hi = b["l"][i] * (1 - PRICE_TOL), b["h"][i] * (1 + PRICE_TOL)
            if not lo <= float(px) <= hi:
                raise ApiException("VALIDATION", f"Trade {k}: the {what} price {px} is outside that bar ({b['l'][i]}-{b['h'][i]}).")
        side = 1 if tr["side"] == "LONG" else -1
        qty = int(tr["qty"])
        entry, exit_ = float(tr["entry"]), float(tr["exit"])
        gross = (exit_ - entry) * qty * side
        buy_v, sell_v = (entry * qty, exit_ * qty) if side == 1 else (exit_ * qty, entry * qty)
        charges = cm.buy_cost(buy_v) + cm.sell_cost(sell_v)
        net = gross - charges
        stop = tr.get("stop")
        risk = abs(entry - float(stop)) * qty if stop else None
        out.append({"side": tr["side"], "qty": qty, "entry_i": ei, "exit_i": xi, "entry_t": b["t"][ei], "exit_t": b["t"][xi],
                    "entry": round(entry, 2), "exit": round(exit_, 2), "stop": stop, "target": tr.get("target"),
                    "reason": tr.get("reason") or "manual", "bars_held": xi - ei, "gross": round(gross, 2),
                    "charges": round(charges, 2), "net": round(net, 2),
                    "ret_pct": round(net / (entry * qty) * 100, 3) if entry * qty else None,
                    "r": round(net / risk, 2) if risk else None})
    return out


def save_result(body: dict) -> dict:
    sess = load(body["symbol"], body["tf"], body["date"])
    trades = _recompute(sess, body.get("trades") or [])
    seen = max(sess["start"], min(int(body.get("last_i") or sess["start"]), len(sess["bars"]["t"]) - 1))
    c = sess["bars"]["c"]
    net = sum(t["net"] for t in trades)
    row = {"id": uuid.uuid4().hex[:12], "at": now_ist().isoformat(timespec="seconds"), "symbol": sess["symbol"],
           "tf": sess["tf"], "date": sess["date"], "blind": bool(body.get("blind")), "bars_seen": seen - sess["start"] + 1,
           "trades": trades, "net": round(net, 2), "capital": sess["capital"],
           "ret_pct": round(net / sess["capital"] * 100, 3) if sess["capital"] else None,
           "buy_hold_pct": round((c[seen] / c[sess["start"]] - 1) * 100, 2) if c[sess["start"]] else None}
    with _lock:
        with open(_log_path(), "a", encoding="utf-8") as f:
            f.write(json.dumps(row, separators=(",", ":")) + "\n")
    return row


def log_rows() -> list[dict]:
    p = _log_path()
    if not p.exists():
        return []
    rows = []
    with _lock:
        lines = p.read_text(encoding="utf-8").splitlines()
    for ln in lines:
        try:
            rows.append(json.loads(ln))
        except ValueError:
            continue                     # a torn last line: skip it
    return rows


def stats(trades: list[dict]) -> dict:
    """Win rate, average win / loss, profit factor, expectancy (also in R when stops were set), exits by reason."""
    n = len(trades)
    wins = [t["net"] for t in trades if t["net"] > 0]
    losses = [t["net"] for t in trades if t["net"] <= 0]
    rs = [t["r"] for t in trades if t.get("r") is not None]
    reasons: dict[str, int] = {}
    for t in trades:
        reasons[t.get("reason") or "manual"] = reasons.get(t.get("reason") or "manual", 0) + 1
    return {"trades": n, "wins": len(wins), "win_rate": round(len(wins) / n * 100, 1) if n else None,
            "avg_win": round(sum(wins) / len(wins), 2) if wins else None,
            "avg_loss": round(sum(losses) / len(losses), 2) if losses else None,
            "profit_factor": round(sum(wins) / -sum(losses), 2) if losses and sum(losses) < 0 else None,
            "net": round(sum(t["net"] for t in trades), 2),
            "expectancy": round(sum(t["net"] for t in trades) / n, 2) if n else None,
            "expectancy_r": round(sum(rs) / len(rs), 2) if rs else None,
            "with_stop_pct": round(sum(1 for t in trades if t.get("stop")) / n * 100, 1) if n else None,
            "avg_bars_held": round(sum(t["bars_held"] for t in trades) / n, 1) if n else None,
            "exits": reasons}


def history(limit: int = 30) -> dict:
    rows = log_rows()
    trades = [t for r in rows for t in r.get("trades") or []]
    by_tf = {tf: stats([t for r in rows if r.get("tf") == tf for t in r.get("trades") or []]) for tf in TFS}
    return {"sessions": len(rows), "overall": stats(trades), "by_tf": by_tf,
            "recent": [{k: r.get(k) for k in ("id", "at", "symbol", "tf", "date", "blind", "bars_seen", "net", "ret_pct",
                                                "buy_hold_pct")} | {"trades": len(r.get("trades") or [])}
                       for r in reversed(rows[-limit:])],
            "note": "Practice only: replays use real past bars with real charges, but no real money and no real order "
                    "book. Skill here is a start, not proof."}


def info(symbol: str | None = None) -> dict:
    """What can be replayed: the intraday symbols, a symbol's sessions, the daily range."""
    out: dict = {"intraday_symbols": intraday_symbols(), "daily_context": DAILY_CONTEXT, "daily_replay": DAILY_REPLAY}
    if symbol:
        sym = symbol.upper().strip()
        out["symbol"] = sym
        out["sessions"] = sessions(sym)[CONTEXT_SESSIONS:] if sym in out["intraday_symbols"] else []
        try:
            idx = chart_data.bars_frame(sym).index
            if len(idx) > DAILY_MIN_CONTEXT + 5:
                out["daily_first"] = idx[DAILY_MIN_CONTEXT].date().isoformat()
                out["daily_last"] = idx[len(idx) - 6].date().isoformat()
        except ApiException:
            pass
    return out


def default_day(tf: str, symbol: str) -> str:
    if tf != "1d":
        have = sessions(symbol)[CONTEXT_SESSIONS:]
        if not have:
            raise not_found(f"Intraday sessions of {symbol.upper()}")
        return have[-1]
    return (today_ist() - timedelta(days=180)).isoformat()
