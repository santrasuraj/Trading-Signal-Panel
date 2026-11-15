"""Options signals (scanner/option_signals.py, web/api/services/optsig_svc.py, the auto-trader's options-signals pass):
intraday and stock signals as option buys, the volatility (IV rank) trades, their marks and exits on the chain, the
nightly settlement at NSE's official closes, the per-source record and the volatility backtest. Synthetic chains
priced with Black-76; nothing is fetched from NSE and nothing is sent anywhere."""
import io
import math
import zipfile
from datetime import date, datetime

import numpy as np
import pandas as pd
import pytest

from scanner import option_signals as osg
from scanner import options as opt
from scanner.settings import IST

NOW = datetime(2026, 11, 16, 10, 0, tzinfo=IST)          # a Monday, market open
EXP = date(2026, 12, 15)


def chain(sym="NIFTY", spot=25000.0, expiry=EXP, iv=0.16, step=50, n=60, oi=5000.0, now=NOW):
    """An NSE-like chain: every strike priced by Black-76 at one IV, bid / ask 1% either side, plenty of OI."""
    T = opt.years_to_expiry(expiry, now)
    F = spot * math.exp(osg.R * T)
    base = round(spot / step) * step
    ks = np.array([base + step * i for i in range(-n, n + 1)], dtype=float)
    df = pd.DataFrame({"strike": ks})
    for side, call in (("ce", 1.0), ("pe", 0.0)):
        px = opt.black76(F, ks, T, osg.R, np.full(len(ks), iv), np.full(len(ks), call))
        df[f"{side}_ltp"], df[f"{side}_bid"], df[f"{side}_ask"] = px, px * 0.99, px * 1.01
        df[f"{side}_oi"], df[f"{side}_iv_nse"] = oi, iv * 100
    return {"symbol": sym, "expiry": expiry, "df": df, "spot": spot, "T": T, "F": F, "time": now.isoformat()}


@pytest.fixture
def world(tmp_path, monkeypatch):
    """The journal in tmp, the market open, one lot size and a chain the test can move."""
    w = {"chain": chain("RELIANCE", 2500.0, step=10), "scan": {}}
    monkeypatch.setattr(osg, "FILE", tmp_path / "option_signals.json")
    monkeypatch.setattr(osg, "LOCK", tmp_path / ".option_signals.lock")
    monkeypatch.setattr(osg.ov, "lot_sizes", lambda: {"RELIANCE": 500, "NIFTY": 65})
    monkeypatch.setattr(osg, "_market_open", lambda now: True)
    monkeypatch.setattr(osg, "get_chain", lambda *a, **k: w["chain"])
    monkeypatch.setattr(osg.opt, "expiries", lambda sym: ([EXP], 200))
    monkeypatch.setattr(osg, "_latest_scan", lambda: w["scan"])
    return w


def isig(state="open", reason=None, side="LONG", stop=2450.0, target=2560.0):
    return {"signals": [{"strategy_key": "sweep_pdhl", "strategy_name": "PDH/PDL sweep", "symbol": "RELIANCE",
                         "side": side, "entry_time": "10:00", "stop": stop, "target": target, "state": state,
                         "reason": reason, "strategy_status": "untested", "proven": False}]}


# ---- picking the expiry -------------------------------------------------------------------------------------------
def test_expiry_rules():
    today = date(2026, 11, 16)
    exps = [date(2026, 11, 17), date(2026, 11, 24), date(2026, 11, 30), date(2026, 12, 8), date(2026, 12, 29),
            date(2027, 1, 26)]
    assert osg._pick_expiry(exps, today, "near") == date(2026, 11, 24)     # at least 2 days: not tomorrow's
    assert osg._pick_expiry(exps, today, "month") == date(2026, 12, 29)    # at least 25 days
    assert osg._pick_expiry(exps, today, "vol") == date(2026, 12, 29)      # the monthly expiry nearest 30 days
    assert osg._pick_expiry([date(2026, 11, 17)], today, "near") is None
    late_month = date(2026, 11, 13)                                            # 11 days to November's expiry
    assert osg.vol_expiries([date(2026, 11, 24), date(2026, 12, 29)], late_month) == [date(2026, 12, 29), date(2026, 11, 24)]
    assert osg.vol_expiries([date(2026, 11, 24), date(2026, 12, 29)], date(2026, 11, 16)) == [date(2026, 12, 29)]


