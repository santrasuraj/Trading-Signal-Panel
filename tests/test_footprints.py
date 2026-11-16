"""Big money live (scanner/footprints.py, web/api/services/footprints_svc.py). No network, files in tmp_path."""
from datetime import datetime

import numpy as np
import pandas as pd
import pytest

from scanner import footprints as fp
from scanner.settings import IST

DAYS = pd.bdate_range("2026-09-14", periods=21)          # 20 past sessions + "today"
TODAY = DAYS[-1]


def bars(today_mult: dict[str, float], today_close: dict[str, float]) -> pd.DataFrame:
    """Every session 09:15-11:25 (27 bars) of 1,000 shares at 100; today's volume x `today_mult`, closing at
    `today_close` (bars rise linearly from 100, so the VWAP sits below a higher close)."""
    rows = []
    for d in DAYS:
        for sym in today_mult:
            for k in range(27):
                ts = d + pd.Timedelta(minutes=555 + 5 * k)
                is_today = d == TODAY
                px = 100 + (today_close[sym] - 100) * (k + 1) / 27 if is_today else 100.0
                v = 1000 * (today_mult[sym] if is_today else 1)
                rows.append({"ts": ts, "symbol": sym, "open": px, "high": px, "low": px, "close": px, "volume": v,
                             "flags": 0, "source": "fyers_ws" if is_today else "fyers"})
    return pd.DataFrame(rows)


def frames(syms) -> dict:
    close = pd.DataFrame({s: 100.0 for s in syms}, index=DAYS[:-1])
    return {"close": close}


def test_relative_volume_compares_the_same_time_of_day():
    b = bars({"AAA": 4.0, "BBB": 1.0}, {"AAA": 105, "BBB": 100})
    upto = TODAY + pd.Timedelta(hours=11, minutes=30)
    rv = fp.relative_volume(b, TODAY, upto).set_index("symbol")
    assert rv.loc["AAA", "rvol"] == pytest.approx(4.0) and rv.loc["BBB", "rvol"] == pytest.approx(1.0)
    assert rv.loc["AAA", "sessions"] == 20 and rv.loc["AAA", "vwap"] < rv.loc["AAA", "last"] == 105


@pytest.fixture
def files(tmp_path, monkeypatch):
    monkeypatch.setattr(fp, "FP_FILE", tmp_path / "footprints.json")
    monkeypatch.setattr(fp, "LOG_FILE", tmp_path / "footprints_log.parquet")
    monkeypatch.setattr(fp, "LIVE_DIR", tmp_path / "live")
    from scanner.intraday import run
    monkeypatch.setattr(run, "intraday_universe", lambda cfg, f: (list(f["close"].columns), {}))
    return tmp_path


def test_scan_alerts_on_heavy_volume_only_when_enough_money_trades(files, monkeypatch):
    monkeypatch.setattr(fp, "MIN_VALUE_CR", 0.0)
    b = bars({"AAA": 4.0, "BBB": 1.2, "CCC": 3.0}, {"AAA": 105, "BBB": 101, "CCC": 96})
    now = datetime(2026, 10, 12, 11, 32, tzinfo=IST)
    assert pd.Timestamp(now.date()) == TODAY
    out = fp.scan({}, now=now, bars=b, frames=frames(["AAA", "BBB", "CCC"]), fetch_blocks=False, log=lambda m: None)
    got = {r["symbol"]: (r["direction"], r["kinds"]) for r in out["rows"]}
    assert got == {"AAA": ("up", ["volume"]), "CCC": ("down", ["volume"])}          # BBB is normal volume
    assert out["rows"][0]["symbol"] == "AAA" and "4.0x normal" in out["rows"][0]["reasons"][0]
    fp.scan({}, now=now, bars=b, frames=frames(["AAA", "BBB", "CCC"]), fetch_blocks=False, log=lambda m: None)
    log = fp.load_log()
    assert sorted(log["symbol"]) == ["AAA", "CCC"]                                 # once per stock and day
    monkeypatch.setattr(fp, "MIN_VALUE_CR", 1e9)
    assert fp.scan({}, now=now, bars=b, frames=frames(["AAA"]), fetch_blocks=False, log=lambda m: None)["rows"] == []


