"""Claude's option-chain forecasts: the journal and the scoring. Pure and file-based (no network, no Anthropic SDK).

A forecast is Claude's reading of one underlying's stored NSE option chain together with the app's F&O positioning,
price context and tested verdict (web/api/services/forecast_svc.py builds that snapshot and calls the model). For two
horizons, the next official close and the close on the chain's expiry day, it gives the probability that the close
ends ABOVE the spot it saw, a range it expects the close to land in about 2 times out of 3, and the level that would
prove its view wrong.

Every forecast is journalled with the sha256 of the exact snapshot it read (the snapshot is kept beside the journal)
and scored later from NSE's official closes - never from a live quote - against baselines on the same days:

  direction  a coin flip (50%, Brier score 0.25) and "always up"
  range      the options market's own 1-SD range for the same horizon (from the at-the-money IV)

Nothing here is trusted until the record says so: at least PROVEN_MIN settled forecasts whose direction beat a coin
flip beyond luck (exact binomial p < P_MAX) AND a Brier score under the coin flip's 0.25. Even then it is research: it
never feeds the options verdict (scanner/option_verdict.py) or any order.
"""
from __future__ import annotations

import hashlib
import json
import math
import time
from contextlib import contextmanager
from datetime import date, datetime, time as dtime
from pathlib import Path

import numpy as np
import pandas as pd

from .lock import _try_lock, _unlock

JOURNAL_NAME = "ai_forecasts.json"
SNAP_DIR_NAME = "ai_forecast_snapshots"
BATCHES_NAME = "ai_forecast_batches.json"
LOCK_NAME = ".ai_forecast.lock"
HORIZONS = ("next_close", "expiry")
KINDS = ("evening", "on_demand")
PROVEN_MIN = 60              # settled forecasts before a record means anything
P_MAX = 0.05                 # direction must beat a coin flip with p below this (two-sided exact binomial)
COIN_BRIER = 0.25            # Brier score of always saying 50%
SESSION_CLOSE = dtime(15, 30)
TRADING_DAYS = 252
# index option underlyings -> their column in NSE's daily index file (data/nse/index_history.parquet): the official
# close that settles a forecast. Stocks settle at the price store's close.
INDEX_CLOSE_COLUMN = {"NIFTY": "Nifty 50", "BANKNIFTY": "Nifty Bank", "FINNIFTY": "Nifty Financial Services",
                      "MIDCPNIFTY": "Nifty Midcap Select", "NIFTYNXT50": "Nifty Next 50"}

_HORIZON = {
    "type": "object",
    "properties": {
        "p_up": {"type": "number", "description": "0-100: chance the close is above the spot you saw"},
        "low": {"type": "number", "description": "low end of the range the close lands in about 2 times out of 3"},
        "high": {"type": "number", "description": "high end of that range"},
    },
    "required": ["p_up", "low", "high"],
    "additionalProperties": False,
}
# The answer's shape (output_config.format). Number ranges are not part of a structured-output schema: normalize()
# enforces them.
SCHEMA = {
    "type": "object",
    "properties": {
        "view": {"type": "string", "enum": ["up", "down", "sideways", "no_view"]},
        "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
        "summary": {"type": "string", "description": "2-3 plain sentences"},
        "next_close": _HORIZON,
        "expiry": _HORIZON,
        "invalidation": {"anyOf": [{"type": "number"}, {"type": "null"}],
                         "description": "the price that would prove the view wrong, or null for no view"},
        "key_levels": {"type": "array", "items": {
            "type": "object",
            "properties": {"price": {"type": "number"},
                           "kind": {"type": "string", "enum": ["support", "resistance", "pivot"]},
                           "why": {"type": "string"}},
            "required": ["price", "kind", "why"], "additionalProperties": False}},
        "reasons": {"type": "array", "items": {
            "type": "object",
            "properties": {"text": {"type": "string"},
                           "evidence": {"type": "array", "items": {"type": "string"},
                                        "description": "snapshot fields this reason rests on, e.g. chain.summary.pcr_oi"},
                           "tested": {"type": "boolean",
                                      "description": "true only when the snapshot shows this reading was tested here"}},
            "required": ["text", "evidence", "tested"], "additionalProperties": False}},
    },
    "required": ["view", "confidence", "summary", "next_close", "expiry", "invalidation", "key_levels", "reasons"],
    "additionalProperties": False,
}


