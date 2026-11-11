"""Order flow from the normal feed (scanner/intraday/orderflow.py) and its chart data (orderflow_svc.py)."""
from datetime import datetime

import pandas as pd
import pytest

from scanner.intraday import orderflow
from scanner.intraday.live import live_dir
from scanner.settings import IST
from web.api.paths import P
from web.api.services import orderflow_svc


def _t(h, m, s=0):
    return int(datetime(2026, 11, 12, h, m, s, tzinfo=IST).timestamp())


def tick(px, cum, bid, ask, t):
    return {"symbol": "NSE:TCS-EQ", "ltp": px, "vol_traded_today": cum, "bid_price": bid, "ask_price": ask, "last_traded_time": t}


def test_volume_is_split_by_the_quote_and_tick_rules():
    b = orderflow.OrderFlowBuilder()
    b.on_tick(tick(1000, 50_000, 999.9, 1000.1, _t(9, 30)))          # the day so far: no new volume
    b.on_tick(tick(1000.1, 50_100, 999.9, 1000.1, _t(9, 30, 5)))     # at the ask: bought
    b.on_tick(tick(999.9, 50_160, 999.9, 1000.1, _t(9, 30, 9)))      # at the bid: sold
    b.on_tick(tick(1000.0, 50_200, 999.8, 1000.2, _t(9, 31, 2)))     # between, up from 999.9: bought (tick rule)
    b.on_tick(tick(1000.0, 50_200, 999.8, 1000.2, _t(9, 31, 3)))     # nothing new
    df = b.frame()
    assert df["buy"].sum() == 140 and df["sell"].sum() == 60
    assert sorted(df["ts"].dt.strftime("%H:%M").unique()) == ["09:30", "09:31"]
    assert orderflow.level_step(1335.0) == pytest.approx(0.65)


def test_chart_data_has_delta_cumulative_delta_and_a_profile(tmp_path, monkeypatch):
    monkeypatch.setattr(P, "data", tmp_path)
    monkeypatch.setattr(orderflow_svc, "today_ist", lambda: pd.Timestamp("2026-11-12").date())
    rows = [("2026-11-12 09:30", "TCS", 1000.0, 100, 20), ("2026-11-12 09:33", "TCS", 1000.5, 10, 50),
            ("2026-11-12 09:36", "TCS", 1000.0, 30, 30), ("2026-11-12 09:36", "INFY", 1500.0, 9, 9)]
    df = pd.DataFrame(rows, columns=orderflow.COLS)
    df["ts"] = pd.to_datetime(df["ts"])
    d = live_dir(tmp_path / "intraday")
    df.to_parquet(d / orderflow.file_name(pd.Timestamp("2026-11-12")), index=False)
    f = orderflow_svc.flow("TCS", "5m")
    assert f["bars"]["delta"] == [40.0, 0.0] and f["bars"]["cum_delta"] == [40.0, 40.0]
    assert f["poc"] == 1000.0 and f["totals"] == {"buy": 140.0, "sell": 100.0}
    with pytest.raises(Exception):
        orderflow_svc.flow("WIPRO", "5m")
