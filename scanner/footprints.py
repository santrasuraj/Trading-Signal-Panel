"""Big money live: footprints of large investors in today's market, from data this app already collects.

Nobody can see who is buying in real time (NSE names the buyer only later, in the disclosures of smart_money.py).
What shows live is the footprint, per stock of the liquid F&O universe:
  - relative volume: today's volume so far against the average of the last 20 sessions up to the same time of day
    (5-minute bars: the FYERS live feed, else Yahoo ~15 min delayed) - 4x normal at 11:30 means something;
  - large trades: single prints of LARGE_PRINT_CR or more, from the FYERS live feed (live.py records them and calls
    a print at or above the ask buyer-initiated, at or below the bid seller-initiated);
  - order-book pressure: total pending buy vs sell quantity in the FYERS feed;
  - today's block deals, from NSE's large-deal snapshot (published shortly after each block window).
A stock becomes an alert when one of them is unusual. Every alert is logged once per stock and day
(footprints_log.parquet) so its next-day result can be measured: these are clues, never orders.
"""
from __future__ import annotations

import json
import time
from datetime import timedelta

import numpy as np
import pandas as pd

from .settings import DATA_DIR, RESULTS_DIR, ist_now

FP_FILE = RESULTS_DIR / "footprints.json"
LOG_FILE = RESULTS_DIR / "footprints_log.parquet"
LIVE_DIR = DATA_DIR / "intraday" / "live"
LOOKBACK_SESSIONS = 20      # sessions behind "normal volume at this time of day"
MIN_SESSIONS = 10           # fewer stored sessions than this: no relative volume for the stock
RVOL_MIN = 2.5              # today's volume so far at least this many times normal = unusual
MIN_VALUE_CR = 25.0         # ... and at least this much traded so far (Rs crore), so a quiet stock never alerts
LARGE_PRINT_CR = 2.0        # a single trade of this value or more (Rs crore) is a large print
PRINTS_ALERT_CR = 10.0      # large prints adding up to this much today make an alert on their own
BOOK_RATIO = 2.0            # pending buy / sell quantity (or the inverse) at least this = one-sided book
LOG_COLS = ["date", "time", "symbol", "price", "direction", "rvol", "value_cr", "prints_cr", "block", "kinds"]


def prints_file(day) -> "Path":   # noqa: F821
    return LIVE_DIR / f"prints_{day:%Y%m%d}.parquet"


def book_file() -> "Path":   # noqa: F821
    return LIVE_DIR / "book.json"


class FootprintRecorder:
    """Inside the live service: keeps every trade of LARGE_PRINT_CR or more and the latest order-book totals.
    Fed with the same FYERS SymbolUpdate ticks as the bar builder (fields read defensively: a tick without trade
    size or book totals simply adds nothing)."""

    def __init__(self, min_cr: float = LARGE_PRINT_CR):
        self.min_value = min_cr * 1e7
        self.prints: list[dict] = []
        self.book: dict[str, dict] = {}

    def on_tick(self, msg: dict) -> None:
        sym, ltp = msg.get("symbol"), msg.get("ltp")
        if not sym or not ltp or float(ltp) <= 0:
            return
        sym = str(sym).split(":")[-1].removesuffix("-EQ")
        ltp = float(ltp)
        qty = float(msg.get("last_traded_qty") or 0)
        t = msg.get("last_traded_time") or msg.get("exch_feed_time")
        if qty * ltp >= self.min_value and t:
            bid, ask = float(msg.get("bid_price") or 0), float(msg.get("ask_price") or 0)
            side = "BUY" if ask and ltp >= ask else "SELL" if bid and ltp <= bid else None
            ts = pd.Timestamp(int(t), unit="s") + pd.Timedelta(hours=5, minutes=30)
            self.prints.append({"ts": ts, "symbol": sym, "price": ltp, "qty": qty, "value": qty * ltp, "side": side})
        tb, ts_ = msg.get("tot_buy_qty"), msg.get("tot_sell_qty")
        if tb is not None and ts_ is not None:
            self.book[sym] = {"buy_qty": float(tb), "sell_qty": float(ts_)}

    def flush(self, day) -> None:
        """Append the new prints to today's file and rewrite the book (called every few seconds)."""
        LIVE_DIR.mkdir(parents=True, exist_ok=True)
        if self.prints:
            new = pd.DataFrame(self.prints)
            path = prints_file(day)
            old = pd.read_parquet(path) if path.exists() else new.iloc[0:0]
            tmp = path.with_suffix(".tmp")
            pd.concat([old, new], ignore_index=True).to_parquet(tmp, index=False)
            tmp.replace(path)
            self.prints = []
        if self.book:
            tmp = book_file().with_suffix(".tmp")
            tmp.write_text(json.dumps({"at": ist_now().isoformat(timespec="seconds"), "book": self.book}), encoding="utf-8")
            tmp.replace(book_file())


