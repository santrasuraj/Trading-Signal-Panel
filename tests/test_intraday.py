"""Intraday engine rules (costs, fills, stop-first ambiguity, forced square-off) and the intraday data
plumbing (FYERS sync bookkeeping, tick bars, live files, source priority). No network, no real data folder."""
import json
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from scanner.intraday import data as idata
from scanner.intraday import fyers_sync, live
from scanner.intraday.engine import (FLAT_FNO, FLAT_OTHER, SLOTS, Day, IntradayCosts, IntradayStrategy, run_intraday,
                                     slot_of, stop_entry, walk_exit)
from scanner.intraday.strategies import orb15

IST = timezone(timedelta(hours=5, minutes=30))


def make_day(prices=None, is_fno=True, **kw) -> Day:
    p = np.full(SLOTS, 100.0) if prices is None else np.asarray(prices, dtype=float)
    o = p.copy()
    h, l, c = p * 1.001, p * 0.999, p.copy()
    v = np.full(SLOTS, 1000.0)
    args = dict(symbol="X", date=pd.Timestamp("2026-10-01"), o=o, h=h, l=l, c=c, v=v, prev_close=100.0,
                prev_high=101.0, prev_low=99.0, atr_d=2.0, is_fno=is_fno, large=True)
    args.update(kw)
    return Day(**args)


def test_slots_and_square_off_times():
    assert slot_of(9, 15) == 0 and slot_of(15, 0) == FLAT_FNO == 69 and slot_of(15, 15) == FLAT_OTHER == 72


def test_intraday_charges_match_fyers_model():
    c = IntradayCosts()
    # 1 lakh each side: brokerage Rs20 x2, STT 0.025% on 1L sell = 25, stamp 0.003% = 3, exch+sebi on 2L, GST
    exch, sebi = 200000 * 0.0000307, 200000 * 0.000001
    expected = 40 + exch + sebi + 0.18 * (40 + exch + sebi) + 25 + 3
    assert c.charges(100000, 100000) == pytest.approx(expected, rel=1e-6)


def test_stop_wins_when_bar_hits_stop_and_target():
    d = make_day()
    d.h[10], d.l[10] = 103.0, 97.0               # one bar spans both levels
    slot, px, why = walk_exit(d, +1, 5, stop=98.0, target=102.0)
    assert (slot, px, why) == (10, 98.0, "stop")


def test_gap_through_stop_fills_at_open():
    d = make_day()
    d.o[12], d.h[12], d.l[12], d.c[12] = 95.0, 95.5, 94.5, 95.0
    slot, px, why = walk_exit(d, +1, 5, stop=98.0, target=None)
    assert (slot, px, why) == (12, 95.0, "stop")


def test_forced_square_off_at_1500_for_fno_and_1515_others():
    s1, px1, why1 = walk_exit(make_day(is_fno=True), +1, 5, None, None)
    s2, _, _ = walk_exit(make_day(is_fno=False), +1, 5, None, None)
    assert (s1, why1) == (FLAT_FNO, "square-off") and s2 == FLAT_OTHER


def test_stop_entry_fills_at_level_or_gapped_open():
    d = make_day()
    d.h[4] = 101.5                                    # trades through 101 inside the bar
    assert stop_entry(d, +1, 101.0, 3, 60) == (4, 101.0)
    d2 = make_day()
    d2.o[4], d2.h[4] = 102.0, 102.5                   # opens above the level
    assert stop_entry(d2, +1, 101.0, 3, 60) == (4, 102.0)


def test_orb15_long_breakout_with_2r_target():
    d = make_day(atr_d=4.0)                           # range 1.0 < 1.5 x ATR/4 -> stop at the range low
    d.h[:3], d.l[:3] = 100.5, 99.5                    # opening range 99.5 - 100.5
    d.h[5], d.o[5], d.c[5] = 101.0, 100.4, 100.9      # breakout bar
    d.h[8], d.c[8] = 103.0, 102.8                     # reaches 2R
    t = orb15(d, {})[0]
    assert t.side == 1 and t.entry_slot == 5 and t.reason == "target"
    assert t.exit_px == pytest.approx(t.entry_px + 2 * (t.entry_px - 99.5))


def test_costs_turn_zero_edge_into_loss():
    """A strategy with zero gross edge must lose roughly its costs - the core intraday reality check."""
    days = []
    for k in range(20):
        d = make_day(date=pd.Timestamp("2026-09-01") + pd.Timedelta(days=k))
        days.append(d)
    flat = IntradayStrategy("flat", "flat", "", "TEST",
                            lambda d, p: [__import__("scanner.intraday.engine", fromlist=["Trade"]).Trade(
                                "", d.symbol, str(d.date.date()), 1, 10, 100.0, 60, 100.0, 99.0, "time")])
    res = run_intraday(flat, days, IntradayCosts(), capital=500000)
    assert res.metrics["trades"] == 20 and res.metrics["return_pct"] < 0
    assert all(t.pnl < 0 for t in res.trades)


