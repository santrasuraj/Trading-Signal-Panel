"""Live 5-minute bars from the FYERS WebSocket - real-time, and it costs no REST API calls.

Run during market hours (4_intraday_live.bat or `python intraday_sync.py --live`). It subscribes to
up to 100 symbols (the Standard plan's WebSocket limit) - the most liquid stocks of the intraday
universe - builds 5-minute bars from the ticks, and every few seconds writes:
  data/intraday/live/YYYYMMDD.parquet   completed bars of today
  data/intraday/live/forming.json       the bar currently forming per symbol, and when the last tick came
  data/intraday/live/prints_YYYYMMDD.parquet, book.json   large trades and order-book totals (footprints.py)
  data/intraday/live/orders_feed.json   your FYERS order updates from the order socket (order_feed.py, read-only)
  data/intraday/live/1m_YYYYMMDD.parquet, forming_1m.json   the same ticks as 1-minute bars (1-minute charts)
  data/intraday/live/orderflow_YYYYMMDD.parquet   buyer- / seller-initiated volume per minute and price (orderflow.py)
At the end of the session the completed bars are merged into the intraday store, so they are kept
even though FYERS' REST history only covers a rolling year. The intraday scanner reads these files
for today's setups instead of Yahoo's ~15-minute delayed data, as long as ticks keep arriving.

Started before today's FYERS login (e.g. by the 09:14 scheduled task), it waits for the login - checked
locally, no API call - instead of connecting with yesterday's expired token. Only one live service runs
at a time (data/intraday/live/.live.lock): a second one would go over FYERS' 100-symbol limit.
"""
from __future__ import annotations

import base64
import json
import threading
import time
from datetime import datetime

import pandas as pd

from .. import watch
from ..providers import load_token
from ..settings import IST, LOG_DIR, ist_now
from . import data as idata
from . import order_feed, orderflow, quote_hub
from .fyers_sync import is_trading_day

MAX_SYMBOLS = 100               # FYERS Standard plan WebSocket limit (all connections together)
FLUSH_SECONDS = 5
SESSION_END = (15, 31)
LOGIN_POLL_SECONDS = 60
STALE_SECONDS = 120             # no tick for this long during the session = the live feed is not working
FORMING_FILE_NAME = "forming.json"
FORMING_1M_NAME = "forming_1m.json"
LOCK_FILE_NAME = ".live.lock"


def live_dir(root):
    d = root / "live"
    d.mkdir(parents=True, exist_ok=True)
    return d


def live_file(root, day=None):
    return live_dir(root) / f"{(day or ist_now().date()):%Y%m%d}.parquet"


def live_file_1m(root, day=None):
    return live_dir(root) / f"1m_{(day or ist_now().date()):%Y%m%d}.parquet"


def load_live(root, day=None, one_minute: bool = False) -> pd.DataFrame:
    """Today's completed live bars (empty if the live service hasn't run today); `one_minute`: the 1-minute ones."""
    p = live_file_1m(root, day) if one_minute else live_file(root, day)
    if not p.exists():
        return idata.empty_bars()
    try:
        return pd.read_parquet(p)
    except Exception:
        return idata.empty_bars()


def feed_fresh(root, now: datetime | None = None) -> bool:
    """True when the live service received ticks until recently: within STALE_SECONDS of now during the
    session, or of the close once the session is over. False when it stopped early (crash, lost
    connection, never logged in): today's live bars are then frozen at that time."""
    now = now or ist_now()
    try:
        info = json.loads((live_dir(root) / FORMING_FILE_NAME).read_text(encoding="utf-8"))
        last = datetime.fromisoformat(info["last_tick"])
    except Exception:
        return False
    if last.date() != now.date():
        return False
    close = now.replace(hour=15, minute=30, second=0, microsecond=0)
    return (min(now, close) - last).total_seconds() <= STALE_SECONDS


def _forming(builder: idata.TickBarBuilder) -> dict:
    return {b["symbol"]: {k: (str(v) if k == "ts" else v) for k, v in b.items()} for b in builder.cur.values()}


def _iso(epoch: float | None) -> str | None:
    return datetime.fromtimestamp(epoch, IST).isoformat(timespec="seconds") if epoch else None


