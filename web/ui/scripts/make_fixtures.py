"""Dev-only: build the UI mock fixtures (src/api/mock/fixtures/*.json) from the REAL local data.

Reads (never writes) data/results/latest.json, curves.parquet, intraday.json, scan_*.json, the price store,
data/nse/* caches, config.yaml and holdings.csv, and transcribes them into the Final API contract shapes of
docs/ui_spec_review.md so the React app can be developed while web/api is being built. Nothing is invented:
every number comes from those files. Fields the real API derives from backend additions that do not exist yet
(B1 trades artifact, B2 screener artifact, B4 rejected tests, B8 validation) are left out or marked unavailable,
except the screener, which is computed here from the stored closes so the page can be exercised.

Run from web/ui:   ..\\..\\..\\..\\.venv\\Scripts\\python.exe scripts/make_fixtures.py
(or `npm run fixtures`). Output is git-ignored.
"""
from __future__ import annotations

import json
import math
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

UI = Path(__file__).resolve().parent.parent
ROOT = UI.parent.parent
sys.path.insert(0, str(ROOT))

from scanner.settings import load_config  # noqa: E402
from scanner.store import PanelStore  # noqa: E402

OUT = UI / "src" / "api" / "mock" / "fixtures"
DATA = ROOT / "data"
RESULTS = DATA / "results"
NSE = DATA / "nse"
IST = timezone(timedelta(hours=5, minutes=30))
NOW = datetime.now(IST)
TODAY = NOW.date()


# ------------------------------------------------------------------ helpers
def clean(o):
    """NaN/inf -> None recursively, numpy -> python, Timestamps -> ISO date."""
    if isinstance(o, dict):
        return {str(k): clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    if isinstance(o, (np.floating, float)):
        f = float(o)
        return None if not math.isfinite(f) else f
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.bool_):
        return bool(o)
    if isinstance(o, (pd.Timestamp, datetime)):
        return o.strftime("%Y-%m-%d")
    if isinstance(o, date):
        return o.isoformat()
    return o


def r(x, nd=2):
    if x is None:
        return None
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    return round(f, nd) if math.isfinite(f) else None


def write(name: str, obj) -> None:
    p = OUT / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(clean(obj), separators=(",", ":"), ensure_ascii=False), encoding="utf-8")


