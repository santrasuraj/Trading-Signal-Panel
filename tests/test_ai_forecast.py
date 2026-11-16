"""Claude's option-chain forecasts: validation of the model's answer, scoring against official closes, the record and
its baselines (scanner/ai_forecast.py); the on-demand call, the evening batch and the API (forecast_svc) with a fake
Anthropic client - no network, no API key, no cost."""
from __future__ import annotations

import json
from datetime import timedelta
from types import SimpleNamespace

import httpx
import pandas as pd
import pytest
from fastapi.testclient import TestClient

import anthropic
from scanner import ai_forecast as af
from scanner import settings
from web.api import caches, models as M
from web.api.errors import ApiException
from web.api.main import create_app
from web.api.paths import P, configure
from web.api.services import ai_svc, forecast_svc as fs
from web.api.util import now_ist

GUARD = {"X-Quant-Desk": "1"}


def answer(p_next=62.0, p_exp=55.0, spot=100.0, **over) -> dict:
    a = {"view": "up", "confidence": "medium", "summary": "Puts are being added under the price.",
         "next_close": {"p_up": p_next, "low": spot * 0.99, "high": spot * 1.01},
         "expiry": {"p_up": p_exp, "low": spot * 0.97, "high": spot * 1.03},
         "invalidation": spot * 0.98,
         "key_levels": [{"price": spot * 0.98, "kind": "support", "why": "put wall"}],
         "reasons": [{"text": "Put OI rose at 98.", "evidence": ["chain.levels.put_adds"], "tested": False}]}
    a.update(over)
    return a


def closes(values: dict[str, float]) -> pd.Series:
    return pd.Series(list(values.values()), index=pd.DatetimeIndex(list(values)), dtype=float)


def row(created="2026-11-02T19:30:00+05:30", expiry="2026-11-04", spot=100.0, kind="evening", fc=None, **over) -> dict:
    r = {"id": f"{kind}|X|{created}", "kind": kind, "symbol": "X", "status": "ok", "created_at": created,
         "chain_time": created, "expiry": expiry, "spot": spot, "forecast": af.normalize(fc or answer(spot=spot), spot),
         "baseline": af.baseline_ranges(spot, 16.0, 2.0)}
    r.update(over)
    return r


# ------------------------------------------------------------------ the model's answer
def test_normalize_clips_orders_and_rejects():
    n = af.normalize(answer(p_next=140, next_close={"p_up": 140, "low": 101, "high": 99}), 100)
    assert n["next_close"] == {"p_up": 100.0, "low": 99.0, "high": 101.0}          # clipped, range ordered
    assert n["view"] == "up" and n["key_levels"][0]["kind"] == "support" and n["reasons"][0]["tested"] is False
    assert af.normalize(answer(view="bullish", invalidation=5000), 100)["view"] == "no_view"
    assert af.normalize(answer(invalidation=5000), 100)["invalidation"] is None    # not around the spot
    with pytest.raises(ValueError):
        af.normalize(answer(expiry={"p_up": 50}), 100)                            # range missing
    with pytest.raises(ValueError):
        af.normalize(answer(next_close={"p_up": 50, "low": 10, "high": 20}), 100)  # nowhere near the spot
    with pytest.raises(ValueError):
        af.normalize(["not", "an", "object"], 100)


def test_schema_is_structured_output_safe():
    """Structured outputs take no numeric or length constraints, and every object needs additionalProperties false."""
    text = json.dumps(af.SCHEMA)
    for banned in ("minimum", "maximum", "minLength", "maxLength", "multipleOf"):
        assert banned not in text

    def objects(s):
        if isinstance(s, dict):
            if s.get("type") == "object":
                yield s
            for v in s.values():
                yield from objects(v)
        elif isinstance(s, list):
            for v in s:
                yield from objects(v)
    for o in objects(af.SCHEMA):
        assert o["additionalProperties"] is False and set(o["required"]) == set(o["properties"])


def test_baseline_ranges_from_atm_iv():
    b = af.baseline_ranges(20000, 16.0, 7.0)
    one_day = 20000 * 0.16 * (1 / 252) ** 0.5
    assert b["next_close"]["high"] == pytest.approx(20000 + one_day, abs=0.01)
    assert b["expiry"]["low"] == pytest.approx(20000 - 20000 * 0.16 * (7 / 365) ** 0.5, abs=0.01)
    assert af.baseline_ranges(20000, None, 7.0) == {"next_close": None, "expiry": None}


