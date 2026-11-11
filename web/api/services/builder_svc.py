"""Strategy builder (POST /api/builder/...): a strategy in plain English (Claude turns it into a spec: scanner/custom.py)
or from the form, tested like the built-in strategies on the 8-year survivorship-free top 500, optimised with a
walk-forward, and saved (data/custom_strategies.json). Claude only translates; it never writes code, and it never says
whether a strategy will work: the backtest does.
"""
from __future__ import annotations

import hashlib
import json
import threading
import time

import anthropic

from scanner import custom, scans

from . import ai_svc, data, scan_text
from ..errors import ApiException, log
from ..paths import P

KEEP_S = 10 * 60
_setup: dict = {"obj": None, "at": 0.0, "key": None}
_setup_lock = threading.Lock()
_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()


def _file():
    return P.data / "custom_strategies.json"


def setup() -> custom.Setup:
    """The test bench (point-in-time panel, scan context, benchmarks), kept for 10 minutes after its last use."""
    key = data.store_version()
    with _setup_lock:
        if _setup["obj"] is None or _setup["key"] != key or time.monotonic() - _setup["at"] > KEEP_S:
            try:
                _setup["obj"] = custom.Setup(data.store(), data.config())
            except RuntimeError as e:
                raise ApiException("FEATURE_UNAVAILABLE", str(e), None, {"feature": "builder"})
            _setup["key"] = key
        _setup["at"] = time.monotonic()
        return _setup["obj"]


def _invalid(e: Exception) -> ApiException:
    return ApiException("VALIDATION", str(e))


def test(spec: dict) -> dict:
    try:
        return custom.backtest(spec, setup())
    except ValueError as e:
        raise _invalid(e) from None


def _hash(spec: dict) -> str:
    return hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()[:16]


def optimise_start(spec: dict) -> dict:
    """Start the walk-forward optimisation in the background (27 simulations: a minute or two)."""
    try:
        spec = custom.validate(spec)
    except ValueError as e:
        raise _invalid(e) from None
    h = _hash(spec)
    with _jobs_lock:
        j = _jobs.get(h)
        if j and j["state"] in ("running", "done"):
            return {"id": h, **{k: v for k, v in j.items() if k != "result"}}
        _jobs[h] = {"state": "running", "done": 0, "total": 0, "error": None, "result": None, "started": time.time()}

    def work():
        def prog(i, n):
            _jobs[h].update(done=i, total=n)
        try:
            _jobs[h]["result"] = custom.optimise(spec, setup(), progress=prog)
            _jobs[h]["state"] = "done"
        except Exception as e:
            log.exception("Strategy optimisation failed")
            _jobs[h].update(state="error", error=f"{type(e).__name__}: {e}")
    threading.Thread(target=work, name="optimise", daemon=True).start()
    return {"id": h, "state": "running", "done": 0, "total": 0}


def optimise_status(job_id: str) -> dict:
    j = _jobs.get(job_id)
    if not j:
        raise ApiException("NOT_FOUND", "No optimisation with that id (the server may have restarted).")
    return {"id": job_id, **j}


def saved() -> list[dict]:
    return custom.saved(_file())


def save(spec: dict, sid: str | None, result: dict | None) -> dict:
    try:
        return custom.save(spec, sid, _file(), result)
    except ValueError as e:
        raise _invalid(e) from None


def delete(sid: str) -> None:
    custom.delete(sid, _file())


# ---- plain English -> spec (Claude) -------------------------------------------------------------------------------

def _schema() -> dict:
    rule = scan_text._schema()["properties"]["rules"]["items"]
    num_or_null = {"anyOf": [{"type": "number"}, {"type": "null"}]}
    return {"type": "object", "additionalProperties": False,
            "required": ["name", "entry_match", "entry_rules", "stop_pct", "target_pct", "trail_pct", "max_days",
                         "exit_match", "exit_rules", "max_positions", "priority", "explanation", "unsupported"],
            "properties": {"name": {"type": "string"},
                           "entry_match": {"type": "string", "enum": ["all", "any"]},
                           "entry_rules": {"type": "array", "items": rule},
                           "stop_pct": num_or_null, "target_pct": num_or_null, "trail_pct": num_or_null,
                           "max_days": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
                           "exit_match": {"type": "string", "enum": ["all", "any"]},
                           "exit_rules": {"type": "array", "items": rule},
                           "max_positions": {"type": "integer"},
                           "priority": {"anyOf": [{"type": "string", "enum": scan_text.FIELD_KEYS}, {"type": "null"}]},
                           "explanation": {"type": "string"}, "unsupported": {"type": "string"}}}


