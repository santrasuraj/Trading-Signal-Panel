"""AI analyst: Claude reads this platform's own data for one symbol (setup and base rates, levels, signals with their
tested records, the options verdict, F&O positioning and NSE disclosures) and explains it in plain English.

The API key is read from ANTHROPIC_API_KEY in the project's .env on every call (so a new key needs no restart). It is
never sent to the browser, never logged and never written anywhere. Claude gets only the numbers below - no web
access - and is told never to invent data, never to forecast with certainty and never to override the tested options
verdict. One analysis at a time; the same question on the same data is answered from a 15-minute cache (each call
costs money: roughly Rs 5-10 per analysis on Claude Opus 5.5).
"""
from __future__ import annotations

import json
import os
import threading
import time

import anthropic
import pandas as pd
from dotenv import dotenv_values

from ..errors import ApiException, feature_unavailable
from ..paths import P
from ..util import now_ist, today_ist
from . import data, levels_svc, outlook_svc

MODEL = "claude-opus-5-5"
MAX_TOKENS = 16000
EFFORT = "high"
CACHE_S = 15 * 60
NOTE = ("Written by Claude (Anthropic) from this page's data only - it has no news and no live feed of its own and can "
        "be wrong. Base rates, not forecasts. Research, not investment advice: you decide.")

SYSTEM = """You are the research analyst inside Quant Desk, a personal research tool for one investor trading Indian \
stocks (NSE). Each request gives you a JSON snapshot of one stock or index, built from NSE's official day files, the \
app's 8-year survivorship-free studies of what happened after similar setups, a stored NSE option chain, NSE's F&O \
bhavcopy, and SEBI disclosures (promoter pledges, 5%+ holders' filings, bulk and block deals).

How to answer:
- Use only the numbers in the snapshot. Never invent prices, levels, news, results dates, holders or anything else. \
If something the reader would want is missing or stale (an old option chain, a provisional live candle), say so.
- Nobody knows the next move. Speak in base rates, ranges and scenarios ("in 3,659 similar cases, 57% ended higher \
after 20 days"), never in certainties or single-price predictions.
- The options verdict comes from the app's tested rules. Never override it: if it says NO TRADE, explain why and do \
not suggest buying calls or puts anyway. If it says BUY CALL or BUY PUT, repeat its strike, price, breakeven and exit \
plan, and remind the reader that the verdict's own record is still being built.
- Say which signals were tested here and how they did ("tested: no edge", "worked in reverse", a strategy's backtest) \
and which are untested positioning (PCR, max pain, OI walls, filings). Untested readings never set the direction.
- Point out where signals disagree, and what price levels would change the picture.
- Write for a reader whose English is simple: short sentences, plain words, numbers with units (Rs, %, days).

Format (Markdown, under 450 words unless the reader asks something specific):
**In short** - 2-3 sentences.
**Setup and what usually followed**
**Levels to watch** - nearest support and resistance with distances, and the trend-change levels.
**Options and big money**
**Risks**
**What would change this view**
Answer the reader's own question first when there is one. End with one line: "Research, not investment advice - you \
decide."
"""

_lock = threading.Lock()
_client: anthropic.Anthropic | None = None
_client_key: str | None = None
_cache: dict[tuple, tuple[float, dict]] = {}


def _key() -> str:
    try:
        v = dotenv_values(P.root / ".env").get("ANTHROPIC_API_KEY")
    except OSError:
        v = None
    return (v or os.environ.get("ANTHROPIC_API_KEY") or "").strip()


def status() -> dict:
    return {"configured": bool(_key()), "model": MODEL, "running": _lock.locked(),
            "note": "Add ANTHROPIC_API_KEY=... to the .env file next to config.yaml. The key stays on this PC."}


def _get_client() -> anthropic.Anthropic:
    global _client, _client_key
    key = _key()
    if not key:
        raise feature_unavailable("ai", "The AI analyst needs an Anthropic API key.",
                                  "Create a key at console.anthropic.com, then add ANTHROPIC_API_KEY=... to the .env "
                                  "file next to config.yaml (never paste it into a chat or a web page).")
    if _client is None or key != _client_key:
        _client, _client_key = anthropic.Anthropic(api_key=key, timeout=300.0, max_retries=2), key
    return _client


def _trim_levels(lv: dict) -> dict:
    d = dict(lv.get("daily") or {})
    d["chart_patterns"] = [{k: p.get(k) for k in ("name", "bias", "status", "direction", "breakout", "invalidation",
                                                    "target", "start", "end", "evidence")} for p in d.get("chart_patterns") or []]
    return {"daily": d, "intraday": lv.get("intraday"), "intraday_source": lv.get("intraday_source")}