def _write(root, done: pd.DataFrame, forming: dict, last_tick: str | None = None, one_minute: bool = False) -> None:
    """Merge newly completed bars into today's file and replace forming.json. Both writes are atomic and
    retried (on Windows a replace fails while a scan is reading the file); a failure raises, so the caller
    keeps the bars for the next attempt instead of losing them. `one_minute`: the 1-minute files instead."""
    p = live_file_1m(root) if one_minute else live_file(root)
    if len(done):
        old = pd.read_parquet(p) if p.exists() else idata.empty_bars()   # unreadable: raise, never overwrite
        allb = pd.concat([old, done], ignore_index=True) if len(old) else done
        allb = allb.sort_values(["symbol", "ts"]).drop_duplicates(["symbol", "ts"], keep="last")
        tmp = p.with_suffix(".tmp")
        allb.to_parquet(tmp, index=False)
        idata._replace(tmp, p)
    f = live_dir(root) / (FORMING_1M_NAME if one_minute else FORMING_FILE_NAME)
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps({"updated": ist_now().isoformat(timespec="seconds"), "last_tick": last_tick,
                               "bars": forming}, default=str), encoding="utf-8")
    idata._replace(tmp, f)


def _wanted(root) -> list[str]:
    """The user's symbols, in stream priority: the open screens (subscriptions.json), then active price alerts and
    watchlists (scanner/watch.py) - those stay streamed with no dashboard open, so alerts fire on real-time ticks."""
    out = quote_hub.read_subscriptions(live_dir(root))
    try:
        for s in watch.feed_symbols():
            if s not in out:
                out.append(s)
    except Exception:
        pass
    return out


def _token_ok(tok: dict | None) -> bool:
    """The saved FYERS access token is a JWT: usable while it hasn't expired. Checked locally (no API call),
    the same way the SDK checks it - with an expired token the SDK silently never connects."""
    if not tok:
        return False
    try:
        payload = str(tok["access_token"]).split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        return float(claims["exp"]) > time.time() + 60
    except Exception:
        return False


def _session_over() -> bool:
    now = ist_now()
    return (now.hour, now.minute) >= SESSION_END


def _wait_for_login(log) -> dict | None:
    """Today's valid FYERS token, polling the token file until the user logs in; None if the session ends."""
    tok, told = load_token(), False
    while not _token_ok(tok):
        if _session_over():
            return None
        if not told:
            log("FYERS login missing or expired - waiting for today's login (run 1_login.bat)...")
            told = True
        time.sleep(LOGIN_POLL_SECONDS)
        tok = load_token()
    return tok


def _stop_socket(sock) -> None:
    """Close the FYERS socket and stop the SDK's worker threads (fyers_apiv3 3.2.0 internals, hence the
    guards): close_connection() does nothing when the socket never opened or its reconnects ran out."""
    try:
        sock.restart_flag = False                 # no reconnect after we close
        sock.close_connection()
    except Exception:
        pass
    ev = getattr(sock, "message_thread_stop_event", None)
    if ev is not None:
        try:
            ev.set()
            with sock.message_lock:
                sock.message_condition.notify_all()
        except Exception:
            pass
    try:
        sock._FyersDataSocket__ws_run = False
    except Exception:
        pass


def run_live(symbols: list[str], root, interval: str = "5m", log=print, fno: list[dict] | None = None,
             fno_settings: dict | None = None) -> int:
    """Stream ticks for up to 100 symbols until the session ends; returns the number of bars written. `fno`: index
    futures / options to stream too (scanner/fno_live.py) - their large trades are recorded, they make no bars."""
    lock = idata.FileLock(live_dir(root) / LOCK_FILE_NAME)
    if not lock.acquire(timeout=0):
        log("Live feed already running in another window - not starting a second one "
            "(FYERS allows 100 symbols across all connections).")
        return 0
    try:
        return _run_live(symbols, root, interval, log, fno or [], fno_settings)
    finally:
        lock.release()