def test_a_volatility_trade_falls_back_to_the_liquid_expiry(monkeypatch):
    far, near = chain(expiry=date(2026, 12, 29), oi=5.0), chain(expiry=date(2026, 11, 24))   # next month: no OI
    monkeypatch.setattr(osg.opt, "expiries", lambda sym: ([date(2026, 11, 24), date(2026, 12, 29)], 200))
    monkeypatch.setattr(osg, "get_chain", lambda sym, rule=None, expiry=None, now=None: far if expiry == far["expiry"] else near)
    when = NOW.replace(day=13)
    r = osg.build_straddle("NIFTY", {"rank": 5.0, "percentile": 5.0, "iv": 10.0}, when, 65)
    assert r is not None and r["expiry"] == "2026-11-24"


# ---- the builders ---------------------------------------------------------------------------------------------------
def test_buy_picks_the_target_delta_and_prices_the_stop_and_target(world):
    world["chain"] = c = chain()
    r = osg.build_buy("intraday", "u1", "NIFTY", "LONG", 24900.0, 25150.0, "near", 0.55, {"key": "k"}, NOW, 65)
    (leg,) = r["legs"]
    assert leg["type"] == "CE" and leg["action"] == "buy" and leg["delta"] == pytest.approx(0.55, abs=0.03)
    row = c["df"][c["df"]["strike"] == leg["strike"]].iloc[0]
    assert r["entry"] == pytest.approx(row["ce_ask"], abs=0.01)                    # bought at the ask
    assert r["stop"] < r["entry"] < r["target"]                                   # re-priced at the underlying's levels
    ask = float(row["ce_ask"])
    assert r["capital"] == pytest.approx(ask * 65 + osg._charges(ask * 65, "buy", NOW.date()), abs=0.01)
    assert r["max_loss"] > (r["entry"] - r["stop"]) * 65                          # plus both orders' charges
    assert r["kind"] == "debit" and r["state"] == "open" and r["id"] == "intraday|u1"
    p = osg.build_buy("intraday", "u2", "NIFTY", "SHORT", 25100.0, 24850.0, "near", 0.55, {"key": "k"}, NOW, 65)
    assert p["legs"][0]["type"] == "PE" and p["stop"] < p["entry"] < p["target"]


def test_buy_without_a_usable_stop_risks_the_whole_premium(world):
    world["chain"] = chain()
    r = osg.build_buy("stock", "u", "NIFTY", "LONG", 25500.0, None, "month", 0.70, {"key": "k"}, NOW, 65)   # stop above
    assert r["stop"] is None and r["target"] is None
    assert r["max_loss"] == pytest.approx(r["capital"], abs=0.05)


def test_buy_needs_a_liquid_option(world):
    world["chain"] = chain(oi=10.0)                                               # under OI_MIN everywhere
    assert osg.build_buy("intraday", "u", "NIFTY", "LONG", 24900.0, 25150.0, "near", 0.55, {}, NOW, 65) is None
    world["chain"] = None                                                         # NSE refused
    assert osg.build_buy("intraday", "u", "NIFTY", "LONG", 24900.0, 25150.0, "near", 0.55, {}, NOW, 65) is None


def test_iron_condor_is_defined_risk_with_wings_further_out(world):
    world["chain"] = c = chain()
    r = osg.build_condor("NIFTY", {"rank": 80.0, "percentile": 85.0, "iv": 16.0}, NOW, 65)
    sc, lc, sp, lp = r["legs"]
    assert [(x["action"], x["type"]) for x in r["legs"]] == [("sell", "CE"), ("buy", "CE"), ("sell", "PE"), ("buy", "PE")]
    assert sc["delta"] == pytest.approx(osg.CONDOR_DELTA, abs=0.03) and sp["delta"] == pytest.approx(-osg.CONDOR_DELTA, abs=0.03)
    want = c["spot"] * osg.WING_PCT["index"] / 100
    assert lc["strike"] - sc["strike"] >= want and sp["strike"] - lp["strike"] >= want
    width = max(lc["strike"] - sc["strike"], sp["strike"] - lp["strike"])
    assert r["kind"] == "credit" and osg.MIN_CREDIT_OF_WIDTH * width <= r["entry"] < width
    assert r["stop"] == pytest.approx(r["entry"] * 2, abs=0.02) and r["target"] == pytest.approx(r["entry"] / 2, abs=0.02)
    assert r["max_loss"] > (width - r["entry"]) * 65                              # the width minus the credit, + charges
    assert r["breakevens"] == [pytest.approx(sp["strike"] - r["entry"]), pytest.approx(sc["strike"] + r["entry"])]
    assert r["strategy"]["status"] == "untested"


