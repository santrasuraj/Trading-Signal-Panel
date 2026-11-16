"""Intraday OI history and the F&O OI build-up backtest: the snapshot store (scanner/fno_intraday.py append_history /
load_history), the hook in the live fetch (web/api/services/fno_svc.py), the backtest replaying the live rule
(scanner/intraday/oi_buildup.py) and its status in intraday.json (scanner/intraday/run.py run_intraday_all)."""
import json
from datetime import date, datetime

import numpy as np
import pandas as pd
import pytest

from scanner import fno
from scanner import fno_intraday as fi
from scanner.intraday import oi_buildup as ob
from scanner.intraday import run as irun
from scanner.intraday.engine import SLOTS, Day, IntradayCosts, slot_of
from scanner.settings import IST


@pytest.fixture
def fno_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(fno, "FNO_DIR", tmp_path / "fno")
    return tmp_path / "fno"


def view(day="2026-11-16", nse="10:00:00", fetched="10:00:40", rows=None, prices=None):
    rows = rows if rows is not None else [
        {"symbol": "KAYNES", "oi": 63135.0, "prev_oi": 34540.0, "oi_chg": 28595.0, "oi_chg_pct": 82.79,
         "spot_rounded": 2974.0},
        {"symbol": "NIFTY", "oi": 12310241.0, "prev_oi": 12000000.0, "oi_chg": 310241.0, "oi_chg_pct": 2.59,
         "spot_rounded": 25901.0}]
    return {"nse_time": f"{day}T{nse}+05:30", "trade_date": day, "prev_date": "2026-11-13", "rows": rows,
            "prices": prices if prices is not None else
            {"KAYNES": {"price": 2969.8, "time": day}, "NIFTY": {"price": 1.0, "time": "2026-11-13"}},
            "fetched_at": f"{day}T{fetched}+05:30"}


# ---- the snapshot store -----------------------------------------------------------------------------------------------
def test_a_snapshot_keeps_symbol_times_oi_change_and_the_price_the_app_had():
    df = fi.snapshot_frame(view())
    assert list(df.columns) == fi.HISTORY_COLS and len(df) == 2
    k = df[df["symbol"] == "KAYNES"].iloc[0]
    assert k["ts"] == pd.Timestamp("2026-11-16 10:00:00") and k["fetched"] == pd.Timestamp("2026-11-16 10:00:40")
    assert k["oi"] == 63135 and k["oi_chg"] == 28595
    assert k["price"] == pytest.approx(2969.8)                         # today's quote
    assert df[df["symbol"] == "NIFTY"].iloc[0]["price"] == 25901        # yesterday's quote: NSE's rounded spot instead


def test_only_market_hours_of_the_feeds_own_day_are_kept():
    assert fi.snapshot_frame(view(nse="09:14:00", fetched="09:14:30")).empty           # pre-open
    assert fi.snapshot_frame(view(nse="15:29:59", fetched="15:45:00")).empty           # fetched after the close
    assert fi.snapshot_frame({**view(), "trade_date": "2026-11-13",
                              "nse_time": "2026-11-13T15:30:00+05:30"}).empty          # 09:20 fetch, feed not rolled over
    assert fi.snapshot_frame({**view(), "nse_time": None}).empty
    assert len(fi.snapshot_frame(view(nse="15:30:00", fetched="15:30:20"))) == 2
    skew = fi.snapshot_frame(view(nse="10:00:00", fetched="09:59:55"))                # this PC's clock behind NSE's
    assert (skew["fetched"] == pd.Timestamp("2026-11-16 10:00:00")).all()