# ------------------------------------------------------------------------------------ FYERS sync bookkeeping
END = date(2026, 6, 30)          # a Tuesday; the window [END - days, END]


class FakeFyers:
    """Only what fetch_fyers_intraday and fyers_sync.sync use: _call(fn, payload), api, limiter.usage().
    Answers one 09:15 candle on the chunk's first day; chunks starting before `fail_before` fail."""

    def __init__(self, fail_before: date | None = None):
        self.fail_before = fail_before
        self.payloads: list[dict] = []
        self.api = SimpleNamespace(history=None)
        self.limiter = SimpleNamespace(
            usage=lambda: {"data": {"calls_today": len(self.payloads), "daily_limit": 4500}})

    def _call(self, fn, payload=None, bucket="data"):
        self.payloads.append(payload)
        day = date.fromisoformat(payload["range_from"])
        if self.fail_before and day < self.fail_before:
            return {"s": "error", "code": -1, "message": "range not available"}
        t = int(datetime(day.year, day.month, day.day, 9, 15, tzinfo=IST).timestamp())
        return {"s": "ok", "candles": [[t, 100.0, 101.0, 99.0, 100.5, 1000.0]]}


@pytest.fixture
def sync_root(tmp_path, monkeypatch):
    monkeypatch.setattr(fyers_sync, "last_complete_day", lambda: END)
    monkeypatch.setattr(fyers_sync, "_holidays", lambda year: frozenset())
    monkeypatch.setattr(fyers_sync, "ist_now", lambda: datetime(2026, 7, 1, 10, 0, tzinfo=IST))
    return tmp_path


def _run_sync(fake, root, days=250, symbols=("AAA",)):
    return fyers_sync.sync(fake, list(symbols), root, days, log=lambda m: None)


def test_sync_new_symbol_newest_chunk_first_then_up_to_date(sync_root):
    assert fyers_sync.plan_calls(["AAA"], sync_root, 250)["calls"] == 3       # 251 days in <=100-day chunks
    fake = FakeFyers()
    res = _run_sync(fake, sync_root)
    assert res["symbols_done"] == 1 and not res["failed"]
    assert fake.payloads[0]["range_to"] == END.isoformat()                    # newest chunk first
    state = fyers_sync.load_state(sync_root)
    assert state["symbols"]["AAA"] == {"from": (END - timedelta(days=250)).isoformat(), "to": END.isoformat()}
    assert len(idata.IntradayStore(sync_root / "bars").load("5m")) == 3
    assert fyers_sync.plan_calls(["AAA"], sync_root, 250)["calls"] == 0


def test_failed_chunk_is_not_marked_covered_and_is_retried_the_next_day(sync_root):
    fake = FakeFyers(fail_before=END - timedelta(days=150))                   # the older chunks fail
    res = _run_sync(fake, sync_root)
    assert "AAA" in res["failed"] and res["symbols_done"] == 0
    state = fyers_sync.load_state(sync_root)
    # only the chunk that succeeded is covered - the failed range stays missing
    assert state["symbols"]["AAA"] == {"from": (END - timedelta(days=99)).isoformat(), "to": END.isoformat()}
    assert state["failed"]["AAA"]["tries"] == 1
    calls = len(fake.payloads)
    assert calls == 2
    _run_sync(fake, sync_root)                                                # same day: no calls burnt again
    assert len(fake.payloads) == calls
    assert fyers_sync.plan_calls(["AAA"], sync_root, 250)["calls"] == 0


def test_chunk_failing_on_max_tries_days_is_accepted_as_empty(sync_root):
    fyers_sync._save_state(sync_root, {
        "symbols": {"AAA": {"from": (END - timedelta(days=99)).isoformat(), "to": END.isoformat()}},
        "failed": {"AAA": {"tries": fyers_sync.MAX_TRIES - 1, "day": "2026-06-30", "message": "x"}}})
    fake = FakeFyers(fail_before=END - timedelta(days=150))
    res = _run_sync(fake, sync_root)
    state = fyers_sync.load_state(sync_root)
    assert not res["failed"] and "AAA" not in state["failed"]
    assert state["symbols"]["AAA"]["from"] == (END - timedelta(days=250)).isoformat()
    assert len(fake.payloads) == 2                                            # each old chunk asked once
    assert fyers_sync.plan_calls(["AAA"], sync_root, 250)["calls"] == 0


