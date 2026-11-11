"""A scan from plain English (POST /api/scans/from-text): Claude translates the description into the scan builder's
rules (scanner/scans.py), in a fixed JSON shape (structured outputs), using only the builder's own fields and
comparisons. The result is shown in the builder for you to check, run and backtest; Claude never runs it, never
judges whether it works (the backtest does) and says what it could not express."""
from __future__ import annotations

import json

import anthropic

from scanner import scans

from . import ai_svc
from ..errors import ApiException

MAX_TOKENS = 16000

FIELD_KEYS = list(scans.FIELDS)


def _schema() -> dict:
    side = {"type": "object", "additionalProperties": False, "required": ["kind", "value", "field", "mult"],
            "properties": {"kind": {"type": "string", "enum": ["value", "field"]},
                           "value": {"type": "number"},
                           "field": {"type": "string", "enum": FIELD_KEYS},
                           "mult": {"type": "number"}}}
    rule = {"type": "object", "additionalProperties": False, "required": ["left", "op", "right"],
            "properties": {"left": {"type": "string", "enum": FIELD_KEYS}, "op": {"type": "string", "enum": list(scans.OPS)},
                           "right": side}}
    return {"type": "object", "additionalProperties": False,
            "required": ["name", "match", "direction", "rules", "explanation", "unsupported"],
            "properties": {"name": {"type": "string"}, "match": {"type": "string", "enum": ["all", "any"]},
                           "direction": {"type": "string", "enum": ["long", "short"]},
                           "rules": {"type": "array", "items": rule},
                           "explanation": {"type": "string"}, "unsupported": {"type": "string"}}}


def _system() -> str:
    fields = "\n".join(f"- {k}: {f.label} ({f.group}{', ' + f.unit if f.unit else ''})" for k, f in scans.FIELDS.items())
    return f"""You translate a stock-scan idea written in plain English into the rules of a scan builder for Indian \
(NSE) stocks. Use only these fields (daily data; values are for the scan day; "_prev" highs and lows exclude that day):
{fields}

Comparisons: >, >=, <, <=, crosses_above, crosses_below (crosses = true only on the day the left side moves from \
below to above the right side, or the reverse). The right side is either a number (kind "value") or another field \
times a multiplier (kind "field", e.g. close > 1.02 x sma50 is field sma50 with mult 1.02). Fill every property: for \
kind "value" set field to "close" and mult to 1 (they are ignored); for kind "field" set value to 0. Percent fields \
are in percent (5 means 5%). match "all" = every rule must hold, "any" = at least one. direction "long" for a bullish \
setup (tested as a buy), "short" for a bearish one. At most {scans.MAX_RULES} rules.

Rules of the job:
- Translate faithfully; do not add conditions the user did not ask for, except an obvious unit or threshold the idea \
  needs (say so in the explanation).
- If part of the idea cannot be expressed with these fields (fundamentals, news, intraday, sectors, options data), \
  leave it out and say exactly what in "unsupported" (empty string when everything fits).
- name: a short name (max 60 characters). explanation: one or two plain sentences on how you read the idea.
- Never say whether the scan will work or make money: the user backtests it."""


def translate(text: str) -> dict:
    text = (text or "").strip()
    if not text:
        raise ApiException("VALIDATION", "Describe the scan first.")
    if len(text) > 1000:
        raise ApiException("VALIDATION", "Keep the description under 1,000 characters.")
    client = ai_svc._get_client()                       # FEATURE_UNAVAILABLE without ANTHROPIC_API_KEY in .env
    try:
        msg = client.beta.messages.create(
            model=ai_svc.MODEL, max_tokens=MAX_TOKENS,
            betas=["server-side-fallback-2026-07-01"], fallbacks="default",
            thinking={"type": "adaptive"},
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": _schema()}},
            system=[{"type": "text", "text": _system(), "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": text}],
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
    if msg.stop_reason == "refusal":
        raise ApiException("VALIDATION", "Claude declined to translate this description.", "Rephrase it as a price / volume rule.")
    if msg.stop_reason == "max_tokens":
        raise ApiException("INTERNAL", "The translation was cut off.", "Try a shorter description.")
    raw = next((b.text for b in msg.content if getattr(b, "type", None) == "text"), "")
    try:
        d = json.loads(raw)
    except ValueError:
        raise ApiException("INTERNAL", "Claude's answer was not valid JSON.", "Try again.")
    return to_scan(d) | {"model": getattr(msg, "model", ai_svc.MODEL)}


def to_scan(d: dict) -> dict:
    """The structured answer as a validated scan (rules the builder accepts), plus Claude's notes."""
    rules = []
    for r in d.get("rules") or []:
        rt = r.get("right") or {}
        right = {"field": rt.get("field"), "mult": rt.get("mult") or 1.0} if rt.get("kind") == "field" else {"value": rt.get("value", 0)}
        rules.append({"left": r.get("left"), "op": r.get("op"), "right": right})
    try:
        scan = scans.validate({"name": d.get("name"), "match": d.get("match"), "direction": d.get("direction"),
                               "rules": rules[:scans.MAX_RULES]})
    except ValueError as e:
        raise ApiException("VALIDATION", f"Claude's scan did not fit the builder: {e}",
                           str(d.get("unsupported") or "Rephrase it with price, volume or indicator rules."))
    return {"scan": scan, "rules_text": [scans.describe_rule(r) for r in scan["rules"]],
            "explanation": str(d.get("explanation") or ""), "unsupported": str(d.get("unsupported") or "")}