def _run_live(symbols: list[str], root, interval: str, log, fno: list[dict], fno_settings: dict | None) -> int:
    tok = _wait_for_login(log)
    if tok is None:
        log("The session ended before a valid FYERS login was found - no live bars today.")
        return 0
    from fyers_apiv3.FyersWebsocket import data_ws

    fno = fno[:MAX_SYMBOLS]
    fno_tickers = [i["ticker"] for i in fno]
    base = [s if ":" in s else f"NSE:{s}-EQ" for s in symbols]
    # The screen's symbols (quote_hub.subscriptions.json) come first, then F&O, then the liquid stocks.
    tickers = quote_hub.plan_tickers(_wanted(root), base, fno_tickers, MAX_SYMBOLS)
    book = quote_hub.QuoteBook()              # every tick's latest price: the screen's live quotes
    builder = idata.TickBarBuilder(interval)
    builder1 = idata.TickBarBuilder("1m")      # the same ticks as 1-minute bars (1-minute charts, archived at the close)
    flowb = orderflow.OrderFlowBuilder()        # estimated buy / sell volume per minute and price (order flow)
    try:
        orderflow.cleanup(live_dir(root))
    except Exception:
        pass
    from ..footprints import FootprintRecorder
    recorder = FootprintRecorder()            # large trades + order-book totals for Big money live (footprints.py)
    from ..fno_live import FnoRecorder
    fno_rec = FnoRecorder(fno, fno_settings) if fno else None    # large futures / options trades (fno_live.py)
    lock = threading.Lock()
    status = {"live": False, "errors": 0, "ticks": 0, "last_tick": None}

    def on_message(msg):
        if isinstance(msg, dict) and msg.get("ltp") is not None:
            try:
                book.on_tick(msg)
            except Exception:                  # a quote glitch must never stop the bars
                pass
            if not str(msg.get("symbol") or "").endswith("-EQ") and not (fno_rec is not None and fno_rec.wants(msg.get("symbol"))):
                with lock:                     # an index (or other non-stock) on the screen: a quote only, no bars
                    status["ticks"] += 1
                    status["last_tick"] = time.time()
                return
            if fno_rec is not None and fno_rec.wants(msg.get("symbol")):
                with lock:                     # F&O: large trades only - no bars, no stock footprints
                    try:
                        fno_rec.on_tick(msg)
                    except Exception:
                        pass
                    status["ticks"] += 1
                    status["last_tick"] = time.time()
                return
            with lock:
                builder.on_tick(msg)
                builder1.on_tick(msg)
                try:
                    flowb.on_tick(msg)
                except Exception:              # an order-flow glitch must never stop the bars
                    pass
                try:
                    recorder.on_tick(msg)
                except Exception:              # a footprint glitch must never stop the bars
                    pass
                status["ticks"] += 1
                status["last_tick"] = time.time()
            if not status["live"]:
                status["live"] = True
                log(f"Live: receiving ticks for {len(tickers)} symbols")

    def on_error(msg):
        status["errors"] += 1
        log(f"FYERS socket error: {msg}")

    def on_close(msg):
        status["live"] = False
        log(f"FYERS socket closed: {msg}")

    def on_connect():
        # Also called after every reconnect (subscribe again) - and by the SDK even when it could not
        # connect at all, so only ticks, never this callback, mark the feed as live.
        sock.subscribe(symbols=list(tickers), data_type="SymbolUpdate")
        log(f"Live: subscribing to {len(tickers)} symbols")

    def resubscribe() -> None:
        """Follow the screen: subscribe to symbols a page, holding or watchlist now needs, and drop the ones
        that made room for them, staying within the symbol limit."""
        nonlocal tickers
        want = quote_hub.plan_tickers(_wanted(root), base, fno_tickers, MAX_SYMBOLS)
        add, drop = [t for t in want if t not in tickers], [t for t in tickers if t not in want]
        if not add and not drop:
            return
        if drop:
            sock.unsubscribe(symbols=drop, data_type="SymbolUpdate")
        if add:
            sock.subscribe(symbols=add, data_type="SymbolUpdate")
        tickers = want
        log(f"Live: now streaming {len(want)} symbols (+{len(add)} for the screen, -{len(drop)})")

    stop_quotes = threading.Event()
    feed = order_feed.OrderFeed(live_dir(root))         # your order updates (fills, rejections) pushed by FYERS

    def quote_writer() -> None:
        """quotes.json about twice a second while ticks arrive: the browser's live prices."""
        while not stop_quotes.wait(quote_hub.WRITE_EVERY_S):
            try:
                if book.write_if_changed(live_dir(root), idata._replace):
                    _, quotes = book.snapshot()
                    fired = watch.evaluate(quotes)            # price alerts fire on the tick, dashboard open or not
                    if fired:
                        watch.notify(fired)
                        log("Alerts: " + "; ".join(watch.message(a) for a in fired))
            except Exception:
                pass                           # the next round tries again
            try:
                feed.write(idata._replace)     # cheap when nothing changed; a heartbeat once a minute
            except Exception:
                pass

    sock = data_ws.FyersDataSocket(access_token=f"{tok['client_id']}:{tok['access_token']}", log_path=str(LOG_DIR),
                                   litemode=False, write_to_file=False, reconnect=True, reconnect_retry=10,
                                   on_connect=on_connect, on_close=on_close, on_error=on_error,
                                   on_message=on_message)
    # The SDK's threads are non-daemon by default and some survive close_connection(); as daemons they can
    # never keep this process alive after the session (our own loop below keeps it alive until then).
    sock.background_flag = True
    written, write_fails = 0, 0
    threading.Thread(target=quote_writer, name="quotes", daemon=True).start()
    osock = None
    try:
        sock.connect()
        try:
            osock = order_feed.start_socket(tok, feed, log, LOG_DIR)
        except Exception as e:                              # orders still show on the page's own poll
            log(f"Order updates: could not start the FYERS order socket ({type(e).__name__}: {e})")
        while not _session_over():
            time.sleep(FLUSH_SECONDS)
            try:
                order_feed.keep_subscribed(osock, feed)
            except Exception:
                pass
            if status["live"]:
                try:
                    resubscribe()
                except Exception as e:
                    log(f"Live: changing the subscription failed ({type(e).__name__}: {e})")
            with lock:
                done = builder.flush()
                forming, last = _forming(builder), status["last_tick"]
                done1, forming1 = builder1.flush(), _forming(builder1)
            try:
                _write(root, done1, forming1, one_minute=True)
            except Exception:                                # the 5-minute bars matter more: retry these next round
                with lock:
                    builder1.done[:0] = done1.to_dict("records")
            try:
                _write(root, done, forming, _iso(last))     # outside the lock: ticks keep flowing meanwhile
                written += len(done)
                write_fails = 0

            except Exception as e:                           # keep the bars and try again on the next round
                with lock:
                    builder.done[:0] = done.to_dict("records")
                write_fails += 1
                if write_fails == 1 or write_fails % 60 == 0:
                    log(f"Live: writing bars failed ({type(e).__name__}: {e}) - retrying")
            try:
                with lock:
                    flow_df_due = flowb.dirty
                if flow_df_due:
                    with lock:
                        frame = flowb.frame()
                        flowb.dirty = False
                    p = live_dir(root) / orderflow.file_name(ist_now().date())
                    frame.to_parquet(p.with_suffix(".oftmp"), index=False)
                    idata._replace(p.with_suffix(".oftmp"), p)
            except Exception as e:
                log(f"Live: writing order flow failed ({type(e).__name__}: {e})")
            try:                                             # large trades / book (footprints): separate from the bars
                with lock:
                    recorder.flush(ist_now().date())
                    if fno_rec is not None:
                        fno_rec.flush(ist_now().date(), live_dir(root))
            except Exception as e:
                log(f"Live: writing footprints failed ({type(e).__name__}: {e})")
    finally:
        stop_quotes.set()
        _stop_socket(sock)
        order_feed.stop_socket(osock)
        feed.set_connected(False)
        try:
            feed.write(idata._replace)
        except Exception:
            pass
        try:
            book.write_if_changed(live_dir(root), idata._replace)     # the last trade of the day stays on screen
        except Exception:
            pass
        now = ist_now().replace(tzinfo=None)
        with lock:
            # end of session (or stopped early): close the bars whose time is over, keep everything in the store
            for bld in (builder, builder1):
                for key, b in list(bld.cur.items()):
                    if b["ts"] + pd.Timedelta(minutes=bld.step) <= now:
                        bld.done.append(bld.cur.pop(key))
            done = builder.flush()
            forming, last = _forming(builder), status["last_tick"]
            done1, forming1 = builder1.flush(), _forming(builder1)
        try:
            _write(root, done, forming, _iso(last))
            written += len(done)
        except Exception as e:
            log(f"Live: final write failed ({type(e).__name__}: {e})")
        try:
            _write(root, done1, forming1, one_minute=True)
        except Exception as e:
            log(f"Live: final write of the 1-minute bars failed ({type(e).__name__}: {e})")
        try:
            today = load_live(root)
            if len(today):
                idata.IntradayStore(root / "bars").save(idata.clean_bars(today, interval), interval)
        except Exception as e:
            log(f"Live: saving today's bars to the intraday store failed ({type(e).__name__}: {e})")
        try:   # 1-minute bars are kept from the live feed only (FYERS' 1-minute history would cost ~150 more calls a day)
            today1 = load_live(root, one_minute=True)
            if len(today1):
                idata.IntradayStore(root / "bars").save(idata.clean_bars(today1, "1m"), "1m")
        except Exception as e:
            log(f"Live: saving today's 1-minute bars failed ({type(e).__name__}: {e})")
        log(f"Live session ended: {written} bars written, {status['ticks']} ticks, {status['errors']} errors")
    return written


def market_open_now(lead_minutes: int = 0) -> bool:
    """A trading day (weekends and NSE holidays excluded), from 09:15 minus `lead_minutes` until 15:31."""
    now = ist_now()
    minute = now.hour * 60 + now.minute
    return (is_trading_day(now.date()) and 9 * 60 + 15 - lead_minutes <= minute
            < SESSION_END[0] * 60 + SESSION_END[1])
