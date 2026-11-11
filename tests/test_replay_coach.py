"""Market replay (services/replay_svc.py), your fills (scanner/fills.py), FYERS order updates (scanner/intraday/
order_feed.py) and the trade coach (services/coach_svc.py). Synthetic sessions and a fake Claude client: nothing here
reads the real data folder or calls an API."""
import json
import time
from types import SimpleNamespace

import pytest

from scanner import fills
from scanner.intraday import order_feed
from web.api.errors import ApiException
from web.api.paths import P
from web.api.services import ai_svc, coach_svc, data, holdings_svc, replay_svc


def _session(tf="5m"):
    # 2 context bars, then 4 to replay
    return {"symbol": "TCS", "tf": tf, "date": "2026-10-29", "start": 2, "capital": 500_000.0,
            "bars": {"t": [0, 300, 600, 900, 1200, 1500], "o": [100, 101, 100, 101, 104, 103],
                     "h": [101, 102, 101.5, 105, 105, 104], "l": [99, 100, 99.5, 100.5, 102, 98],
                     "c": [100.5, 101, 101, 104, 103, 99], "v": [0] * 6}}


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(P, "data", tmp_path)
    monkeypatch.setattr(data, "config", lambda: {"account": {"capital": 500_000}, "costs": {}})
    monkeypatch.setattr(replay_svc, "load", lambda symbol, tf, day: _session(tf))
    monkeypatch.setattr(holdings_svc, "rows", lambda lt: ([], False))
    monkeypatch.setattr(data, "latest", lambda: {})
    return tmp_path


def _trade(**kw):
    t = {"side": "LONG", "qty": 100, "entry_i": 2, "exit_i": 3, "entry": 101.1, "exit": 104.0, "stop": 99.0, "target": None,
         "reason": "manual"}
    return {**t, **kw}


def test_replay_pnl_is_recomputed_with_real_charges(env):
    row = replay_svc.save_result({"symbol": "TCS", "tf": "5m", "date": "2026-10-29", "last_i": 3, "trades": [_trade()]})
    t = row["trades"][0]
    assert t["gross"] == pytest.approx(290.0)
    assert 0 < t["charges"] < 20                       # intraday: brokerage capped at Rs 20 a side, no DP charge
    assert t["net"] == pytest.approx(t["gross"] - t["charges"])
    assert t["r"] == pytest.approx(t["net"] / (2.1 * 100), abs=0.01)
    assert row["buy_hold_pct"] == pytest.approx((104 / 101 - 1) * 100, abs=0.01)
    daily = replay_svc.save_result({"symbol": "TCS", "tf": "1d", "date": "2026-10-29", "last_i": 3, "trades": [_trade()]})
    assert daily["trades"][0]["charges"] > t["charges"]  # delivery: STT both sides + DP charge
    h = replay_svc.history()
    assert h["sessions"] == 2 and h["overall"]["trades"] == 2 and h["overall"]["win_rate"] == 100.0
    assert h["by_tf"]["5m"]["trades"] == 1 and h["recent"][0]["tf"] == "1d"


def test_replay_rejects_fills_outside_the_bars(env):
    with pytest.raises(ApiException, match="outside that bar"):
        replay_svc.save_result({"symbol": "TCS", "tf": "5m", "date": "2026-10-29", "trades": [_trade(exit=110.0)]})
    with pytest.raises(ApiException, match="outside the replay"):           # an entry in the context bars
        replay_svc.save_result({"symbol": "TCS", "tf": "5m", "date": "2026-10-29", "trades": [_trade(entry_i=1, entry=101.0)]})
    assert replay_svc.history()["sessions"] == 0


def test_fills_are_kept_once_and_matched_first_in_first_out(tmp_path):
    rows = [{"id": "1", "symbol": "TCS", "side": "BUY", "qty": 10, "price": 100, "time": "2026-11-02 10:00:00", "product": "CNC", "strategy_key": "momentum"},
            {"id": "2", "symbol": "TCS", "side": "BUY", "qty": 10, "price": 110, "time": "2026-11-03 10:00:00", "product": "CNC"},
            {"id": "3", "symbol": "TCS", "side": "SELL", "qty": 15, "price": 120, "time": "2026-11-05 10:00:00", "product": "CNC"}]
    assert fills.record(rows, tmp_path) == 3
    assert fills.record(rows[:1], tmp_path) == 0                             # same order id: not twice
    closed, still = fills.round_trips(fills.read(tmp_path))
    assert [(c["qty"], c["entry"], c["pnl"]) for c in closed] == [(10, 100, 200.0), (5, 110, 50.0)]
    assert closed[0]["strategy_key"] == "momentum"
    assert len(still) == 1 and still[0]["qty"] == 5


