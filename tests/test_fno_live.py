"""Big trades live in index futures / options (scanner/fno_live.py): FYERS' public symbol list in its real format
(checked 2 Nov 2026), picking the futures and near-the-money options, recording large trades with their likely side
from FYERS SymbolUpdate ticks, and the page summary."""
from datetime import date, datetime

import pandas as pd
import pytest

from scanner import fno_live as fl
from scanner.settings import IST


def epoch(day: str) -> int:
    return int(pd.Timestamp(f"{day} 15:40", tz=IST).timestamp())


def master_text() -> str:
    rows = ["101126112361471,NIFTY 23 Nov 26 FUT,11,65,0.1,,0915-1540|1815-1915:,2026-10-30,"
            f"{epoch('2026-11-23')},NSE:NIFTY26NOVFUT,10,11,61471,NIFTY,26000,-1.0,XX,101000000026000,None,0,0.0",
            "101126122958875,NIFTY 29 Dec 26 FUT,11,65,0.1,,0915-1540|1815-1915:,2026-10-30,"
            f"{epoch('2026-12-29')},NSE:NIFTY26DECFUT,10,11,58875,NIFTY,26000,-1.0,XX,101000000026000,None,0,0.0",
            "101126112361466,BANKNIFTY 23 Nov 26 FUT,11,30,0.2,,0915-1540|1815-1915:,2026-10-30,"
            f"{epoch('2026-11-23')},NSE:BANKNIFTY26NOVFUT,10,11,61466,BANKNIFTY,26009,-1.0,XX,101000000026009,None,0,0.0"]
    for exp, code in (("2026-11-03", "26N03"), ("2026-11-09", "26N09")):
        for k in range(22800, 23301, 50):
            for t in ("CE", "PE"):
                rows.append(f"1,NIFTY {exp} {k} {t},14,65,0.05,,0915-1530|1815-1915:,2026-10-30,{epoch(exp)},"
                            f"NSE:NIFTY{code}{k}{t},10,11,1,NIFTY,26000,{k}.0,{t},101000000026000,None,0,0.0")
    return "\n".join(rows) + "\n"


def test_lot_count_handles_units_and_lots():
    assert fl.lot_count(650, 65) == 10        # units: a multiple of the lot size
    assert fl.lot_count(10, 65) == 10         # fewer than one lot in units is impossible: lots
    assert fl.lot_count(70, 65) == 70         # not a multiple of the lot size: lots
    assert fl.lot_count(0, 65) == 0


def test_parse_master_and_pick():
    m = fl.parse_master(master_text())
    fut = m[m["ticker"] == "NSE:NIFTY26NOVFUT"].iloc[0]
    assert fut["expiry"] == date(2026, 11, 23) and fut["lot"] == 65 and fut["opt"] == "XX"
    st = fl.settings({"live_fno": {"futures": ["NIFTY", "BANKNIFTY"], "options": ["NIFTY"], "strikes_each_side": 2}})
    got = fl.pick(m, st, {"NIFTY": 23053.1}, today=date(2026, 11, 2))
    assert [g["ticker"] for g in got[:2]] == ["NSE:NIFTY26NOVFUT", "NSE:BANKNIFTY26NOVFUT"]      # nearest futures
    opts = got[2:]
    assert {g["expiry"] for g in opts} == {"2026-11-03"}                                        # nearest expiry
    assert sorted({g["strike"] for g in opts}) == [22950.0, 23000.0, 23050.0, 23100.0, 23150.0]  # ATM 23050 +- 2
    assert len(opts) == 10 and {g["kind"] for g in opts} == {"ce", "pe"}
    assert fl.pick(m, st, {}, today=date(2026, 11, 2))[2:] == []            # no spot known: no options
    later = fl.pick(m, st, {"NIFTY": 23053.1}, today=date(2026, 11, 4))
    assert {g["expiry"] for g in later[2:]} == {"2026-11-09"}               # expired weekly skipped