def test_stale_range_outside_the_window_is_replaced_not_merged(sync_root):
    fyers_sync._save_state(sync_root, {"symbols": {"AAA": {"from": "2024-01-01", "to": "2024-03-01"}}})
    assert fyers_sync.plan_calls(["AAA"], sync_root, 250)["calls"] == 3       # the window only, not 2024 -> now
    fake = FakeFyers()
    _run_sync(fake, sync_root)
    assert min(p["range_from"] for p in fake.payloads) == (END - timedelta(days=250)).isoformat()
    assert fyers_sync.load_state(sync_root)["symbols"]["AAA"] == {
        "from": (END - timedelta(days=250)).isoformat(), "to": END.isoformat()}


def test_daily_archive_is_one_call_and_weekend_only_ranges_cost_nothing(sync_root):
    fyers_sync._save_state(sync_root, {"symbols": {
        "AAA": {"from": (END - timedelta(days=250)).isoformat(), "to": (END - timedelta(days=1)).isoformat()},
        "BBB": {"from": "2026-06-29", "to": END.isoformat()}}})               # 3-day window starts Sat 27 Jun
    assert fyers_sync.plan_calls(["AAA"], sync_root, 250)["calls"] == 1
    assert fyers_sync.plan_calls(["BBB"], sync_root, 3)["calls"] == 0
    fake = FakeFyers()
    fyers_sync.sync(fake, ["BBB"], sync_root, 3, log=lambda m: None)
    assert not fake.payloads
    assert fyers_sync.load_state(sync_root)["symbols"]["BBB"]["from"] == "2026-06-27"


def test_second_sync_skips_while_another_one_runs(sync_root, monkeypatch):
    monkeypatch.setattr(fyers_sync, "LOCK_WAIT_S", 0.0)
    holder = idata.FileLock(sync_root / fyers_sync.LOCK_FILE_NAME)
    assert holder.acquire(timeout=0)
    try:
        fake = FakeFyers()
        res = _run_sync(fake, sync_root)
        assert res["stopped"] and not fake.payloads
    finally:
        holder.release()


def test_last_complete_day_steps_over_weekends_and_holidays(monkeypatch):
    monkeypatch.setattr(fyers_sync, "_holidays", lambda year: frozenset({"2026-10-26"}))
    for now, expected in [(datetime(2026, 10, 24, 17, 0), date(2026, 10, 23)),     # Saturday -> Friday
                          (datetime(2026, 10, 26, 16, 0), date(2026, 10, 23)),     # holiday Monday -> Friday
                          (datetime(2026, 10, 27, 12, 0), date(2026, 10, 23)),     # Tuesday before the close
                          (datetime(2026, 10, 27, 15, 40), date(2026, 10, 27))]:   # Tuesday after the close
        monkeypatch.setattr(fyers_sync, "ist_now", lambda now=now: now.replace(tzinfo=IST))
        assert fyers_sync.last_complete_day() == expected


def test_file_lock_is_exclusive(tmp_path):
    a, b = idata.FileLock(tmp_path / "x.lock"), idata.FileLock(tmp_path / "x.lock")
    assert a.acquire(timeout=0)
    assert not b.acquire(timeout=0)
    a.release()
    assert b.acquire(timeout=0)
    b.release()


# ------------------------------------------------------------------------------------ source priority
def _bar(ts, close, source, sym="AAA"):
    return {"ts": pd.Timestamp(ts), "symbol": sym, "open": close, "high": close, "low": close, "close": close,
            "volume": 100.0, "flags": 0, "source": source}


def test_official_fyers_bars_beat_tick_built_bars_which_beat_yahoo():
    live_bars = pd.DataFrame([_bar("2026-10-23 09:15", 99.0, "fyers_ws"), _bar("2026-10-23 09:20", 101.0, "fyers_ws")])
    out = idata.merge_by_priority(pd.DataFrame([_bar("2026-10-23 09:15", 100.0, "fyers")]), live_bars)
    assert out["source"].tolist() == ["fyers", "fyers_ws"] and out["close"].tolist() == [100.0, 101.0]
    out = idata.merge_by_priority(pd.DataFrame([_bar("2026-10-23 09:15", 100.0, "yahoo")]), live_bars)
    assert out["source"].tolist() == ["fyers_ws", "fyers_ws"]


# ------------------------------------------------------------------------------------ live ticks -> bars
def _tick(hh, mm, ss, ltp, cum, day=None, sym="AAA"):
    d = day or datetime.now(IST).date()
    t = int(datetime(d.year, d.month, d.day, hh, mm, ss, tzinfo=IST).timestamp())
    return {"symbol": f"NSE:{sym}-EQ", "ltp": ltp, "vol_traded_today": cum, "last_traded_time": t}