def test_append_merges_per_month_atomically_and_skips_a_snapshot_nse_has_not_updated(fno_dir):
    assert fi.append_history(view()) == 2
    assert fi.append_history(view(fetched="10:03:00")) == 0             # same NSE time: nothing new
    assert fi.append_history(view(nse="10:05:00", fetched="10:05:30")) == 2
    assert fi.append_history(view(day="2026-12-01", nse="09:30:00", fetched="09:30:10")) == 2
    assert fi.append_history(view(nse="16:00:00", fetched="16:00:10")) == 0      # after hours
    d = fi.history_dir()
    assert sorted(p.name for p in d.glob("*.parquet")) == ["2026-11.parquet", "2026-12.parquet"]
    assert not list(d.glob("*.tmp"))
    h = fi.load_history()
    assert len(h) == 6 and list(h["fetched"]) == sorted(h["fetched"])
    first = h[(h["symbol"] == "KAYNES") & (h["ts"] == pd.Timestamp("2026-11-16 10:00"))].iloc[0]
    assert first["fetched"] == pd.Timestamp("2026-11-16 10:00:40")            # the first fetch of it is kept
    assert first["oi_chg_pct"] == fi.parse({"timestamp": "16-Nov-2026 10:00:00", "data": [
        {"symbol": "KAYNES", "latestOI": 63135, "prevOI": 34540, "changeInOI": 28595}]})["rows"][0]["oi_chg_pct"]
    assert len(fi.load_history(start="2026-12-01")) == 2 and len(fi.load_history(end="2026-11-30")) == 4


def test_a_damaged_month_does_not_hide_the_others_and_the_store_stays_small(fno_dir):
    fi.append_history(view())
    (fi.history_dir() / "2026-10.parquet").write_bytes(b"not parquet")
    assert len(fi.load_history()) == 2
    # a realistic month: 220 underlyings every 5 minutes for 22 sessions stays a few MB (5-minute bars: ~3.7 MB)
    rng = np.random.default_rng(0)
    syms = [f"S{i:03d}" for i in range(220)]
    base = rng.integers(1_000, 10_000_000, len(syms)).astype(float)
    parts = []
    for day in pd.bdate_range("2026-10-01", periods=22):
        oi = base.copy()
        for k in range(75):
            oi = np.maximum(1, np.round(oi * (1 + rng.normal(0, 0.004, len(oi)))))
            t = day + pd.Timedelta(minutes=555 + 5 * k)
            parts.append(pd.DataFrame({"fetched": t + pd.Timedelta(seconds=30), "ts": t, "symbol": syms,
                                       "oi": oi.astype("int64"), "oi_chg": oi - base,
                                       "price": rng.uniform(100, 5000, len(oi)).round(2)}))
    month = fi.history_dir() / "2026-10.parquet"
    fi._write_history(fi._tidy(pd.concat(parts, ignore_index=True)), month)
    assert month.stat().st_size < 4_000_000
    assert len(fi.load_history(start="2026-10-01", end="2026-10-31")) == 22 * 75 * 220


def test_the_live_fetch_stores_each_snapshot_and_a_failed_write_never_fails_it(monkeypatch):
    from web.api.services import fno_svc, quotes_svc
    saved, stored = [], []
    monkeypatch.setattr(fi, "fetch", lambda: ({k: v for k, v in view().items() if k not in ("prices", "fetched_at")},
                                              None))
    monkeypatch.setattr(fi, "save", saved.append)
    monkeypatch.setattr(fi, "append_history", stored.append)
    monkeypatch.setattr(fno_svc, "_kinds", lambda: {"NIFTY": "index"})
    monkeypatch.setattr(quotes_svc, "quotes", lambda syms, **k: {"source": "yahoo", "quotes": [
        {"symbol": s, "price": 2969.8, "time": "2026-11-16"} for s in syms]})
    assert fno_svc.refresh_live_now() is None
    assert len(saved) == 1 and stored == saved                          # the same view: prices and fetch time included
    assert stored[0]["prices"]["KAYNES"]["price"] == 2969.8 and stored[0]["fetched_at"]

    def broken(v):
        raise OSError("disk full")
    monkeypatch.setattr(fi, "append_history", broken)
    fno_svc._live["last"] = 0.0
    assert fno_svc.refresh_live_now() is None and len(saved) == 2       # the live snapshot is still saved


# ---- the backtest replays the live rule ---------------------------------------------------------------------------------
DAY = pd.Timestamp("2026-10-01")


def path_day(sym="AAA", slope=0.0003, rev_at=None, prev=1000.0, d=DAY) -> Day:
    """Opens at the previous close and moves `slope` a bar (reversing from bar `rev_at`)."""
    steps = np.full(SLOTS, slope)
    if rev_at is not None:
        steps[rev_at:] = -2 * slope
    c = prev * np.cumprod(1 + steps)
    o = np.r_[prev, c[:-1]]
    return Day(symbol=sym, date=d, o=o, h=np.maximum(o, c) * 1.0002, l=np.minimum(o, c) * 0.9998, c=c,
               v=np.full(SLOTS, 1000.0), prev_close=prev, prev_high=prev * 1.01, prev_low=prev * 0.99, atr_d=20.0,
               is_fno=True, large=False)


