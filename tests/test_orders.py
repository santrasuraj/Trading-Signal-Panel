"""Orders on the user's own FYERS account (web/api/services/orders_svc.py), against a fake broker: nothing here can
reach FYERS. Two steps, every check, one attempt per order, kill switch, daily-loss lockout, protection, audit."""
import pytest

from web.api.errors import ApiException
from web.api.paths import P
from web.api.services import clock, data, orders_svc as o, quotes_svc


class FakeBroker:
    def __init__(self, pl=0.0, held=100, pending=(), place_raises=False):
        self.calls, self.pl, self.held, self.pending, self.place_raises = [], pl, held, list(pending), place_raises

    def place(self, payload):
        self.calls.append(("place", payload))
        if self.place_raises:      # what Broker._once returns for a timeout: the outcome is unknown
            return {"s": "error", "code": -99, "unknown": True, "message": "No answer from FYERS"}
        return {"s": "ok", "id": f"ORD{len(self.calls)}", "message": "Successfully placed order"}

    def cancel(self, oid):
        self.calls.append(("cancel", oid))
        return {"s": "ok"}

    def orderbook(self):
        return {"s": "ok", "orderBook": [{"id": i, "symbol": "NSE:TCS-EQ", "status": 6, "side": 1, "qty": 1, "type": 1} for i in self.pending]}

    def positions(self):
        return {"s": "ok", "overall": {"pl_total": self.pl}, "netPositions": []}

    def holdings(self):
        return {"s": "ok", "holdings": [{"symbol": "NSE:TCS-EQ", "quantity": self.held, "remainingQuantity": self.held}]}

    def place_gtt(self, payload):
        self.calls.append(("gtt", payload))
        return {"s": "ok", "id": "GTT1"}

    def gtt_orders(self):
        return {"s": "ok", "orderBook": []}


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(P, "data", tmp_path)
    monkeypatch.setattr(clock, "market_clock", lambda now=None: {"session": "open"})
    monkeypatch.setattr(data, "config", lambda: {"account": {"capital": 500_000}, "orders": {}, "costs": {}})
    monkeypatch.setattr(data, "latest", lambda: {})
    monkeypatch.setattr(quotes_svc, "quotes", lambda syms, allow_network=True: {
        "quotes": [{"symbol": s, "price": 1000.0, "source": "live"} for s in syms]})
    b = FakeBroker()
    monkeypatch.setattr(o, "broker", lambda: b)
    o._previews.clear()
    return b


T = {"symbol": "TCS", "side": "BUY", "qty": 10, "type": "LIMIT", "product": "CNC", "limit_price": 1001.0, "stop": 950.0,
     "target": 1150.0, "ref_price": 1000.0, "strategy_key": "momentum", "source": "action_card"}


def _failed(pv):
    return [c["key"] for c in pv["checks"] if c["blocking"] and not c["ok"]]


def test_off_by_default_and_switching_on_needs_the_phrase(env):
    pv = o.preview(T)
    assert not pv["ok"] and pv["preview_id"] is None and _failed(pv) == ["enabled"]
    with pytest.raises(ApiException):
        o.set_enabled(True, "yes")
    assert o.set_enabled(True, "enable")["enabled"]
    assert env.calls == []                                                      # nothing was ever sent


def test_preview_then_one_place_with_the_exact_payload(env):
    o.set_enabled(True, "ENABLE")
    pv = o.preview(T)
    assert pv["ok"] and pv["value"] == 10_010 and pv["risk_if_stopped"] == 510.0 and pv["charges"] >= 0
    assert pv["payload"] == {"symbol": "NSE:TCS-EQ", "qty": 10, "type": 1, "side": 1, "productType": "CNC",
                             "limitPrice": 1001.0, "stopPrice": 0, "validity": "DAY", "disclosedQty": 0, "offlineOrder": False}
    with pytest.raises(ApiException):
        o.place(pv["preview_id"], confirm=False)
    r = o.place(pv["preview_id"], confirm=True)
    assert r["ok"] and r["order_id"] == "ORD1" and [c[0] for c in env.calls] == ["place"]
    with pytest.raises(ApiException):
        o.place(pv["preview_id"], confirm=True)                                 # a preview is used once
    again = o.preview(T)
    assert "repeat" in _failed(again)                                            # the same order moments later
    events = [a["event"] for a in o.audit_tail()]
    assert events[:3] == ["preview", "placed", "send"] and "preview" in events


def test_no_answer_is_never_retried(env):
    o.set_enabled(True, "ENABLE")
    env.place_raises = True
    r = o.place(o.preview(T)["preview_id"], confirm=True)
    assert not r["ok"] and r["unknown"] and len([c for c in env.calls if c[0] == "place"]) == 1
    assert o.state()["count"] == 1 and o.audit_tail()[0]["event"] == "unknown"