def test_recorder_keeps_large_prints_with_their_side_and_the_book(files):
    rec = fp.FootprintRecorder(min_cr=1.0)
    t = int(datetime(2026, 10, 12, 10, 0, tzinfo=IST).timestamp())
    base = {"symbol": "NSE:AAA-EQ", "last_traded_time": t, "bid_price": 999.0, "ask_price": 1000.0}
    rec.on_tick({**base, "ltp": 1000.0, "last_traded_qty": 20000})          # Rs 2 cr at the ask: buyer
    rec.on_tick({**base, "ltp": 999.0, "last_traded_qty": 15000})           # Rs 1.5 cr at the bid: seller
    rec.on_tick({**base, "ltp": 1000.0, "last_traded_qty": 50, "tot_buy_qty": 9000, "tot_sell_qty": 3000})
    assert [(p["symbol"], p["side"]) for p in rec.prints] == [("AAA", "BUY"), ("AAA", "SELL")]
    rec.flush(TODAY.date())
    saved = pd.read_parquet(fp.prints_file(TODAY.date()))
    assert len(saved) == 2 and rec.prints == [] and fp.book_file().exists()
    assert rec.book["AAA"] == {"buy_qty": 9000.0, "sell_qty": 3000.0}


def test_outcomes_measure_the_next_close_in_the_alert_direction():
    log = pd.DataFrame([{"date": "2026-10-09", "time": "11:30", "symbol": "AAA", "price": 100.0, "direction": "up"},
                        {"date": "2026-10-09", "time": "11:30", "symbol": "BBB", "price": 100.0, "direction": "down"},
                        {"date": "2026-10-12", "time": "11:30", "symbol": "AAA", "price": 100.0, "direction": "up"}])
    close = pd.DataFrame({"AAA": [100.0, 103.0], "BBB": [100.0, 98.0]}, index=pd.to_datetime(["2026-10-09", "2026-10-12"]))
    out = fp.outcomes(log, close)
    assert list(out["move_pct"].round(2)[:2]) == [3.0, 2.0] and np.isnan(out["move_pct"].iloc[2])   # no next close yet


def test_live_api_joins_the_disclosures(files, monkeypatch):
    from fastapi.testclient import TestClient
    from web.api.main import create_app
    from web.api.models import smart_money as M
    from web.api.services import footprints_svc
    monkeypatch.setattr(fp, "MIN_VALUE_CR", 0.0)
    b = bars({"AAA": 4.0, "CCC": 3.0}, {"AAA": 105, "CCC": 96})
    fp.scan({}, now=datetime(2026, 10, 12, 11, 32, tzinfo=IST), bars=b, frames=frames(["AAA", "CCC"]),
            fetch_blocks=False, log=lambda m: None)
    ctx = {"AAA": {"direction": "up", "reasons": ["Promoter bought"], "deal_net_value": 1e8, "insider_buy_value": 1e8,
                   "insider_sell_value": 0.0, "promoter_buying": True, "promoter_selling": False}}
    monkeypatch.setattr(footprints_svc, "_context", lambda: ctx)
    monkeypatch.setattr(footprints_svc, "data_market_open", lambda: False)
    r = TestClient(create_app(warm=False), base_url="http://127.0.0.1").get("/api/smart-money/live")
    assert r.status_code == 200
    d = M.SmLiveResponse.model_validate(r.json()).model_dump()
    assert [(x["symbol"], x["agree"]) for x in d["rows"]] == [("AAA", True), ("CCC", False)]   # agreement first
    assert d["track"]["min_to_judge"] == 30 and d["fresh"]


def test_track_handles_alerts_with_and_without_a_next_close(files, monkeypatch):
    from web.api.models import smart_money as M
    from web.api.services import footprints_svc, data
    pd.DataFrame([{"date": "2026-10-09", "time": "11:30", "symbol": "AAA", "price": 100.0, "direction": "up", "rvol": 3.0,
                   "value_cr": 50.0, "prints_cr": 0.0, "block": False, "kinds": "volume"},
                  {"date": "2026-10-12", "time": "11:30", "symbol": "AAA", "price": 103.0, "direction": "down",
                   "rvol": 3.0, "value_cr": 50.0, "prints_cr": 0.0, "block": False, "kinds": "volume"}]
                 ).to_parquet(fp.LOG_FILE, index=False)
    close = pd.DataFrame({"AAA": [100.0, 103.0]}, index=pd.to_datetime(["2026-10-09", "2026-10-12"]))
    monkeypatch.setattr(data, "store_close", lambda: close)
    monkeypatch.setattr(footprints_svc, "_context", lambda: {})
    t = M.SmLiveTrack.model_validate(footprints_svc.track()).model_dump()
    assert [(a["date"], a["next_date"], a["move_pct"]) for a in t["recent"]] == [
        ("2026-10-12", None, None), ("2026-10-09", "2026-10-12", 3.0)]
    assert t["all"] == {"alerts": 1, "hit_rate": 100.0, "avg_move_pct": 3.0}