def test_tick_bars_volume_deltas_and_rollover():
    b = idata.TickBarBuilder("5m")
    b.on_tick(_tick(9, 15, 5, 100.0, 1000))         # first tick sets the volume base
    b.on_tick(_tick(9, 17, 0, 102.0, 1500))
    b.on_tick(_tick(9, 19, 59, 99.0, 1700))
    b.on_tick(_tick(9, 20, 1, 101.0, 2000))         # opens 09:20, closes 09:15
    done = b.flush()
    assert len(done) == 1
    bar = done.iloc[0]
    assert bar["symbol"] == "AAA" and bar["ts"].strftime("%H:%M") == "09:15"
    assert [bar["open"], bar["high"], bar["low"], bar["close"], bar["volume"]] == [100.0, 102.0, 99.0, 99.0, 700.0]
    cur = b.cur["NSE:AAA-EQ"]
    assert cur["open"] == 101.0 and cur["volume"] == 300.0


def test_tick_bars_ignore_yesterday_pre_open_and_late_ticks():
    b = idata.TickBarBuilder("5m")
    yesterday = datetime.now(IST).date() - timedelta(days=1)
    b.on_tick(_tick(15, 29, 58, 90.0, 5000, day=yesterday))   # subscription snapshot: yesterday's last trade
    b.on_tick(_tick(9, 10, 0, 95.0, 100))                       # pre-open
    assert not b.cur and not b.done
    b.on_tick(_tick(9, 21, 0, 100.0, 1000))
    b.on_tick(_tick(9, 18, 0, 50.0, 900))                       # late tick for an earlier bar
    b.on_tick(_tick(9, 22, 0, 101.0, 1100))
    assert not b.done
    cur = b.cur["NSE:AAA-EQ"]
    assert cur["ts"].strftime("%H:%M") == "09:20" and cur["low"] == 100.0 and cur["volume"] == 100.0


def test_live_write_merges_completed_bars_and_writes_the_forming_bar(tmp_path):
    b = idata.TickBarBuilder("5m")
    b.on_tick(_tick(9, 15, 5, 100.0, 1000))
    b.on_tick(_tick(9, 20, 5, 101.0, 1200))
    live._write(tmp_path, b.flush(), live._forming(b))
    b.on_tick(_tick(9, 25, 5, 102.0, 1300))
    live._write(tmp_path, b.flush(), live._forming(b), "2026-10-23T09:25:05+05:30")
    bars = live.load_live(tmp_path)
    assert bars["ts"].dt.strftime("%H:%M").tolist() == ["09:15", "09:20"]
    info = json.loads((live.live_dir(tmp_path) / live.FORMING_FILE_NAME).read_text(encoding="utf-8"))
    assert info["bars"]["AAA"]["close"] == 102.0 and info["last_tick"] == "2026-10-23T09:25:05+05:30"


def test_live_feed_freshness(tmp_path):
    f = live.live_dir(tmp_path) / live.FORMING_FILE_NAME
    now = datetime(2026, 10, 23, 11, 0, tzinfo=IST)
    f.write_text(json.dumps({"last_tick": "2026-10-23T10:59:30+05:30"}), encoding="utf-8")
    assert live.feed_fresh(tmp_path, now)
    f.write_text(json.dumps({"last_tick": "2026-10-23T10:50:00+05:30"}), encoding="utf-8")
    assert not live.feed_fresh(tmp_path, now)                   # stopped 10 minutes ago
    after_close = datetime(2026, 10, 23, 17, 0, tzinfo=IST)
    f.write_text(json.dumps({"last_tick": "2026-10-23T15:29:58+05:30"}), encoding="utf-8")
    assert live.feed_fresh(tmp_path, after_close)               # ran until the close
    f.write_text(json.dumps({"last_tick": None}), encoding="utf-8")
    assert not live.feed_fresh(tmp_path, now)


def test_market_open_now_skips_holidays_and_allows_a_lead(monkeypatch):
    monkeypatch.setattr(fyers_sync, "_holidays", lambda year: frozenset({"2026-10-26"}))
    monkeypatch.setattr(live, "ist_now", lambda: datetime(2026, 10, 27, 9, 14, tzinfo=IST))
    assert not live.market_open_now() and live.market_open_now(lead_minutes=2)
    monkeypatch.setattr(live, "ist_now", lambda: datetime(2026, 10, 26, 10, 0, tzinfo=IST))   # NSE holiday
    assert not live.market_open_now()