def test_guards_band_value_market_and_lockout(env, monkeypatch):
    o.set_enabled(True, "ENABLE")
    assert "band" in _failed(o.preview({**T, "limit_price": 1100.0}))           # 10% above the last price
    assert "value" in _failed(o.preview({**T, "qty": 100}))                     # Rs 1 lakh > 10% of 5 lakh
    assert "type" in _failed(o.preview({**T, "type": "MARKET", "limit_price": None}))
    env.pl = -20_000                                                              # -4% of capital today
    assert "loss" in _failed(o.preview(T))
    assert "loss" not in _failed(o.preview({**T, "side": "SELL", "qty": 5}))    # exits are never locked out
    assert "held" in _failed(o.preview({**T, "side": "SELL", "qty": 500}))      # more than held
    monkeypatch.setattr(clock, "market_clock", lambda now=None: {"session": "post_close"})
    assert "market" in _failed(o.preview({**T, "side": "SELL", "qty": 5}))
    monkeypatch.setattr(o, "broker", lambda: (_ for _ in ()).throw(ApiException("FYERS_LOGIN_REQUIRED", "log in")))
    assert "login" in _failed(o.preview(T))


def test_kill_switch_blocks_and_cancels_pending(env):
    o.set_enabled(True, "ENABLE")
    pv = o.preview(T)
    env.pending = ["P1", "P2"]
    r = o.set_kill(True, "test")
    assert r["kill"] and [c["id"] for c in r["cancelled"]] == ["P1", "P2"]
    with pytest.raises(ApiException):
        o.place(pv["preview_id"], confirm=True)                                 # an earlier preview can't slip through
    assert "kill" in _failed(o.preview(T))
    assert not o.set_kill(False)["kill"] and o.preview(T)["ok"]


def test_daily_limit_and_gap(env, monkeypatch):
    monkeypatch.setattr(data, "config", lambda: {"account": {"capital": 500_000}, "costs": {},
                                                  "orders": {"max_orders_per_day": 1, "min_seconds_between_orders": 30}})
    o.set_enabled(True, "ENABLE")
    o.place(o.preview(T)["preview_id"], confirm=True)
    f = _failed(o.preview({**T, "symbol": "INFY", "qty": 5}))
    assert "count" in f and "gap" in f


def test_protection_is_an_oco_below_and_above_the_price(env):
    body = o.gtt_payload("TCS", 10, 950.0, 1150.0)
    assert body["side"] == -1 and body["productType"] == "CNC"
    assert body["orderInfo"]["leg1"]["triggerPrice"] == 1150.0 and body["orderInfo"]["leg2"]["triggerPrice"] == 950.0
    assert body["orderInfo"]["leg2"]["price"] < 950.0                          # the stop fills a little through
    o.set_enabled(True, "ENABLE")
    for bad in ((10, 1150.0, 950.0), (500, 950.0, 1150.0), (10, 1010.0, 1150.0)):   # target below stop / too many / stop above price
        with pytest.raises(ApiException):
            o.protect("TCS", *bad, confirm=True)
    assert o.protect("TCS", 10, 950.0, 1150.0, confirm=True)["ok"] and env.calls[-1][0] == "gtt"


def test_slippage_reconciliation():
    orders = [{"id": "A", "symbol": "TCS", "side": "BUY", "status": "filled", "avg_price": 1010.0},
              {"id": "B", "symbol": "INFY", "side": "SELL", "status": "filled", "avg_price": 990.0},
              {"id": "C", "symbol": "SBIN", "side": "BUY", "status": "pending", "avg_price": None}]
    trail = [{"event": "placed", "order_id": "A", "ticket": {"ref_price": 1000.0, "strategy_key": "momentum"}},
             {"event": "placed", "order_id": "B", "ticket": {"ref_price": 1000.0}}]
    r = o.reconcile(orders, trail)
    assert [(x["id"], x["slippage_pct"]) for x in r] == [("A", 1.0), ("B", 1.0)]   # both cost 1%


def test_basket_previews_each_order_and_sends_them_one_by_one(env):
    o.set_enabled(True, "ENABLE")
    t2 = {**T, "symbol": "INFY", "strategy_key": None}
    bp = o.basket_preview([T, t2])
    assert bp["total"] == 2 and bp["ok"] == 2 and bp["buy_value"] == 20_020 and not bp["over_capital"]
    import time as _t
    slept = []
    r = o.basket_place([p["preview_id"] for p in bp["previews"]], confirm=True, sleep=lambda s: (slept.append(s), _t.sleep(s)))
    assert r["sent"] == 2 and len([c for c in env.calls if c[0] == "place"]) == 2
    assert len(slept) == 1 and slept[0] >= 1                                   # spaced by the minimum gap (real wait)
    again = o.basket_place([p["preview_id"] for p in bp["previews"]], confirm=True, sleep=slept.append)
    assert again["sent"] == 0 and "expired or was already used" in again["results"][0]["message"]   # never twice
