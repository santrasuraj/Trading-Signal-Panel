"""Trade coach (GET /api/coach, POST /api/coach/review): what your own trading does well and where it leaks money.

The numbers are computed here, from your own records only, and shown as they are:
  - practice: finished replays (data/replay_log.jsonl, services/replay_svc.py), the P&L recomputed with real charges;
  - real money: your FYERS fills (data/fills.jsonl, scanner/fills.py) matched into round trips first-in, first-out;
  - now: your holdings (holdings.csv) against their stops and targets as of the last scan.
Behaviour checks: stop discipline, holding losers longer than winners, the largest loss against the average win,
overtrading, the trade after a loss, longs against shorts, charges eaten, and the trend of recent trades.

The written review is Claude's (POST, one call, about Rs 5-15): it gets these numbers and nothing else - no prices, no
news - and is told to cite them, to say when the sample is too small to mean much, and never to tip stocks. The last
review is kept in data/results/coach.json and shown until your numbers change.
"""
from __future__ import annotations

import hashlib
import json
import threading
from statistics import mean

import anthropic

from scanner import fills

from . import ai_svc, data, holdings_svc, replay_svc
from ..errors import ApiException, log
from ..paths import P
from ..util import now_ist

MAX_TOKENS = 16000
ENOUGH_PRACTICE, ENOUGH_REAL = 30, 15
NOTE = ("Numbers from your own records only. The written review is Claude's reading of them: a coach, not a forecast "
        "and not investment advice.")

SYSTEM = """You are the trading coach inside Quant Desk, a personal tool for one retail trader in Indian stocks (NSE). \
Each request gives you a JSON summary of that trader's own record: practice sessions on past market data (replays, \
with real charges but no real money), real fills on their FYERS account matched into round trips, and the holdings \
they have now. You get nothing else: no prices, no news, no charts.

How to coach:
- Judge the process, not single outcomes: stops, position size, holding losers longer than winners, the largest loss \
against the average win, overtrading, the trade right after a loss, charges, and what the trend of recent trades shows.
- Every strength and every leak must quote the numbers behind it from the JSON (e.g. "41 of 60 losing trades had no \
stop; they lost Rs 1,240 on average against Rs 610 for stopped ones"). Never invent a number, a trade or a stock.
- Separate practice from real money and say which one a point comes from. Practice skill is a start, not proof.
- Sample size: if a group has fewer than about 30 trades, say the pattern is a first hint, not a finding. If there \
is almost nothing to review, say so plainly and suggest how to build a record (more replays, blind mode, stops).
- Never tip stocks, predict prices or tell them to buy or sell anything. Coach behaviour and rules only.
- Personal rules must be concrete and checkable, written as "If ..., then ..." (e.g. "If a trade has no stop, \
then don't enter it."), at most five, each tied to a leak you found.
- Simple English: short sentences, plain words, numbers with units (Rs, %, bars, days).

Return the JSON the schema asks for. Leave a list empty rather than pad it."""

_lock = threading.Lock()


def _schema() -> dict:
    item = lambda *keys: {"type": "object", "additionalProperties": False, "required": list(keys),  # noqa: E731
                          "properties": {k: {"type": "string"} for k in keys}}
    return {"type": "object", "additionalProperties": False,
            "required": ["headline", "strengths", "leaks", "rules", "next_focus", "sample_note"],
            "properties": {"headline": {"type": "string"},
                           "strengths": {"type": "array", "items": item("title", "evidence")},
                           "leaks": {"type": "array", "items": item("title", "evidence", "cost", "fix")},
                           "rules": {"type": "array", "items": {"type": "string"}},
                           "next_focus": {"type": "string"},
                           "sample_note": {"type": "string"}}}


def _avg(xs: list[float]) -> float | None:
    return round(mean(xs), 2) if xs else None


def _group(trades: list[dict]) -> dict:
    n = len(trades)
    wins = [t["net"] for t in trades if t["net"] > 0]
    return {"trades": n, "win_rate": round(len(wins) / n * 100, 1) if n else None,
            "net": round(sum(t["net"] for t in trades), 2), "per_trade": _avg([t["net"] for t in trades])}