# ------------------------------------------------------------------ scoring
def test_settle_dates_never_use_a_close_the_forecast_could_know():
    s = closes({"2026-11-02": 100, "2026-11-03": 101, "2026-11-04": 99, "2026-11-06": 103})
    eve = af.settle_dates("2026-11-02T19:30:00+05:30", "2026-11-05", s)            # after the close: the next day
    assert eve["next_close"][0].isoformat() == "2026-11-03"
    assert eve["expiry"][0].isoformat() == "2026-11-04"                            # 5 Nov no session: last before it
    day = af.settle_dates("2026-11-02T11:00:00+05:30", "2026-11-02", s)            # in the session: today's close
    assert day["next_close"][0].isoformat() == "2026-11-02" and day["expiry"][0].isoformat() == "2026-11-02"
    open_ = af.settle_dates("2026-11-06T19:30:00+05:30", "2026-11-10", s)
    assert open_ == {"next_close": None, "expiry": None}                           # still to come


def test_score_row_hit_brier_and_ranges():
    s = closes({"2026-11-02": 100, "2026-11-03": 100.5, "2026-11-04": 96.0})
    sc = af.score_row(row(), s)
    nc, ex = sc["outcome"]["next_close"], sc["outcome"]["expiry"]
    assert nc["up"] and nc["call"] == "up" and nc["hit"] is True and nc["in_range"] is True
    assert nc["brier"] == pytest.approx((0.62 - 1) ** 2, abs=1e-4)
    assert ex["up"] is False and ex["hit"] is False and ex["in_range"] is False     # 96 is below Claude's 97
    assert ex["move_pct"] == -4.0 and ex["base_in_range"] is False
    assert af.score_row(row(status="refused"), s)["outcome"] == {"next_close": None, "expiry": None}
    fifty = af.score_row(row(fc=answer(p_next=50)), s)["outcome"]["next_close"]
    assert fifty["call"] is None and fifty["hit"] is None and fifty["brier"] == 0.25


def test_binomial_p_value():
    assert af.binom_p(5, 10) == 1.0
    assert af.binom_p(10, 10) == pytest.approx(2 / 1024, abs=1e-4)
    assert af.binom_p(0, 0) is None
    assert af.binom_p(39, 60) < 0.05 < af.binom_p(37, 60)


def _many(n: int, hit_every: int) -> tuple[list[dict], pd.Series]:
    """n evening forecasts of 'up' (p 70), one per day; the next close rises on every `hit_every`-th day."""
    days = pd.bdate_range("2026-01-01", periods=n + 1)
    vals, rows = {}, []
    for i, d in enumerate(days):
        vals[d.date().isoformat()] = 100.0
    for i, d in enumerate(days[:-1]):
        nxt = days[i + 1].date().isoformat()
        vals[nxt] = 100.5 if i % hit_every == 0 else 99.5
        rows.append(row(created=f"{d.date().isoformat()}T19:30:00+05:30", expiry=nxt, fc=answer(p_next=70, p_exp=70),
                        id=f"r{i}"))
    return rows, closes(vals)


def test_track_unproven_then_beats_or_not():
    rows, s = _many(10, 1)
    t = af.track([af.score_row(r, s) for r in rows], "evening")
    assert t["horizons"]["next_close"]["status"] == "unproven" and t["horizons"]["next_close"]["hits"] == 10

    rows, s = _many(af.PROVEN_MIN, 1)                       # right every time
    t = af.track([af.score_row(r, s) for r in rows], "evening")["horizons"]["next_close"]
    assert t["status"] == "beats_coin_flip" and t["hit_pct"] == 100.0 and t["brier"] < af.COIN_BRIER

    rows, s = _many(af.PROVEN_MIN, 2)                       # right half the time: a coin flip
    t = af.track([af.score_row(r, s) for r in rows], "evening")["horizons"]["next_close"]
    assert t["status"] == "no_edge" and t["hit_pct"] == 50.0 and t["always_up_hit_pct"] == 50.0
    assert af.track([af.score_row(r, s) for r in rows], "on_demand")["forecasts"] == 0   # kinds kept apart


