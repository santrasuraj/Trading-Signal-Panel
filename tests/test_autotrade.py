"""High-speed auto-trader on the practice account (web/api/services/autotrade_svc.py): entries from the intraday
signal file with the signal's stop and target, exits by stop / strategy / 15:00 square-off / kill switch, the limits,
the speed and slippage record, and one-lot index option practice trades. Synthetic quotes and files; nothing is sent
anywhere."""
from datetime import date, datetime

import pandas as pd
import pytest

from scanner.settings import IST

DAY = datetime(2026, 11, 16, 10, 2, tzinfo=IST)


def at_(h, m, s=0):
    return DAY.replace(hour=h, minute=m, second=s)


def sig(sym="SBIN", side="LONG", entry=100.0, stop=99.0, target=102.0, t="10:00", state="open", key="sweep_pdhl",
        proven=False, status="untested", qty=200, reason="open"):
    return {"strategy_key": key, "strategy_name": key, "symbol": sym, "side": side, "entry_time": t, "entry": entry,
            "stop": stop, "target": target, "qty": qty, "amount": qty * entry, "state": state, "exit_time": None,
            "exit": None, "last": entry, "reason": reason, "pnl": 0.0, "ret_pct": 0.0, "proven": proven,
            "strategy_status": status}


def q(price, source="live"):
    return {"symbol": "", "price": price, "source": source, "time": DAY.isoformat()}


@pytest.fixture
def eng(tmp_path, monkeypatch):
    from web.api.services import autotrade_svc as at, clock, data, sim_svc
    monkeypatch.setattr(at, "_path", lambda: tmp_path / "autotrade.json")
    monkeypatch.setattr(at, "_capital", lambda: 500000.0)
    monkeypatch.setattr(data, "config", lambda: {"account": {"capital": 500000}, "intraday": {"leverage": 2.0}})
    world = {"session": "open", "quotes": {}, "signals": ({}, None), "now": DAY}
    monkeypatch.setattr(sim_svc, "now_ist", lambda: world["now"])     # the practice account's 15:20 square-off clock
    monkeypatch.setattr(at, "now_ist", lambda: world["now"])
    real_tick = at.tick

    def tick(now=None):
        world["now"] = now or world["now"]
        return real_tick(world["now"])

    monkeypatch.setattr(at, "tick", tick)
    monkeypatch.setattr(clock, "market_clock", lambda: {"session": world["session"]})
    monkeypatch.setattr(at, "_quotes", lambda syms: {s: {**world["quotes"][s], "symbol": s} for s in syms
                                                     if s in world["quotes"]})
    monkeypatch.setattr(at, "_signals", lambda now: world["signals"])
    monkeypatch.setattr(at, "today_ist", lambda: DAY.date())
    at.settings({"on": True, "options": False})
    return at, world


def signals(*rows, gen=None):
    import time
    return {"generated_at": (gen or at_(10, 1)).isoformat(), "signals": list(rows)}, time.time() - 0.2


def test_an_open_signal_is_entered_at_once_with_its_stop_target_and_speed_record(eng):
    at, w = eng
    w["signals"] = signals(sig())
    w["quotes"] = {"SBIN": q(100.3)}
    out = at.tick(DAY)
    st = at._load()
    rec = st["open"]["SBIN"]
    pos = st["account"]["positions"]["SBIN"]
    assert pos["qty"] == 200 and pos["stop"] == 99.0 and pos["target"] == 102.0
    assert rec["fill"] > 100.3                                   # bought at the live price plus slippage
    assert rec["slippage_bps"] > 30                              # vs the signal's 100.00
    assert rec["signal_lag_s"] == 60.0 and rec["react_ms"] >= 0 and rec["strategy_status"] == "untested"
    assert any(e["kind"] == "entry" for e in out["events"])
    at.tick(DAY.replace(second=5))                               # the same signal again: never a second order
    assert len([o for o in at._load()["account"]["orders"] if o.get("by") == "autotrade"]) == 1


def test_proven_mode_skips_signals_the_backtest_has_not_proven(eng):
    at, w = eng
    at.settings({"mode": "proven"})
    w["signals"] = signals(sig(), sig("TCS", proven=True, status="working", entry=3000.0, stop=2970.0, target=3060.0))
    w["quotes"] = {"SBIN": q(100.0), "TCS": q(3000.0)}
    at.tick(DAY)
    assert set(at._load()["open"]) == {"TCS"}


def test_stop_on_the_next_price_update_books_the_loss_after_charges(eng):
    at, w = eng
    w["signals"] = signals(sig())
    w["quotes"] = {"SBIN": q(100.0)}
    at.tick(DAY)
    w["quotes"] = {"SBIN": q(98.9)}
    at.tick(DAY.replace(second=30))
    st = at._load()
    assert "SBIN" not in st["open"] and "SBIN" not in st["account"]["positions"]
    (t,) = st["closed"]
    assert t["exit_reason"] == "stop" and t["pnl_net"] < t["pnl_gross"] < 0 and t["charges"] > 0