def behaviour(trades: list[dict], sessions: list[dict]) -> dict:
    """Process checks on practice trades (replay_svc rows, each with tf / session added)."""
    base = replay_svc.stats(trades)
    losers = [t for t in trades if t["net"] <= 0]
    winners = [t for t in trades if t["net"] > 0]
    stopped_losses = [t["net"] for t in losers if t.get("reason") == "stop"]
    other_losses = [t["net"] for t in losers if t.get("reason") != "stop"]
    by_session: dict[str, list[dict]] = {}
    for t in trades:
        by_session.setdefault(t["session"], []).append(t)
    busy = [t for ts in by_session.values() if len(ts) >= 4 for t in ts]
    calm = [t for ts in by_session.values() if len(ts) <= 3 for t in ts]
    after_loss = [ts[i] for ts in by_session.values() for i in range(1, len(ts)) if ts[i - 1]["net"] <= 0]
    gross_wins = sum(t["gross"] for t in trades if t["gross"] > 0)
    recent, earlier = trades[-20:], trades[:-20]
    return {
        "summary": base,
        "by_bar_size": {tf: _group([t for t in trades if t["tf"] == tf]) for tf in replay_svc.TFS if any(t["tf"] == tf for t in trades)},
        "long_vs_short": {s: _group([t for t in trades if t["side"] == s]) for s in ("LONG", "SHORT") if any(t["side"] == s for t in trades)},
        "blind_vs_named": {k: _group([t for t in trades if bool(t.get("blind")) == (k == "blind")]) for k in ("blind", "named")
                           if any(bool(t.get("blind")) == (k == "blind") for t in trades)},
        "stops": {"with_stop_pct": base["with_stop_pct"], "losers": len(losers),
                  "losers_exited_by_stop": len(stopped_losses), "avg_loss_stopped": _avg(stopped_losses),
                  "avg_loss_other_exits": _avg(other_losses)},
        "holding": {"avg_bars_winners": _avg([t["bars_held"] for t in winners]),
                    "avg_bars_losers": _avg([t["bars_held"] for t in losers])},
        "largest_loss": min((t["net"] for t in trades), default=None),
        "largest_loss_vs_avg_win": (round(-min(t["net"] for t in trades) / base["avg_win"], 2)
                                    if base["avg_win"] and losers else None),
        "overtrading": {"sessions": len(by_session), "trades_per_session": round(len(trades) / max(len(by_session), 1), 2),
                        "in_sessions_with_4_plus_trades": _group(busy), "in_sessions_with_up_to_3": _group(calm)},
        "trade_after_a_loss": _group(after_loss),
        "charges": {"total": round(sum(t["charges"] for t in trades), 2),
                    "pct_of_gross_wins": round(sum(t["charges"] for t in trades) / gross_wins * 100, 1) if gross_wins else None},
        "trend": {"last_20": _group(recent), "before": _group(earlier)} if earlier else None,
        "sessions": len(sessions),
    }


def real_money() -> dict | None:
    fl = fills.read(P.data)
    if not fl:
        return None
    closed, still = fills.round_trips(fl)
    for t in closed:
        t["net"] = t["pnl"]
    sig = [t for t in closed if t.get("strategy_key")]
    off = [t for t in closed if not t.get("strategy_key")]
    slip = [(float(f["price"]) / float(f["ref_price"]) - 1) * 100 * (1 if f.get("side") == "BUY" else -1)
            for f in fl if f.get("ref_price")]
    wins = [t["pnl"] for t in closed if t["pnl"] > 0]
    losses = [t["pnl"] for t in closed if t["pnl"] <= 0]
    return {"fills": len(fl), "closed": _group(closed) | {"avg_win": _avg(wins), "avg_loss": _avg(losses),
                                                          "with_stop_pct": round(sum(1 for t in closed if t.get("stop")) / len(closed) * 100, 1) if closed else None},
            "from_a_signal": _group(sig), "off_signal": _group(off), "still_open_lots": len(still),
            "avg_slippage_pct": _avg(slip), "note": "Charges are not in these P&Ls (FYERS' contract notes have them)."}


def holdings_now() -> dict:
    try:
        rows, stale = holdings_svc.rows(data.latest())
    except Exception:
        log.exception("Coach: reading holdings failed")
        return {"count": 0}
    if not rows:
        return {"count": 0}
    val = sum(r["value"] or 0 for r in rows)
    below = [r for r in rows if r.get("price") is not None and r.get("stop_price") is not None and r["price"] < r["stop_price"]]
    inds: dict[str, float] = {}
    for r in rows:
        inds[r.get("industry") or "unknown"] = inds.get(r.get("industry") or "unknown", 0) + (r["value"] or 0)
    top_ind = max(inds.items(), key=lambda kv: kv[1]) if inds else None
    pnl = [r["pnl_amount"] for r in rows if r.get("pnl_amount") is not None]
    return {"count": len(rows), "value": round(val, 0), "unrealised_pnl": round(sum(pnl), 0) if pnl else None,
            "losing": sum(1 for r in rows if (r.get("pnl_pct") or 0) < 0),
            "below_their_stop": [{"symbol": r["symbol"], "pnl_pct": r.get("pnl_pct")} for r in below],
            "without_a_stop": sum(1 for r in rows if r.get("stop_price") is None),
            "largest_weight_pct": max((r.get("weight_pct") or 0 for r in rows), default=None),
            "top_industry": {"name": top_ind[0], "pct": round(top_ind[1] / val * 100, 1)} if top_ind and val else None,
            "in_a_tested_strategy": sum(1 for r in rows if r.get("in_models")), "as_of_last_scan": True, "stale": stale}