def test_condor_refuses_a_thin_credit(world, monkeypatch):
    world["chain"] = chain()
    monkeypatch.setattr(osg, "MIN_CREDIT_OF_WIDTH", 0.9)
    assert osg.build_condor("NIFTY", {"rank": 80.0, "percentile": 85.0, "iv": 16.0}, NOW, 65) is None


def test_straddle_buys_both_at_the_money_options(world):
    world["chain"] = c = chain()
    r = osg.build_straddle("NIFTY", {"rank": 5.0, "percentile": 5.0, "iv": 10.0}, NOW, 65)
    ce, pe = r["legs"]
    assert ce["strike"] == pe["strike"] == float(c["df"]["strike"].iloc[(c["df"]["strike"] - c["F"]).abs().argmin()])
    assert r["entry"] == pytest.approx(ce["premium"] + pe["premium"], abs=0.02)
    assert r["stop"] < r["entry"] < r["target"]


# ---- marks and exits ------------------------------------------------------------------------------------------------
def test_value_now_marks_at_mid_and_closes_across_the_spread(world):
    world["chain"] = c = chain()
    b = osg.build_buy("intraday", "u", "NIFTY", "LONG", 24900.0, 25150.0, "near", 0.55, {}, NOW, 65)
    row = c["df"][c["df"]["strike"] == b["legs"][0]["strike"]].iloc[0]
    assert osg.value_now(b, c) == pytest.approx(row["ce_ltp"])                      # mid
    assert osg.value_now(b, c, "close") == pytest.approx(row["ce_bid"])             # a bought leg sells at the bid
    k = osg.build_condor("NIFTY", {"rank": 80.0, "percentile": 85.0, "iv": 16.0}, NOW, 65)
    assert osg.value_now(k, c, "close") > osg.value_now(k, c) > 0                  # buying back costs more than mid
    assert osg.value_now(b, None) is None


def test_exit_rules_for_debit_and_credit():
    debit = {"kind": "debit", "stop": 80.0, "target": 150.0}
    assert osg._exit_rule(debit, 79.0) == "stop" and osg._exit_rule(debit, 151.0) == "target"
    assert osg._exit_rule(debit, 100.0) is None
    credit = {"kind": "credit", "stop": 200.0, "target": 50.0}
    assert osg._exit_rule(credit, 201.0) == "stop" and osg._exit_rule(credit, 49.0) == "target"


def test_close_books_the_pnl_after_both_sides_charges(world):
    world["chain"] = chain()
    b = osg.build_buy("intraday", "u", "NIFTY", "LONG", 24900.0, 25150.0, "near", 0.55, {}, NOW, 65)
    osg._close(b, b["entry"] + 10.0, "target", NOW)
    assert b["state"] == "closed" and b["exit_reason"] == "target"
    assert b["pnl"] == pytest.approx(10.0 * 65 - b["charges"], abs=0.05) and b["charges"] > b["charges_in"]
    assert b["ret_pct"] == pytest.approx(b["pnl"] / b["capital"] * 100, abs=0.1)


# ---- refresh: open, mark, exit ----------------------------------------------------------------------------------------
def test_an_intraday_signal_opens_once_and_exits_at_its_target(world):
    rep = osg.refresh(intraday=isig(), now=NOW, sources=("intraday",))
    assert rep["opened"] == 1 and rep["open"] == 1
    (r,) = osg.load()
    assert r["source"] == "intraday" and r["symbol"] == "RELIANCE" and r["lot"] == 500 and r["legs"][0]["type"] == "CE"
    assert osg.refresh(intraday=isig(), now=NOW.replace(minute=1), sources=("intraday",))["opened"] == 0   # once
    world["chain"] = chain("RELIANCE", 2600.0, step=10)                            # the stock ran past the target
    rep = osg.refresh(intraday=isig(), now=NOW.replace(minute=5), sources=("intraday",))
    (r,) = osg.load()
    assert rep["closed"] == 1 and r["state"] == "closed" and r["exit_reason"] == "target" and r["pnl"] > 0