def test_strategy_exit_and_the_1500_square_off_close_positions(eng):
    at, w = eng
    w["signals"] = signals(sig(), sig("TCS", entry=3000.0, stop=2970.0, target=3060.0))
    w["quotes"] = {"SBIN": q(100.0), "TCS": q(3000.0)}
    at.tick(DAY)
    w["signals"] = signals(sig(state="closed", reason="flip"), sig("TCS", entry=3000.0, stop=2970.0, target=3060.0))
    at.tick(at_(10, 6))
    st = at._load()
    assert "SBIN" not in st["open"] and st["closed"][0]["exit_reason"] == "strategy exit (flip)"
    at.tick(at_(15, 0, 1))
    st = at._load()
    assert st["open"] == {} and st["closed"][-1]["exit_reason"] == "square-off 15:00"


def test_limits_late_busy_and_daily_loss(eng):
    at, w = eng
    at.settings({"max_late_min": 5})
    w["signals"] = signals(sig(t="09:40"), sig("TCS", entry=3000.0, stop=2970.0, target=3060.0))
    w["quotes"] = {"SBIN": q(100.0), "TCS": q(3000.0)}
    at.tick(DAY)
    st = at._load()
    assert set(st["open"]) == {"TCS"} and any("too late" in v for v in st["skipped"].values())
    w["signals"] = signals(sig("TCS", key="orb15", entry=3000.0, stop=2970.0, target=3060.0))
    at.tick(DAY.replace(second=10))
    assert any("already holding" in v for v in at._load()["skipped"].values())
    at.settings({"daily_loss_pct": 0.1})                          # Rs 500 on Rs 5 lakh
    w["quotes"] = {"TCS": q(2985.0)}                              # an open loss of about Rs 1,000+
    w["signals"] = signals(sig("INFY", entry=1500.0, stop=1485.0, target=1530.0))
    w["quotes"]["INFY"] = q(1500.0)
    at.tick(DAY.replace(second=20))
    st = at._load()
    assert "INFY" not in st["open"] and any("daily loss stop" in v for v in st["skipped"].values())


def test_kill_switch_turns_the_engine_off_and_closes_everything(eng):
    at, w = eng
    w["signals"] = signals(sig())
    w["quotes"] = {"SBIN": q(100.0)}
    at.tick(DAY)
    v = at.stop_all()
    assert v["settings"]["on"] is False and v["positions"] == [] and at._load()["closed"][0]["exit_reason"] == "kill switch"


def test_a_buy_verdict_buys_one_lot_at_the_chains_ask_and_settles_at_expiry(eng, monkeypatch):
    at, w = eng
    from scanner import option_verdict as ov
    from scanner.intraday import fyers_sync
    from web.api.services import data, options_svc
    at.settings({"on": False, "options": True})
    row = {"id": "NIFTY|2026-11-17|2026-11-13", "day": "2026-11-13", "symbol": "NIFTY", "expiry": "2026-11-17",
           "verdict": "BUY_CALL", "side": "ce", "strike": 25150.0, "premium": 137.75, "lot": 65}
    monkeypatch.setattr(ov, "load_journal", lambda: [row])
    monkeypatch.setattr(fyers_sync, "last_complete_day", lambda: date(2026, 11, 13))
    chain = {"time": DAY.isoformat(), "rows": [{"strike": 25150.0, "ce": {"ask": 140.0, "bid": 139.5, "ltp": 139.8}}]}
    monkeypatch.setattr(options_svc, "chain", lambda s, e, w_: chain)
    at.tick(DAY)
    (p,) = at._load()["options"]["open"]
    assert p["premium"] == 140.0 and p["lot"] == 65 and p["cost_unit"] == pytest.approx(ov.buy_cost(140.0, 65), abs=1e-4)
    after = datetime(2026, 11, 18, 10, 0, tzinfo=IST)                # the day after expiry: settled
    monkeypatch.setattr(at, "today_ist", lambda: after.date())
    monkeypatch.setattr(ov, "load_index_history", lambda: pd.DataFrame({"Nifty 50": [25300.0]},
                                                                       index=pd.to_datetime(["2026-11-17"])))
    monkeypatch.setattr(data, "store_close", lambda: pd.DataFrame())
    w["session"] = "closed"
    at.tick(after)
    st = at._load()
    (c,) = st["options"]["closed"]
    want = (float(ov.expiry_value(150.0, 65)) - ov.buy_cost(140.0, 65)) * 65
    assert st["options"]["open"] == [] and c["settle"] == 25300.0 and c["pnl_net"] == pytest.approx(want, abs=0.02)


