"""Daily / weekly chart for one symbol from the price store: bars, indicators, markers and price lines.

Indicators are computed on the full history (scanner.indicators.add_indicators + Bollinger / MACD
histogram here) and then sliced to the range, so the SMA200 is valid at the left edge. NaN-close rows
are dropped (never forward-filled). Weekly bars are stamped with the LAST TRADING DATE of the week.
"""
from __future__ import annotations

import pandas as pd

from scanner.indicators import add_indicators

from . import data, holdings_svc, strategies as st
from ..errors import ApiException, not_found
from ..util import num, ser_list

RANGE_DAYS = {"3m": 92, "6m": 183, "1y": 366, "2y": 731, "5y": 1827, "max": None}
INDICATORS = ("sma20", "sma50", "sma200", "ema21", "bb_upper", "bb_mid", "bb_lower", "rsi14", "macd",
              "macd_signal", "macd_hist", "vol_avg20")
DEFAULT_INDICATORS = ("sma20", "sma50", "sma200", "rsi14")


def bars_frame(symbol: str) -> pd.DataFrame:
    frames = data.store()
    c = frames["close"]
    if symbol not in c.columns:
        raise ApiException("NOT_FOUND", f"Symbol '{symbol}' not found in the price store.",
                           "Run a scan, or check the NSE symbol (e.g. M&M).")
    df = pd.DataFrame({f: frames[f][symbol] for f in ("open", "high", "low", "close", "volume")}).dropna(subset=["close"])
    if df.empty:
        raise not_found(f"Price history for '{symbol}'")
    df["volume"] = df["volume"].fillna(0.0)
    for f in ("open", "high", "low"):
        df[f] = df[f].fillna(df["close"])
    return df


def weekly(df: pd.DataFrame) -> pd.DataFrame:
    g = df.groupby(df.index.to_period("W-FRI"))
    w = pd.DataFrame({"open": g["open"].first(), "high": g["high"].max(), "low": g["low"].min(),
                      "close": g["close"].last(), "volume": g["volume"].sum()})
    last_day = pd.Series(df.index, index=df.index).groupby(df.index.to_period("W-FRI")).last()
    w.index = pd.DatetimeIndex(last_day.reindex(w.index).values, name="date")
    return w


def with_indicators(df: pd.DataFrame) -> pd.DataFrame:
    out = add_indicators(df)
    out["rsi14"] = out["rsi"]
    std = df["close"].rolling(20, min_periods=20).std()
    out["bb_mid"] = out["sma20"]
    out["bb_upper"] = out["sma20"] + 2 * std
    out["bb_lower"] = out["sma20"] - 2 * std
    out["macd_hist"] = out["macd"] - out["macd_signal"]
    return out


def build(symbol: str, tf: str, rng: str, indicators: list[str]) -> dict:
    lt = data.latest() or {}
    df = bars_frame(symbol)
    source_date = df.index[-1].date().isoformat()
    if tf == "1w":
        df = weekly(df)
    full = with_indicators(df)
    days = RANGE_DAYS[rng]
    view = full if days is None else full[full.index >= full.index[-1] - pd.Timedelta(days=days)]
    first = view.index[0].date().isoformat()
    t = [d.date().isoformat() for d in view.index]
    kind = data.symbol_kind(symbol)
    meta = data.symbol_meta().get(symbol, {})
    out_ind = {k: ser_list(view[k], 4) for k in indicators if k in view.columns}
    markers, lines, avail = _markers_and_lines(symbol, lt, first, t, tf)
    results_on = None
    for s in lt.get("strategies") or []:
        for row in (s.get("positions") or []) + (s.get("actions") or []) + (s.get("ranking") or []):
            if row.get("symbol") == symbol and row.get("results_on"):
                results_on = row["results_on"]
    for h in lt.get("holdings") or []:
        if h.get("symbol") == symbol and h.get("results_on"):
            results_on = h["results_on"]
    past = [d for d in data.past_results(symbol) if d >= first and d <= t[-1]]
    for d in past:
        markers.append({"t": _snap(d, t), "position": "belowBar", "shape": "circle", "kind": "results", "tone": "neutral",
                        "text": "R", "detail": f"Results {d}", "strategy_key": None})
    year = full.iloc[-252 if tf == "1d" else -52:]
    lines.append({"price": num(year["high"].max(), 2), "label": "52w high", "strategy_key": None, "kind": "high_52w"})
    lines.append({"price": num(year["low"].min(), 2), "label": "52w low", "strategy_key": None, "kind": "low_52w"})
    markers = [m for m in markers if m["t"] is not None]
    markers.sort(key=lambda m: m["t"])
    return {
        "symbol": symbol, "company": meta.get("company"), "industry": meta.get("industry"), "kind": kind,
        "tf": tf, "range": rng, "adjusted": True, "source_date": source_date,
        "bars": {"t": t, "o": ser_list(view["open"], 2), "h": ser_list(view["high"], 2), "l": ser_list(view["low"], 2),
                 "c": ser_list(view["close"], 2), "v": [0.0] * len(view) if kind == "index" else ser_list(view["volume"], 0)},
        "indicators": out_ind, "markers": markers, "price_lines": [x for x in lines if x["price"] is not None],
        "strategies_available": avail, "results_on": results_on, "past_results": past,
    }