def _system() -> str:
    return scan_text._system().split("Rules of the job:")[0] + """This time the idea is a whole trading strategy (long \
only, daily bars): when to buy (entry_rules, combined by entry_match) and when to sell. Ways out: stop_pct (stop-loss % \
below the fill price), target_pct (profit target %), trail_pct (trailing stop % below the highest close since entry), \
max_days (sell after this many trading days), and exit_rules (sell at the next open when they hold, combined by \
exit_match). Use null for a way out the idea does not mention; if it mentions none, use stop_pct 8 and say so. \
max_positions: how many stocks at once (default 10). priority: the field whose highest values are bought first when \
there are more signals than free positions (null when not stated; rs_rating is a sensible default only if the idea \
ranks by strength).

Rules of the job:
- Translate faithfully; do not add conditions the user did not ask for, except an obvious unit, threshold or default \
  the strategy needs (say so in the explanation).
- If part of the idea cannot be expressed (fundamentals, news, intraday, short selling, options, position sizing other \
  than equal money), leave it out and say exactly what in "unsupported" (empty string when everything fits).
- name: a short name (max 60 characters). explanation: two plain sentences on how you read the idea.
- Never say whether the strategy will work or make money: the backtest decides."""


def _rules(rs: list[dict]) -> list[dict]:
    out = []
    for r in rs or []:
        rt = r.get("right") or {}
        right = {"field": rt.get("field"), "mult": rt.get("mult") or 1.0} if rt.get("kind") == "field" else {"value": rt.get("value", 0)}
        out.append({"left": r.get("left"), "op": r.get("op"), "right": right})
    return out[:scans.MAX_RULES]


def from_text(text: str) -> dict:
    text = (text or "").strip()
    if not text:
        raise ApiException("VALIDATION", "Describe the strategy first.")
    if len(text) > 1500:
        raise ApiException("VALIDATION", "Keep the description under 1,500 characters.")
    client = ai_svc._get_client()
    try:
        msg = client.beta.messages.create(
            model=ai_svc.MODEL, max_tokens=scan_text.MAX_TOKENS,
            betas=["server-side-fallback-2026-07-01"], fallbacks="default",
            thinking={"type": "adaptive"},
            output_config={"effort": "medium", "format": {"type": "json_schema", "schema": _schema()}},
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
        raise ApiException("VALIDATION", "Claude declined to translate this description.", "Rephrase it as trading rules.")
    if msg.stop_reason == "max_tokens":
        raise ApiException("INTERNAL", "The translation was cut off.", "Try a shorter description.")
    raw = next((b.text for b in msg.content if getattr(b, "type", None) == "text"), "")
    try:
        d = json.loads(raw)
    except ValueError:
        raise ApiException("INTERNAL", "Claude's answer was not valid JSON.", "Try again.") from None
    return to_spec(d) | {"model": getattr(msg, "model", ai_svc.MODEL)}


def to_spec(d: dict) -> dict:
    """Claude's structured answer as a validated spec, with its explanation and what it couldn't express."""
    spec = {"name": d.get("name"), "entry": {"match": d.get("entry_match", "all"), "rules": _rules(d.get("entry_rules"))},
            "exit": {"stop_pct": d.get("stop_pct"), "target_pct": d.get("target_pct"), "trail_pct": d.get("trail_pct"),
                     "max_days": d.get("max_days"), "match": d.get("exit_match", "any"), "rules": _rules(d.get("exit_rules"))},
            "max_positions": d.get("max_positions") or 10, "priority": d.get("priority")}
    try:
        spec = custom.validate(spec)
    except ValueError as e:
        raise ApiException("VALIDATION", f"Claude's strategy did not fit the builder: {e}",
                           str(d.get("unsupported") or "Rephrase it with price, volume or indicator rules."))
    return {"spec": spec, "text": custom.describe(spec), "explanation": str(d.get("explanation") or ""),
            "unsupported": str(d.get("unsupported") or "")}