def snaps(*rows) -> pd.DataFrame:
    """rows: (symbol, fetched 'HH:MM:SS', OI change %[, day])."""
    out = []
    for r in rows:
        day = r[3] if len(r) > 3 else DAY
        out.append({"fetched": pd.Timestamp(f"{day:%Y-%m-%d} {r[1]}"), "ts": pd.Timestamp(f"{day:%Y-%m-%d} {r[1]}"),
                    "symbol": r[0], "oi_chg_pct": r[2]})
    return pd.DataFrame(out)


def test_the_backtest_enters_at_the_first_bar_close_after_the_snapshot_was_fetched():
    (t,) = ob.picks([path_day()], snaps(("AAA", "10:00:30", 8.0)))[("AAA", DAY)]
    assert t.side == 1 and t.entry_slot == slot_of(10, 5)               # decided at the 10:05 close (no earlier)
    d = path_day()
    k = t.entry_slot - 1
    assert t.entry_px == pytest.approx(d.o[k + 1])                      # next bar's open
    assert t.stop == pytest.approx(np.min(d.l[:k + 1]))                 # the day's low so far
    risk = d.c[k] - t.stop
    assert t.reason == "target" and t.exit_px == pytest.approx(d.c[k] + 2 * risk)


def test_the_backtest_signal_matches_the_live_signal_bar_for_bar():
    d = path_day(slope=0.0004)
    oi = {"trade_date": "2026-10-01", "fetched_at": "2026-10-01T10:00:30+05:30",
          "rows": [{"symbol": "AAA", "oi_chg_pct": 9.5}]}
    (t,) = ob.picks([d], snaps(("AAA", "10:00:30", 9.5)))[("AAA", DAY)]
    k = t.entry_slot - 1                                                # the bar whose close decided
    for j in range(slot_of(10, 0), k + 1):                              # the live list at each close since the fetch
        part = path_day(slope=0.0004)
        for a in (part.o, part.h, part.l, part.c):
            a[j + 1:] = np.nan
        close = datetime(2026, 10, 1, 9, 20, tzinfo=IST) + pd.Timedelta(minutes=5 * j)
        live = irun.oi_buildup_signals({"AAA": part}, oi, close, 500000, 0.5, 2.0, IntradayCosts())
        if j < k:
            assert live == [] or close < datetime(2026, 10, 1, 10, 0, 30, tzinfo=IST)
        else:
            (s,) = live
            assert s["side"] == "LONG" and s["entry_time"] == irun._hhmm(t.entry_slot)
            assert s["stop"] == pytest.approx(t.stop, abs=0.01)
            assert s["target"] == pytest.approx(d.c[k] + 2 * (d.c[k] - t.stop), abs=0.01)


def test_no_trade_without_the_02pct_move_a_build_up_or_a_fresh_snapshot():
    flat = path_day(slope=0.00001)                                       # +0.01% a bar: under 0.2% until late
    assert ob.picks([flat], snaps(("AAA", "09:30:00", 8.0))) == {}
    assert ob.picks([path_day()], snaps(("AAA", "10:00:30", 4.9))) == {}           # under 5% OI
    assert ob.picks([path_day()], snaps(("AAA", "10:00:30", -8.0))) == {}          # short covering
    assert ob.picks([path_day()], snaps(("AAA", "10:00:30", float("nan")))) == {}
    # the price only gets 0.2% above yesterday after the snapshot went stale (20 minutes): no signal
    late = path_day(slope=0.00004)                                       # +0.2% at bar ~50 (13:25)
    assert ob.picks([late], snaps(("AAA", "10:00:30", 8.0))) == {}
    assert ob.picks([late], snaps(("AAA", "10:00:30", 8.0), ("AAA", "13:30:10", 8.0)))[("AAA", DAY)]


def test_a_short_build_up_below_vwap_is_a_short_and_nothing_starts_from_1430():
    (t,) = ob.picks([path_day(slope=-0.0003)], snaps(("AAA", "10:00:30", 6.0)))[("AAA", DAY)]
    assert t.side == -1 and t.stop > t.entry_px
    assert ob.picks([path_day()], snaps(("AAA", "14:25:10", 8.0))) == {}            # first close 14:30: too late
    (t,) = ob.picks([path_day()], snaps(("AAA", "14:20:10", 8.0)))[("AAA", DAY)]
    assert t.entry_slot == slot_of(14, 25)