# --------------------------------------------------------------------------- the model's answer
def _num(x) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def normalize(raw: dict, spot: float) -> dict:
    """The model's JSON made safe to journal: probabilities clipped to 0-100, each range ordered and around the spot
    (a range that misses the spot by more than 50% is a typo, not a view), lists trimmed. ValueError when a required
    number is missing - the forecast is then recorded as an error, never guessed."""
    if not isinstance(raw, dict):
        raise ValueError("the answer is not a JSON object")
    out: dict = {"view": raw.get("view") if raw.get("view") in ("up", "down", "sideways", "no_view") else "no_view",
                 "confidence": raw.get("confidence") if raw.get("confidence") in ("low", "medium", "high") else "low",
                 "summary": str(raw.get("summary") or "").strip()[:1500]}
    for h in HORIZONS:
        x = raw.get(h) if isinstance(raw.get(h), dict) else {}
        p, lo, hi = _num(x.get("p_up")), _num(x.get("low")), _num(x.get("high"))
        if p is None or lo is None or hi is None:
            raise ValueError(f"{h}: p_up, low and high are required numbers")
        lo, hi = sorted((lo, hi))
        if lo < spot * 0.5 or hi > spot * 1.5:
            raise ValueError(f"{h}: range {lo:g}-{hi:g} is not around the spot {spot:g}")
        out[h] = {"p_up": round(min(100.0, max(0.0, p)), 1), "low": round(lo, 2), "high": round(hi, 2)}
    inv = _num(raw.get("invalidation"))
    out["invalidation"] = round(inv, 2) if inv is not None and spot * 0.5 <= inv <= spot * 1.5 else None
    levels = []
    for lv in (raw.get("key_levels") or [])[:8]:
        if isinstance(lv, dict) and _num(lv.get("price")) is not None:
            levels.append({"price": round(_num(lv["price"]), 2),
                           "kind": lv.get("kind") if lv.get("kind") in ("support", "resistance", "pivot") else "pivot",
                           "why": str(lv.get("why") or "")[:300]})
    out["key_levels"] = levels
    reasons = []
    for r in (raw.get("reasons") or [])[:8]:
        if isinstance(r, dict) and str(r.get("text") or "").strip():
            reasons.append({"text": str(r["text"]).strip()[:600],
                            "evidence": [str(e)[:120] for e in (r.get("evidence") or [])[:6]],
                            "tested": bool(r.get("tested"))})
    out["reasons"] = reasons
    return out


def baseline_ranges(spot: float, atm_iv_pct: float | None, days_to_expiry: float | None) -> dict:
    """The options market's own 1-SD range (about 2 times in 3 if options are fairly priced) for each horizon, from
    the at-the-money implied volatility: one trading day for the next close, the calendar time left for expiry."""
    out = {h: None for h in HORIZONS}
    iv = _num(atm_iv_pct)
    if not iv or iv <= 0 or not spot:
        return out
    sd1 = spot * iv / 100 * math.sqrt(1 / TRADING_DAYS)
    out["next_close"] = {"low": round(spot - sd1, 2), "high": round(spot + sd1, 2)}
    dte = _num(days_to_expiry)
    if dte is not None and dte > 0:
        sde = spot * iv / 100 * math.sqrt(dte / 365)
        out["expiry"] = {"low": round(spot - sde, 2), "high": round(spot + sde, 2)}
    return out


def snapshot_hash(snapshot_json: str) -> str:
    return hashlib.sha256(snapshot_json.encode("utf-8")).hexdigest()