def test_intraday_options_follow_the_strategy_exit_and_square_off_at_15(world):
    osg.refresh(intraday=isig(), now=NOW, sources=("intraday",))
    osg.refresh(intraday=isig("closed", "trend exit"), now=NOW.replace(hour=11), sources=("intraday",))
    (r,) = osg.load()
    assert r["exit_reason"] == "strategy exit (trend exit)"
    later = NOW.replace(hour=12)
    sig = isig()
    sig["signals"][0]["entry_time"] = "12:00"
    osg.refresh(intraday=sig, now=later, sources=("intraday",))
    osg.refresh(intraday=sig, now=later.replace(hour=15, minute=0), sources=("intraday",))
    assert [x["exit_reason"] for x in osg.load()] == ["strategy exit (trend exit)", "square-off 15:00"]
    assert osg.refresh(intraday=isig(), now=later.replace(hour=15, minute=5), sources=("intraday",))["opened"] == 0


def test_nothing_opens_or_marks_with_the_market_closed(world, monkeypatch):
    monkeypatch.setattr(osg, "_market_open", lambda now: False)
    assert osg.refresh(intraday=isig(), now=NOW, sources=("intraday",))["opened"] == 0 and osg.load() == []


def test_a_working_strategys_buy_becomes_a_monthly_call_left_to_the_strategys_exit(world):
    world["chain"] = chain("RELIANCE", 2500.0, expiry=date(2026, 12, 29), step=10)
    world["scan"] = {"scan_id": "2026-11-13T18:00", "generated_at": "2026-11-13T18:00:00+05:30", "strategies": [
        {"key": "momentum", "name": "Momentum", "status": "working",
         "actions": [{"symbol": "RELIANCE", "action": "BUY", "stop": 2380.0}]},
        {"key": "losing", "name": "Losing", "status": "not-working",
         "actions": [{"symbol": "RELIANCE", "action": "BUY", "stop": 2380.0}]}]}
    assert osg.refresh(now=NOW, sources=("stock",))["opened"] == 1                  # only the working strategy's
    (r,) = osg.load()
    assert r["source"] == "stock" and r["target"] is None and r["stop"] < r["entry"]
    assert r["legs"][0]["delta"] == pytest.approx(osg.DELTA_MONTH, abs=0.04)
    later = {"generated_at": "2026-11-16T18:00:00+05:30", "strategies": [
        {"key": "momentum", "status": "working", "actions": [{"symbol": "RELIANCE", "action": "SELL"}], "positions": []}]}
    assert osg._stock_exit(r, later) == "strategy exit (sell)"
    gone = {"generated_at": "2026-11-16T18:00:00+05:30", "strategies": [{"key": "momentum", "actions": [], "positions": []}]}
    assert osg._stock_exit(r, gone) == "strategy exit (no longer held)"
    assert osg._stock_exit(r, world["scan"]) is None                                # the scan it came from


def test_volatility_trades_open_on_a_high_or_low_iv_rank(world, monkeypatch):
    from scanner import iv_history as ivh
    world["chain"] = chain()
    ranks = pd.DataFrame({"symbol": ["NIFTY", "RELIANCE"], "rank": [85.0, 40.0], "percentile": [90.0, 50.0],
                          "iv": [18.0, 25.0]})
    monkeypatch.setattr(ivh, "ranks", lambda: ranks)
    rep = osg.refresh(now=NOW, sources=("volatility",))
    (r,) = osg.load()
    assert rep["opened"] == 1 and r["symbol"] == "NIFTY" and r["structure"].startswith("Iron condor")
    assert osg.refresh(now=NOW.replace(minute=30), sources=("volatility",))["opened"] == 0   # one open per underlying
    early = osg.refresh(now=NOW.replace(hour=9, minute=20), sources=("volatility",))
    assert early["opened"] == 0                                                     # not before 09:30


# ---- nightly settlement at NSE's official closes -----------------------------------------------------------------
def bhavcopy(rows: list[tuple], under: dict) -> bytes:
    df = pd.DataFrame([{"FinInstrmTp": "STO" if s != "NIFTY" else "IDO", "TckrSymb": s, "XpryDt": e, "StrkPric": k,
                        "OptnTp": t, "ClsPric": px, "SttlmPric": px, "UndrlygPric": under[s]} for s, e, k, t, px in rows])
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("fo.csv", df.to_csv(index=False))
    return buf.getvalue()