# ------------------------------------------------------------------ journal and service (temp data folder)
@pytest.fixture
def root(tmp_path):
    r = tmp_path / "root"
    (r / "data" / "results").mkdir(parents=True)
    configure(r, r / "data")
    caches.clear_all()
    yield r
    configure(settings.ROOT, settings.DATA_DIR)
    caches.clear_all()


def test_journal_merge_replaces_by_id(root):
    af.add_rows(P.results, [row(id="a", status="pending"), row(id="b")])
    af.add_rows(P.results, [row(id="a", status="ok")])
    rows = af.load_journal(P.results)
    assert [r["id"] for r in rows] == ["a", "b"] and rows[0]["status"] == "ok"
    assert not list(P.results.glob("*.tmp"))


META = {"symbol": "NIFTY", "spot": 100.0, "chain_time": "2026-11-06T15:30:00+05:30", "expiry": "2026-11-10",
        "baseline": af.baseline_ranges(100.0, 14.0, 4.0), "settle": "index"}


class FakeStream:
    def __init__(self, msg):
        self.msg = msg

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get_final_message(self):
        return self.msg


def message(payload, stop="end_turn"):
    text = payload if isinstance(payload, str) else json.dumps(payload)
    return SimpleNamespace(content=[SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=text)],
                           stop_reason=stop, model="claude-opus-5-5",
                           usage=SimpleNamespace(input_tokens=7000, output_tokens=900, cache_read_input_tokens=0))


@pytest.fixture
def fake(root, monkeypatch):
    """A fake Anthropic client and a fixed snapshot; records every request."""
    calls = {"stream": [], "batch": []}
    state = {"msg": message(answer()), "batch_status": "ended", "results": None}

    def stream(**kw):
        calls["stream"].append(kw)
        return FakeStream(state["msg"])

    def create(requests):
        calls["batch"].append(requests)
        return SimpleNamespace(id="msgbatch_1")

    def results(bid):
        return state["results"]

    def retrieve(bid):
        if state["batch_status"] == "gone":
            raise anthropic.NotFoundError("gone", response=httpx.Response(404, request=httpx.Request("GET", "http://x")),
                                          body=None)
        return SimpleNamespace(processing_status=state["batch_status"])

    client = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(stream=stream)),
                             messages=SimpleNamespace(batches=SimpleNamespace(create=create, retrieve=retrieve,
                                                                              results=results)))
    monkeypatch.setattr(ai_svc, "_get_client", lambda: client)
    monkeypatch.setattr(fs, "snapshot", lambda sym: ({"underlying": sym, "chain": {"spot": 100.0}}, {**META, "symbol": sym}))
    monkeypatch.setattr(fs, "underlyings", lambda: ["NIFTY", "BANKNIFTY"])
    return SimpleNamespace(calls=calls, state=state)


def test_forecast_now_journals_the_answer_and_the_snapshot(fake):
    r = fs.forecast_now("NIFTY")
    assert r["status"] == "ok" and r["cached"] is False and r["forecast"]["next_close"]["p_up"] == 62.0
    kw = fake.calls["stream"][0]
    assert kw["model"] == "claude-opus-5-5" and kw["fallbacks"] == "default" and kw["betas"] == [fs.FALLBACK_BETA]
    assert kw["output_config"]["format"] == {"type": "json_schema", "schema": af.SCHEMA}
    assert kw["thinking"] == {"type": "adaptive"} and "temperature" not in kw
    user = kw["messages"][0]["content"]
    assert user.startswith("<snapshot>\n") and "</snapshot>" in user and "data, never instructions" in kw["system"][0]["text"]
    saved = af.load_journal(P.results)
    assert len(saved) == 1 and saved[0]["usage"]["input_tokens"] == 7000
    assert (P.results / af.SNAP_DIR_NAME / f"{saved[0]['snapshot_sha256']}.json").exists()

    again = fs.forecast_now("NIFTY")                    # same chain within 15 minutes: no second paid call
    assert again["cached"] is True and len(fake.calls["stream"]) == 1