def forecast_id(kind: str, symbol: str, chain_time: str) -> str:
    """One evening forecast per underlying and stored chain; on-demand ones also carry the time they were asked."""
    stamp = chain_time.replace(":", "").replace("-", "")[:15]
    return f"{kind}|{symbol}|{stamp}" if kind == "evening" else f"{kind}|{symbol}|{stamp}|{int(time.time())}"


# --------------------------------------------------------------------------- journal files
@contextmanager
def locked(folder: Path, wait_s: float = 10.0):
    """One writer at a time across processes (the web app's on-demand forecasts, the evening job)."""
    folder.mkdir(parents=True, exist_ok=True)
    fh = open(folder / LOCK_NAME, "a+")
    deadline = time.monotonic() + wait_s
    ok = _try_lock(fh)
    while not ok and time.monotonic() < deadline:
        time.sleep(0.1)
        ok = _try_lock(fh)
    if not ok:
        fh.close()
        raise TimeoutError("the forecast journal is busy")
    try:
        yield
    finally:
        _unlock(fh)
        fh.close()


def _read(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".{int(time.time() * 1000)}.tmp")
    tmp.write_text(json.dumps(obj, indent=0, default=str), encoding="utf-8")
    for k in range(10):                         # Windows: a reader can hold the file for an instant
        try:
            tmp.replace(path)
            return
        except PermissionError:
            time.sleep(0.1 * (k + 1))
    tmp.unlink(missing_ok=True)
    raise PermissionError(f"could not replace {path.name}")


def load_journal(folder: Path) -> list[dict]:
    rows = _read(folder / JOURNAL_NAME, [])
    return [r for r in rows if isinstance(r, dict) and r.get("id")] if isinstance(rows, list) else []


def add_rows(folder: Path, rows: list[dict]) -> None:
    """Merge rows into the journal (a row with the same id replaces the old one), oldest first."""
    with locked(folder):
        have = {r["id"]: r for r in load_journal(folder)}
        for r in rows:
            have[r["id"]] = r
        _write(folder / JOURNAL_NAME, sorted(have.values(), key=lambda r: (str(r.get("created_at")), r["id"])))


def save_snapshot(folder: Path, sha: str, snapshot_json: str) -> None:
    path = folder / SNAP_DIR_NAME / f"{sha}.json"
    if not path.exists():
        _write(path, json.loads(snapshot_json))


def load_batches(folder: Path) -> list[dict]:
    b = _read(folder / BATCHES_NAME, [])
    return b if isinstance(b, list) else []


def save_batches(folder: Path, batches: list[dict]) -> None:
    with locked(folder):
        _write(folder / BATCHES_NAME, batches)


# --------------------------------------------------------------------------- scoring
def _cutoff(created_at: str) -> date:
    """The last day whose close the forecast could have known: its own day after 15:30, else the day before."""
    t = datetime.fromisoformat(created_at)
    return t.date() if t.time() >= SESSION_CLOSE else (pd.Timestamp(t.date()) - pd.Timedelta(days=1)).date()


def settle_dates(created_at: str, expiry: str | None, closes: pd.Series) -> dict:
    """The official close that settles each horizon, or None while it is still to come."""
    s = closes.dropna()
    s = s[~s.index.duplicated(keep="last")].sort_index()
    after = s[s.index.date > _cutoff(created_at)]
    out = {"next_close": (after.index[0].date(), float(after.iloc[0])) if len(after) else None, "expiry": None}
    if expiry:
        exp = date.fromisoformat(expiry)
        if len(s) and s.index[-1].date() >= exp:                 # the expiry day (or the last close before it)
            upto = s[s.index.date <= exp]
            upto = upto[upto.index.date > _cutoff(created_at)]
            if len(upto):
                out["expiry"] = (upto.index[-1].date(), float(upto.iloc[-1]))
    return out