def test_settle_day_closes_left_over_intraday_at_the_close_and_expired_at_intrinsic(world):
    osg.refresh(intraday=isig(), now=NOW, sources=("intraday",))
    rows = osg.load()
    exp_rec = {**rows[0], "id": "stock|x", "source": "stock", "expiry": NOW.date().isoformat(),
               "legs": [{**rows[0]["legs"][0], "expiry": NOW.date().isoformat()}]}
    osg._save(rows + [exp_rec])
    k = rows[0]["legs"][0]["strike"]
    content = bhavcopy([("RELIANCE", EXP.isoformat(), k, "CE", 61.5)], {"RELIANCE": 2540.0})
    assert osg.settle_day(content, NOW.date()) == 2
    a, b = osg.load()
    assert a["exit"] == 61.5 and a["exit_reason"] == "day's close (not closed live)" and a["exit_src"] == "nse close"
    assert b["exit"] == pytest.approx(max(2540.0 - k, 0.0)) and b["exit_reason"] == "expiry"


# ---- the record --------------------------------------------------------------------------------------------------
def test_record_per_source_after_charges():
    rows = [{"source": "intraday", "state": "closed", "pnl": 500.0, "ret_pct": 10.0},
            {"source": "intraday", "state": "closed", "pnl": -300.0, "ret_pct": -6.0},
            {"source": "intraday", "state": "open"},
            {"source": "volatility", "state": "closed", "pnl": 1200.0, "ret_pct": 4.0}]
    rec = {r["source"]: r for r in osg.record(rows)}
    assert rec["intraday"]["trades"] == 2 and rec["intraday"]["win_rate"] == 50.0 and rec["intraday"]["pnl"] == 200.0
    assert rec["intraday"]["open"] == 1 and rec["intraday"]["avg_ret_pct"] == 2.0
    assert rec["stock"]["trades"] == 0 and rec["stock"]["pnl"] == 0.0
    assert all(r["verdict"] == "not enough trades yet" for r in rec.values())


# ---- the volatility backtest ---------------------------------------------------------------------------------------
def test_iv_rank_and_percentile_against_the_days_before():
    s = pd.Series(np.r_[np.linspace(10, 20, 130), [25.0, 10.0]], index=pd.bdate_range("2026-01-01", periods=132))
    rk = osg.iv_rank_series(s)
    assert rk["rank"].iloc[:119].isna().all()                                      # 120 days needed first
    assert rk["rank"].iloc[-2] == pytest.approx(100.0) and rk["percentile"].iloc[-2] == pytest.approx(100.0)
    assert rk["rank"].iloc[-1] == pytest.approx(0.0) and rk["percentile"].iloc[-1] == pytest.approx(0.0)


def test_vol_backtest_enters_only_on_high_rank_days(monkeypatch):
    from scanner import options_backtest as ob
    seen = []
    monkeypatch.setattr(ob, "backtest", lambda hist, spec, entry_days=None: (seen.append(entry_days),
                                                                              {"stats": {"trades": len(entry_days)}, "trades": []})[1])
    idx = pd.bdate_range("2025-01-01", periods=200)
    calm = 12 + 2 * np.sin(np.arange(150) / 3) * (1 - np.arange(150) / 150)       # quietening: no new highs late
    iv = pd.Series(np.r_[calm, np.linspace(12, 30, 30), np.linspace(30, 11, 20)], index=idx)
    out = osg.vol_backtest("NIFTY", pd.DataFrame(), iv)
    always, high = seen
    assert high and high < always and min(high) >= idx[150]                         # the spike only
    assert out["high_days"] == len(high) and out["days_with_rank"] == len(always)


def test_options_backtest_entry_days_filter():
    from scanner import options_backtest as ob
    days = pd.bdate_range("2026-03-02", "2026-03-30")
    exp = pd.Timestamp("2026-03-30")
    rows = []
    for d in days:
        tv = 150.0 * max((exp - d).days, 0) / 30
        for k in range(9000, 11001, 100):
            for typ in ("CE", "PE"):
                px = (max(10000 - k, 0) if typ == "CE" else max(k - 10000, 0)) + tv * np.exp(-abs(k - 10000) / 400)
                rows.append({"date": d, "symbol": "NIFTY", "expiry": exp, "strike": float(k), "type": typ, "close": px,
                             "settle": px, "oi": 1000.0, "volume": 10.0, "underlying": 10000.0, "lot": 65.0})
    h = pd.DataFrame(rows)
    spec = {"strategy": "iron_condor", "cycle": "monthly", "entry_dte": 30, "short_pct": 2, "wing_pct": 4, "slippage_pct": 0}
    pick = days[5]
    (t,) = ob.backtest(h, spec, entry_days={pick})["trades"]
    assert t["entry"] == pick.date().isoformat()
    assert ob.backtest(h, spec, entry_days=set())["trades"] == []


