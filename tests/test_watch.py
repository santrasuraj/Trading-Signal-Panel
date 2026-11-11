"""Watchlists and price alerts (scanner/watch.py), intraday candles (web/api/services/intraday_chart.py)."""
import time

import pandas as pd
import pytest

from scanner import watch


@pytest.fixture
def wdir(tmp_path, monkeypatch):
    monkeypatch.setattr(watch, "DATA_DIR", tmp_path)
    watch._cache.clear()
    return tmp_path


def test_watchlists_round_trip_and_clean_symbols(wdir):
    assert watch.watchlists() == {"lists": [{"name": "Main", "symbols": []}]}
    out = watch.save_watchlists([{"name": "Main", "symbols": ["reliance", "TCS", "TCS", "bad sym", ""]},
                                 {"name": "Banks", "symbols": ["HDFCBANK"]}])
    assert out["lists"][0]["symbols"] == ["RELIANCE", "TCS"]
    assert watch.watchlists()["lists"][1] == {"name": "Banks", "symbols": ["HDFCBANK"]}
    with pytest.raises(ValueError):
        watch.save_watchlists([{"name": "A", "symbols": []}, {"name": "a", "symbols": []}])


def test_alert_fires_once_on_a_live_price_never_on_a_stored_close(wdir):
    a = watch.add_alert("RELIANCE", "above", 1500)
    b = watch.add_alert("TCS", "change_below", -2)
    assert watch.evaluate({"RELIANCE": {"price": 1499.9, "source": "live"}}) == []
    assert watch.evaluate({"RELIANCE": {"price": 1600, "source": "close"}}) == []          # a stored close: never
    fired = watch.evaluate({"RELIANCE": {"price": 1501, "source": "live"}, "TCS": {"price": 1, "change_pct": -1.5, "source": "fyers"}})
    assert [x["id"] for x in fired] == [a["id"]] and fired[0]["fired_price"] == 1501
    assert watch.evaluate({"RELIANCE": {"price": 1600, "source": "live"}}) == []           # one-shot
    late = watch.evaluate({"TCS": {"price": 1, "change_pct": -2.5, "source": "yahoo"}})
    assert [x["id"] for x in late] == [b["id"]] and "15 min late" in watch.message(late[0])
    assert {x["id"]: x["active"] for x in watch.alerts()} == {a["id"]: False, b["id"]: False}
    assert [x["id"] for x in watch.recent_fired()] == [b["id"], a["id"]]                   # newest first
    _, since = watch.fired_since(time.time() - 60)
    assert {x["id"] for x in since} == {a["id"], b["id"]}
    assert watch.update_alert(a["id"], active=True)["fired_at"] is None                    # re-armed
    assert watch.feed_symbols() == ["RELIANCE"]
    watch.update_alert(a["id"], delete=True)
    assert [x["id"] for x in watch.alerts()] == [b["id"]]


def test_alert_validation(wdir):
    for args in (("bad sym", "above", 1), ("TCS", "sideways", 1), ("TCS", "below", 0)):
        with pytest.raises(ValueError):
            watch.add_alert(*args)


def test_feed_symbols_put_alerts_before_watchlists(wdir):
    watch.save_watchlists([{"name": "Main", "symbols": ["INFY", "TCS"]}])
    watch.add_alert("SBIN", "below", 500)
    assert watch.feed_symbols() == ["SBIN", "INFY", "TCS"]


def test_intraday_resample_and_vwap():
    from web.api.services import intraday_chart as ic
    ts = pd.date_range("2026-11-10 09:15", periods=6, freq="5min").append(pd.date_range("2026-11-11 09:15", periods=3, freq="5min"))
    df = pd.DataFrame({"ts": ts, "open": range(1, 10), "high": [x + 1 for x in range(1, 10)], "low": range(1, 10),
                       "close": range(1, 10), "volume": [100.0] * 9, "flags": [0] * 8 + [16]})
    m15 = ic.resample(df, "15m")
    assert list(m15["ts"].dt.strftime("%d %H:%M")) == ["10 09:15", "10 09:30", "11 09:15"]
    assert list(m15["open"]) == [1, 4, 7] and list(m15["close"]) == [3, 6, 9] and list(m15["volume"]) == [300, 300, 300]
    assert int(m15["flags"].iloc[-1]) == 16                                                # still forming
    v = ic.vwap(df)
    assert v[0] == round((2 + 1 + 1) / 3, 2) and v[6] == round((8 + 7 + 7) / 3, 2)        # restarts each session