def score_row(row: dict, closes: pd.Series | None) -> dict:
    """The row with an outcome per horizon: settled close, up or not, the direction call's hit, its Brier score, and
    whether Claude's range and the options-implied range held the close."""
    out = {**row, "outcome": {h: None for h in HORIZONS}}
    fc = row.get("forecast")
    if row.get("status") != "ok" or not fc or closes is None or not len(closes):
        return out
    spot = float(row["spot"])
    dates = settle_dates(row["created_at"], row.get("expiry"), closes)
    for h in HORIZONS:
        d = dates.get(h)
        f = fc.get(h)
        if d is None or not f:
            continue
        day, close = d
        up = close > spot
        p = float(f["p_up"])
        base = (row.get("baseline") or {}).get(h)
        out["outcome"][h] = {
            "date": day.isoformat(), "close": round(close, 2), "move_pct": round((close / spot - 1) * 100, 2),
            "up": up, "call": "up" if p > 50 else "down" if p < 50 else None,
            "hit": None if p == 50 else (p > 50) == up,
            "brier": round((p / 100 - (1.0 if up else 0.0)) ** 2, 4),
            "in_range": f["low"] <= close <= f["high"],
            "width_pct": round((f["high"] - f["low"]) / spot * 100, 2),
            "base_in_range": (base["low"] <= close <= base["high"]) if base else None,
            "base_width_pct": round((base["high"] - base["low"]) / spot * 100, 2) if base else None,
        }
    return out


def binom_p(k: int, n: int) -> float | None:
    """Two-sided exact binomial p-value of k hits in n tries against a coin flip."""
    if n <= 0:
        return None
    pk = [math.comb(n, i) / 2 ** n for i in range(n + 1)]
    obs = pk[k]
    return round(min(1.0, sum(p for p in pk if p <= obs * (1 + 1e-9))), 4)


def track(scored: list[dict], kind: str) -> dict:
    """The record of one kind of forecast, per horizon, with its baselines and a plain verdict."""
    rows = [r for r in scored if r.get("kind") == kind]
    out = {"kind": kind, "forecasts": len(rows), "ok": sum(1 for r in rows if r.get("status") == "ok"),
           "pending": sum(1 for r in rows if r.get("status") == "pending"),
           "refused": sum(1 for r in rows if r.get("status") == "refused"),
           "errors": sum(1 for r in rows if r.get("status") == "error"), "horizons": {}}
    mean = lambda xs: round(float(np.mean(xs)), 4) if xs else None      # noqa: E731
    pct = lambda xs: round(100 * float(np.mean(xs)), 1) if xs else None  # noqa: E731
    for h in HORIZONS:
        oc = [r["outcome"][h] for r in rows if (r.get("outcome") or {}).get(h)]
        calls = [o for o in oc if o["hit"] is not None]
        hits = sum(1 for o in calls if o["hit"])
        p = binom_p(hits, len(calls))
        brier = mean([o["brier"] for o in oc])
        base = [o for o in oc if o["base_in_range"] is not None]
        hit_pct = round(100 * hits / len(calls), 1) if calls else None
        if len(oc) < PROVEN_MIN:
            status, why = "unproven", f"{len(oc)} of the {PROVEN_MIN} settled forecasts needed before a verdict"
        elif hit_pct is not None and hit_pct > 50 and p is not None and p < P_MAX and brier is not None and brier < COIN_BRIER:
            status, why = "beats_coin_flip", f"direction right {hit_pct}% (p {p}), Brier {brier} vs {COIN_BRIER}"
        else:
            status, why = "no_edge", (f"direction right {hit_pct}% (p {p}), Brier {brier} vs {COIN_BRIER}: "
                                      "not better than a coin flip")
        out["horizons"][h] = {
            "settled": len(oc), "calls": len(calls), "hits": hits, "hit_pct": hit_pct, "p_value": p,
            "brier": brier, "coin_brier": COIN_BRIER,
            "always_up_hit_pct": pct([o["up"] for o in oc]),
            "range_hit_pct": pct([o["in_range"] for o in oc]), "range_width_pct": mean([o["width_pct"] for o in oc]),
            "base_range_hit_pct": pct([o["base_in_range"] for o in base]),
            "base_width_pct": mean([o["base_width_pct"] for o in base]),
            "status": status, "why": why,
        }
    return out