def test_settings_validation():
    s = fl.settings({"live_fno": {"futures": "x", "strikes_each_side": 99, "option_print_lakh": "bad"}})
    assert s["futures"] == fl.DEFAULTS["futures"] and s["strikes_each_side"] == 15
    assert s["option_print_lakh"] == fl.DEFAULTS["option_print_lakh"]
    assert fl.settings({"live_fno": {"futures": [], "options": []}})["futures"] == []


def tick(sym, ltp, qty, bid, ask, t=1793678400, **kw):
    return {"symbol": sym, "ltp": ltp, "last_traded_qty": qty, "bid_price": bid, "ask_price": ask,
            "last_traded_time": t, **kw}


def test_recorder_keeps_large_trades_with_their_side(tmp_path):
    inst = [{"ticker": "NSE:NIFTY26NOVFUT", "underlying": "NIFTY", "kind": "fut", "strike": None,
             "expiry": "2026-11-23", "lot": 65},
            {"ticker": "NSE:NIFTY26N0323000CE", "underlying": "NIFTY", "kind": "ce", "strike": 23000.0,
             "expiry": "2026-11-03", "lot": 65}]
    rec = fl.FnoRecorder(inst, fl.settings({}))                    # futures >= Rs 5 cr, options >= Rs 25 lakh
    assert rec.wants("NSE:NIFTY26NOVFUT") and not rec.wants("NSE:RELIANCE-EQ")
    rec.on_tick(tick("NSE:NIFTY26NOVFUT", 23100, 65 * 40, 23099, 23100, tot_buy_qty=1e5, tot_sell_qty=5e4))  # 6.0 cr at ask
    rec.on_tick(tick("NSE:NIFTY26NOVFUT", 23100, 65 * 10, 23099, 23100))     # 1.5 cr: below the threshold
    rec.on_tick(tick("NSE:NIFTY26N0323000CE", 120.0, 400, 120.0, 121.0))      # 400 lots x 65 x 120 = 31.2 lakh, at bid
    rec.on_tick(tick("NSE:NIFTY26N0323000CE", 120.5, 26000, 120.0, 121.0))    # 400 lots in units, between: unknown
    rec.on_tick(tick("NSE:RELIANCE-EQ", 1300, 1e6, 1299, 1300))               # not ours: ignored
    assert [(p["kind"], p["side"], p["lots"]) for p in rec.prints] == [("fut", "BUY", 40), ("ce", "SELL", 400),
                                                                          ("ce", None, 400)]
    assert rec.prints[0]["value"] == pytest.approx(65 * 40 * 23100)
    rec.flush(date(2026, 11, 2), tmp_path)
    s = fl.summary(tmp_path, now=datetime.now(IST))
    assert s["date"] == "2026-11-02" and s["live"] and len(s["recent"]) == 3
    by = {i["ticker"]: i for i in s["instruments"]}
    f = by["NSE:NIFTY26NOVFUT"]
    assert f["prints"] == 1 and f["buy_cr"] == pytest.approx(6.01, abs=0.01) and f["sell_cr"] == 0
    assert f["buy_qty"] == 1e5 and f["sell_qty"] == 5e4
    c = by["NSE:NIFTY26N0323000CE"]
    assert c["sell_cr"] == pytest.approx(0.31, abs=0.01) and c["unknown_cr"] > 0 and c["net_cr"] < 0
    rec.on_tick(tick("NSE:NIFTY26NOVFUT", 23050, 65 * 40, 23050, 23051))      # 6.0 cr at bid; a 2nd flush appends
    rec.flush(date(2026, 11, 2), tmp_path)
    assert len(fl.summary(tmp_path)["recent"]) == 4


def test_summary_without_any_feed(tmp_path):
    s = fl.summary(tmp_path / "missing")
    assert s["date"] is None and not s["live"] and s["instruments"] == [] and s["recent"] == []
