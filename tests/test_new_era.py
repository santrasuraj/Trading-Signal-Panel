"""New-era intraday strategies (scanner/intraday/strategies.py: liquidity sweep + retest, opening-range break-and-retest
with VWAP), signals from every strategy labelled with its backtest result, and live F&O OI build-up signals
(scanner/intraday/run.py). Synthetic bars only; nothing is fetched or sent."""
import numpy as np
import pandas as pd
import pytest

from scanner.intraday.engine import SLOTS, Day
from scanner.intraday.strategies import SWEEP_STOP_BUFFER, build_intraday_strategies, orb_retest_vwap, sweep_or15, sweep_pdhl


def make_day(**kw) -> Day:
    p = np.full(SLOTS, 100.0)
    args = dict(symbol="X", date=pd.Timestamp("2026-10-01"), o=p.copy(), h=p * 1.001, l=p * 0.999, c=p.copy(),
                v=np.full(SLOTS, 1000.0), prev_close=100.0, prev_high=101.0, prev_low=99.0, atr_d=2.0, is_fno=True,
                large=True)
    args.update(kw)
    return Day(**args)


def bar(d: Day, i: int, o=None, h=None, l=None, c=None):
    for arr, v in ((d.o, o), (d.h, h), (d.l, l), (d.c, c)):
        if v is not None:
            arr[i] = v


# ---- liquidity sweep + retest ---------------------------------------------------------------------------------------
def test_sweep_of_yesterdays_low_then_retest_goes_long_with_stop_beyond_the_sweep():
    d = make_day()
    bar(d, 5, l=98.7, c=99.3)                    # trades through yesterday's low (99), closes back above: the trap
    bar(d, 8, l=99.02, c=99.6)                   # comes back to 99 and holds: the retest
    bar(d, 9, o=99.7)
    (t,) = sweep_pdhl(d, {})
    assert t.side == 1 and t.entry_slot == 9 and t.entry_px == pytest.approx(99.7)
    assert t.stop == pytest.approx(98.7 * (1 - SWEEP_STOP_BUFFER))


def test_sweep_of_yesterdays_high_then_retest_goes_short():
    d = make_day()
    bar(d, 5, h=101.4, c=100.8)
    bar(d, 8, h=100.98, c=100.5)
    bar(d, 9, o=100.4)
    (t,) = sweep_pdhl(d, {})
    assert t.side == -1 and t.entry_slot == 9 and t.stop == pytest.approx(101.4 * (1 + SWEEP_STOP_BUFFER))


def test_a_real_breakdown_is_not_a_trap():
    d = make_day()
    for i in range(5, 20):                       # closes below yesterday's low and stays there
        bar(d, i, o=98.8, h=98.9, l=98.6, c=98.8)
    assert sweep_pdhl(d, {}) == []


def test_a_new_extreme_before_the_retest_cancels_the_setup():
    d = make_day()
    bar(d, 5, l=98.7, c=99.3)
    bar(d, 7, l=98.5, c=99.2)                    # sweeps again, lower: the first trap failed
    bar(d, 8, l=99.02, c=99.6)
    assert sweep_pdhl(d, {}) == []


def test_opening_range_sweep_starts_after_0930():
    d = make_day()
    bar(d, 0, h=100.5, l=99.5)                   # opening range 99.5 - 100.5
    bar(d, 6, l=99.3, c=99.7)
    bar(d, 9, l=99.52, c=99.9)
    bar(d, 10, o=99.95)
    (t,) = sweep_or15(d, {})
    assert t.side == 1 and t.entry_slot == 10


# ---- opening-range break-and-retest with VWAP -----------------------------------------------------------------------
def test_orb_break_and_retest_above_vwap_goes_long():
    d = make_day()
    bar(d, 4, o=100.2, h=100.7, l=100.2, c=100.6)    # closes above the range (100.1) and VWAP
    bar(d, 5, o=100.6, h=100.6, l=100.3, c=100.5)
    bar(d, 6, o=100.5, h=100.55, l=100.12, c=100.5)  # retests 100.1 and holds
    bar(d, 7, o=100.55)
    (t,) = orb_retest_vwap(d, {})
    assert t.side == 1 and t.entry_slot == 7 and t.stop == pytest.approx(100.12 * (1 - SWEEP_STOP_BUFFER))


def test_orb_close_back_inside_the_range_is_a_failed_breakout():
    d = make_day()
    bar(d, 4, o=100.2, h=100.7, l=100.2, c=100.6)
    bar(d, 5, o=100.4, h=100.4, l=99.95, c=100.0)    # back inside
    assert orb_retest_vwap(d, {}) == []


# ---- live F&O OI build-up signals -----------------------------------------------------------------------------------
from datetime import datetime  # noqa: E402

from scanner.intraday.engine import IntradayCosts  # noqa: E402
from scanner.intraday.run import OI_KEY, oi_buildup_signals  # noqa: E402
from scanner.settings import IST  # noqa: E402

NOW = datetime(2026, 10, 1, 11, 0, tzinfo=IST)