def context(symbol: str) -> dict:
    """Everything the analyst reads for one symbol (files only)."""
    from ..routers.lookup import stock          # the same snapshot the Chart page's side panel shows
    sym = symbol.strip().upper()
    o = outlook_svc.outlook_for(sym)
    lt = data.latest() or {}
    try:
        snap = stock(sym)
    except ApiException:
        snap = None
    big = dict(o["big_money"])
    big["filings"] = big["filings"][:10]
    return {"symbol": sym, "built_at": now_ist().isoformat(timespec="seconds"),
            "market_regime": (lt.get("market") or {}), "scan_data_date": lt.get("data_date"),
            "snapshot": snap, "outlook": {**o, "big_money": big}, "price_action": _trim_levels(levels_svc.levels_for(sym))}


def _stream(system: str, user: str, output_config: dict):
    """One Claude call (one at a time across the analyst and the planner): Claude Opus 5.5, adaptive thinking, the
    server-side refusal fallback, the system prompt cached. Anthropic's errors become the API's own errors."""
    client = _get_client()
    if not _lock.acquire(blocking=False):
        raise ApiException("SCAN_BUSY", "An AI analysis is already running.", "Wait for it to finish (about a minute).",
                           {"started": "?", "by": "ai", "pid": None})
    try:
        try:
            with client.beta.messages.stream(
                model=MODEL, max_tokens=MAX_TOKENS,
                betas=["server-side-fallback-2026-07-01"], fallbacks="default",
                thinking={"type": "adaptive"}, output_config=output_config,
                system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": user}],
            ) as stream:
                return stream.get_final_message()
        except anthropic.AuthenticationError:
            raise ApiException("FEATURE_UNAVAILABLE", "The Anthropic API key in .env was rejected.",
                               "Create a new key at console.anthropic.com (keys start with sk-ant-api) and put it in .env.",
                               {"feature": "ai"})
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


def _text(msg) -> str | None:
    return "".join(b.text for b in msg.content if getattr(b, "type", None) == "text").strip() or None


def _usage(msg) -> dict:
    u = msg.usage
    return {"input_tokens": getattr(u, "input_tokens", None), "output_tokens": getattr(u, "output_tokens", None),
            "cache_read_tokens": getattr(u, "cache_read_input_tokens", None)}


def analyze(symbol: str, question: str | None) -> dict:
    sym = symbol.strip().upper()
    q = (question or "").strip() or None
    ctx = context(sym)
    key = (sym, q, ctx["outlook"]["date"], ctx["outlook"]["close"], json.dumps(ctx["outlook"]["derivatives"]["verdict"] or {},
                                                                              sort_keys=True, default=str)[:4000])
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < CACHE_S:
        return {**hit[1], "cached": True}
    user = ("<snapshot>\n" + json.dumps(ctx, default=str, separators=(",", ":")) + "\n</snapshot>\n\n"
            + (f"The reader asks: {q}" if q else "Explain what this data says about this stock now and what "
                                                "usually happens next in a setup like this."))
    msg = _stream(SYSTEM, user, {"effort": EFFORT})
    refused = msg.stop_reason == "refusal"
    out = {"symbol": sym, "question": q, "answer": None if refused else _text(msg), "refused": refused,
           "stop_reason": msg.stop_reason, "model": getattr(msg, "model", MODEL), "data_date": ctx["outlook"]["date"],
           "generated_at": now_ist().isoformat(timespec="seconds"), "cached": False, **_usage(msg), "note": NOTE}
    if not refused:
        _cache[key] = (time.monotonic(), out)
    return out


# ------------------------------------------------------------------ AI trade plan (chart reading)
PLAN_CACHE_S = 5 * 60                 # intraday: a new 5-minute bar is new data
PLAN_BARS = 40                        # the last 40 five-minute bars of the latest session
PLAN_NOTE = ("Written by Claude (Anthropic) from this app's own data - levels, today's 5-minute bars and the scanner's "
             "signals. It has no news and no live feed of its own and can be wrong. A plan to check, not a forecast "
             "and not investment advice: you decide and place every trade yourself.")

PLAN_SYSTEM = """You are the intraday trade planner inside Quant Desk, a personal research tool for one investor \
trading Indian stocks (NSE). Each request gives a JSON snapshot of ONE stock or index: its daily setup and levels, \
intraday price-action levels (previous day high / low / close, opening range, VWAP, pivots), the latest 5-minute bars \
(time, open, high, low, close, volume) and today's signals from the app's intraday strategies, each labelled with its \
backtest result.

Write a price-action plan the way many Indian intraday traders read a chart - key levels, where stop-losses are \
likely to sit (liquidity), and IF-THEN conditions on 5-minute closes - but honestly:
- Use only the snapshot. Every price you give must come from it or be computed from it. Never invent levels, news, \
results dates or anything else.
- Nobody knows the next move. Give conditional setups ("if price sweeps X and a 5-minute candle closes back above it, \
then ..."), never certainties. If nothing is clean, return no setups and say why in no_trade_if.
- At most two setups. Each has an entry zone, the exact conditions to wait for, a stop beyond the level that proves \
it wrong, target_1 at about twice the risk and target_2 at about three times (or the next level if that is nearer), \
and what cancels it.
- A strategy labelled untested, not proven or losing is an idea, not evidence; never call a setup proven unless its \
strategy is labelled working (proven).
- If the bars are not from today, or are delayed, say so in the summary.
- risk_note: one or two sentences on sizing (risk a small fixed share of capital to the stop), intraday costs, and \
that most individual intraday and F&O traders in India lose money (SEBI's studies).
Plain English, short sentences, prices in rupees."""

