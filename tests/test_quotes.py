"""Live quotes (web/api/services/quotes_svc.py): closed market, FYERS, Yahoo fallback, per-symbol cache, budget."""
import pytest

from web.api.services import clock, quotes_svc as q


class FakeLimiter:
    def __init__(self, left):
        self.left = left

    def usage(self):
        return {"data": {"remaining_today": self.left}}


class FakeFyers:
    def __init__(self, left=4000, known=("AAA", "BBB", "NIFTY50")):
        self.limiter, self.known, self.calls = FakeLimiter(left), set(known), []

    def live_rows(self, syms):
        self.calls.append(list(syms))
        return {s: (None, {"close": 110.0, "prev_close": 100.0}) for s in syms if s in self.known}


@pytest.fixture
def market(monkeypatch):
    """Market open, an empty cache, Yahoo and the store stubbed (no network)."""
    monkeypatch.setattr(clock, "market_clock", lambda now=None: {"session": "open"})
    monkeypatch.setattr(q, "_cache", {})
    yahoo = []
    monkeypatch.setattr(q, "_from_yahoo", lambda syms: yahoo.append(list(syms)) or {
        s: {"symbol": s, "price": 50.0, "prev_close": 49.0, "change_pct": 2.04, "time": "x"} for s in syms if s != "ZZZ"})
    monkeypatch.setattr(q, "_from_store", lambda syms: {
        s: {"symbol": s, "price": 1.0, "prev_close": None, "change_pct": None, "time": "close"} for s in syms})
    return yahoo


def test_parse_rejects_bad_lists():
    assert q.parse(" aaa, BBB ,aaa") == ["AAA", "BBB"]
    for bad in ("", "AAA,bad sym", ",".join(f"S{i}" for i in range(101))):
        with pytest.raises(q.ApiException):
            q.parse(bad)


def test_closed_market_uses_stored_closes_and_no_network(monkeypatch):
    monkeypatch.setattr(clock, "market_clock", lambda now=None: {"session": "post_close"})
    monkeypatch.setattr(q, "get_fyers", lambda cfg: pytest.fail("no FYERS call while the market is shut"))
    monkeypatch.setattr(q, "_from_store", lambda syms: {"AAA": {"symbol": "AAA", "price": 9.0}})
    r = q.quotes(["AAA", "BBB"])
    assert r["source"] == "close" and not r["delayed"] and [x["symbol"] for x in r["quotes"]] == ["AAA"]


def test_fyers_real_time_with_per_symbol_cache_and_yahoo_top_up(market, monkeypatch):
    fy = FakeFyers()
    monkeypatch.setattr(q, "get_fyers", lambda cfg: (fy, "ok"))
    r = q.quotes(["AAA", "CCC"])                        # CCC: FYERS has no quote -> Yahoo top-up
    assert r["source"] == "fyers" and not r["delayed"]
    assert {x["symbol"]: x["price"] for x in r["quotes"]} == {"AAA": 110.0, "CCC": 50.0}
    assert r["quotes"][0]["change_pct"] == 10.0 and market == [["CCC"]]
    q.quotes(["AAA", "BBB"])                            # AAA is cached: only BBB is asked for
    assert fy.calls == [["AAA", "CCC"], ["BBB"]]


def test_screen_leaves_the_fyers_budget_to_the_scans(market, monkeypatch):
    monkeypatch.setattr(q, "get_fyers", lambda cfg: (FakeFyers(left=q.FYERS_RESERVE - 1), "ok"))
    r = q.quotes(["AAA", "ZZZ"])                         # ZZZ: no trade today -> last close
    assert r["source"] == "yahoo" and r["delayed"]
    assert {x["symbol"]: x["price"] for x in r["quotes"]} == {"AAA": 50.0, "ZZZ": 1.0}
    q.quotes(["AAA", "ZZZ"])
    assert market == [["AAA", "ZZZ"]]                    # both cached, the missing one too