def facts() -> dict:
    rows = replay_svc.log_rows()
    trades = [dict(t, tf=r["tf"], blind=r.get("blind"), session=r["id"]) for r in rows for t in r.get("trades") or []]
    practice = behaviour(trades, rows) if trades else None
    real = real_money()
    hold = holdings_now()
    n_p = len(trades)
    n_r = (real or {}).get("closed", {}).get("trades", 0)
    return {"practice": practice, "real_money": real, "holdings": hold,
            "sample": {"practice_trades": n_p, "real_round_trips": n_r,
                       "enough": n_p >= ENOUGH_PRACTICE or n_r >= ENOUGH_REAL,
                       "rule_of_thumb": f"{ENOUGH_PRACTICE}+ practice trades or {ENOUGH_REAL}+ real round trips before patterns mean much"}}


def _key(f: dict) -> str:
    return hashlib.sha256(json.dumps(f, sort_keys=True, default=str).encode()).hexdigest()[:16]


def _saved_path():
    return P.results / "coach.json"


def last() -> dict | None:
    try:
        return json.loads(_saved_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def view() -> dict:
    f = facts()
    prev = last()
    return {"facts": f, "review": prev, "stale": bool(prev) and prev.get("key") != _key(f), "ai": ai_svc.status(),
            "note": NOTE}


def review() -> dict:
    f = facts()
    if not f["practice"] and not f["real_money"] and not f["holdings"].get("count"):
        raise ApiException("VALIDATION", "Nothing to review yet.",
                           "Finish a few replays with trades (Replay page), or trade through the Orders page, or add your "
                           "holdings: the coach needs your own record.")
    client = ai_svc._get_client()                      # FEATURE_UNAVAILABLE without ANTHROPIC_API_KEY in .env
    if not _lock.acquire(blocking=False):
        raise ApiException("SCAN_BUSY", "A review is already being written.", "Wait a minute.",
                           {"started": "?", "by": "coach", "pid": None})
    try:
        msg = client.beta.messages.create(
            model=ai_svc.MODEL, max_tokens=MAX_TOKENS,
            betas=["server-side-fallback-2026-07-01"], fallbacks="default",
            thinking={"type": "adaptive"},
            output_config={"effort": "medium", "format": {"type": "json_schema", "schema": _schema()}},
            system=SYSTEM,
            messages=[{"role": "user", "content": "My trading record (JSON):\n" + json.dumps(f, default=str)}],
        )
    except anthropic.AuthenticationError:
        raise ApiException("FEATURE_UNAVAILABLE", "The Anthropic API key in .env was rejected.",
                           "Create a new key at console.anthropic.com and put it in .env.", {"feature": "ai"})
    except anthropic.PermissionDeniedError:
        raise ApiException("FEATURE_UNAVAILABLE", "This Anthropic key may not use this model.",
                           "Check the key's workspace and billing in console.anthropic.com.", {"feature": "ai"})
    except anthropic.RateLimitError:
        raise ApiException("SCAN_BUSY", "Anthropic's rate limit was reached.", "Try again in a minute.",
                           {"started": "?", "by": "ai", "pid": None})
    except anthropic.APIStatusError as e:
        raise ApiException("INTERNAL", f"The Anthropic API answered {e.status_code}.", str(e.message)[:300])
    except anthropic.APIConnectionError:
        raise ApiException("INTERNAL", "Can't reach the Anthropic API.", "Check the internet connection.")
    finally:
        _lock.release()
    if msg.stop_reason == "refusal":
        raise ApiException("INTERNAL", "Claude declined to write this review.", "Try again later.")
    if msg.stop_reason == "max_tokens":
        raise ApiException("INTERNAL", "The review was cut off.", "Try again.")
    raw = next((b.text for b in msg.content if getattr(b, "type", None) == "text"), "")
    try:
        rv = json.loads(raw)
    except ValueError:
        raise ApiException("INTERNAL", "Claude's review was not valid JSON.", "Try again.") from None
    out = {"key": _key(f), "at": now_ist().isoformat(timespec="seconds"), "model": getattr(msg, "model", ai_svc.MODEL),
           "review": rv, "sample": f["sample"]}
    try:
        _saved_path().parent.mkdir(parents=True, exist_ok=True)
        _saved_path().write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError:
        log.exception("Saving the coach review failed")
    return out
