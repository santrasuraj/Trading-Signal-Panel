"""The daily scan: market mood, buy/sell signals, movers and holdings alerts."""
from __future__ import annotations

import json
import math
from datetime import date

import numpy as np
import pandas as pd

from .backtest import load_backtest
from .data import load_cached, refresh
from .indicators import add_indicators
from .providers import INDEX_NIFTY, INDEX_VIX, get_provider
from .rules import active_rules
from .settings import HOLDINGS_FILE, RESULTS_DIR, ist_now, ist_today, market_session_fraction
from .universe import get_universe

LATEST_FILE = RESULTS_DIR / "latest.json"
HOLDING_COLS = ["symbol", "qty", "buy_price", "stop_loss_pct", "target_pct"]
MIN_BARS = 210  # need ~200 days for the 200-DMA


def load_holdings() -> pd.DataFrame:
    if not HOLDINGS_FILE.exists():
        return pd.DataFrame(columns=HOLDING_COLS)
    df = pd.read_csv(HOLDINGS_FILE, dtype={"symbol": str})
    for c in HOLDING_COLS:
        if c not in df.columns:
            df[c] = np.nan
    df["symbol"] = df["symbol"].fillna("").str.strip().str.upper()
    df = df[df["symbol"] != ""]
    for c in HOLDING_COLS[1:]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df[HOLDING_COLS].reset_index(drop=True)


def _num(x, nd=2):
    if x is None:
        return None
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(x) or math.isinf(x) else round(x, nd)


def _market_mood(frames: dict, snaps: list[dict]) -> dict:
    mood: dict = {}
    nifty = frames.get(INDEX_NIFTY)
    if nifty is not None and len(nifty) > 1:
        r = nifty.iloc[-1]
        mood.update(
            nifty=_num(r["close"]), nifty_change_pct=_num(r["chg_pct"]), nifty_rsi=_num(r["rsi"], 0),
            nifty_above_50=bool(r["close"] > r["sma50"]) if not pd.isna(r["sma50"]) else None,
            nifty_above_200=bool(r["close"] > r["sma200"]) if not pd.isna(r["sma200"]) else None,
            nifty_date=nifty.index[-1].date().isoformat(),
        )
    vix = frames.get(INDEX_VIX)
    if vix is not None and len(vix) > 1:
        mood.update(vix=_num(vix["close"].iloc[-1]), vix_change_pct=_num(vix["chg_pct"].iloc[-1]))

    fresh = [s for s in snaps if s["fresh"]]
    if fresh:
        mood["advances"] = sum(1 for s in fresh if (s["change_pct"] or 0) > 0)
        mood["declines"] = sum(1 for s in fresh if (s["change_pct"] or 0) < 0)
        mood["breadth_50"] = _num(100 * np.mean([s["above_50"] for s in fresh]), 1)
        mood["breadth_200"] = _num(100 * np.mean([s["above_200"] for s in fresh]), 1)

    b50 = mood.get("breadth_50") or 50
    if mood.get("nifty_above_50") and mood.get("nifty_above_200") and b50 >= 50:
        mood["label"], mood["level"] = "Bullish", "good"
        mood["advice"] = "Market trend is UP. Buy signals have better odds in this kind of market."
    elif mood.get("nifty_above_50") is False and (mood.get("nifty_above_200") is False or b50 < 45):
        mood["label"], mood["level"] = "Bearish", "bad"
        mood["advice"] = ("Market trend is DOWN. Most buy signals fail in a falling market - be very careful, "
                          "use smaller positions or wait.")
    else:
        mood["label"], mood["level"] = "Mixed / Sideways", "neutral"
        mood["advice"] = "Market is mixed. Be selective and keep strict stop-losses."
    if (mood.get("vix") or 0) >= 20:
        mood["advice"] += " India VIX is high - expect big swings."
    return mood


