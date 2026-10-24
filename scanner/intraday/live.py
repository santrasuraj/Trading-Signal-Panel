"""Live 5-minute bars from the FYERS WebSocket - real-time, and it costs no REST API calls.

Run during market hours (4_intraday_live.bat or `python intraday_sync.py --live`). It subscribes to
up to 100 symbols (the Standard plan's WebSocket limit) - the most liquid stocks of the intraday
universe - builds 5-minute bars from the ticks, and every few seconds writes:
  data/intraday/live/YYYYMMDD.parquet   completed bars of today
  data/intraday/live/forming.json       the bar currently forming per symbol, and when the last tick came
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

from ..providers import load_token
from ..settings import IST, LOG_DIR, ist_now
from . import data as idata
from .fyers_sync import is_trading_day

MAX_SYMBOLS = 100               # FYERS Standard plan WebSocket limit (all connections together)
FLUSH_SECONDS = 5
SESSION_END = (15, 31)
LOGIN_POLL_SECONDS = 60
STALE_SECONDS = 120             # no tick for this long during the session = the live feed is not working
FORMING_FILE_NAME = "forming.json"
LOCK_FILE_NAME = ".live.lock"


def live_dir(root):
    d = root / "live"
    d.mkdir(parents=True, exist_ok=True)
    return d


def live_file(root, day=None):
    return live_dir(root) / f"{(day or ist_now().date()):%Y%m%d}.parquet"


def load_live(root, day=None) -> pd.DataFrame:
    """Today's completed live bars (empty if the live service hasn't run today)."""
    p = live_file(root, day)
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


def _write(root, done: pd.DataFrame, forming: dict, last_tick: str | None = None) -> None:
    """Merge newly completed bars into today's file and replace forming.json. Both writes are atomic and
    retried (on Windows a replace fails while a scan is reading the file); a failure raises, so the caller
    keeps the bars for the next attempt instead of losing them."""
    p = live_file(root)
    if len(done):
        old = pd.read_parquet(p) if p.exists() else idata.empty_bars()   # unreadable: raise, never overwrite
        allb = pd.concat([old, done], ignore_index=True) if len(old) else done
        allb = allb.sort_values(["symbol", "ts"]).drop_duplicates(["symbol", "ts"], keep="last")
        tmp = p.with_suffix(".tmp")
        allb.to_parquet(tmp, index=False)
        idata._replace(tmp, p)
    f = live_dir(root) / FORMING_FILE_NAME
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps({"updated": ist_now().isoformat(timespec="seconds"), "last_tick": last_tick,
                               "bars": forming}, default=str), encoding="utf-8")
    idata._replace(tmp, f)


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


def run_live(symbols: list[str], root, interval: str = "5m", log=print) -> int:
    """Stream ticks for up to 100 symbols until the session ends; returns the number of bars written."""
    lock = idata.FileLock(live_dir(root) / LOCK_FILE_NAME)
    if not lock.acquire(timeout=0):
        log("Live feed already running in another window - not starting a second one "
            "(FYERS allows 100 symbols across all connections).")
        return 0
    try:
        return _run_live(symbols, root, interval, log)
    finally:
        lock.release()


def _run_live(symbols: list[str], root, interval: str, log) -> int:
    tok = _wait_for_login(log)
    if tok is None:
        log("The session ended before a valid FYERS login was found - no live bars today.")
        return 0
    from fyers_apiv3.FyersWebsocket import data_ws

    tickers = [s if ":" in s else f"NSE:{s}-EQ" for s in symbols[:MAX_SYMBOLS]]
    builder = idata.TickBarBuilder(interval)
    lock = threading.Lock()
    status = {"live": False, "errors": 0, "ticks": 0, "last_tick": None}

    def on_message(msg):
        if isinstance(msg, dict) and msg.get("ltp") is not None:
            with lock:
                builder.on_tick(msg)
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
        sock.subscribe(symbols=tickers, data_type="SymbolUpdate")
        log(f"Live: subscribing to {len(tickers)} symbols")

    sock = data_ws.FyersDataSocket(access_token=f"{tok['client_id']}:{tok['access_token']}", log_path=str(LOG_DIR),
                                   litemode=False, write_to_file=False, reconnect=True, reconnect_retry=10,
                                   on_connect=on_connect, on_close=on_close, on_error=on_error,
                                   on_message=on_message)
    # The SDK's threads are non-daemon by default and some survive close_connection(); as daemons they can
    # never keep this process alive after the session (our own loop below keeps it alive until then).
    sock.background_flag = True
    written, write_fails = 0, 0
    try:
        sock.connect()
        while not _session_over():
            time.sleep(FLUSH_SECONDS)
            with lock:
                done = builder.flush()
                forming, last = _forming(builder), status["last_tick"]
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
    finally:
        _stop_socket(sock)
        now = ist_now().replace(tzinfo=None)
        with lock:
            # end of session (or stopped early): close the bars whose time is over, keep everything in the store
            for key, b in list(builder.cur.items()):
                if b["ts"] + pd.Timedelta(minutes=builder.step) <= now:
                    builder.done.append(builder.cur.pop(key))
            done = builder.flush()
            forming, last = _forming(builder), status["last_tick"]
        try:
            _write(root, done, forming, _iso(last))
            written += len(done)
        except Exception as e:
            log(f"Live: final write failed ({type(e).__name__}: {e})")
        try:
            today = load_live(root)
            if len(today):
                idata.IntradayStore(root / "bars").save(idata.clean_bars(today, interval), interval)
        except Exception as e:
            log(f"Live: saving today's bars to the intraday store failed ({type(e).__name__}: {e})")
        log(f"Live session ended: {written} bars written, {status['ticks']} ticks, {status['errors']} errors")
    return written


def market_open_now(lead_minutes: int = 0) -> bool:
    """A trading day (weekends and NSE holidays excluded), from 09:15 minus `lead_minutes` until 15:31."""
    now = ist_now()
    minute = now.hour * 60 + now.minute
    return (is_trading_day(now.date()) and 9 * 60 + 15 - lead_minutes <= minute
            < SESSION_END[0] * 60 + SESSION_END[1])