def test_each_bar_close_keeps_the_ten_biggest_oi_changes():
    days = [path_day(sym=f"S{i:02d}") for i in range(12)]
    p = ob.picks(days, snaps(*[(f"S{i:02d}", "10:00:30", 6.0 + i) for i in range(12)]))
    assert sorted(s for s, _ in p) == [f"S{i:02d}" for i in range(2, 12)]      # S00 / S01: the two smallest


def test_one_trade_per_stock_and_side_a_day_never_two_at_once():
    # up, then a reversal that stops the long out; OI stays up, so the short build-up below VWAP follows
    d = path_day(slope=0.0005, rev_at=slot_of(11, 0))
    shots = snaps(*[("AAA", f"{h:02d}:{m:02d}:30", 9.0) for h in range(9, 15) for m in range(0, 60, 5)
                    if (9, 15) <= (h, m) < (14, 30)])
    ts = ob.picks([d], shots)[("AAA", DAY)]
    assert [t.side for t in ts] == [1, -1]                                # never a second long, nor a stacked short
    assert ts[1].entry_slot > ts[0].exit_slot


# ---- the status in intraday.json ----------------------------------------------------------------------------------------
def test_strategy_status_rules():
    assert irun.strategy_status({"days": 39, "significant": True, "avg_day_pct": 1}) == "unknown"
    assert irun.strategy_status({"days": 40, "significant": True, "avg_day_pct": 0.1}) == "working"
    assert irun.strategy_status({"days": 40, "significant": False, "avg_day_pct": 0.1}) == "mixed"
    assert irun.strategy_status({"days": 40, "significant": True, "avg_day_pct": -0.1}) == "not-working"


def _market(n_days: int, rev: bool = False):
    """n_days sessions of 5-minute bars for AAA (a long build-up that trends on, or reverses through the stop with
    rev) and BBB (OI barely changes), with a daily store that matches them and 25 quiet days before."""
    rng = np.random.default_rng(7)
    pre = pd.bdate_range("2026-06-01", periods=25)
    sessions = pd.bdate_range(pre[-1] + pd.Timedelta(days=1), periods=n_days)
    daily = {k: {} for k in ("open", "high", "low", "close", "volume")}
    bars, prev = [], {"AAA": 1000.0, "BBB": 500.0}
    for d in pre:
        for s, p in prev.items():
            for k, v in (("open", p), ("high", p), ("low", p), ("close", p), ("volume", 1e7)):
                daily[k].setdefault(s, {})[d] = v
    for d in sessions:
        for s in ("AAA", "BBB"):
            day = path_day(sym=s, slope=float(rng.uniform(0.0003, 0.0006)), prev=prev[s], d=d,
                           rev_at=slot_of(10, 15) if rev and s == "AAA" else None)
            ts = d + pd.to_timedelta(555 + 5 * np.arange(SLOTS), unit="m")
            bars.append(pd.DataFrame({"symbol": s, "ts": ts, "open": day.o, "high": day.h, "low": day.l,
                                      "close": day.c, "volume": day.v, "source": "fyers"}))
            for k, v in (("open", day.o[0]), ("high", day.h.max()), ("low", day.l.min()), ("close", day.c[-1]),
                         ("volume", 1e7)):
                daily[k].setdefault(s, {})[d] = v
            prev[s] = float(day.c[-1])
    frames = {k: pd.DataFrame(v).sort_index() for k, v in daily.items()}
    return frames, pd.concat(bars, ignore_index=True), sessions