def relative_volume(bars: pd.DataFrame, today: pd.Timestamp, upto: pd.Timestamp) -> pd.DataFrame:
    """Per symbol: today's volume, value and VWAP up to `upto` (bar start times before it), the average volume of
    the last LOOKBACK_SESSIONS sessions up to the same time of day, and their ratio (rvol)."""
    b = bars[bars["ts"] < upto] if len(bars) else bars
    if b.empty:
        return pd.DataFrame(columns=["symbol", "volume", "value_cr", "vwap", "last", "rvol", "sessions"])
    b = b.assign(day=b["ts"].dt.normalize(), tod=b["ts"] - b["ts"].dt.normalize())
    cut = upto - today
    now_ = b[b["day"] == today]
    past = b[(b["day"] < today) & (b["tod"] < cut)]
    days = sorted(past["day"].unique())[-LOOKBACK_SESSIONS:]
    past = past[past["day"].isin(days)]
    per_day = past.groupby(["symbol", "day"])["volume"].sum()
    normal = per_day.groupby("symbol").agg(["mean", "count"])
    g = now_.assign(value=now_["close"] * now_["volume"]).sort_values("ts").groupby("symbol")
    out = pd.DataFrame({"volume": g["volume"].sum(), "value": g["value"].sum(), "last": g["close"].last()})
    out["vwap"] = out["value"] / out["volume"].where(out["volume"] > 0)
    out = out.join(normal, how="left")
    out["rvol"] = np.where(out["count"] >= MIN_SESSIONS, out["volume"] / out["mean"].where(out["mean"] > 0), np.nan)
    out["value_cr"] = out["value"] / 1e7
    return out.rename(columns={"count": "sessions"}).reset_index()[
        ["symbol", "volume", "value_cr", "vwap", "last", "rvol", "sessions"]]


def _block_deals_today(day) -> dict[str, list[dict]]:
    """Today's block deals per symbol from NSE's large-deal snapshot (empty when NSE has none or is unreachable)."""
    try:
        from . import smart_money as sm
        code, body = sm._fetch(sm.API + "snapshot-capital-market-largedeal", None, api=True, referer=sm.PAGES["large"])
        if code != 200 or not sm._readable(body):
            return {}
        df = sm.parse_large_deals(body)
    except Exception:
        return {}
    df = df[(df["kind"] == "block") & (df["date"].astype(str) == day.isoformat())] if len(df) else df
    out: dict[str, list[dict]] = {}
    for r in df.to_dict("records"):
        out.setdefault(r["symbol"], []).append({"client": r.get("client"), "side": r.get("side"),
                                                "value_cr": round(float(r.get("value") or 0) / 1e7, 2)})
    return out


