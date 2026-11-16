"""ZeroMQ tick bus (scanner/intraday/bus.py): ticks and new-bar events from the live feed reach the dashboard's
handlers, a stopped publisher is noticed, a taken port leaves the feed on files, and the live feed's flush lands just
after each 5-minute close. Loopback only, on a free port."""
import socket
import time

import pytest

from scanner.intraday import bus, live

pytest.importorskip("zmq")


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def _until(cond, timeout=5.0):
    t = time.time()
    while time.time() - t < timeout:
        if cond():
            return True
        time.sleep(0.02)
    return False


def test_ticks_and_bar_events_reach_the_subscriber():
    port = _free_port()
    pub = bus.open_publisher(port, log=lambda m: None)
    got, bars = [], []
    sub = bus.Subscriber(port, on_tick=[lambda s, q: got.append((s, q))],
                         on_bars=[lambda iv, n, w: bars.append((iv, n, w))]).start()
    try:
        # a SUB socket joins a moment after connecting: publish until the first tick arrives
        assert _until(lambda: (pub.tick("SBIN", 812.35, 812.3, 812.4, 1.5e6, 1763350000.0, time.time()), bool(got))[1])
        sym, q = got[-1]
        assert sym == "SBIN" and q["price"] == 812.35 and q["bid"] == 812.3 and q["ask"] == 812.4
        assert q["exch_ts"] == 1763350000.0 and q["source"] == "live" and q["bus_ts"] >= q["recv_ts"]
        assert sub.latest("SBIN")["price"] == 812.35 and sub.alive()
        pub.tick_msg({"symbol": "NSE:INFY-EQ", "ltp": 1500.5, "bid_price": None, "exch_feed_time": 1763350001},
                     time.time(), "INFY")
        assert _until(lambda: sub.latest("INFY") is not None)
        assert sub.latest("INFY")["bid"] is None
        pub.bars("5m", 87)
        assert _until(lambda: bool(bars)) and bars[0][:2] == ("5m", 87)
        pub.heartbeat()
        assert _until(lambda: sub.counts["H"] >= 1)
    finally:
        sub.stop()
        pub.close()


def test_old_quotes_and_a_silent_publisher_are_not_live():
    sub = bus.Subscriber(_free_port())
    sub.quotes["SBIN"] = {"price": 800.0, "bus_ts": time.time() - 30}
    sub.last_msg = time.time()
    assert sub.latest("SBIN") is None                          # 30 s old
    sub.quotes["SBIN"]["bus_ts"] = time.time()
    assert sub.latest("SBIN")["price"] == 800.0
    sub.last_msg = time.time() - bus.ALIVE_S - 1               # no heartbeat: the feed stopped
    assert not sub.alive() and sub.latest("SBIN") is None


def test_a_taken_port_leaves_the_live_feed_on_files():
    port = _free_port()
    first = bus.open_publisher(port, log=lambda m: None)
    msgs = []
    try:
        assert bus.open_publisher(port, log=msgs.append) is None
        assert "not started" in msgs[0]
    finally:
        first.close()


def test_port_comes_from_config_with_a_default():
    assert bus.port({}) == bus.DEFAULT_PORT
    assert bus.port({"intraday": {"bus_port": 6001}}) == 6001
    assert bus.port({"intraday": {"bus_port": "x"}}) == bus.DEFAULT_PORT


def test_live_feed_flushes_one_second_after_each_five_minute_close():
    b = 1763350500.0                                           # a 5-minute boundary (10:05:00 IST)
    assert b % 300 == 0
    assert live._sleep_s(b - 0.5) == pytest.approx(1.5)        # 10:04:59.5 -> 10:05:01
    assert live._sleep_s(b + 0.2) == pytest.approx(0.8)        # 10:05:00.2 -> 10:05:01
    assert live._sleep_s(b + 2.0) == live.FLUSH_SECONDS        # otherwise the usual every 5 s
    assert live._sleep_s(b + 298.0) == pytest.approx(3.0)      # 10:09:58 -> 10:10:01