_LEVEL = {"type": "object", "additionalProperties": False, "required": ["price", "label", "kind"],
          "properties": {"price": {"type": "number"}, "label": {"type": "string"},
                         "kind": {"type": "string", "enum": ["support", "resistance", "liquidity", "pivot"]}}}
_SETUP = {"type": "object", "additionalProperties": False,
          "required": ["name", "side", "entry_low", "entry_high", "conditions", "stop", "target_1", "target_2",
                       "invalidation"],
          "properties": {"name": {"type": "string"}, "side": {"type": "string", "enum": ["LONG", "SHORT"]},
                         "entry_low": {"type": "number"}, "entry_high": {"type": "number"},
                         "conditions": {"type": "array", "items": {"type": "string"}},
                         "stop": {"type": "number"}, "target_1": {"type": "number"}, "target_2": {"type": "number"},
                         "invalidation": {"type": "string"}}}
PLAN_SCHEMA = {"type": "object", "additionalProperties": False,
               "required": ["bias", "summary", "levels", "setups", "no_trade_if", "risk_note"],
               "properties": {"bias": {"type": "string", "enum": ["long", "short", "neutral"]},
                              "summary": {"type": "string"}, "levels": {"type": "array", "items": _LEVEL},
                              "setups": {"type": "array", "items": _SETUP},
                              "no_trade_if": {"type": "string"}, "risk_note": {"type": "string"}}}


def _today_for(sym: str) -> dict:
    """The latest session's last PLAN_BARS 5-minute bars (live feed, else stored - Yahoo when FYERS isn't logged in)
    and today's intraday signals for the symbol."""
    bars, source = levels_svc._intraday_bars(sym)
    session, rows = None, []
    if bars is not None and len(bars):
        b = bars.sort_values("ts")
        last = pd.Timestamp(b["ts"].max()).normalize()
        day = b[b["ts"] >= last].tail(PLAN_BARS)
        session = last.date().isoformat()
        rows = [[pd.Timestamp(r.ts).strftime("%H:%M"), round(float(r.open), 2), round(float(r.high), 2),
                 round(float(r.low), 2), round(float(r.close), 2), int(r.volume) if pd.notna(r.volume) else None]
                for r in day.itertuples()]
    sig = data.intraday_signals() or {}
    mine = [{k: x.get(k) for k in ("strategy_name", "strategy_status", "side", "state", "entry_time", "entry", "stop",
                                   "target", "last", "detail")}
            for x in sig.get("signals") or [] if x.get("symbol") == sym
            and str(sig.get("generated_at") or "")[:10] == today_ist().isoformat()]
    return {"session": session, "is_today": session == today_ist().isoformat(), "bars_source": source,
            "bars_5m": {"columns": ["time", "open", "high", "low", "close", "volume"], "rows": rows},
            "signals": mine}


def plan(symbol: str) -> dict:
    """POST /api/ai/plan: Claude reads the symbol's levels, the latest 5-minute bars and today's signals and returns an
    IF-THEN intraday plan as structured JSON (PLAN_SCHEMA): bias, key levels, up to two setups with entry zone,
    conditions, stop, two targets and what cancels it. Cached for 5 minutes on the same bars and signals."""
    sym = symbol.strip().upper()
    ctx = {**context(sym), "today": _today_for(sym)}
    t = ctx["today"]
    key = ("plan", sym, t["session"], json.dumps(t["bars_5m"]["rows"][-1:], default=str),
           json.dumps(t["signals"], sort_keys=True, default=str)[:4000])
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < PLAN_CACHE_S:
        return {**hit[1], "cached": True}
    user = ("<snapshot>\n" + json.dumps(ctx, default=str, separators=(",", ":")) + "\n</snapshot>\n\n"
            f"Write today's intraday plan for {sym}.")
    msg = _stream(PLAN_SYSTEM, user, {"effort": EFFORT, "format": {"type": "json_schema", "schema": PLAN_SCHEMA}})
    refused = msg.stop_reason == "refusal"
    body = None
    if not refused and msg.stop_reason != "max_tokens":
        try:
            body = json.loads(_text(msg) or "")
        except ValueError:
            body = None
    out = {"symbol": sym, "plan": body, "refused": refused, "stop_reason": msg.stop_reason,
           "model": getattr(msg, "model", MODEL), "session": t["session"], "bars_source": t["bars_source"],
           "generated_at": now_ist().isoformat(timespec="seconds"), "cached": False, **_usage(msg), "note": PLAN_NOTE}
    if body is not None:
        _cache[key] = (time.monotonic(), out)
    return out