def _snap(d: str, t: list[str]) -> str | None:
    """Align a date to the bar that contains it (weekly bars carry the week's last trading date)."""
    if not t or d < t[0] or d > t[-1]:
        return None
    import bisect
    i = bisect.bisect_left(t, d)
    return t[min(i, len(t) - 1)]


def _markers_and_lines(symbol: str, lt: dict, first: str, t: list[str], tf: str):
    markers, lines, avail = [], [], []
    names = {s["key"]: s.get("name") or s["key"] for s in st.all_strategies(lt)} if lt else {}
    tr = data.trades()
    if tr is not None:
        mine = tr[tr["symbol"] == symbol]
        for key, g in mine.groupby("strategy"):
            avail.append({"key": str(key), "name": names.get(key, str(key)), "trades": int(len(g))})
        for r in mine.itertuples(index=False):
            short = (names.get(r.strategy, r.strategy) or "")[:12]
            if r.entry_date >= first:
                markers.append({"t": _snap(r.entry_date, t), "position": "belowBar", "shape": "arrowUp", "kind": "entry",
                                "tone": "profit", "text": f"B · {short}", "detail": f"Bought at {r.entry_price:.2f}",
                                "strategy_key": r.strategy})
            if r.exit_date >= first:
                markers.append({"t": _snap(r.exit_date, t), "position": "aboveBar", "shape": "arrowDown", "kind": "exit",
                                "tone": "profit" if r.ret_pct > 0 else "loss", "text": f"S {r.ret_pct:+.1f}%",
                                "detail": f"{r.reason} at {r.exit_price:.2f}", "strategy_key": r.strategy})
        avail.sort(key=lambda x: -x["trades"])
    for s in st.all_strategies(lt) if lt else []:
        if s["lifecycle"] != "active":
            continue
        # a strategy that only holds, orders or ranks this symbol draws lines / markers too: make it pickable
        if s["key"] not in {a["key"] for a in avail} and any(
                r.get("symbol") == symbol for r in (s.get("positions") or []) + (s.get("actions") or [])):
            avail.append({"key": s["key"], "name": names.get(s["key"], s["key"]), "trades": 0})
        for p in s.get("positions") or []:
            if p.get("symbol") != symbol:
                continue
            if str(p.get("entry_date")) >= first:
                markers.append({"t": _snap(str(p["entry_date"]), t), "position": "belowBar", "shape": "circle",
                                "kind": "open_entry", "tone": "neutral", "text": f"Held · {s.get('name', '')[:12]}",
                                "detail": f"Model entry {p.get('entry_price')}", "strategy_key": s["key"]})
            lines.append({"price": num(p.get("entry_price"), 2), "label": f"{s.get('name')} entry",
                          "strategy_key": s["key"], "kind": "model_entry"})
            if p.get("stop") is not None:
                lines.append({"price": num(p.get("stop"), 2), "label": f"{s.get('name')} stop",
                              "strategy_key": s["key"], "kind": "model_stop"})
        for a in s.get("actions") or []:
            if a.get("symbol") != symbol:
                continue
            markers.append({"t": t[-1] if t else None, "position": "aboveBar" if a.get("action") == "SELL" else "belowBar",
                            "shape": "arrowDown" if a.get("action") == "SELL" else "arrowUp", "kind": "pending_order",
                            "tone": "warn", "text": f"{a.get('action')} next open", "detail": a.get("reason"),
                            "strategy_key": s["key"]})
            if a.get("stop") is not None:
                lines.append({"price": num(a.get("stop"), 2), "label": f"Order stop ({s.get('name')})",
                              "strategy_key": s["key"], "kind": "order_stop"})
    for ca in data.store_meta().get("corporate_actions") or []:
        if ca.get("symbol") == symbol and str(ca.get("date", "")) >= first:
            markers.append({"t": _snap(str(ca["date"]), t), "position": "aboveBar", "shape": "square",
                            "kind": "corporate_action", "tone": "neutral", "text": f"x{num(ca.get('factor'), 4)}",
                            "detail": str(ca.get("reason") or ""), "strategy_key": None})
    try:
        held = holdings_svc.rows(lt)[0] if lt else []     # holdings.csv as it is now (edits after the scan count)
    except Exception:
        held = lt.get("holdings") or []
    for h in held:
        if h.get("symbol") != symbol:
            continue
        for k, kind, label in (("buy_price", "your_buy", "Your buy"), ("stop_price", "your_stop", "Your stop"),
                               ("target_price", "your_target", "Your target")):
            if h.get(k) is not None:
                lines.append({"price": num(h[k], 2), "label": label, "strategy_key": None, "kind": kind})
    return markers, lines, avail