def run_scan(cfg: dict | None = None, source: str | None = None, update: bool = True,
             progress=None, log=print) -> dict:
    from .settings import load_config

    cfg = cfg or load_config()
    started = ist_now()
    provider, source_note = get_provider(source or cfg.get("data_source", "auto"))
    log(f"Data source: {provider.label}. {source_note}")

    uni, uni_note = get_universe(cfg.get("universe", "nifty500"))
    log(f"Universe: {uni_note}")
    meta = uni.set_index("symbol")[["company", "industry"]].to_dict("index")
    holdings = load_holdings()
    symbols = list(dict.fromkeys(list(uni["symbol"]) + list(holdings["symbol"])))

    if update:
        histories, info = refresh(provider, symbols, int(cfg.get("lookback_days", 1100)), progress=progress, log=log)
    else:
        histories = load_cached(provider.name, symbols + [INDEX_NIFTY, INDEX_VIX])
        info = {"errors": {}, "live_day": None}

    log("Calculating indicators and signals...")
    frames = {s: add_indicators(df) for s, df in histories.items() if len(df) >= 30}
    stock_frames = {s: f for s, f in frames.items() if s not in (INDEX_NIFTY, INDEX_VIX)}
    if not stock_frames:
        raise RuntimeError("No price data available. Check internet connection and try again.")
    data_date: date = max(f.index[-1].date() for f in stock_frames.values())

    # Today's volume is still building during market hours - project it to a full day.
    frac = market_session_fraction()
    live_today = frac is not None and data_date == ist_today()
    if live_today:
        factor = max(frac, 0.1)
        for f in stock_frames.values():
            if f.index[-1].date() == data_date:
                f.loc[f.index[-1], "vol_ratio"] = f["volume"].iloc[-1] / (f["vol_avg20"].iloc[-1] * factor)

    filters = cfg.get("filters") or {}
    min_price = float(filters.get("min_price", 0))
    min_vol = float(filters.get("min_avg_volume", 0))
    rules = active_rules(cfg)
    bt = load_backtest()
    bt_stats = {r["key"]: r for r in (bt or {}).get("rules", [])}
    sl_pct = float((cfg.get("holdings_defaults") or {}).get("stop_loss_pct", 5))
    tg_pct = float((cfg.get("holdings_defaults") or {}).get("target_pct", 10))

    snaps, buys, sells, skipped = [], [], [], []
    fired_by_symbol: dict[str, list] = {}
    for sym in symbols:
        f = stock_frames.get(sym)
        if f is None or len(f) < MIN_BARS:
            skipped.append(sym)
            continue
        r = f.iloc[-1]
        fresh = f.index[-1].date() == data_date
        info_m = meta.get(sym, {})
        snap = {
            "symbol": sym, "company": info_m.get("company", sym), "industry": info_m.get("industry", ""),
            "date": f.index[-1].date().isoformat(), "fresh": fresh,
            "close": _num(r["close"]), "change_pct": _num(r["chg_pct"]), "volume": _num(r["volume"], 0),
            "vol_ratio": _num(r["vol_ratio"]), "rsi": _num(r["rsi"], 1),
            "above_50": bool(r["close"] > r["sma50"]), "above_200": bool(r["close"] > r["sma200"]),
            "from_52w_high_pct": _num((r["close"] / r["high_52w"] - 1) * 100) if r["high_52w"] else None,
            "liquid": bool(r["close"] >= min_price and (r["vol_avg20"] or 0) >= min_vol),
        }
        snaps.append(snap)

        fired = []
        for rule, params in rules:
            if rule.evaluate(f, params).iloc[-1]:
                fired.append((rule, params))
        fired_by_symbol[sym] = fired
        if not (fresh and snap["liquid"]):
            continue
        for side, bucket in (("BUY", buys), ("SELL", sells)):
            hits = [(ru, p) for ru, p in fired if ru.side == side]
            if not hits:
                continue
            wr = [bt_stats[ru.key].get("win_rate") for ru, _ in hits if bt_stats.get(ru.key, {}).get("win_rate") is not None]
            entry = {
                **{k: snap[k] for k in ("symbol", "company", "industry", "close", "change_pct", "vol_ratio", "rsi")},
                "signals": [ru.name for ru, _ in hits],
                "rule_keys": [ru.key for ru, _ in hits],
                "reasons": [ru.reason(r, p) for ru, p in hits],
                "score": len(hits),
                "backtest_win_rate": _num(np.mean(wr), 1) if wr else None,
            }
            if side == "BUY":
                entry["stop_loss"] = _num(r["close"] * (1 - sl_pct / 100))
                entry["target"] = _num(r["close"] * (1 + tg_pct / 100))
            bucket.append(entry)

    key = lambda e: (-e["score"], -(e["vol_ratio"] or 0))
    buys.sort(key=key)
    sells.sort(key=key)
    conflicted = {e["symbol"] for e in buys} & {e["symbol"] for e in sells}
    for e in buys + sells:
        e["mixed"] = e["symbol"] in conflicted

    movers_n = int(cfg.get("movers_count", 15))
    pool = [s for s in snaps if s["fresh"] and s["liquid"] and s["change_pct"] is not None]
    cols = ("symbol", "company", "industry", "close", "change_pct", "vol_ratio", "rsi")
    pick = lambda lst: [{k: s[k] for k in cols} for s in lst]
    gainers = pick(sorted(pool, key=lambda s: -s["change_pct"])[:movers_n])
    losers = pick(sorted(pool, key=lambda s: s["change_pct"])[:movers_n])
    spikes = pick(sorted([s for s in pool if (s["vol_ratio"] or 0) >= 3], key=lambda s: -s["vol_ratio"])[:movers_n])

    # Holdings
    holding_rows = []
    for h in holdings.itertuples(index=False):
        f = stock_frames.get(h.symbol)
        if f is None or f.empty:
            holding_rows.append({"symbol": h.symbol, "level": "unknown",
                                 "alerts": ["No price data - check the NSE symbol spelling (e.g. RELIANCE, TCS)"]})
            continue
        r = f.iloc[-1]
        close = float(r["close"])
        sl = h.stop_loss_pct if not pd.isna(h.stop_loss_pct) else sl_pct
        tg = h.target_pct if not pd.isna(h.target_pct) else tg_pct
        buy = float(h.buy_price) if not pd.isna(h.buy_price) else None
        qty = float(h.qty) if not pd.isna(h.qty) else 0
        alerts, level = [], "ok"
        if buy:
            if close <= buy * (1 - sl / 100):
                alerts.append(f"STOP-LOSS HIT: down more than {sl:g}% from your buy price")
                level = "danger"
            elif close >= buy * (1 + tg / 100):
                alerts.append(f"TARGET REACHED: up more than {tg:g}% from your buy price")
                level = "good"
        for ru, p in fired_by_symbol.get(h.symbol, []):
            if ru.side == "SELL":
                alerts.append(f"Sell signal: {ru.name} - {ru.reason(r, p)}")
                level = "danger"
        if not pd.isna(r["sma20"]) and close < r["sma20"]:
            alerts.append("Below 20-day average (short-term weakness)")
            if level == "ok":
                level = "watch"
        holding_rows.append({
            "symbol": h.symbol, "company": meta.get(h.symbol, {}).get("company", h.symbol),
            "qty": _num(qty, 0), "buy_price": _num(buy), "close": _num(close),
            "change_pct": _num(r["chg_pct"]),
            "pnl_pct": _num((close / buy - 1) * 100) if buy else None,
            "pnl_amount": _num((close - buy) * qty) if buy else None,
            "stop_price": _num(buy * (1 - sl / 100)) if buy else None,
            "target_price": _num(buy * (1 + tg / 100)) if buy else None,
            "level": level, "alerts": alerts,
        })

    result = {
        "generated_at": started.isoformat(timespec="seconds"),
        "source": provider.label, "source_name": provider.name, "source_note": source_note,
        "universe": uni_note, "data_date": data_date.isoformat(), "live": live_today,
        "stocks_scanned": len(snaps), "skipped": skipped,
        "errors": info.get("errors", {}),
        "market": _market_mood(frames, snaps),
        "buy": buys, "sell": sells,
        "gainers": gainers, "losers": losers, "volume_spikes": spikes,
        "holdings": holding_rows,
        "snapshot": [{k: s[k] for k in ("symbol", "company", "close", "change_pct")} for s in snaps],
        "backtest_available": bt is not None,
    }
    text = json.dumps(result, indent=1, default=str)
    LATEST_FILE.write_text(text, encoding="utf-8")
    (RESULTS_DIR / f"scan_{started:%Y%m%d_%H%M}.json").write_text(text, encoding="utf-8")
    log(f"Scan done: {len(snaps)} stocks, {len(buys)} buy signals, {len(sells)} sell signals.")
    return result


def load_latest() -> dict | None:
    if not LATEST_FILE.exists():
        return None
    try:
        return json.loads(LATEST_FILE.read_text(encoding="utf-8"))
    except Exception:
        return None