# ------------------------------------------------------------------ the speed path: tick bus, live engine, memory state
def test_a_bus_tick_through_the_stop_closes_at_once_and_is_timed(eng):
    import time as _t
    from web.api.services import latency_svc
    at, w = eng
    latency_svc.reset()
    w["signals"] = signals(sig())
    w["quotes"] = {"SBIN": q(100.3)}
    at.tick(DAY)
    assert "SBIN" in at._held                                   # the bus thread's quick check knows the position
    at.on_tick("INFY", {"price": 1.0, "bus_ts": _t.time()})     # not held: ignored
    at.on_tick("SBIN", {"price": 99.5, "bus_ts": _t.time(), "exch_ts": None})      # above the 99 stop: nothing
    assert "SBIN" in at._load()["open"]
    at.on_tick("SBIN", {"price": 98.9, "bus_ts": _t.time(), "exch_ts": DAY.timestamp()})
    st = at._load()
    assert "SBIN" not in st["open"] and st["closed"][-1]["exit_reason"] == "stop" and "SBIN" not in at._held
    assert {r["name"]: r for r in latency_svc.summary()}["tick_to_exit"]["n"] == 1


def test_the_live_engines_signals_win_unless_the_file_has_later_bars(tmp_path, monkeypatch):
    import json as _json
    from web.api.paths import P
    from web.api.services import autotrade_svc as at, livesig_svc
    monkeypatch.setattr(P, "data", tmp_path)
    (tmp_path / "results").mkdir()
    f = {"generated_at": DAY.isoformat(), "bars_to": "2026-11-16T09:55:00", "signals": [sig(t="09:55")]}
    (tmp_path / "results" / "intraday_signals.json").write_text(_json.dumps(f), encoding="utf-8")
    live = {"generated_at": DAY.isoformat(), "bars_to": "2026-11-16T10:00:00", "engine": "live", "signals": [sig()]}
    monkeypatch.setattr(livesig_svc, "latest", lambda: (live, 123.0))
    assert at._signals(DAY) == (live, 123.0)
    monkeypatch.setattr(livesig_svc, "latest", lambda: ({**live, "bars_to": "2026-11-16T09:50:00"}, 123.0))
    got, mtime = at._signals(DAY)
    assert got["bars_to"] == "2026-11-16T09:55:00" and mtime is not None       # the task's file is newer
    monkeypatch.setattr(livesig_svc, "latest", lambda: (None, None))
    assert at._signals(DAY.replace(day=17)) == ({}, None)                      # yesterday's file: nothing today


def test_state_stays_in_memory_until_the_file_changes(eng):
    import json as _json
    at, w = eng
    a = at._load()
    assert at._load() is a                                       # no re-read while the file is unchanged
    st = _json.loads(at._path().read_text(encoding="utf-8"))
    st["settings"]["max_positions"] = 7
    at._path().write_text(_json.dumps(st), encoding="utf-8")     # changed outside this process
    b = at._load()
    assert b is not a and b["settings"]["max_positions"] == 7


def test_bus_quotes_come_first_then_the_quote_service(monkeypatch):
    from web.api.services import autotrade_svc as at, quotes_svc, tickbus_svc
    monkeypatch.setattr(at, "now_ist", lambda: DAY)
    monkeypatch.setattr(tickbus_svc, "latest", lambda s, max_age_s=5.0: {"price": 812.5, "exch_ts": DAY.timestamp()}
                        if s == "SBIN" else None)
    asked = []
    monkeypatch.setattr(quotes_svc, "quotes", lambda syms, allow_network=True: (
        asked.append(list(syms)), {"quotes": [{"symbol": s, "price": 1.0, "source": "yahoo"} for s in syms]})[1])
    out = at._quotes(["SBIN", "INFY"])
    assert out["SBIN"]["price"] == 812.5 and out["SBIN"]["bus"] and out["SBIN"]["source"] == "live"
    assert out["SBIN"]["time"] == DAY.isoformat(timespec="seconds") and asked == [["INFY"]]


def test_speed_endpoint_and_prometheus_metrics(monkeypatch):
    from fastapi.testclient import TestClient
    from web.api.main import create_app
    from web.api.services import latency_svc
    latency_svc.reset()
    for x in (0.002, 0.004, 0.010):
        latency_svc.record("tick_transport", x)
    latency_svc.record("tick_age", -0.5)                         # clock skew: never recorded as a latency
    c = TestClient(create_app(warm=False), base_url="http://127.0.0.1")
    sp = c.get("/api/autotrade/speed").json()
    row = {r["name"]: r for r in sp["latency"]}["tick_transport"]
    assert row["n"] == 3 and row["p50"] == pytest.approx(0.004) and row["max"] == pytest.approx(0.010)
    assert {r["name"]: r for r in sp["latency"]}["tick_age"]["n"] == 0
    assert set(sp["bus"]) >= {"available", "connected", "port"} and "numba" in sp["engine"]
    m = c.get("/api/metrics")
    assert m.status_code == 200 and "quantdesk_tick_transport_seconds_count 3.0" in m.text
