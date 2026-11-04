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
from dotenv import dotenv_values

from ..errors import ApiException, feature_unavailable
from ..paths import P
from ..util import now_ist
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


def analyze(symbol: str, question: str | None) -> dict:
    sym = symbol.strip().upper()
    q = (question or "").strip() or None
    ctx = context(sym)
    key = (sym, q, ctx["outlook"]["date"], ctx["outlook"]["close"], json.dumps(ctx["outlook"]["derivatives"]["verdict"] or {},
                                                                              sort_keys=True, default=str)[:4000])
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < CACHE_S:
        return {**hit[1], "cached": True}
    client = _get_client()
    if not _lock.acquire(blocking=False):
        raise ApiException("SCAN_BUSY", "An AI analysis is already running.", "Wait for it to finish (about a minute).",
                           {"started": "?", "by": "ai", "pid": None})
    try:
        user = ("<snapshot>\n" + json.dumps(ctx, default=str, separators=(",", ":")) + "\n</snapshot>\n\n"
                + (f"The reader asks: {q}" if q else "Explain what this data says about this stock now and what "
                                                    "usually happens next in a setup like this."))
        try:
            with client.beta.messages.stream(
                model=MODEL, max_tokens=MAX_TOKENS,
                betas=["server-side-fallback-2026-07-01"], fallbacks="default",
                thinking={"type": "adaptive"}, output_config={"effort": EFFORT},
                system=[{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": user}],
            ) as stream:
                msg = stream.get_final_message()
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
        refused = msg.stop_reason == "refusal"
        text = None if refused else "".join(b.text for b in msg.content if getattr(b, "type", None) == "text").strip() or None
        u = msg.usage
        out = {"symbol": sym, "question": q, "answer": text, "refused": refused, "stop_reason": msg.stop_reason,
               "model": getattr(msg, "model", MODEL), "data_date": ctx["outlook"]["date"],
               "generated_at": now_ist().isoformat(timespec="seconds"), "cached": False,
               "input_tokens": getattr(u, "input_tokens", None), "output_tokens": getattr(u, "output_tokens", None),
               "cache_read_tokens": getattr(u, "cache_read_input_tokens", None), "note": NOTE}
        if not refused:
            _cache[key] = (time.monotonic(), out)
        return out
    finally:
        _lock.release()
