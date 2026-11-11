"""The practice account on live prices (web/api/services/sim_svc.py) and market depth parsing (depth_svc.py).
Quotes are faked: nothing reaches FYERS."""
import pytest

from web.api.errors import ApiException
from web.api.paths import P
from web.api.services import clock, data, depth_svc, quotes_svc, sim_svc


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(P, "data", tmp_path)
    monkeypatch.setattr(data, "config", lambda: {"account": {"capital": 100_000}, "costs": {"slippage_pct": 0}})
    prices = {"TCS": 1000.0}
    sess = {"s": "open"}
    monkeypatch.setattr(clock, "market_clock", lambda now=None: {"session": sess["s"]})
    from datetime import datetime
    from scanner.settings import IST
    monkeypatch.setattr(sim_svc, "now_ist", lambda: datetime(2026, 11, 12, 11, 0, tzinfo=IST))
    monkeypatch.setattr(quotes_svc, "quotes", lambda syms, allow_network=True: {
        "session": sess["s"], "quotes": [{"symbol": s, "price": prices[s], "source": "live"} for s in syms if s in prices]})
    return prices, sess


def test_market_buy_then_stop_closes_it(env):
    prices, _ = env
    o = sim_svc.place({"symbol": "TCS", "side": "BUY", "qty": 10, "type": "MARKET", "product": "CNC", "stop": 950, "target": 1100})
    assert o["status"] == "filled" and o["fill_price"] == 1000
    v = sim_svc.view()
    assert v["positions"][0]["qty"] == 10 and v["cash"] < 100_000 - 10_000           # paid plus charges
    prices["TCS"] = 940.0
    v = sim_svc.view()
    assert v["positions"] == [] and v["trades"][0]["reason"] == "stop" and v["trades"][0]["pnl"] == -600


def test_limit_order_waits_for_the_price(env):
    prices, _ = env
    o = sim_svc.place({"symbol": "TCS", "side": "BUY", "qty": 5, "type": "LIMIT", "product": "CNC", "limit_price": 980})
    assert o["status"] == "open"
    sim_svc.on_quotes({"TCS": {"symbol": "TCS", "price": 985, "source": "live"}})
    assert sim_svc.view()["orders"][0]["status"] == "open"
    sim_svc.on_quotes({"TCS": {"symbol": "TCS", "price": 975, "source": "live"}})
    v = sim_svc.view()
    assert v["orders"][0]["status"] == "filled" and v["orders"][0]["fill_price"] == 975   # the better price


def test_delivery_cannot_sell_short_and_market_needs_an_open_market(env):
    _, sess = env
    with pytest.raises(ApiException):
        sim_svc.place({"symbol": "TCS", "side": "SELL", "qty": 1, "type": "MARKET", "product": "CNC"})
    short = sim_svc.place({"symbol": "TCS", "side": "SELL", "qty": 2, "type": "MARKET", "product": "INTRADAY"})
    assert short["status"] == "filled" and sim_svc.view()["positions"][0]["qty"] == -2
    sess["s"] = "closed"
    with pytest.raises(ApiException):
        sim_svc.place({"symbol": "TCS", "side": "BUY", "qty": 1, "type": "MARKET", "product": "CNC"})
    assert sim_svc.reset(50_000)["cash"] == 50_000


def test_depth_reply_is_read_into_bids_and_asks():
    r = {"s": "ok", "d": {"NSE:TCS-EQ": {"bids": [{"price": 999.5, "volume": 120, "ord": 3}], "ask": [{"price": 1000, "volume": 80, "ord": 2}],
                                          "totalbuyqty": 5000, "totalsellqty": 4000, "ltp": 999.8}}}
    d = depth_svc.parse("TCS", r)
    assert d["bids"][0] == {"price": 999.5, "qty": 120, "orders": 3} and d["asks"][0]["price"] == 1000
    assert d["total_buy"] == 5000 and d["ltp"] == 999.8


def test_trailing_stop_only_tightens_and_closes(env):
    prices, _ = env
    sim_svc.place({"symbol": "TCS", "side": "BUY", "qty": 10, "type": "MARKET", "product": "CNC",
                   "trail": {"type": "pct", "value": 5}})
    assert sim_svc.view()["positions"][0]["stop"] == 950                    # 5% under the entry
    prices["TCS"] = 1100.0
    assert sim_svc.view()["positions"][0]["stop"] == 1045                   # follows the best price
    prices["TCS"] = 1060.0
    assert sim_svc.view()["positions"][0]["stop"] == 1045                   # never loosens
    prices["TCS"] = 1040.0
    v = sim_svc.view()
    assert v["positions"] == [] and v["trades"][0]["reason"] == "stop" and v["trades"][0]["pnl"] == 400


def test_scale_out_targets_and_breakeven(env):
    prices, _ = env
    sim_svc.place({"symbol": "TCS", "side": "BUY", "qty": 10, "type": "MARKET", "product": "CNC", "stop": 950,
                   "targets": [{"price": 1050, "qty": 5}, {"price": 1100, "qty": 5}], "breakeven": True})
    prices["TCS"] = 1055.0
    v = sim_svc.view()
    p = v["positions"][0]
    assert p["qty"] == 5 and p["stop"] == 1000 and len(p["targets"]) == 1      # half sold, stop at the entry
    assert v["trades"][0]["reason"] == "scale_out" and v["trades"][0]["exit"] == 1050
    prices["TCS"] = 1101.0
    v = sim_svc.view()
    assert v["positions"] == [] and sum(t["pnl"] for t in v["trades"]) == 750
    with pytest.raises(ApiException):
        sim_svc.place({"symbol": "TCS", "side": "BUY", "qty": 2, "type": "MARKET", "product": "CNC",
                       "targets": [{"price": 1200, "qty": 3}]})