def inr(x: float) -> str:
    """Indian digit grouping: 500000 -> 'Rs 5,00,000' (with the rupee sign)."""
    s = f"{int(round(x)):d}"
    head, tail = s[:-3], s[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return "₹" + ",".join(groups + [tail]) if groups else "₹" + tail


def perf(d) -> dict | None:
    """{} -> None; else PerfStats with every key present."""
    if not d:
        return None
    return {k: d.get(k) for k in ("return_pct", "cagr_pct", "max_dd_pct", "sharpe", "vol_pct", "after_tax_cagr_pct")}


TRADE_KEYS = ("trades", "win_rate", "avg_win_pct", "avg_loss_pct", "expectancy_pct", "profit_factor", "avg_days")


def window(d) -> dict | None:
    if not d:
        return None
    out = perf(d) or {}
    for k in TRADE_KEYS:
        out[k] = d.get(k, 0 if k == "trades" else None)
    out["trades"] = out["trades"] or 0
    for b in ("benchmark", "ew_benchmark", "n500_benchmark", "factor_benchmark"):
        out[b] = perf(d.get(b))
    return out


def full_metrics(d) -> dict:
    out = window(d) or {}
    out.update({
        "exposure_pct": d.get("exposure_pct"), "start": d.get("start"), "end": d.get("end"),
        "after_tax_return_pct": d.get("after_tax_return_pct"),
        "cagr_range": d.get("cagr_range") or None, "te_n500_pct": d.get("te_n500_pct"),
        "factor_benchmark_name": d.get("factor_benchmark_name") or None,
    })
    return out


def days_until(iso: str | None) -> int | None:
    if not iso:
        return None
    try:
        return (date.fromisoformat(iso[:10]) - TODAY).days
    except ValueError:
        return None


def nse_date(s: str) -> str | None:
    try:
        return datetime.strptime(s, "%d-%b-%Y").date().isoformat()
    except (TypeError, ValueError):
        return None


# ------------------------------------------------------------------ load sources
latest = json.loads((RESULTS / "latest.json").read_text(encoding="utf-8"))
cfg = load_config()
curves = pd.read_parquet(RESULTS / "curves.parquet")
idx_hist = pd.read_parquet(NSE / "index_history.parquet") if (NSE / "index_history.parquet").exists() else None
universe = pd.read_csv(DATA / f"universe_{cfg.get('universe', 'nifty500')}.csv")
uni_info = {r_.symbol: (r_.company, r_.industry) for r_ in universe.itertuples()}
etfs = list(cfg.get("etfs") or [])
store = PanelStore()
frames = store.load()
# drop non-trading rows (e.g. an exchange holiday stored as an all-NaN row), as the panel does
_uni = [s_ for s_ in universe.symbol if s_ in frames["close"].columns]
_valid = frames["close"][_uni].notna().mean(axis=1) > 0.5
frames = {k: v.loc[_valid[_valid].index] if len(v) == len(_valid) else v for k, v in frames.items()}
close, high, low, opn, vol = (frames[k] for k in ("close", "high", "low", "open", "volume"))
deliv = frames.get("deliv_pct")
print(f"store {store.version()} {close.shape}, curves {curves.shape}")

events_files = sorted(NSE.glob("events_*.json"))
events_raw = json.loads(events_files[-1].read_text(encoding="utf-8")) if events_files else []
events_cached_on = (datetime.strptime(events_files[-1].stem.split("_")[1], "%Y%m%d").date().isoformat()
                    if events_files else None)
results_on: dict[str, str] = {}
for e in events_raw:
    d = nse_date(e.get("date"))
    if d and "result" in (e.get("purpose") or "").lower() and d >= TODAY.isoformat():
        results_on.setdefault(e["symbol"], d)

try:
    holdings_df = pd.read_csv(ROOT / "holdings.csv")
except Exception:
    holdings_df = pd.DataFrame(columns=["symbol", "qty", "buy_price", "buy_date", "stop_loss_pct", "target_pct"])
held = {str(s).upper(): q for s, q in zip(holdings_df.get("symbol", []), holdings_df.get("qty", []))}

# ------------------------------------------------------------------ clock
def trading_holidays() -> tuple[set[str], dict[str, str], bool]:
    p = NSE / f"holidays_{TODAY.year}.json"
    if not p.exists():
        return set(), {}, False
    raw = json.loads(p.read_text(encoding="utf-8")).get("CM", [])
    names = {nse_date(h["tradingDate"]): h.get("description") for h in raw}
    return set(names), names, True


HOLIDAYS, HOLIDAY_NAMES, HOLIDAYS_KNOWN = trading_holidays()


def is_trading(d: date) -> bool:
    return d.weekday() < 5 and d.isoformat() not in HOLIDAYS


def prev_trading(d: date) -> date:
    d -= timedelta(days=1)
    while not is_trading(d):
        d -= timedelta(days=1)
    return d


def clock() -> dict:
    t = NOW.time()
    trading = is_trading(TODAY)
    hm = t.hour * 60 + t.minute
    if TODAY.weekday() >= 5:
        session = "weekend"
    elif not trading:
        session = "holiday"
    elif 540 <= hm < 555:
        session = "pre_open"
    elif 555 <= hm < 930:
        session = "open"
    elif 930 <= hm < 1080:
        session = "post_close"
    else:
        session = "closed"
    last_completed = TODAY if trading and hm >= 1080 else prev_trading(TODAY)
    nxt = TODAY if trading and hm < 555 else TODAY + timedelta(days=1)
    while not is_trading(nxt):
        nxt += timedelta(days=1)
    return {
        "now": NOW.isoformat(timespec="seconds"), "session": session, "is_trading_day": trading,
        "holiday_name": HOLIDAY_NAMES.get(TODAY.isoformat()), "next_open": f"{nxt.isoformat()}T09:15:00+05:30",
        "last_completed_day": last_completed.isoformat(), "holidays_known": HOLIDAYS_KNOWN,
    }


CLOCK = clock()

# ------------------------------------------------------------------ as_of
strategies_raw = latest.get("strategies", [])
legacy = "indices" not in latest or any("horizon" not in s for s in strategies_raw)
AS_OF = {
    "scan_id": latest["generated_at"], "generated_at": latest["generated_at"], "elapsed_s": latest.get("elapsed_s", 0),
    "data_date": latest["data_date"], "live": bool(latest.get("live")), "live_source": latest.get("live_source"),
    "complete_upto": latest.get("complete_upto"),
    "stale": latest["data_date"] < CLOCK["last_completed_day"],
    "legacy_producer": legacy, "backtest_universe": latest.get("backtest_universe", "current_list"),
    "universe_note": latest.get("universe", ""), "tradable": latest.get("stocks", 0),
    "capital": latest.get("capital", 0),
    "min_position": latest.get("min_position", (cfg.get("account") or {}).get("min_position", 0)) or 0,
    "costs_round_trip_pct": latest.get("costs_round_trip_pct", 0),
}
CAPITAL = AS_OF["capital"]
MARKET = latest.get("market", {})
FACTORS = {f["name"]: f for f in (latest.get("indices") or {}).get("factors", [])}

# ------------------------------------------------------------------ strategy rules (rules.source = 'config': B5 missing)
try:
    from scanner.strategies import REJECTED_REASONS, build_strategies, strategy_lifecycle
    _all = {s.key: s for s in build_strategies(cfg, include_disabled=True)}
except Exception as exc:  # the dev mock must still build
    print("build_strategies failed:", exc)
    _all, REJECTED_REASONS = {}, {}

    def strategy_lifecycle(_c, _k):
        return "active", None


def rules_for(s: dict) -> dict:
    o = _all.get(s["key"])
    g = (lambda n, d=None: getattr(o, n, d)) if o is not None else (lambda n, d=None: d)
    kind = s.get("kind", "rank")
    params = dict((cfg.get("strategies") or {}).get(s["key"]) or {})
    rules = {
        "kind": kind, "rebalance": g("rebalance") if kind == "rank" else None,
        "top_n": g("top_n") if kind == "rank" else None, "keep_rank": g("keep_rank") if kind == "rank" else None,
        "max_positions": s.get("max_positions", 0), "stop_pct": g("stop_pct"), "stop_atr": g("stop_atr"),
        "target_pct": g("target_pct"), "trail_pct": g("trail_pct"), "max_hold": g("max_hold"),
        "sizing": g("sizing", "equal") or "equal", "risk_pct": g("risk_pct") if g("sizing") == "risk" else None,
        "use_regime": bool(g("use_regime", False)), "regime_action": g("regime_action") if kind == "rank" else None,
        "params": params, "source": "config",
    }
    plain = []
    if kind == "rank":
        plain.append(f"Rank every eligible {'ETF' if s.get('universe') == 'etfs' else 'stock'} by the strategy score; "
                     f"hold the top {rules['top_n']}.")
        if rules["keep_rank"]:
            plain.append(f"Keep a holding while it stays within the top {rules['keep_rank']} (fewer trades, lower tax).")
        plain.append(f"Review {rules['rebalance']}; orders are filled at the next open.")
    else:
        plain.append("Buy at the next open when the entry signal fires on the close.")
        plain.append(f"Hold at most {rules['max_positions']} positions at a time; signals beyond that are skipped.")
    if rules["stop_pct"]:
        plain.append(f"Initial stop {r(rules['stop_pct'], 1)}% below the fill price.")
    if rules["stop_atr"]:
        plain.append(f"Initial stop {r(rules['stop_atr'], 1)} × ATR(14) below the fill price.")
    if rules["target_pct"]:
        plain.append(f"Take profit at +{r(rules['target_pct'], 1)}%.")
    if rules["trail_pct"]:
        plain.append(f"Trailing stop {r(rules['trail_pct'], 1)}% below the highest close since entry.")
    if rules["max_hold"]:
        plain.append(f"Exit after {rules['max_hold']} trading days at the latest.")
    if rules["use_regime"]:
        plain.append("No new buys while Nifty 50 is below its 200-day average"
                     + (" (existing holdings are kept)." if rules["regime_action"] != "cash" else "; move to cash."))
    plain.append(f"Every trade pays full delivery costs (≈ {AS_OF['costs_round_trip_pct']}% round trip incl. slippage).")
    rules["plain_rules"] = plain
    return rules


RULES = {s["key"]: rules_for(s) for s in strategies_raw}

# ------------------------------------------------------------------ catalogue evidence
CAT_TEXT = (ROOT / "docs" / "strategy_catalogue.md").read_text(encoding="utf-8")
CAT_ID = {"momentum": "L1", "low_vol": "L2", "index_trend": "L3", "dual_momentum": "L4", "golden_cross": "S11",
          "vcp_breakout": "S1", "trend_breakout": "S4", "donchian": "S3", "pullback_leaders": "S5",
          "earnings_gap": "S6", "sector_rotation": "S7", "bb_squeeze": "S8", "nr7_breakout": "S9",
          "rsi2_pullback": "S10", "near_high": "S4"}


def catalogue_card(cid: str) -> dict:
    m = re.search(rf"^### {re.escape(cid)}\. (.+?)$(.*?)(?=^### |^## )", CAT_TEXT, re.M | re.S)
    if not m:
        return {"title": None, "summary": "", "sources": [], "failure_modes": []}
    title, body = m.group(1).strip(), m.group(2)
    first = next((ln.strip() for ln in body.splitlines() if ln.strip()), "")
    summary = re.sub(r"\*\*", "", first)
    sources = []
    ev = re.search(r"\*\*Evidence:\*\*(.*?)(?=^- \*\*|\Z)", body, re.M | re.S)
    if ev:
        for t, u in re.findall(r"\[([^\]]+)\]\((https?://[^)]+)\)", ev.group(1)):
            sources.append({"title": t, "url": u})
        if not sources:
            for ln in ev.group(1).splitlines():
                ln = ln.strip(" -")
                if ln:
                    sources.append({"title": re.sub(r"\*\*", "", ln)[:160], "url": None})
    fm = []
    f = re.search(r"\*\*Failure modes:\*\*(.*?)(?=^- \*\*|\Z)", body, re.M | re.S)
    if f:
        txt = f.group(1).strip()
        items = [ln.strip()[2:] for ln in txt.splitlines() if ln.strip().startswith("- ")]
        fm = items or [txt]
    fm = [re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", re.sub(r"\*\*", "", x)) for x in fm]
    return {"title": title, "summary": summary, "sources": sources[:8], "failure_modes": fm[:6]}


def evidence_for(s: dict) -> dict:
    cid = CAT_ID.get(s["key"])
    card = catalogue_card(cid) if cid else {"summary": "", "sources": [], "failure_modes": []}
    full = s["metrics"].get("full", {})
    dd = full.get("max_dd_pct")
    expect = (f"Drops like the backtest's worst {r(dd, 1)}% will happen again, and there will be stretches of a year "
              f"or more behind Nifty 500. Live results are usually below the backtest." if dd is not None else
              "Not enough history to say what to expect.")
    return {"grade": s.get("evidence") or "EXPERIMENTAL", "catalogue_id": cid, "summary": card["summary"] or s.get("description", ""),
            "what_to_expect": expect, "sources": card["sources"], "failure_modes": card["failure_modes"], "validation": None}


# ------------------------------------------------------------------ summaries
REGIME_UP = bool(MARKET.get("regime_up"))


def spark(key: str) -> list:
    if key not in curves:
        return []
    v = curves[key].dropna().to_numpy()
    if len(v) > 120:
        idx = np.round(np.linspace(0, len(v) - 1, 120)).astype(int)
        v = v[idx]
    return [r(x, 4) for x in v]


def summary(s: dict, lifecycle="active", rejected_reason=None) -> dict:
    m = s.get("metrics", {})
    full, m12, m6, m3 = (m.get(k) or {} for k in ("full", "12m", "6m", "3m"))
    cg = full.get("cagr_pct")
    sub = lambda a, b: r(a - b, 2) if a is not None and b is not None else None  # noqa: E731
    ew, n5, bn, fb = (full.get(k) or {} for k in ("ew_benchmark", "n500_benchmark", "benchmark", "factor_benchmark"))
    rng = full.get("cagr_range")
    timing = None
    if rng:
        lo, hi = float(rng[0]), float(rng[1])
        timing = {"base_cagr_pct": cg, "low": r(lo, 2), "high": r(hi, 2),
                  "consistent": cg is not None and lo - 0.05 <= cg <= hi + 0.05,
                  "method": "rebalance_offsets" if s.get("kind") == "rank" else "start_offsets"}
    rules = RULES.get(s["key"]) or rules_for(s)
    acts = s.get("actions", [])
    status = s.get("status", "unknown")
    return {
        "key": s["key"], "name": s["name"], "description": s.get("description", ""),
        "kind": s.get("kind", "rank"), "horizon": s.get("horizon") or ("longterm" if s.get("kind") == "rank" else "swing"),
        "evidence": s.get("evidence") or "EXPERIMENTAL", "universe": s.get("universe", "stocks"), "lifecycle": lifecycle,
        "status": status, "status_reason": s.get("status_reason", ""), "rejected_reason": rejected_reason,
        "comparison_only": status == "not-working" or lifecycle != "active",
        "headline": {
            "cagr_pct": cg, "after_tax_cagr_pct": full.get("after_tax_cagr_pct"), "max_dd_pct": full.get("max_dd_pct"),
            "sharpe": full.get("sharpe"), "vol_pct": full.get("vol_pct"), "win_rate": full.get("win_rate"),
            "trades": full.get("trades") or 0, "exposure_pct": full.get("exposure_pct"), "avg_days": full.get("avg_days"),
            "ret_12m_pct": m12.get("return_pct"), "ret_6m_pct": m6.get("return_pct"), "ret_3m_pct": m3.get("return_pct"),
            "n500_12m_pct": (m12.get("n500_benchmark") or {}).get("return_pct"),
        },
        "edges": {
            "primary": "nifty" if s.get("universe") == "etfs" else "ew",
            "vs_ew_cagr_pct": sub(cg, ew.get("cagr_pct")), "vs_n500_cagr_pct": sub(cg, n5.get("cagr_pct")),
            "vs_nifty_cagr_pct": sub(cg, bn.get("cagr_pct")), "vs_factor_cagr_pct": sub(cg, fb.get("cagr_pct")),
            "r12m_vs_n500_pct": sub(m12.get("return_pct"), (m12.get("n500_benchmark") or {}).get("return_pct")),
            "r6m_vs_n500_pct": sub(m6.get("return_pct"), (m6.get("n500_benchmark") or {}).get("return_pct")),
        },
        "timing": timing,
        "factor_benchmark_name": s.get("benchmark") or full.get("factor_benchmark_name") or None,
        "max_positions": s.get("max_positions", 0), "per_position": s.get("per_position", 0),
        "positions": len(s.get("positions", [])),
        "orders_buy": sum(a["action"] == "BUY" for a in acts), "orders_sell": sum(a["action"] == "SELL" for a in acts),
        "rebalance": rules.get("rebalance"), "next_rebalance": s.get("next_rebalance") if s.get("kind") == "rank" else None,
        "uses_regime_filter": rules["use_regime"], "blocked_by_regime": rules["use_regime"] and not REGIME_UP,
        "spark": spark(s["key"]), "paper": None,
    }


SUMMARIES = [summary(s) for s in strategies_raw]
SUM_BY_KEY = {x["key"]: x for x in SUMMARIES}

# ------------------------------------------------------------------ orders
MODEL_SYMS: dict[str, list[str]] = {}
for s in strategies_raw:
    for p in s.get("positions", []):
        MODEL_SYMS.setdefault(p["symbol"], []).append(s["key"])


def curve_last(key):
    return float(curves[key].dropna().iloc[-1]) if key in curves and curves[key].notna().any() else None


def weight_pct(s: dict, p: dict) -> float | None:
    cl = curve_last(s["key"])
    lp = p.get("last_price")
    if not cl or lp is None:
        return None
    return r(p["qty"] * lp / (CAPITAL * cl) * 100, 2)


def order_rows(s: dict) -> list[dict]:
    rows = []
    sm = SUM_BY_KEY[s["key"]]
    rules = RULES[s["key"]]
    pos = {p["symbol"]: p for p in s.get("positions", [])}
    for a in s.get("actions", []):
        pr, st = a.get("price"), a.get("stop")
        you = held.get(a["symbol"])
        if a["action"] == "BUY":
            qty, basis = a.get("qty"), "sized"
        elif you:
            qty, basis = int(you), "your_holding"
        else:
            w = weight_pct(s, pos[a["symbol"]]) if a["symbol"] in pos else None
            qty = int(CAPITAL * w / 100 // pr) if (w and pr) else None
            basis = "model_weight"
        amount = qty * pr if (qty is not None and pr) else None
        rows.append({
            "strategy_key": s["key"], "strategy_name": s["name"], "strategy_status": s["status"], "horizon": sm["horizon"],
            "comparison_only": sm["comparison_only"], "action": a["action"], "symbol": a["symbol"],
            "company": a.get("company"), "industry": a.get("industry"), "reason": a.get("reason", ""),
            "price": pr, "qty": qty, "qty_basis": basis, "amount": r(amount, 2),
            "stop": st, "stop_distance_pct": r((st / pr - 1) * 100, 2) if (st and pr) else None,
            "risk_amount": r(qty * (pr - st), 2) if (a["action"] == "BUY" and qty and st and pr and st < pr) else None,
            "results_on": a.get("results_on"), "results_in_days": days_until(a.get("results_on")),
            "results_warning": bool(a.get("results_warning")), "provisional": bool(a.get("provisional")),
            "below_min_position": a["action"] == "BUY" and amount is not None and amount < AS_OF["min_position"],
            "you_hold_qty": int(you) if you else None,
        })
        _ = rules
    return rows


ORDERS = {s["key"]: order_rows(s) for s in strategies_raw}
ALL_ORDERS = [o for s in strategies_raw for o in ORDERS[s["key"]]]


def empty_reason(s: dict) -> str | None:
    if ORDERS[s["key"]]:
        return None
    sm = SUM_BY_KEY[s["key"]]
    held_n = len(s.get("positions", []))
    if sm["blocked_by_regime"]:
        return (f"Regime filter on: no new buys while Nifty is below its 200-DMA (holding {held_n} of "
                f"{s.get('max_positions')}).")
    if s.get("kind") == "rank" and s.get("next_rebalance"):
        d = date.fromisoformat(s["next_rebalance"])
        return f"No changes until the next review on {d.day} {d:%b}."
    return "No entry signals today."


def horizon_empty(h: str) -> str | None:
    ss = [s for s in strategies_raw if SUM_BY_KEY[s["key"]]["horizon"] == h and not SUM_BY_KEY[s["key"]]["comparison_only"]]
    if h == "intraday":
        return "Intraday strategies are research only: none survives costs, so they produce no orders."
    if any(ORDERS[s["key"]] for s in ss):
        return None
    if not ss:
        return "No active strategies in this horizon."
    if all(SUM_BY_KEY[s["key"]]["blocked_by_regime"] or s.get("kind") == "rank" for s in ss) and not REGIME_UP:
        return "Regime filter on: no new buys while Nifty is below its 200-DMA."
    return "No entry signals today."


# ------------------------------------------------------------------ market snapshot / tiles / breadth
uni_syms = [s for s in universe.symbol if s in close.columns and s not in etfs]
closes = close[uni_syms]
n50 = close["NIFTY50"] if "NIFTY50" in close else pd.Series(dtype=float)
n50_sma200 = n50.rolling(200, min_periods=180).mean()
last_sma = r(n50_sma200.dropna().iloc[-1], 2) if n50_sma200.notna().any() else None
nifty = MARKET.get("nifty")
n500f = FACTORS.get("Nifty 500", {})
SNAP = {
    "label": MARKET.get("label", "Mixed"), "level": MARKET.get("level", "neutral"), "advice": MARKET.get("advice", ""),
    "regime_up": REGIME_UP, "nifty": nifty, "nifty_change_pct": MARKET.get("nifty_change_pct"),
    "nifty_sma200": last_sma, "nifty_vs_sma200_pct": r((nifty / last_sma - 1) * 100, 2) if (nifty and last_sma) else None,
    "nifty500": n500f.get("last"), "nifty500_change_pct": n500f.get("chg_1d"),
    "vix": MARKET.get("vix"), "vix_change_pct": MARKET.get("vix_change_pct"), "high_vix": (MARKET.get("vix") or 0) >= 20,
    "breadth_50": MARKET.get("breadth_50"), "advances": MARKET.get("advances", 0), "declines": MARKET.get("declines", 0),
}
TICKER = {k: SNAP[k] for k in ("nifty", "nifty_change_pct", "nifty500", "nifty500_change_pct", "vix", "vix_change_pct",
                               "advances", "declines", "label")}


def tile(name, col):
    if idx_hist is None or col not in idx_hist:
        return None
    s = idx_hist[col].dropna()
    return {"name": name, "last": r(s.iloc[-1], 2), "chg_1d_pct": r((s.iloc[-1] / s.iloc[-2] - 1) * 100, 2),
            "spark": [r(x, 2) for x in s.iloc[-63:]], "href": "/market/factors"}


TILES = [t for t in (tile("Nifty 50", "Nifty 50"), tile("Nifty 500", "Nifty 500"), tile("India VIX", "India VIX"),
                     tile("Nifty200 Momentum 30", "Nifty200 Momentum 30")) if t]

sma50 = closes.rolling(50, min_periods=50).mean()
above = (closes > sma50).where(sma50.notna())
breadth = (above.sum(axis=1) / above.notna().sum(axis=1).replace(0, np.nan) * 100)
chg = closes.pct_change(fill_method=None)
ad = ((chg > 0).sum(axis=1) - (chg < 0).sum(axis=1)).cumsum()
bt = close.index[close.index >= pd.Timestamp("2019-01-01")]
BREADTH = {
    "source_date": close.index[-1].date().isoformat(), "t": [d.date().isoformat() for d in bt],
    "breadth_50": [r(x, 1) for x in breadth.reindex(bt)], "nifty": [r(x, 2) for x in n50.reindex(bt)],
    "nifty_sma200": [r(x, 2) for x in n50_sma200.reindex(bt)],
    "nifty500": [r(x, 2) for x in close["NIFTY500"].reindex(bt)] if "NIFTY500" in close else [None] * len(bt),
    "vix": [r(x, 2) for x in close["INDIAVIX"].reindex(bt)] if "INDIAVIX" in close else [None] * len(bt),
    "ad_line": [r(x, 0) for x in ad.reindex(bt)],
}

# ------------------------------------------------------------------ movers, results
def mover(m):
    return {k: m.get(k) for k in ("symbol", "company", "industry", "price", "change_pct", "vol_ratio")}


MOVERS = {k: [mover(m) for m in latest.get(k, [])] for k in ("gainers", "losers", "volume_spikes")}
RANKED = {}
for s in strategies_raw:
    if s["key"] == "momentum":
        for row in s.get("ranking", []):
            RANKED[row["symbol"]] = row["rank"]
ORDER_SYMS: dict[str, list[str]] = {}
for o in ALL_ORDERS:
    ORDER_SYMS.setdefault(o["symbol"], []).append(o["strategy_key"])

EVENTS = []
for e in events_raw:
    d = nse_date(e.get("date"))
    if not d or "result" not in (e.get("purpose") or "").lower() or e.get("symbol") not in uni_info:
        continue
    du = days_until(d)
    if du is None or du < 0:
        continue
    sym = e["symbol"]
    EVENTS.append({"symbol": sym, "company": uni_info[sym][0], "industry": uni_info[sym][1], "date": d, "days_until": du,
                   "purpose": e.get("purpose") or "", "you_hold": sym in held, "in_models": MODEL_SYMS.get(sym, []),
                   "in_orders": ORDER_SYMS.get(sym, []), "momentum_rank": RANKED.get(sym)})
EVENTS.sort(key=lambda x: (x["date"], x["symbol"]))
relevant = lambda e: e["you_hold"] or e["in_models"] or e["in_orders"] or e["momentum_rank"] is not None  # noqa: E731
RESULTS_SOON = [e for e in EVENTS if e["days_until"] <= 7 and relevant(e)]

# ------------------------------------------------------------------ alerts + changes
ALERTS = []


def alert(sev, cat, title, detail=None, symbol=None, key=None, href=None, rule="x"):
    ALERTS.append({"id": f"{cat}:{symbol or ''}:{rule}", "severity": sev, "category": cat, "title": title, "detail": detail,
                   "symbol": symbol, "strategy_key": key, "href": href})


for h in latest.get("holdings", []):
    sev = {"danger": "danger", "watch": "warn", "good": "good", "unknown": "warn", "ok": "info"}.get(h.get("level"), "info")
    for i, a in enumerate(h.get("alerts", [])):
        alert(sev, "holding", f"{h['symbol']}: {a}", None, h["symbol"], None, "/portfolio", f"h{i}")
for o in ALL_ORDERS:
    if o["results_warning"] and not o["comparison_only"]:
        alert("warn", "order", f"{o['symbol']} reports {'today' if o['results_in_days'] == 0 else 'in %s days' % o['results_in_days']}; consider waiting",
              f"{o['action']} order from {o['strategy_name']}", o["symbol"], o["strategy_key"], "/signals", "results")
watch_syms = set(held) | set(MODEL_SYMS) | set(ORDER_SYMS) | {s for s, rk in RANKED.items() if rk <= 10}
for e in EVENTS:
    if e["days_until"] <= (cfg.get("results") or {}).get("warn_days", 7) and e["symbol"] in watch_syms and e["days_until"] <= 1:
        why = ("you hold it" if e["you_hold"] else f"#{e['momentum_rank']} momentum" if e["momentum_rank"] else
               "model holding" if e["in_models"] else "order")
        alert("warn", "results", f"{e['symbol']} ({why}) reports {'today' if e['days_until'] == 0 else 'tomorrow'}",
              "Quarterly results: expect a big move either way.", e["symbol"], None, f"/chart/{e['symbol']}", "soon")
if CLOCK["session"] in ("open", "pre_open"):
    alert("warn", "login", "Fyers not logged in: Yahoo prices (~15 min delayed)", latest.get("fyers_note"), None, None,
          "/settings/fyers", "today")
if AS_OF["stale"]:
    alert("warn", "scan", f"Prices are from {AS_OF['data_date']}: run a scan", None, None, None, "/settings/scan", "stale")
if latest.get("stale_symbols"):
    ss = latest["stale_symbols"]
    alert("info", "data", f"{len(ss)} symbols have no fresh price ({', '.join(ss[:3])}{' …' if len(ss) > 3 else ''})",
          None, None, None, "/settings/data", "stale")
if latest.get("errors"):
    alert("warn", "data", f"{len(latest['errors'])} data errors in the last scan", None, None, None, "/settings/data", "errors")
if SNAP["high_vix"]:
    alert("warn", "market", f"India VIX {SNAP['vix']}: high volatility", None, None, None, "/market/breadth", "vix")
if AS_OF["backtest_universe"] == "current_list":
    alert("info", "bias", "Backtests use today's stock list (survivorship bias)",
          "Stocks that fell out of the index are missing, so every backtest looks better than reality. Judge by edge vs the average stock.",
          None, None, "/strategies", "list")
ORDER_SEV = {"danger": 0, "warn": 1, "info": 2, "good": 3}
ALERTS.sort(key=lambda a: ORDER_SEV[a["severity"]])


def changes() -> dict:
    prev = None
    for p in sorted(RESULTS.glob("scan_*.json"), reverse=True):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if d.get("data_date") and d["data_date"] < latest["data_date"]:
            prev = d
            break
    if prev is None:
        return {"since_scan_id": None, "since_data_date": None, "items": []}
    items = []
    pmap = {s["key"]: s for s in prev.get("strategies", [])}
    for s in strategies_raw:
        ps = pmap.get(s["key"])
        if ps and ps.get("status") and ps["status"] != s["status"]:
            items.append({"kind": "status", "text": f"{s['name']}: {ps['status'].replace('-', ' ')} → {s['status'].replace('-', ' ')}",
                          "strategy_key": s["key"], "symbol": None})
    pm = prev.get("market") or {}
    if "regime_up" in pm and pm["regime_up"] != REGIME_UP:
        items.append({"kind": "regime", "text": f"Regime flipped to {'up' if REGIME_UP else 'down'} ({SNAP['label']})",
                      "strategy_key": None, "symbol": None})
    for s in strategies_raw:
        ps = pmap.get(s["key"])
        if not ps:
            continue
        old = {(a["action"], a["symbol"]) for a in ps.get("actions", [])}
        for a in s.get("actions", []):
            if (a["action"], a["symbol"]) not in old:
                items.append({"kind": "new_order", "text": f"New: {a['action']} {a['symbol']} ({s['name']})",
                              "strategy_key": s["key"], "symbol": a["symbol"]})
        if "positions" in ps:
            op = {p["symbol"] for p in ps.get("positions", [])}
            np_ = {p["symbol"] for p in s.get("positions", [])}
            for sym in sorted(np_ - op):
                items.append({"kind": "position_opened", "text": f"{s['name']} bought {sym}", "strategy_key": s["key"], "symbol": sym})
            for sym in sorted(op - np_):
                items.append({"kind": "position_closed", "text": f"{s['name']} sold {sym}", "strategy_key": s["key"], "symbol": sym})
    return {"since_scan_id": prev.get("generated_at"), "since_data_date": prev.get("data_date"), "items": items}


# ------------------------------------------------------------------ paper
PAPER = {"available": False, "journal": None, "survivorship_haircut_pct": 8, "min_days_to_judge": 21, "strategies": []}
PAPER_DETAIL = {}
try:
    from scanner.paper import MIN_DAYS_TO_JUDGE, paper_report  # type: ignore
    rep = paper_report(frames)
    PAPER["survivorship_haircut_pct"] = rep.get("survivorship_haircut_pct", 8)
    PAPER["min_days_to_judge"] = MIN_DAYS_TO_JUDGE
    for key, v in rep.get("strategies", {}).items():
        sm = dict(v.get("summary") or {})
        sm["key"] = key
        sm.setdefault("kind", v.get("kind"))
        sm.setdefault("comparison", None)
        PAPER["strategies"].append(sm)

        def cols(pairs):
            return {d: val for d, val in (pairs or [])}
        p_, a_, b_ = cols(v.get("equity")), cols(v.get("nifty50")), cols(v.get("nifty500"))
        t = sorted(set(p_) | set(a_) | set(b_))
        PAPER_DETAIL[key] = {
            "summary": sm, "capital": v.get("capital"), "cash": v.get("cash"),
            "equity": {"t": t, "series": [
                {"id": "paper", "label": "Paper", "role": "paper", "v": [p_.get(d) for d in t]},
                {"id": "nifty50", "label": "Nifty 50", "role": "benchmark", "v": [a_.get(d) for d in t]},
                {"id": "nifty500", "label": "Nifty 500", "role": "benchmark", "v": [b_.get(d) for d in t]}]},
            "open": v.get("open", []), "trades": v.get("trades", []), "pending": v.get("pending", []),
            "trade_stats": v.get("trade_stats") or {k: None for k in TRADE_KEYS}, "expect": v.get("expect") or {},
            "journal_days": v.get("journal_days", 0), "last_journal": v.get("last_journal"),
        }
    if PAPER["strategies"]:
        PAPER["available"] = True
        jd = max((d["journal_days"] for d in PAPER_DETAIL.values()), default=0)
        first = min((d["summary"].get("start") for d in PAPER_DETAIL.values() if d["summary"].get("start")), default=None)
        last = max((d["last_journal"] for d in PAPER_DETAIL.values() if d["last_journal"]), default=None)
        PAPER["journal"] = {"days": jd, "first": first, "last": last}
    print(f"paper: {len(PAPER['strategies'])} strategies")
except Exception as exc:
    print("paper_report unavailable:", exc)
for sm in PAPER["strategies"]:
    if sm["key"] in SUM_BY_KEY:
        SUM_BY_KEY[sm["key"]]["paper"] = {"return_pct": sm.get("return_pct"), "days": sm.get("days", 0), "level": sm.get("level", "neutral")}
        if sm.get("level") == "bad":
            alert("warn", "paper", f"{sm.get('name')}: paper results behind the backtest", sm.get("verdict"), None, sm["key"],
                  f"/paper/{sm['key']}", "behind")
ALERTS.sort(key=lambda a: ORDER_SEV[a["severity"]])

# ------------------------------------------------------------------ status
def fyers_status() -> dict:
    env = {}
    p = ROOT / ".env"
    if p.exists():
        for ln in p.read_text(encoding="utf-8").splitlines():
            if "=" in ln and not ln.lstrip().startswith("#"):
                k, v = ln.split("=", 1)
                env[k.strip()] = v.strip().strip('"')
    cid = env.get("FYERS_CLIENT_ID", "")
    tok = DATA / "fyers_token.json"
    created = None
    if tok.exists():
        try:
            created = json.loads(tok.read_text(encoding="utf-8")).get("created")
        except Exception:
            created = None
    return {
        "configured": bool(cid and env.get("FYERS_SECRET_KEY")),
        "client_id_masked": (cid[:4] + "****" + cid[-4:]) if len(cid) > 8 else None,
        "plan": cfg.get("fyers_plan", "standard"), "data_source": cfg.get("data_source", "auto"),
        "token_present": tok.exists(), "token_created": created,
        "logged_in_today": bool(created and str(created)[:10] == TODAY.isoformat()),
        "verified": None, "verified_at": None, "user_name": None,
        "redirect_uri": env.get("FYERS_REDIRECT_URI") or "http://127.0.0.1:8000/", "login_modes": ["paste", "window"],
        "note": latest.get("fyers_note") or "",
    }


st = {}
try:
    st = json.loads((RESULTS / "status.json").read_text(encoding="utf-8"))
except Exception:
    pass
SCAN = {
    "state": st.get("state", "idle"), "running": False,
    "progress_pct": r((st.get("progress") or 0) * 100, 1) if st.get("progress") is not None else None,
    "message": st.get("message"),
    "started_at": datetime.fromtimestamp(st["started"], IST).isoformat(timespec="seconds") if st.get("started") else None,
    "by": None, "pid": None, "update": None, "exit_code": None,
}
STATUS = {
    "server_version": "mock", "latest": AS_OF, "scan": SCAN, "fyers": fyers_status(), "clock": CLOCK,
    "features": {"paper": PAPER["available"], "pit": False, "intraday": (RESULTS / "intraday.json").exists(),
                 "trades_artifact": False, "screener_artifact": False, "rejected_tested": False, "config_edit": False},
    "ticker": TICKER,
    "config_changed_since_scan": (ROOT / "config.yaml").stat().st_mtime > datetime.fromisoformat(latest["generated_at"]).timestamp(),
}

# ------------------------------------------------------------------ strategies list / detail
full0 = (strategies_raw[0]["metrics"]["full"] if strategies_raw else {})
ew0, n5_0, b0 = perf(full0.get("ew_benchmark")), perf(full0.get("n500_benchmark")), perf(full0.get("benchmark"))
counts = {"longterm": 0, "swing": 0, "intraday": 0}
for sm in SUMMARIES:
    counts[sm["horizon"]] += 1
intra = json.loads((RESULTS / "intraday.json").read_text(encoding="utf-8")) if (RESULTS / "intraday.json").exists() else None
counts["intraday"] = len(intra.get("strategies", [])) if intra else 0

rejected_catalogue = []
for k, reason in REJECTED_REASONS.items():
    o = _all.get(k)
    rejected_catalogue.append({"key": k, "name": getattr(o, "name", k), "horizon": getattr(o, "horizon", "swing"),
                               "evidence": getattr(o, "evidence", "") or "EXPERIMENTAL", "result_text": reason, "source": "catalogue"})
for cid, name, ev, text in (("S12", "52-week-low mean reversion", "WEAK", "Evidence against it; catalogue verdict SKIP-NO-EVIDENCE."),):
    rejected_catalogue.append({"key": f"catalogue_{cid.lower()}", "name": name, "horizon": "swing", "evidence": ev,
                               "result_text": text, "source": "catalogue"})

STRAT_LIST = {
    "as_of": AS_OF, "period": {"start": full0.get("start"), "end": full0.get("end")},
    "benchmarks": {"nifty50": b0, "nifty500": n5_0, "average_stock": ew0,
                   "survivorship_gap_pct": r(ew0["cagr_pct"] - n5_0["cagr_pct"], 2) if (ew0 and n5_0) else None},
    "counts": counts, "strategies": SUMMARIES, "rejected": [], "rejected_catalogue": rejected_catalogue,
}


def yearly_rows(s: dict) -> list:
    out = []
    years = sorted(int(y) for y in (s.get("yearly") or {}))
    cv = curves
    for y in years:
        seg = cv[cv.index.year == y]
        prev = cv[cv.index.year < y]

        def yr(col):
            if col not in cv or seg[col].dropna().empty:
                return None
            end = seg[col].dropna().iloc[-1]
            startv = prev[col].dropna().iloc[-1] if not prev[col].dropna().empty else seg[col].dropna().iloc[0]
            return r((end / startv - 1) * 100, 1)
        partial = y == years[0] or y == years[-1]
        out.append({"year": y, "partial": partial, "strategy": s["yearly"].get(str(y), s["yearly"].get(y)),
                    "nifty500": yr("NIFTY 500"), "average_stock": yr("Average stock"), "nifty50": yr("NIFTY 50")})
    return out


def monthly_rows(key: str, yearly: dict | None = None) -> list:
    if key not in curves:
        return []
    me = curves[key].dropna().resample("ME").last()
    rets = me.pct_change() * 100
    first_month = curves[key].dropna()
    if not first_month.empty:
        rets.iloc[0] = (me.iloc[0] / first_month.iloc[0] - 1) * 100
    out = []
    for y in sorted(set(rets.index.year)):
        months = [None] * 12
        for d, v in rets[rets.index.year == y].items():
            months[d.month - 1] = r(v, 1)
        seg = curves[key].dropna()
        prev = seg[seg.index.year < y]
        cur = seg[seg.index.year == y]
        tot = r((cur.iloc[-1] / (prev.iloc[-1] if not prev.empty else cur.iloc[0]) - 1) * 100, 1) if not cur.empty else None
        if yearly and (str(y) in yearly or y in yearly):   # same number as the yearly heatmap (latest.yearly)
            tot = yearly.get(str(y), yearly.get(y))
        out.append({"year": y, "months": months, "total": tot})
    return out


def detail(s: dict) -> dict:
    m = s["metrics"]
    sm = SUM_BY_KEY[s["key"]]
    positions = []
    for p in s.get("positions", []):
        positions.append({"symbol": p["symbol"], "company": p.get("company"), "industry": p.get("industry"),
                          "entry_date": p["entry_date"], "entry_price": p["entry_price"], "last_price": p.get("last_price"),
                          "ret_pct": p.get("ret_pct"), "stop": p.get("stop"), "days": p.get("days", 0),
                          "weight_pct": weight_pct(s, p), "results_on": p.get("results_on") or results_on.get(p["symbol"]),
                          "results_in_days": days_until(p.get("results_on") or results_on.get(p["symbol"]))})
    ranking = [{"rank": x["rank"], "symbol": x["symbol"], "company": x.get("company"), "industry": x.get("industry"),
                "score": x.get("score"), "price": x.get("price"), "ret_6m_pct": x.get("ret_6m"), "ret_12m_pct": x.get("ret_12m"),
                "rs": x.get("rs"), "in_portfolio": bool(x.get("in_portfolio")), "results_on": x.get("results_on"),
                "results_in_days": days_until(x.get("results_on"))} for x in s.get("ranking", [])]
    trades = [{"symbol": t["symbol"], "entry_date": t["entry"], "exit_date": t["exit"], "entry_price": None,
               "exit_price": None, "ret_pct": t.get("ret_pct"), "days": t.get("days", 0), "reason": t.get("reason", "")}
              for t in s.get("recent_trades", [])]
    regime_note = None
    if sm["blocked_by_regime"]:
        regime_note = (f"No new buys: Nifty is below its 200-DMA (regime filter on). Holding {len(positions)} of "
                       f"{s.get('max_positions')}.")
    psum = next((p for p in PAPER["strategies"] if p["key"] == s["key"]), None)
    return {
        "as_of": AS_OF, "strategy": sm,
        "metrics": {"full": full_metrics(m.get("full", {})), "m12": window(m.get("12m")), "m6": window(m.get("6m")),
                    "m3": window(m.get("3m"))},
        "yearly": yearly_rows(s), "monthly": monthly_rows(s["key"], s.get("yearly")), "rules": RULES[s["key"]], "evidence": evidence_for(s),
        "positions": positions, "orders": ORDERS[s["key"]], "ranking": ranking, "recent_trades": trades,
        "trades_available": False, "regime_note": regime_note, "paper": psum,
    }


# ------------------------------------------------------------------ curves (raw, columnar; the mock slices + rebases)
fac_cols = {}
for s in strategies_raw:
    name = s.get("benchmark") or (s["metrics"]["full"].get("factor_benchmark_name"))
    if name and idx_hist is not None and name in idx_hist and name not in fac_cols:
        fac_cols[name] = idx_hist[name]
cv = curves.copy()
for name, ser in fac_cols.items():
    al = ser.reindex(cv.index).ffill()
    first = al.dropna().iloc[0] if al.notna().any() else None
    cv[f"factor:{name}"] = al / first if first else al
CURVES = {"t": [d.date().isoformat() for d in cv.index], "columns": {c: [r(x, 5) for x in cv[c]] for c in cv.columns},
          "capital": CAPITAL}

# ------------------------------------------------------------------ screener (computed from the store for the mock)
def screener_rows() -> list:
    c, h, l_, v = close[uni_syms], high[uni_syms], low[uni_syms], vol[uni_syms]
    lastc = c.ffill().iloc[-1]
    ret = lambda n: (lastc / c.shift(n).iloc[-1] - 1) * 100  # noqa: E731
    lr = np.log(c / c.shift(1))
    sig = lr.iloc[-252:].std() * np.sqrt(252)
    r6, r12 = ret(126), ret(252)
    z = lambda x: ((x - x.mean()) / x.std()).clip(-3, 3)  # noqa: E731
    wz = 0.5 * z(r6 / 100 / sig) + 0.5 * z(r12 / 100 / sig)
    score = wz.where(wz < 0, 1 + wz)
    score = score.where(wz >= 0, 1 / (1 - wz))
    turnover = (c * v).iloc[-20:].mean() / 1e7
    tradable = (lastc >= (cfg.get("filters") or {}).get("min_price", 50)) & (turnover >= (cfg.get("filters") or {}).get("min_turnover_cr", 5))
    rs_raw = 0.4 * ret(63) + 0.2 * ret(126) + 0.2 * ret(189) + 0.2 * r12
    rs = (rs_raw.rank(pct=True) * 98 + 1).round(0)
    sma50_ = c.rolling(50).mean().iloc[-1]
    sma200_ = c.rolling(200, min_periods=180).mean().iloc[-1]
    hi52 = h.iloc[-252:].max()
    d = c.diff()
    ag = d.clip(lower=0).ewm(alpha=1 / 14, adjust=False, min_periods=14).mean().iloc[-1]
    al_ = (-d.clip(upper=0)).ewm(alpha=1 / 14, adjust=False, min_periods=14).mean().iloc[-1]
    rsi = 100 - 100 / (1 + ag / al_.replace(0, np.nan))
    vr = v.iloc[-1] / v.iloc[-21:-1].mean()
    pc = c.shift(1)
    tr = pd.concat([(h - l_).stack(), (h - pc).abs().stack(), (l_ - pc).abs().stack()], axis=1).max(axis=1).unstack()
    atr = tr.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean().iloc[-1]
    dl = deliv[uni_syms].ffill().iloc[-1] if deliv is not None else pd.Series(index=uni_syms, dtype=float)
    mom_rank = score[tradable].rank(ascending=False, method="first")
    rows = []
    for sym in uni_syms:
        if not bool(tradable.get(sym, False)) or not np.isfinite(lastc.get(sym, np.nan)):
            continue
        rows.append({
            "symbol": sym, "company": uni_info[sym][0], "industry": uni_info[sym][1], "price": r(lastc[sym]),
            "change_pct": r((c[sym].iloc[-1] / c[sym].iloc[-2] - 1) * 100), "ret_1w_pct": r(ret(5)[sym]),
            "ret_1m_pct": r(ret(21)[sym]), "ret_3m_pct": r(ret(63)[sym]), "ret_6m_pct": r(r6[sym]), "ret_12m_pct": r(r12[sym]),
            "rs": r(rs[sym], 0), "momentum_score": r(score[sym], 3), "momentum_rank": int(mom_rank[sym]) if sym in mom_rank and np.isfinite(mom_rank[sym]) else None,
            "vol_ann_pct": r(sig[sym] * 100, 1), "pct_from_52w_high": r((lastc[sym] / hi52[sym] - 1) * 100),
            "above_sma50": bool(lastc[sym] > sma50_[sym]) if np.isfinite(sma50_[sym]) else None,
            "above_sma200": bool(lastc[sym] > sma200_[sym]) if np.isfinite(sma200_[sym]) else None,
            "sma50_above_sma200": bool(sma50_[sym] > sma200_[sym]) if np.isfinite(sma200_[sym]) else None,
            "rsi14": r(rsi[sym], 1), "vol_ratio": r(vr[sym], 2), "turnover_cr": r(turnover[sym], 1),
            "atr_pct": r(atr[sym] / lastc[sym] * 100, 2), "deliv_pct": r(dl.get(sym), 1),
            "results_on": results_on.get(sym), "in_models": MODEL_SYMS.get(sym, []), "you_hold": sym in held,
        })
    return rows


SCREENER = {"as_of": AS_OF, "source_date": close.index[-1].date().isoformat(), "preset": "all", "rows": screener_rows()}
SCREENER["total"] = len(SCREENER["rows"])
SCR_BY = {x["symbol"]: x for x in SCREENER["rows"]}
print(f"screener rows {SCREENER['total']}")

SPARK = {"source_date": SCREENER["source_date"], "days": 60,
         "series": {s: [r(x) for x in close[s].dropna().iloc[-60:]] for s in uni_syms + [e for e in etfs if e in close]}}

# ------------------------------------------------------------------ symbols
SYMBOLS = []
seen = set()
for sym in latest.get("symbols", []):
    info = uni_info.get(sym, (None, None))
    SYMBOLS.append({"symbol": sym, "company": info[0], "industry": info[1], "kind": "etf" if sym in etfs else "stock",
                    "in_universe": sym in uni_info})
    seen.add(sym)
for sym in etfs:
    if sym not in seen:
        SYMBOLS.append({"symbol": sym, "company": sym, "industry": "ETF", "kind": "etf", "in_universe": False})
for sym, nm in (("NIFTY50", "Nifty 50 index"), ("NIFTY500", "Nifty 500 index"), ("INDIAVIX", "India VIX")):
    SYMBOLS.append({"symbol": sym, "company": nm, "industry": "Index", "kind": "index", "in_universe": False})

# ------------------------------------------------------------------ charts (bars + markers for a subset of symbols)
chart_syms = ["NIFTY50", "NIFTY500", "INDIAVIX"] + [e for e in etfs if e in close]
for s in strategies_raw:
    chart_syms += [p["symbol"] for p in s.get("positions", [])][:6] + [a["symbol"] for a in s.get("actions", [])]
    chart_syms += [t["symbol"] for t in s.get("recent_trades", [])][:3]
chart_syms += [x["symbol"] for x in latest.get("strategies", [{}])[0].get("ranking", [])[:10]]
chart_syms += [m["symbol"] for m in latest.get("gainers", [])[:5] + latest.get("losers", [])[:5]]
chart_syms = [s for s in dict.fromkeys(chart_syms) if s in close.columns][:70]
CA = store.meta.get("corporate_actions", [])
res_hist: dict[str, list[str]] = {}
for p in sorted(NSE.glob("results_*.json")):
    try:
        for e in json.loads(p.read_text(encoding="utf-8")):
            if "result" in (e.get("purpose") or "").lower():
                d = nse_date(e.get("date"))
                if d:
                    res_hist.setdefault(e["symbol"], []).append(d)
    except Exception:
        pass
NAME = {s["key"]: s["name"] for s in strategies_raw}
ABBR = {"momentum": "MOM", "earnings_gap": "PEAD", "low_vol": "LVOL", "golden_cross": "GX", "index_trend": "TREND",
        "dual_momentum": "DUAL", "sector_rotation": "SECT", "vcp_breakout": "VCP", "trend_breakout": "TBO",
        "donchian": "DON", "bb_squeeze": "BB", "pullback_leaders": "PULL", "nr7_breakout": "NR7"}


def chart(sym: str) -> dict:
    df = pd.DataFrame({"o": opn[sym], "h": high[sym], "l": low[sym], "c": close[sym], "v": vol[sym]}).dropna(subset=["c"])
    df["o"] = df["o"].fillna(df["c"])
    df["h"] = df[["h", "o", "c"]].max(axis=1)
    df["l"] = df[["l", "o", "c"]].min(axis=1)
    kind = "index" if sym in ("NIFTY50", "NIFTY500", "INDIAVIX") else "etf" if sym in etfs else "stock"
    if kind == "index":
        df["v"] = 0
    markers, lines, avail = [], [], {}
    for s in strategies_raw:
        k = s["key"]
        for t in s.get("recent_trades", []):
            if t["symbol"] != sym:
                continue
            avail[k] = avail.get(k, 0) + 1
            markers.append({"t": t["entry"], "position": "belowBar", "shape": "arrowUp", "kind": "entry", "tone": "profit",
                            "text": f"B · {ABBR.get(k, k[:4].upper())}", "detail": f"{NAME[k]} bought", "strategy_key": k})
            rp = t.get("ret_pct") or 0
            markers.append({"t": t["exit"], "position": "aboveBar", "shape": "arrowDown", "kind": "exit",
                            "tone": "profit" if rp >= 0 else "loss", "text": f"S {'+' if rp >= 0 else '−'}{abs(rp):.1f}%",
                            "detail": f"{NAME[k]} sold: {t.get('reason')}", "strategy_key": k})
        for p in s.get("positions", []):
            if p["symbol"] != sym:
                continue
            avail[k] = avail.get(k, 0) + 1
            markers.append({"t": p["entry_date"], "position": "belowBar", "shape": "circle", "kind": "open_entry",
                            "tone": "profit", "text": f"B · {ABBR.get(k, k[:4].upper())} (open)", "detail": f"{NAME[k]} holds it",
                            "strategy_key": k})
            lines.append({"price": p["entry_price"], "label": f"{ABBR.get(k, k)} entry", "strategy_key": k, "kind": "model_entry"})
            if p.get("stop"):
                lines.append({"price": p["stop"], "label": f"{ABBR.get(k, k)} stop", "strategy_key": k, "kind": "model_stop"})
        for a in s.get("actions", []):
            if a["symbol"] != sym:
                continue
            last_t = df.index[-1].date().isoformat()
            markers.append({"t": last_t, "position": "belowBar" if a["action"] == "BUY" else "aboveBar",
                            "shape": "arrowUp" if a["action"] == "BUY" else "arrowDown", "kind": "pending_order", "tone": "warn",
                            "text": f"{a['action']} next open · {ABBR.get(k, k)}", "detail": a.get("reason"), "strategy_key": k})
            if a.get("stop"):
                lines.append({"price": a["stop"], "label": f"order stop ({ABBR.get(k, k)})", "strategy_key": k, "kind": "order_stop"})
    first_t = df.index[0].date().isoformat()
    for ca in CA:
        if ca["symbol"] == sym and ca["date"] >= first_t:
            markers.append({"t": ca["date"], "position": "aboveBar", "shape": "square", "kind": "corporate_action", "tone": "neutral",
                            "text": f"{ca['reason'].split(' ')[0].title()} ×{ca['factor']:.2g}", "detail": ca["reason"], "strategy_key": None})
    tail = df.iloc[-252:]
    if len(tail) > 120:
        lines.append({"price": r(tail["h"].max()), "label": "52w high", "strategy_key": None, "kind": "high_52w"})
        lines.append({"price": r(tail["l"].min()), "label": "52w low", "strategy_key": None, "kind": "low_52w"})
    info = uni_info.get(sym, (None, None))
    names = {"NIFTY50": "Nifty 50 index", "NIFTY500": "Nifty 500 index", "INDIAVIX": "India VIX"}
    return {
        "symbol": sym, "company": names.get(sym, info[0] or sym), "industry": "Index" if kind == "index" else info[1] or ("ETF" if kind == "etf" else None),
        "kind": kind, "adjusted": True, "source_date": df.index[-1].date().isoformat(),
        "bars": {"t": [d.date().isoformat() for d in df.index], "o": [r(x) for x in df["o"]], "h": [r(x) for x in df["h"]],
                 "l": [r(x) for x in df["l"]], "c": [r(x) for x in df["c"]], "v": [int(x) if np.isfinite(x) else 0 for x in df["v"]]},
        "markers": markers, "price_lines": lines,
        "strategies_available": [{"key": k, "name": NAME[k], "trades": n} for k, n in avail.items()],
        "results_on": results_on.get(sym), "past_results": sorted(set(res_hist.get(sym, []))),
    }


def stock(sym: str) -> dict:
    sc = SCR_BY.get(sym, {})
    c = close[sym].dropna() if sym in close else pd.Series(dtype=float)
    info = uni_info.get(sym, (None, None))
    roles = []
    for s in strategies_raw:
        if any(p["symbol"] == sym for p in s.get("positions", [])):
            roles.append({"key": s["key"], "name": s["name"], "status": s["status"], "role": "holding", "detail": "Model portfolio holds it"})
        for a in s.get("actions", []):
            if a["symbol"] == sym:
                roles.append({"key": s["key"], "name": s["name"], "status": s["status"], "role": "order", "detail": f"{a['action']} at the next open"})
        for row in s.get("ranking", []):
            if row["symbol"] == sym:
                roles.append({"key": s["key"], "name": s["name"], "status": s["status"], "role": "ranked", "detail": f"Ranked #{row['rank']}"})
    tail = c.iloc[-252:]
    return {
        "as_of": AS_OF, "symbol": sym, "company": info[0], "industry": info[1],
        "kind": "index" if sym in ("NIFTY50", "NIFTY500", "INDIAVIX") else "etf" if sym in etfs else "stock",
        "price": r(c.iloc[-1]) if len(c) else None, "change_pct": r((c.iloc[-1] / c.iloc[-2] - 1) * 100) if len(c) > 1 else None,
        "data_date": c.index[-1].date().isoformat() if len(c) else None,
        "high_52w": r(high[sym].iloc[-252:].max()) if sym in high else None, "low_52w": r(low[sym].iloc[-252:].min()) if sym in low else None,
        "pct_from_52w_high": sc.get("pct_from_52w_high"),
        "ret_1m_pct": sc.get("ret_1m_pct"), "ret_3m_pct": sc.get("ret_3m_pct"), "ret_6m_pct": sc.get("ret_6m_pct"),
        "ret_12m_pct": sc.get("ret_12m_pct"), "rs": sc.get("rs"), "momentum_rank": sc.get("momentum_rank"),
        "sma50": r(tail.iloc[-50:].mean()) if len(tail) >= 50 else None, "sma200": r(c.iloc[-200:].mean()) if len(c) >= 200 else None,
        "vol_ratio": sc.get("vol_ratio"), "turnover_cr": sc.get("turnover_cr"), "deliv_pct": sc.get("deliv_pct"),
        "results_on": results_on.get(sym), "strategies": roles, "your_holding": None,
        "corporate_actions": [{"date": ca["date"], "factor": ca["factor"], "reason": ca["reason"]} for ca in CA if ca["symbol"] == sym],
    }


# ------------------------------------------------------------------ market
def idx_row(x):
    return {k: x.get(k) for k in ("name", "last", "chg_1d", "ret_1m", "ret_3m", "ret_6m", "ret_1y", "cagr", "max_dd", "since",
                                  "above_50dma", "rank")}


def industries() -> list:
    out = []
    c = closes
    s50 = sma50.iloc[-1]
    lastc = c.iloc[-1]
    for ind, grp in universe[universe.symbol.isin(uni_syms)].groupby("industry"):
        syms = list(grp.symbol)
        sub = c[syms]
        ret = lambda n: r(((sub.iloc[-1] / sub.shift(n).iloc[-1] - 1) * 100).mean(), 2)  # noqa: E731
        d1 = sub.iloc[-1] / sub.iloc[-2] - 1
        r3 = (sub.iloc[-1] / sub.shift(63).iloc[-1] - 1) * 100
        ab = (lastc[syms] > s50[syms])
        out.append({"industry": ind, "members": len(syms), "advances": int((d1 > 0).sum()), "declines": int((d1 < 0).sum()),
                    "breadth_50": r(ab.mean() * 100, 1), "ret_1d_pct": ret(1), "ret_1w_pct": ret(5), "ret_1m_pct": ret(21),
                    "ret_3m_pct": ret(63), "ret_6m_pct": ret(126),
                    "leaders": [{"symbol": k, "ret_3m_pct": r(v, 1)} for k, v in r3.dropna().sort_values(ascending=False).iloc[:3].items()]})
    return sorted(out, key=lambda x: -(x["ret_3m_pct"] or -1e9))


# ------------------------------------------------------------------ data health / scans / log / config
def scans() -> list:
    out = []
    for p in sorted(RESULTS.glob("scan_*.json"), reverse=True)[:60]:
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        out.append({"scan_id": d.get("generated_at"), "file": p.name, "data_date": d.get("data_date"), "live": d.get("live"),
                    "elapsed_s": d.get("elapsed_s"), "strategies": len(d.get("strategies", []))})
    return out


SCANS = scans()
log_path = DATA / "logs" / "scanner.log"
log_lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-400:] if log_path.exists() else []
log_lines = [re.sub(r"(access_token=|auth_code=)\S+", r"\1***", ln) for ln in log_lines]
gen = DATA / "history" / "store" / store.version()
size_mb = sum(f.stat().st_size for f in gen.glob("*")) / 1e6 if gen.exists() else 0
journal = DATA / "journal.sqlite"
HEALTH = {
    "store": {"version": store.version(), "first_date": close.index[0].date().isoformat(), "last_date": close.index[-1].date().isoformat(),
              "symbols": int(close.shape[1]), "trading_days": int(close.shape[0]), "fields": list(frames.keys()), "size_mb": r(size_mb, 1)},
    "nse": {"status": latest.get("nse_status"), "complete_upto": latest.get("complete_upto")},
    "failed_symbols": store.meta.get("failed", {}), "stale_symbols": latest.get("stale_symbols", []), "errors": latest.get("errors", {}),
    "corporate_actions_recent": sorted(CA, key=lambda x: x["date"], reverse=True)[:20], "corporate_actions_total": len(CA),
    "index_history": {"last_date": idx_hist.index[-1].date().isoformat(), "columns": int(idx_hist.shape[1])} if idx_hist is not None else None,
    "results_calendar": {"note": latest.get("results_note"), "cached_on": events_cached_on},
    "universe": {"name": cfg.get("universe", "nifty500"), "note": latest.get("universe", ""), "size": int(len(universe))},
    "pit": {"built": (DATA / "history" / "pit").exists() and any((DATA / "history" / "pit").iterdir()),
            "note": "Point-in-time universe is built by the survivorship session; backtests still use today's list."},
    "journal": {"exists": journal.exists(), "days": PAPER["journal"]["days"] if PAPER["journal"] else None,
                "size_kb": r(journal.stat().st_size / 1024, 1) if journal.exists() else None},
    "logs": {"path": str(log_path), "size_kb": r(log_path.stat().st_size / 1024, 1) if log_path.exists() else 0,
             "last_error": next((ln for ln in reversed(log_lines) if " ERROR " in ln), None)},
    "scans": {"count": len(SCANS), "newest": SCANS[0]["scan_id"] if SCANS else None, "oldest": SCANS[-1]["scan_id"] if SCANS else None,
              "mixed_producers": len({s["strategies"] for s in SCANS}) > 1},
}
COSTS = {k: float(v) for k, v in (cfg.get("costs") or {}).items()}
CONFIG = {"values": {
    "account": {"capital": (cfg.get("account") or {}).get("capital", CAPITAL), "min_position": (cfg.get("account") or {}).get("min_position", 0)},
    "data_source": cfg.get("data_source", "auto"), "fyers_plan": cfg.get("fyers_plan", "standard"),
    "universe": cfg.get("universe", "nifty500"), "lookback_days": cfg.get("lookback_days", 3000),
    "filters": cfg.get("filters") or {}, "holdings_defaults": cfg.get("holdings_defaults") or {"stop_loss_pct": 8, "target_pct": 20},
    "results": cfg.get("results") or {"warn_days": 7}, "movers_count": cfg.get("movers_count", 15), "etfs": etfs,
    "costs": COSTS, "tax": cfg.get("tax") or {}, "allocations": cfg.get("allocations") or {},
    "strategies": {k: {"enabled": bool((v or {}).get("enabled", True)), "params": {pk: pv for pk, pv in (v or {}).items() if pk != "enabled"}}
                   for k, v in (cfg.get("strategies") or {}).items()},
    "telegram": {"top_n": (cfg.get("telegram") or {}).get("top_n", 10), "configured": False},
}, "file_mtime": datetime.fromtimestamp((ROOT / "config.yaml").stat().st_mtime, IST).isoformat(timespec="seconds"),
    "needs_rescan": STATUS["config_changed_since_scan"]}

# ------------------------------------------------------------------ holdings
inputs = []
for row in holdings_df.to_dict("records"):
    if not str(row.get("symbol") or "").strip():
        continue
    inputs.append({"symbol": str(row["symbol"]).upper(), "qty": row.get("qty"), "buy_price": row.get("buy_price"),
                   "buy_date": row.get("buy_date") if isinstance(row.get("buy_date"), str) else None,
                   "stop_loss_pct": row.get("stop_loss_pct"), "target_pct": row.get("target_pct")})
HROWS = []
for h in latest.get("holdings", []):
    keys = ("symbol", "company", "industry", "qty", "buy_price", "price", "change_pct", "pnl_pct", "pnl_amount", "stop_price",
            "target_price", "momentum_rank", "rs", "results_on", "level", "alerts")
    row = {k: h.get(k) for k in keys}
    row["alerts"] = row["alerts"] or []
    row["industry"] = row["industry"] or uni_info.get(h["symbol"], (None, None))[1]
    row["value"] = r(h["qty"] * h["price"]) if h.get("qty") and h.get("price") else None
    row["day_pnl"] = r(row["value"] * h["change_pct"] / (100 + h["change_pct"])) if row["value"] and h.get("change_pct") is not None else None
    row["in_models"] = MODEL_SYMS.get(h["symbol"], [])
    HROWS.append(row)
tv = sum(x["value"] or 0 for x in HROWS)
for x in HROWS:
    x["weight_pct"] = r((x["value"] or 0) / tv * 100, 1) if tv else None
inv = sum((x["qty"] or 0) * (x["buy_price"] or 0) for x in HROWS)
HOLD = {"as_of": AS_OF, "rows": HROWS, "inputs": inputs,
        "health_stale": (ROOT / "holdings.csv").exists() and (ROOT / "holdings.csv").stat().st_mtime > datetime.fromisoformat(latest["generated_at"]).timestamp()
        or {i["symbol"] for i in inputs} != {h["symbol"] for h in HROWS},
        "totals": {"count": len(HROWS), "invested": r(inv) if HROWS else None, "value": r(tv) if HROWS else None,
                   "pnl": r(tv - inv) if HROWS else None, "pnl_pct": r((tv / inv - 1) * 100) if inv else None,
                   "day_pnl": r(sum(x["day_pnl"] or 0 for x in HROWS)) if HROWS else None,
                   "danger": sum(x["level"] == "danger" for x in HROWS), "watch": sum(x["level"] == "watch" for x in HROWS)},
        "by_industry": [], "defaults": CONFIG["values"]["holdings_defaults"]}
ind_w: dict[str, float] = {}
for x in HROWS:
    ind_w[x["industry"] or "Other"] = ind_w.get(x["industry"] or "Other", 0) + (x["weight_pct"] or 0)
HOLD["by_industry"] = [{"industry": k, "weight_pct": r(v, 1)} for k, v in sorted(ind_w.items(), key=lambda kv: -kv[1])]

# ------------------------------------------------------------------ intraday
def intraday() -> dict:
    if not intra:
        return {"available": False, "reason": "Intraday backtest not run yet", "generated_at": None, "elapsed_s": None, "data": None,
                "rules": {}, "sebi": {"source": "", "url": "", "points": []}, "costs": None, "strategies": []}
    out = []
    for s in intra.get("strategies", []):
        eq = s.get("equity") or []
        t = [e[0] for e in eq]
        out.append({"key": s["key"], "name": s["name"], "description": s.get("description", ""), "evidence": s.get("evidence") or "EXPERIMENTAL",
                    "horizon": "intraday", "status": s.get("status", "unknown"), "metrics": s.get("metrics", {}),
                    "equity": {"t": t, "series": [{"id": s["key"], "label": s["name"], "role": "strategy", "v": [e[1] for e in eq]}]},
                    "recent_trades": [{**x, "open_now": x.get("open_now")} for x in s.get("recent_trades", [])],
                    "today": s.get("today", [])})
    d = intra.get("data") or {}
    return {"available": True, "reason": None, "generated_at": intra.get("generated_at"), "elapsed_s": intra.get("elapsed_s"),
            "data": {"source": d.get("source"), "interval": d.get("interval", "5m"), "from": d.get("from"), "to": d.get("to"),
                     "sessions": d.get("sessions"), "symbols": d.get("symbols"), "note": d.get("note", "")},
            "rules": intra.get("rules", {}), "sebi": intra.get("sebi", {"source": "", "url": "", "points": []}),
            "costs": intra.get("costs"), "strategies": out}


# ------------------------------------------------------------------ write
OUT.mkdir(parents=True, exist_ok=True)
for old in OUT.rglob("*.json"):
    old.unlink()
write("status.json", STATUS)
write("overview.json", {
    "as_of": AS_OF, "market": SNAP, "index_tiles": TILES,
    "orders": [o for o in ALL_ORDERS if SUM_BY_KEY[o["strategy_key"]]["lifecycle"] == "active"],
    "empty_reasons": {h: horizon_empty(h) for h in ("longterm", "swing", "intraday")},
    "alerts": ALERTS, "changes": changes(), "strategy_pulse": [x for x in SUMMARIES if x["lifecycle"] == "active"][:6],
    "movers": {k: v[:5] for k, v in MOVERS.items()}, "results_soon": RESULTS_SOON, "paper": PAPER["strategies"],
})
write("breadth.json", BREADTH)
write("strategies.json", STRAT_LIST)
for s in strategies_raw:
    write(f"strategy/{s['key']}.json", detail(s))
write("curves.json", CURVES)
groups = []
for s in strategies_raw:
    sm = SUM_BY_KEY[s["key"]]
    rl = RULES[s["key"]]
    groups.append({"strategy": sm, "sizing": {"capital": CAPITAL, "per_position": s.get("per_position"), "max_positions": s.get("max_positions"),
                                              "sizing": rl["sizing"], "risk_pct": rl["risk_pct"]},
                   "orders": ORDERS[s["key"]], "empty_reason": empty_reason(s)})
groups.sort(key=lambda g: g["strategy"]["comparison_only"])
write("signals.json", {"as_of": AS_OF, "capital": CAPITAL, "min_position": AS_OF["min_position"], "allocations": [],
                       "allocation_source": "none", "allocation_warning": f"Each strategy is sized on your full capital ({inr(CAPITAL)}). Following more than one? Set allocations so they share it.",
                       "sized_like_scan": True, "regime": {"regime_up": REGIME_UP, "note": None if REGIME_UP else MARKET.get("advice")},
                       "groups": groups, "totals": {}})
write("screener.json", SCREENER)
write("sparklines.json", SPARK)
write("symbols.json", {"as_of": AS_OF, "symbols": SYMBOLS})
for sym in chart_syms:
    write(f"chart/{sym}.json", chart(sym))
write("stocks.json", {sym: stock(sym) for sym in list(SCR_BY) + [s for s in chart_syms if s not in SCR_BY]})
write("holdings.json", HOLD)
write("paper.json", PAPER)
for k, v in PAPER_DETAIL.items():
    write(f"paper/{k}.json", v)
write("market_movers.json", {"as_of": AS_OF, **MOVERS})
write("market_sectors.json", {"as_of": AS_OF, "nse_sectors": [idx_row(x) for x in (latest.get("indices") or {}).get("sectors", [])],
                              "industries": industries(), "industries_source_date": close.index[-1].date().isoformat()})
write("market_factors.json", {"as_of": AS_OF, "factors": [idx_row(x) for x in (latest.get("indices") or {}).get("factors", [])],
                              "note": "Real NSE indices from the daily NSE index file: no survivorship bias. Index funds or ETFs exist for most of them."})
write("market_results.json", {"cached_on": events_cached_on, "note": latest.get("results_note") or "", "events": EVENTS})
write("scan_history.json", {"scans": SCANS})
write("scan_log.json", {"path": str(log_path), "lines": log_lines})
write("data_health.json", HEALTH)
write("config.json", CONFIG)
write("intraday.json", intraday())
total = sum(p.stat().st_size for p in OUT.rglob("*.json")) / 1e6
print(f"wrote {len(list(OUT.rglob('*.json')))} files, {total:.1f} MB -> {OUT}")