def scan(cfg: dict, log=print, now=None, bars: pd.DataFrame | None = None, frames: dict | None = None,
         fetch_blocks: bool = True) -> dict:
    """Today's footprints for the liquid F&O universe -> data/results/footprints.json (+ new alerts logged)."""
    from .intraday import live as live_feed
    from .intraday.run import intraday_universe, update_bars
    from .store import load_store
    t0 = time.perf_counter()
    now = now or ist_now()
    today = pd.Timestamp(now.date())
    out = {"generated_at": now.isoformat(timespec="seconds"), "market_open": False, "source": None, "rows": [],
           "note": "", "thresholds": {"rvol": RVOL_MIN, "min_value_cr": MIN_VALUE_CR, "large_print_cr": LARGE_PRINT_CR,
                                      "prints_alert_cr": PRINTS_ALERT_CR, "book_ratio": BOOK_RATIO}}
    if not live_feed.market_open_now() and bars is None:
        out["note"] = "Market closed: footprints appear from 09:20 on trading days."
        _write(out)
        return out
    out["market_open"] = True
    frames = frames or load_store()
    symbols, info = intraday_universe(cfg, frames)
    if bars is None:
        bars, _ = update_bars(symbols, cfg, log=log, today_only=True)
    bars = bars[bars["symbol"].isin(symbols) & (bars["ts"] >= today - pd.Timedelta(days=45))]
    todays = bars[bars["ts"] >= today]
    if todays.empty:
        out["note"] = "No 5-minute bars for today yet."
        _write(out)
        return out
    out["source"] = ", ".join(sorted(todays["source"].astype(str).unique()))
    upto = pd.Timestamp(now.replace(tzinfo=None)).floor("5min")
    rv = relative_volume(bars, today, upto)
    close = frames["close"]
    prev = close[close.index < today].ffill().iloc[-1] if len(close) else pd.Series(dtype=float)
    prints = pd.read_parquet(prints_file(now.date())) if prints_file(now.date()).exists() else None
    book = {}
    try:
        book = json.loads(book_file().read_text(encoding="utf-8")).get("book") or {}
    except Exception:
        pass
    blocks = _block_deals_today(now.date()) if fetch_blocks else {}
    rows = []
    for r in rv.to_dict("records"):
        s = r["symbol"]
        pc = float(prev.get(s, np.nan)) if len(prev) else np.nan
        chg = (r["last"] / pc - 1) * 100 if pc and pc > 0 else np.nan
        p = prints[prints["symbol"] == s] if prints is not None else None
        pr = {"count": int(len(p)) if p is not None else 0,
              "value_cr": round(float(p["value"].sum()) / 1e7, 2) if p is not None and len(p) else 0.0,
              "buy_cr": round(float(p.loc[p["side"] == "BUY", "value"].sum()) / 1e7, 2) if p is not None and len(p) else 0.0,
              "sell_cr": round(float(p.loc[p["side"] == "SELL", "value"].sum()) / 1e7, 2) if p is not None and len(p) else 0.0}
        bk = book.get(s)
        ratio = (bk["buy_qty"] / bk["sell_qty"]) if bk and bk.get("sell_qty") else None
        kinds, reasons = [], []
        rvol = r["rvol"]
        if rvol == rvol and rvol >= RVOL_MIN and r["value_cr"] >= MIN_VALUE_CR:
            kinds.append("volume")
            reasons.append(f"Volume {rvol:.1f}x normal for this time of day (Rs {r['value_cr']:,.0f} cr traded)")
        if pr["value_cr"] >= PRINTS_ALERT_CR:
            kinds.append("prints")
            reasons.append(f"{pr['count']} large trade{'s' if pr['count'] != 1 else ''} of Rs {LARGE_PRINT_CR:g} cr+ "
                           f"(Rs {pr['value_cr']:,.0f} cr; buyer-initiated {pr['buy_cr']:,.0f}, seller {pr['sell_cr']:,.0f})")
        if s in blocks:
            kinds.append("block")
            reasons += [f"Block deal: {b['client']} {b['side']} Rs {b['value_cr']:,.1f} cr" for b in blocks[s][:3]]
        if not kinds:
            continue
        if ratio is not None and (ratio >= BOOK_RATIO or ratio <= 1 / BOOK_RATIO):
            reasons.append(f"Order book {'buy' if ratio > 1 else 'sell'}-heavy ({ratio:.1f}x pending buy vs sell)")
        up = chg == chg and chg > 0 and r["vwap"] == r["vwap"] and r["last"] > r["vwap"]
        down = chg == chg and chg < 0 and r["vwap"] == r["vwap"] and r["last"] < r["vwap"]
        rows.append({"symbol": s, "last": round(float(r["last"]), 2), "change_pct": round(float(chg), 2) if chg == chg else None,
                     "vwap": round(float(r["vwap"]), 2) if r["vwap"] == r["vwap"] else None,
                     "rvol": round(float(rvol), 2) if rvol == rvol else None, "value_cr": round(float(r["value_cr"]), 1),
                     "direction": "up" if up else "down" if down else "mixed", "kinds": kinds, "reasons": reasons,
                     "prints": pr, "book_ratio": round(ratio, 2) if ratio else None, "blocks": blocks.get(s, [])})
    rows.sort(key=lambda x: (-len(x["kinds"]), -(x["rvol"] or 0)))
    out["rows"] = rows
    out["universe"] = len(symbols)
    out["note"] = (f"{len(rows)} stock{'s' if len(rows) != 1 else ''} with unusual big-money activity right now "
                   f"(of {len(symbols)} liquid F&O stocks)." if rows else
                   f"Nothing unusual right now in {len(symbols)} liquid F&O stocks.")
    out["elapsed_s"] = round(time.perf_counter() - t0, 1)
    _write(out)
    _log(rows, now)
    log(f"Footprints: {out['note']}")
    return out