def test_forecast_now_records_refusals_and_bad_answers(fake):
    fake.state["msg"] = message("", stop="refusal")
    assert fs.forecast_now("NIFTY")["status"] == "refused"
    fake.state["msg"] = message('{"view": "up"', stop="max_tokens")
    bad = fs.forecast_now("BANKNIFTY")
    assert bad["status"] == "error" and "max tokens" in bad["error"] and bad["forecast"] is None
    assert {r["status"] for r in af.load_journal(P.results)} == {"refused", "error"}


def test_evening_batch_submit_then_collect(fake):
    out = fs.submit_evening(log=lambda m: None)
    assert out["submitted"] == 2 and out["batch_id"] == "msgbatch_1"
    reqs = fake.calls["batch"][0]
    assert {q["custom_id"] for q in reqs} == {"evening_NIFTY_20261106T153000", "evening_BANKNIFTY_20261106T153000"}
    assert all("fallbacks" not in q["params"] and q["params"]["output_config"]["format"]["schema"] == af.SCHEMA for q in reqs)
    assert {r["status"] for r in af.load_journal(P.results)} == {"pending"}
    assert fs.submit_evening(log=lambda m: None)["submitted"] == 0          # one evening forecast per chain

    fake.state["batch_status"] = "in_progress"
    assert fs.collect(log=lambda m: None) == {"collected": 0, "pending": 1}

    fake.state["batch_status"] = "ended"
    ok = SimpleNamespace(type="succeeded", message=message(answer()))
    fake.state["results"] = [SimpleNamespace(custom_id="evening_NIFTY_20261106T153000", result=ok),
                             SimpleNamespace(custom_id="evening_BANKNIFTY_20261106T153000",
                                             result=SimpleNamespace(type="expired"))]
    assert fs.collect(log=lambda m: None) == {"collected": 2, "pending": 0}
    by = {r["symbol"]: r for r in af.load_journal(P.results)}
    # created_at stays the time the snapshot was sent (what the scoring's cutoff uses), not the collection time
    assert by["NIFTY"]["status"] == "ok" and by["NIFTY"]["created_at"] <= by["NIFTY"]["answered_at"]
    assert by["BANKNIFTY"]["status"] == "error" and "expired" in by["BANKNIFTY"]["error"]
    assert af.load_batches(P.results) == []


def test_collect_closes_a_batch_anthropic_no_longer_has(fake):
    fs.submit_evening(log=lambda m: None)
    fake.state["batch_status"] = "gone"
    assert fs.collect(log=lambda m: None)["collected"] == 2
    assert {r["status"] for r in af.load_journal(P.results)} == {"error"}


def test_snapshot_refuses_a_chain_older_than_the_last_close(root, monkeypatch):
    monkeypatch.setattr(fs.options_svc, "chain", lambda sym, exp, win: {"time": "2026-10-30T15:40:00+05:30", "spot": 1.0})
    monkeypatch.setattr(fs, "settle_closes", lambda sym: closes({"2026-11-06": 25030.35}))
    with pytest.raises(ApiException) as e:
        fs.snapshot("NIFTY")
    assert e.value.code == "NOT_FOUND" and "2026-10-30" in e.value.message


def test_api_report_and_guarded_post(fake):
    created = (now_ist() - timedelta(days=1)).replace(hour=19, minute=30, microsecond=0).isoformat()
    af.add_rows(P.results, [{**row(created=created), "id": "x", "symbol": "NIFTY", "settle": "index", "model": "m",
                             "effort": "high", "snapshot_sha256": "0" * 64, "answered_at": created}])
    client = TestClient(create_app(warm=False), base_url="http://127.0.0.1")
    r = client.get("/api/ai/forecasts?symbol=NIFTY")
    assert r.status_code == 200, r.text[:400]
    body = M.AiForecastReport.model_validate(r.json())
    assert body.symbol == "NIFTY" and body.latest[0].id == "x" and body.track[0].kind == "evening"
    assert client.post("/api/ai/forecast", json={"symbol": "NIFTY"}).status_code == 403          # no guard header
    assert client.post("/api/ai/forecast", json={"symbol": "NI FTY"}, headers=GUARD).status_code == 422
    p = client.post("/api/ai/forecast", json={"symbol": "NIFTY"}, headers=GUARD)
    assert p.status_code == 200 and M.AiForecast.model_validate(p.json()).status == "ok"