def _run(tmp_path, monkeypatch, n_days, rev=False, stored=None):
    frames, bars, sessions = _market(n_days, rev)
    for d in sessions[:stored]:
        fi.append_history(view(day=f"{d:%Y-%m-%d}", nse="10:00:00", fetched="10:00:30", prices={}, rows=[
            {"symbol": "AAA", "oi": 108000, "oi_chg": 8000}, {"symbol": "BBB", "oi": 101000, "oi_chg": 1000}]))

    class Store:
        def __init__(self, root):
            pass

        def load(self, interval):
            return bars

    info = {"fno": {"AAA", "BBB"} | {f"F{i}" for i in range(60)}, "turnover": {}, "top30": {"AAA", "BBB"},
            "etfs": set(), "min_turnover_cr": 100.0}
    monkeypatch.setattr(irun, "intraday_universe", lambda cfg, fr: (["AAA", "BBB"], info))
    monkeypatch.setattr(irun.idata, "IntradayStore", Store)
    monkeypatch.setattr(irun, "results_history", lambda *a, **k: {})
    monkeypatch.setattr(irun, "get_universe", lambda name: (pd.DataFrame({"symbol": []}), ""))
    monkeypatch.setattr(irun.fyers_sync, "coverage", lambda d: {})
    monkeypatch.setattr("scanner.intraday.fast.enable", lambda: None)
    monkeypatch.setattr(irun, "RESULT_FILE", tmp_path / "intraday.json")
    irun.run_intraday_all({}, frames, update=False, log=lambda m: None)
    return json.loads((tmp_path / "intraday.json").read_text(encoding="utf-8"))


def test_untested_until_40_sessions_of_snapshots_then_judged_like_the_others(tmp_path, monkeypatch, fno_dir):
    r = _run(tmp_path, monkeypatch, 45, stored=12)
    assert ob.OI_KEY not in [s["key"] for s in r["strategies"]]          # not judged: the evidence rule sees 'untested'
    o = r["oi_buildup"]
    assert o["status"] == "untested" and o["days"] == 12 and o["min_days"] == 40 and o["trades"] == 12
    assert "12 of the 40" in r["rules"]["oi_buildup"]
    assert "for 3 strategies" in r["rules"]["significance"]

    r = _run(tmp_path, monkeypatch, 45, stored=45)
    (s,) = [s for s in r["strategies"] if s["key"] == ob.OI_KEY]
    assert s["status"] == "working" and s["metrics"]["days"] == 45 and s["metrics"]["trades"] == 45
    assert s["metrics"]["t_stat"] >= s["metrics"]["t_crit"] and s["evidence"] == "EXPERIMENTAL"
    assert r["oi_buildup"]["status"] == "working" and r["oi_buildup"]["metrics"] is None
    assert "for 4 strategies" in r["rules"]["significance"]              # Bonferroni counts it once it is judged
    from scanner import option_signals as osg
    monkeypatch.setattr(osg, "RESULTS_DIR", tmp_path)
    assert osg.tested_status()[ob.OI_KEY] == "working"                   # what the options side and Signals page read


def test_a_failing_oi_backtest_never_costs_the_other_strategies_results(tmp_path, monkeypatch, fno_dir):
    def broken(*a, **k):
        raise ValueError("bad snapshot")
    monkeypatch.setattr(irun, "oi_backtest", broken)
    r = _run(tmp_path, monkeypatch, 41, stored=0)
    assert len(r["strategies"]) == 3 and r["oi_buildup"]["status"] == "untested"
    assert "failed" in r["rules"]["oi_buildup"]


def test_a_build_up_that_reverses_through_its_stop_is_not_working(tmp_path, monkeypatch, fno_dir):
    r = _run(tmp_path, monkeypatch, 42, rev=True, stored=42)
    (s,) = [s for s in r["strategies"] if s["key"] == ob.OI_KEY]
    assert s["status"] == "not-working" and s["metrics"]["avg_day_pct"] < 0


def test_live_signals_carry_the_backtest_status():
    d = path_day()
    for a in (d.o, d.h, d.l, d.c):
        a[slot_of(11, 0):] = np.nan
    now = datetime(2026, 10, 1, 11, 0, tzinfo=IST)
    oi = {"trade_date": "2026-10-01", "fetched_at": now.isoformat(), "rows": [{"symbol": "AAA", "oi_chg_pct": 8.0}]}
    (s,) = irun.oi_buildup_signals({"AAA": d}, oi, now, 500000, 0.5, 2.0, IntradayCosts(), "working")
    assert s["strategy_status"] == "working" and s["proven"]
    (s,) = irun.oi_buildup_signals({"AAA": d}, oi, now, 500000, 0.5, 2.0, IntradayCosts())
    assert s["strategy_status"] == "untested" and not s["proven"]
    assert date(2026, 10, 1) in ob.history_days(snaps(("AAA", "10:00:00", 8.0)), "2026-10-02")
