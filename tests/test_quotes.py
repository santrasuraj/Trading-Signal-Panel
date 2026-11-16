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
    """Market open, an empty cache, no live feed, Yahoo and the store stubbed (no network)."""
    monkeypatch.setattr(clock, "market_clock", lambda now=None: {"session": "open"})
    monkeypatch.setattr(q, "_cache", {})
    monkeypatch.setattr(q, "hub_info", lambda: None)
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
    for session in ("closed", "pre_open", "weekend", "holiday"):
        monkeypatch.setattr(clock, "market_clock", lambda now=None, s=session: {"session": s})
        monkeypatch.setattr(q, "get_fyers", lambda cfg: pytest.fail("no FYERS call while the market is shut"))
        monkeypatch.setattr(q, "hub_info", lambda: pytest.fail("no live feed while the market is shut"))
        monkeypatch.setattr(q, "_from_store", lambda syms: {"AAA": {"symbol": "AAA", "price": 9.0}})
        r = q.quotes(["AAA", "BBB"])
        assert r["source"] == "close" and not r["delayed"] and [x["symbol"] for x in r["quotes"]] == ["AAA"]


def _hub(written_ago=1.0, **prices):
    import time as _t
    return {"updated": q.now_ist().isoformat(), "written": _t.time() - written_ago,
            "quotes": {s: {"symbol": s, "price": p, "prev_close": 100.0, "change_pct": round(p - 100.0, 2),
                           "time": q.now_ist().isoformat(timespec="seconds"), "volume": 5.0} for s, p in prices.items()}}


def test_live_feed_first_rest_for_the_rest(market, monkeypatch):
    fy = FakeFyers()
    monkeypatch.setattr(q, "get_fyers", lambda cfg: (fy, "ok"))
    monkeypatch.setattr(q, "hub_info", lambda: _hub(AAA=101.5))
    r = q.quotes(["AAA", "BBB"])
    by = {x["symbol"]: x for x in r["quotes"]}
    assert by["AAA"]["price"] == 101.5 and by["AAA"]["source"] == "live" and by["AAA"]["volume"] == 5.0
    assert by["BBB"]["source"] == "fyers" and fy.calls == [["BBB"]]      # only the symbol the feed lacks
    assert r["source"] == "live" and not r["delayed"]


def test_a_stale_live_feed_is_ignored_while_open(market, monkeypatch):
    monkeypatch.setattr(q, "get_fyers", lambda cfg: (None, "no login"))
    monkeypatch.setattr(q, "hub_info", lambda: _hub(written_ago=600, AAA=101.5))
    r = q.quotes(["AAA"])
    assert r["quotes"][0]["source"] == "yahoo" and r["quotes"][0]["price"] == 50.0 and r["delayed"]


def test_after_the_close_the_last_trade_stays(market, monkeypatch):
    monkeypatch.setattr(clock, "market_clock", lambda now=None: {"session": "post_close"})
    monkeypatch.setattr(q, "get_fyers", lambda cfg: (None, "no login"))
    monkeypatch.setattr(q, "hub_info", lambda: _hub(written_ago=3600, AAA=99.0))   # feed stopped at 15:30: still today's
    r = q.quotes(["AAA", "BBB"])
    by = {x["symbol"]: x for x in r["quotes"]}
    assert by["AAA"]["price"] == 99.0 and by["AAA"]["source"] == "live"
    assert by["BBB"]["source"] == "yahoo"                                 # one fetch, cached for 5 minutes
    assert "15:30" in r["note"]
    q.quotes(["BBB"])
    assert market == [["BBB"]]


def test_no_network_path_uses_the_cache_never_rest(market, monkeypatch):
    fy = FakeFyers()
    monkeypatch.setattr(q, "get_fyers", lambda cfg: (fy, "ok"))
    q.quotes(["AAA"])                                                    # fills the cache from FYERS
    monkeypatch.setattr(q, "get_fyers", lambda cfg: pytest.fail("the event stream's fast path never calls FYERS"))
    monkeypatch.setattr(q, "_cache", {s: (0.0, src, v) for s, (t, src, v) in q._cache.items()})   # long expired
    r = q.quotes(["AAA", "BBB"], allow_network=False)
    by = {x["symbol"]: x for x in r["quotes"]}
    assert by["AAA"]["source"] == "fyers" and by["BBB"]["source"] == "close"