# ---- the auto-trader mirrors the journal ------------------------------------------------------------------------
def test_auto_trader_takes_todays_signals_within_its_limit_and_closes_with_them(monkeypatch):
    from web.api.services import autotrade_svc as at
    rec = lambda i, state="open", **kw: {"id": f"intraday|{i}", "source": "intraday", "symbol": "RELIANCE",   # noqa: E731
                                          "structure": "Buy CE", "kind": "debit", "expiry": EXP.isoformat(), "lot": 500,
                                          "entry": 40.0, "stop": 30.0, "target": 55.0, "capital": 20030.0,
                                          "max_loss": 5100.0, "mark": 41.0, "day": NOW.date().isoformat(),
                                          "legs": [{"action": "buy", "type": "CE", "strike": 2500.0}], "state": state, **kw}
    journal = [rec(1), rec(2), {**rec(3), "day": "2026-11-13"}]
    monkeypatch.setattr(osg, "load", lambda: journal)
    st = {"options": {}, "settings": {"option_signals": True, "max_option_positions": 1}, "log": []}
    ev: list = []
    at._option_signals_pass(st, NOW, ev)
    assert list(st["options"]["signals_open"]) == ["intraday|1"] and [e["kind"] for e in ev] == ["entry"]  # limit 1
    journal[0] = rec(1, "closed", exit=55.5, exit_reason="target", pnl=7600.0, ret_pct=38.0, closed_at=NOW.isoformat())
    ev.clear()
    at._option_signals_pass(st, NOW.replace(minute=5), ev)
    assert st["options"]["signals_closed"][0]["pnl"] == 7600.0 and ev[0]["kind"] == "exit"
    assert list(st["options"]["signals_open"]) == ["intraday|2"]                     # the slot freed: the next one
    assert "intraday|3" not in st["options"]["signals_taken"]                       # an old day's signal: never
    st["settings"]["option_signals"] = False
    journal[1] = rec(2, "closed", exit=30.0, exit_reason="stop", pnl=-5100.0)
    at._option_signals_pass(st, NOW.replace(minute=6), ev)
    assert st["options"]["signals_open"] == {}                                      # switched off: still closed out


# ---- the API ---------------------------------------------------------------------------------------------------------
def test_view_shows_todays_signals_or_the_last_sessions(world, monkeypatch):
    from scanner import option_verdict as ov
    from web.api.services import optsig_svc
    monkeypatch.setattr(ov, "load_journal", lambda: [])
    monkeypatch.setattr(optsig_svc, "now_ist", lambda: NOW.replace(day=21))       # a Saturday: nothing today
    osg.refresh(intraday=isig(), now=NOW, sources=("intraday",))
    osg.refresh(intraday=isig(), now=NOW.replace(hour=15), sources=("intraday",))  # squared off
    v = optsig_svc.view()
    assert [r["source"] for r in v["signals"]] == ["intraday"] and v["signals"][0]["state"] == "closed"
    assert {r["source"] for r in v["record"]} == {"intraday", "stock", "volatility"}
    assert optsig_svc.view("stock")["signals"] == [] and "SEBI" in v["note"]
    assert v["verdicts"] == {"day": None, "rows": [], "track": None}


def test_signals_routes(world, monkeypatch):
    from fastapi.testclient import TestClient
    from scanner import option_verdict as ov
    from web.api.main import create_app
    from web.api.services import optsig_svc
    monkeypatch.setattr(ov, "load_journal", lambda: [])
    monkeypatch.setattr(optsig_svc, "_intraday", lambda: isig())
    monkeypatch.setattr(optsig_svc, "vol_test", lambda: {"tests": [], "note": "n"})
    c = TestClient(create_app(warm=False), base_url="http://127.0.0.1")
    assert c.get("/api/options/signals").status_code == 200
    assert c.post("/api/options/signals/refresh", json={}).status_code == 403          # the CSRF guard
    r = c.post("/api/options/signals/refresh", json={}, headers={"X-Quant-Desk": "1"})
    assert r.status_code == 200 and isinstance(r.json()["signals"], list)
    assert c.get("/api/options/signals?source=intraday").status_code == 200
    assert c.get("/api/options/vol-test").json() == {"tests": [], "note": "n"}