def oi_day(closes, **kw):
    c = np.full(SLOTS, np.nan)
    c[:len(closes)] = closes
    return make_day(symbol="X", date=pd.Timestamp("2026-10-01"), o=c.copy(), h=c * 1.001, l=c * 0.999, c=c, **kw)


def live_oi(oi_pct, fetched=NOW, trade_date="2026-10-01"):
    return {"trade_date": trade_date, "fetched_at": fetched.isoformat(), "rows": [{"symbol": "X", "oi_chg_pct": oi_pct}]}


def _oi(day, oi):
    return oi_buildup_signals({"X": day}, oi, NOW, 500000, 0.5, 2.0, IntradayCosts())


def test_long_buildup_above_vwap_is_a_long_with_the_days_low_as_stop():
    d = oi_day(np.linspace(100.2, 101.5, 20))
    (s,) = _oi(d, live_oi(8.0))
    assert s["strategy_key"] == OI_KEY and s["side"] == "LONG" and s["strategy_status"] == "untested" and not s["proven"]
    assert s["entry"] == pytest.approx(101.5) and s["stop"] == pytest.approx(100.2 * 0.999, abs=0.01)
    assert s["target"] == pytest.approx(101.5 + 2 * (101.5 - 100.2 * 0.999), abs=0.02)
    assert "open interest +8.0%" in s["detail"]


def test_short_buildup_below_vwap_is_a_short():
    (s,) = _oi(oi_day(np.linspace(99.8, 98.6, 20)), live_oi(6.0))
    assert s["side"] == "SHORT" and s["stop"] > s["entry"] > s["target"]


def test_no_oi_signal_from_small_changes_unwinding_stale_or_old_snapshots():
    up = oi_day(np.linspace(100.2, 101.5, 20))
    assert _oi(up, live_oi(3.0)) == []                                      # below the 5% OI threshold
    assert _oi(up, live_oi(-8.0)) == []                                     # short covering: not a build-up
    assert _oi(up, live_oi(8.0, fetched=datetime(2026, 10, 1, 10, 0, tzinfo=IST))) == []   # an hour old
    assert _oi(up, live_oi(8.0, trade_date="2026-09-30")) == []             # yesterday's feed


# ---- the API serves every signal with its current label -------------------------------------------------------------
def _sig(key, status=None):
    s = {"strategy_key": key, "strategy_name": key, "symbol": "X", "side": "LONG", "entry_time": "10:00", "entry": 100.0,
         "stop": 99.0, "qty": 10, "amount": 1000.0, "state": "open", "exit_time": None, "exit": None, "last": 100.5,
         "reason": "open", "pnl": 5.0, "ret_pct": 0.5}
    return {**s, "strategy_status": status} if status else s


def test_signals_are_served_with_their_current_backtest_label(monkeypatch):
    from web.api.services import intraday_view as iv
    from web.api.util import today_ist
    bt = {"generated_at": "2026-10-01T15:45:00+05:30",
          "strategies": [{"key": "orb15", "status": "not-working"}, {"key": "vwap_trend", "status": "working"}]}
    f = {"generated_at": f"{today_ist().isoformat()}T11:00:00+05:30", "backtest_at": bt["generated_at"],
         "show_untested": True, "source": "yahoo",
         "signals": [_sig("orb15", "working"), _sig("vwap_trend"), _sig(OI_KEY, "untested"), _sig("sweep_pdhl")]}
    monkeypatch.setattr(iv.data, "intraday", lambda: bt)
    monkeypatch.setattr(iv.data, "intraday_signals", lambda: f)
    out = iv.signals_payload()
    got = {s["strategy_key"]: (s["strategy_status"], s["proven"]) for s in out["signals"]}
    assert got == {"orb15": ("not-working", False), "vwap_trend": ("working", True), OI_KEY: ("untested", False),
                   "sweep_pdhl": ("untested", False)}           # the current backtest wins over the file's label
    assert out["show_untested"] and out["delayed"]
    monkeypatch.setattr(iv.data, "intraday_signals", lambda: {**f, "show_untested": False})
    assert [s["strategy_key"] for s in iv.signals_payload()["signals"]] == ["vwap_trend"]   # the original rule


def test_show_untested_is_off_unless_configured_and_on_in_config_yaml():
    import yaml
    from pathlib import Path
    import scanner.intraday.run as r
    assert "show_untested\", False" in Path(r.__file__).read_text(encoding="utf-8")          # code default: the old rule
    cfg = yaml.safe_load((Path(r.__file__).resolve().parents[2] / "config.yaml").read_text(encoding="utf-8"))
    assert cfg["intraday"]["show_untested"] is True                                           # the user's choice


def test_new_era_strategies_are_registered_and_can_be_switched_off():
    keys = {s.key for s in build_intraday_strategies({})}
    assert {"sweep_pdhl", "sweep_or15", "orb_retest_vwap"} <= keys
    off = {s.key for s in build_intraday_strategies({"intraday_strategies": {"sweep_pdhl": {"enabled": False}}})}
    assert "sweep_pdhl" not in off and "sweep_or15" in off