def test_quote_book_and_ticker_plan(tmp_path):
    from scanner.intraday import data as idata, quote_hub as hub
    book = hub.QuoteBook()
    import time as _t
    t = int(_t.time())
    book.on_tick({"symbol": "NSE:RELIANCE-EQ", "ltp": 1500.5, "prev_close_price": 1490.0, "chp": 0.7,
                  "vol_traded_today": 12345, "last_traded_time": t})
    book.on_tick({"symbol": "NSE:NIFTY50-INDEX", "ltp": 25000.0, "prev_close_price": 25100.0, "exch_feed_time": t})
    book.on_tick({"symbol": "NSE:BAD-EQ", "ltp": 0})                   # a zero price is a bad tick
    assert book.write_if_changed(tmp_path, idata._replace) and not book.write_if_changed(tmp_path, idata._replace)
    info = hub.read_quotes(tmp_path)
    assert set(info["quotes"]) == {"RELIANCE", "NIFTY50"} and hub.feed_live(info)
    assert info["quotes"]["NIFTY50"]["change_pct"] == round((25000 / 25100 - 1) * 100, 2)
    plan = hub.plan_tickers(["NIFTY50", "TCS", "RELIANCE"], ["RELIANCE", "INFY", "SBIN"], ["NSE:NIFTY26NOVFUT"], 4)
    assert plan == ["NSE:NIFTY50-INDEX", "NSE:TCS-EQ", "NSE:RELIANCE-EQ", "NSE:NIFTY26NOVFUT"]
    assert hub.plan_tickers([f"S{i}" for i in range(10)], ["X"], ["F1", "F2"], 5)[-2:] == ["F1", "F2"]   # F&O keep slots
    hub.write_subscriptions(tmp_path / "new", ["AAA"], idata._replace)
    assert hub.read_subscriptions(tmp_path / "new") == ["AAA"]


def test_fyers_real_time_with_per_symbol_cache_and_yahoo_top_up(market, monkeypatch):
    fy = FakeFyers()
    monkeypatch.setattr(q, "get_fyers", lambda cfg: (fy, "ok"))
    r = q.quotes(["AAA", "CCC"])                        # CCC: FYERS has no quote -> Yahoo top-up
    assert r["source"] == "fyers" and r["delayed"]      # one of them is Yahoo's: the answer says so
    assert [(x["source"], x["delayed"]) for x in r["quotes"]] == [("fyers", False), ("yahoo", True)]
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


def test_event_stream_sends_a_snapshot_then_only_changes(monkeypatch):
    import asyncio
    import json as _json
    from web.api.routers import stream
    from web.api.services import live_subs

    monkeypatch.setattr(stream, "TICK_S", 0.0)
    monkeypatch.setattr(clock, "market_clock", lambda now=None: {"session": "open"})
    published = []
    monkeypatch.setattr(live_subs.quote_hub, "write_subscriptions", lambda d, w, r: published.append(list(w)))
    live_subs.reset()
    prices = iter([100.0, 100.0, 101.0, 101.0, 101.0])
    calls = []

    def fake_quotes(syms, allow_network=True):
        calls.append(allow_network)
        p = next(prices)
        return {"as_of": "t", "session": "open", "source": "live", "delayed": False, "note": "",
                "quotes": [{"symbol": "AAA", "price": p, "source": "live", "change_pct": None},
                           {"symbol": "BBB", "price": 7.0, "source": "fyers", "change_pct": None}]}

    monkeypatch.setattr(stream.quotes_svc, "quotes", fake_quotes)

    class Req:
        n = 0

        async def is_disconnected(self):
            Req.n += 1
            return Req.n > 3

    async def collect():
        return [e async for e in stream.quote_events(Req(), ["AAA", "BBB"])]

    events = [_json.loads(e.split("data: ", 1)[1]) for e in asyncio.run(collect()) if e.startswith("event:")]
    assert not events[0]["full"] and len(events[0]["quotes"]) == 2      # at hand at once (no network)
    assert events[1]["full"] and len(events[1]["quotes"]) == 2          # then the full snapshot
    assert [(e["full"], [x["symbol"] for x in e["quotes"]]) for e in events[2:]] == [(False, ["AAA"])]
    assert calls[:3] == [False, True, False]               # cache first, snapshot with REST, then the fast path
    assert published[0][:3] == live_subs.ALWAYS and "AAA" in published[0] and published[-1] == live_subs.ALWAYS