def test_order_socket_updates_are_written_once_and_fills_recorded(tmp_path):
    clock = [1000.0]
    feed = order_feed.OrderFeed(tmp_path / "live", data_dir=tmp_path, clock=lambda: clock[0])
    pending = {"orders": {"id": "A1", "symbol": "NSE:TCS-EQ", "side": 1, "status": 6, "qty": 10, "filledQty": 0}}
    filled = {"orders": {"id": "A1", "symbol": "NSE:TCS-EQ", "side": 1, "status": 2, "qty": 10, "filledQty": 10,
                         "tradedPrice": 3512.0, "productType": "CNC", "orderDateTime": "11-Nov-2026 10:01:02"}}
    feed.on_order(pending)
    feed.on_order(pending)                                                     # repeated after a reconnect: ignored
    feed.on_order(filled)
    assert [e["status"] for e in feed.events] == ["pending", "filled"]
    assert feed.events[-1]["text"] == "BUY 10 TCS filled at 3,512.00"
    assert fills.read(tmp_path)[0] | {} == fills.read(tmp_path)[0] and fills.read(tmp_path)[0]["price"] == 3512.0
    feed.set_connected(True)
    assert feed.write() and not feed.write()                                   # nothing new: no rewrite
    clock[0] += order_feed.HEARTBEAT_S + 1
    assert feed.write()                                                        # heartbeat
    st = order_feed.status(tmp_path / "live", now=clock[0] + 1)
    assert st["connected"] and st["seq"] == 2
    assert not order_feed.status(tmp_path / "live", now=clock[0] + order_feed.FRESH_S + 5)["connected"]
    seq, evs = order_feed.since(tmp_path / "live", 0, started=0)
    assert seq == 2 and [e["seq"] for e in evs] == [1, 2]
    assert order_feed.since(tmp_path / "live", 2, started=0)[1] == []
    assert order_feed.since(tmp_path / "live", 0, started=time.time() + 10_000)[1] == []    # a new tab: no old ones
    rej = order_feed.normalize({"id": "B", "symbol": "NSE:INFY-EQ", "side": -1, "status": 5, "qty": 3, "message": "RMS: margin"})
    assert order_feed.text(rej) == "SELL 3 INFY rejected: RMS: margin"


def _practice_log(env, n=12):
    trades = []
    for i in range(n):
        win = i % 3 == 0
        trades.append(_trade(exit=104.0 if win else 100.0, exit_i=3, stop=99.0 if i % 2 else None,
                             reason="manual"))
    for k in range(0, n, 4):
        replay_svc.save_result({"symbol": "TCS", "tf": "5m", "date": "2026-10-29", "blind": k == 0, "last_i": 3,
                                "trades": trades[k:k + 4]})


def test_coach_numbers_come_from_your_own_record(env):
    assert coach_svc.facts()["practice"] is None
    with pytest.raises(ApiException, match="Nothing to review"):
        coach_svc.review()
    _practice_log(env)
    f = coach_svc.facts()
    p = f["practice"]
    assert p["summary"]["trades"] == 12 and p["sessions"] == 3
    assert p["stops"]["with_stop_pct"] == 50.0
    assert p["overtrading"]["in_sessions_with_4_plus_trades"]["trades"] == 12
    assert set(p["blind_vs_named"]) == {"blind", "named"}
    assert p["largest_loss_vs_avg_win"] > 0 and p["charges"]["total"] > 0
    assert f["sample"]["enough"] is False


class _FakeMessages:
    def __init__(self, answer):
        self.answer, self.calls = answer, []

    def create(self, **kw):
        self.calls.append(kw)
        return SimpleNamespace(stop_reason="end_turn", model="claude-opus-5-5",
                               content=[SimpleNamespace(type="text", text=json.dumps(self.answer))])


def test_coach_review_sends_only_the_numbers_and_is_kept(env, monkeypatch):
    _practice_log(env)
    answer = {"headline": "Stops help you.", "strengths": [], "leaks": [{"title": "No stop", "evidence": "6 of 12",
              "cost": "Rs 200", "fix": "Always set one"}], "rules": ["If a trade has no stop, then don't enter it."],
              "next_focus": "Blind replays.", "sample_note": "12 trades: a first hint."}
    fake = _FakeMessages(answer)
    monkeypatch.setattr(ai_svc, "_get_client", lambda: SimpleNamespace(beta=SimpleNamespace(messages=fake)))
    out = coach_svc.review()
    assert out["review"] == answer
    kw = fake.calls[0]
    assert kw["model"] == "claude-opus-5-5" and kw["fallbacks"] == "default"
    assert kw["output_config"]["format"]["type"] == "json_schema" and kw["thinking"] == {"type": "adaptive"}
    sent = kw["messages"][0]["content"]
    assert '"practice"' in sent and "ANTHROPIC" not in sent
    v = coach_svc.view()
    assert v["review"]["key"] == out["key"] and v["stale"] is False
    replay_svc.save_result({"symbol": "TCS", "tf": "5m", "date": "2026-10-29", "trades": [_trade()]})
    assert coach_svc.view()["stale"] is True                                   # new trades since the review