def _write(out: dict) -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    tmp = FP_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
    tmp.replace(FP_FILE)


def _log(rows: list[dict], now) -> None:
    """The first alert of each stock each day, with its price then (its next-day result is measured later)."""
    day = now.date().isoformat()
    old = pd.read_parquet(LOG_FILE) if LOG_FILE.exists() else pd.DataFrame(columns=LOG_COLS)
    seen = set(old.loc[old["date"] == day, "symbol"]) if len(old) else set()
    new = [{"date": day, "time": now.strftime("%H:%M"), "symbol": r["symbol"], "price": r["last"],
            "direction": r["direction"], "rvol": r["rvol"], "value_cr": r["value_cr"],
            "prints_cr": r["prints"]["value_cr"], "block": bool(r["blocks"]), "kinds": ",".join(r["kinds"])}
           for r in rows if r["symbol"] not in seen]
    if new:
        both = pd.concat([old, pd.DataFrame(new, columns=LOG_COLS)], ignore_index=True)
        tmp = LOG_FILE.with_suffix(".tmp")
        both.to_parquet(tmp, index=False)
        tmp.replace(LOG_FILE)


def load_log() -> pd.DataFrame:
    try:
        return pd.read_parquet(LOG_FILE)
    except Exception:
        return pd.DataFrame(columns=LOG_COLS)


def outcomes(log_df: pd.DataFrame, close: pd.DataFrame) -> pd.DataFrame:
    """Each logged alert + its next trading day's close and the move in the alert's direction (%), from the daily
    store. 'mixed' alerts get the raw move; an alert without a next close yet has NaN."""
    if log_df.empty:
        return log_df.assign(next_date=None, next_close=np.nan, move_pct=np.nan)
    idx = close.index
    nd, nc = [], []
    for r in log_df.itertuples(index=False):
        i = idx.searchsorted(pd.Timestamp(r.date), side="right")
        if i < len(idx) and r.symbol in close.columns and not np.isnan(close[r.symbol].iloc[i]):
            nd.append(idx[i].date().isoformat())
            nc.append(float(close[r.symbol].iloc[i]))
        else:
            nd.append(None)
            nc.append(np.nan)
    out = log_df.assign(next_date=nd, next_close=nc)
    raw = (out["next_close"] / out["price"].astype(float) - 1) * 100
    sign = np.where(out["direction"] == "down", -1.0, 1.0)
    return out.assign(move_pct=raw * sign)


def cleanup_old_prints(keep_days: int = 10) -> None:
    cutoff = (ist_now() - timedelta(days=keep_days)).strftime("%Y%m%d")
    for f in LIVE_DIR.glob("prints_*.parquet"):
        if f.stem.split("_")[-1] < cutoff:
            f.unlink(missing_ok=True)
