"""AI analyst (web/api/services/ai_svc.py): no key = a clear 501, the key never leaves the server, the request carries
the platform's data and the fallback opt-in, refusals are reported, and repeat questions are served from the cache.
A fake client stands in for Anthropic: these tests never call the network or spend money."""
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from web.api.main import create_app
from web.api.services import ai_svc

GUARD = {"X-Quant-Desk": "1", "Origin": "http://127.0.0.1"}


class FakeStream:
    def __init__(self, msg, seen, kwargs):
        self.msg, self.seen, self.kwargs = msg, seen, kwargs

    def __enter__(self):
        self.seen.append(self.kwargs)
        return self

    def __exit__(self, *a):
        return False

    def get_final_message(self):
        return self.msg


def fake_client(msg, seen):
    return SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(stream=lambda **kw: FakeStream(msg, seen, kw))))


def _msg(text="**In short** fine.", stop="end_turn"):
    return SimpleNamespace(stop_reason=stop, model=ai_svc.MODEL, content=[SimpleNamespace(type="text", text=text)],
                           usage=SimpleNamespace(input_tokens=6000, output_tokens=800, cache_read_input_tokens=0))


@pytest.fixture
def client(monkeypatch):
    ai_svc._cache.clear()
    return TestClient(create_app(warm=False), base_url="http://127.0.0.1")


def test_no_key_is_a_clear_501(client, monkeypatch):
    monkeypatch.setattr(ai_svc, "_key", lambda: "")
    r = client.post("/api/ai/analyze", json={"symbol": "NIFTY50"}, headers=GUARD)
    assert r.status_code == 501 and r.json()["error"]["code"] == "FEATURE_UNAVAILABLE"
    assert client.get("/api/ai/status").json()["configured"] is False


def test_status_never_returns_the_key(client, monkeypatch):
    monkeypatch.setattr(ai_svc, "_key", lambda: "test-only-not-a-real-key-123")
    body = client.get("/api/ai/status").text
    assert "test-only-not-a-real-key-123" not in body and '"configured":true' in body.replace(" ", "")


def test_analysis_sends_the_data_and_the_fallback_opt_in(client, monkeypatch):
    seen = []
    monkeypatch.setattr(ai_svc, "_get_client", lambda: fake_client(_msg(), seen))
    r = client.post("/api/ai/analyze", json={"symbol": "NIFTY50", "question": "Is it a buy?"}, headers=GUARD)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["answer"].startswith("**In short**") and not out["refused"] and not out["cached"]
    kw = seen[0]
    assert kw["model"] == "claude-opus-5-5" and kw["fallbacks"] == "default"
    assert kw["betas"] == ["server-side-fallback-2026-07-01"] and kw["thinking"] == {"type": "adaptive"}
    user = kw["messages"][0]["content"]
    assert "<snapshot>" in user and '"symbol":"NIFTY50"' in user and "Is it a buy?" in user
    assert "Never override it" in kw["system"][0]["text"]
    again = client.post("/api/ai/analyze", json={"symbol": "NIFTY50", "question": "Is it a buy?"}, headers=GUARD).json()
    assert again["cached"] and len(seen) == 1                 # the same question on the same data: not billed twice


def test_refusal_is_reported_not_shown_as_an_answer(client, monkeypatch):
    seen = []
    monkeypatch.setattr(ai_svc, "_get_client", lambda: fake_client(_msg(text="partial", stop="refusal"), seen))
    out = client.post("/api/ai/analyze", json={"symbol": "NIFTY50"}, headers=GUARD).json()
    assert out["refused"] and out["answer"] is None


def test_analyze_needs_the_guard_header(client):
    assert client.post("/api/ai/analyze", json={"symbol": "NIFTY50"}).status_code == 403
