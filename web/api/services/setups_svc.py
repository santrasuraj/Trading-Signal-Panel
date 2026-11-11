"""Live setups (GET /api/setups): today's intraday events from the live bars (scanner/intraday/setups.py).

Source, best first: today's 1-minute live bars, today's 5-minute live bars (both need the 09:14 live service and the
day's FYERS login), else the last stored 5-minute session (marked as such: the page is then a replay of that day).
Computed once per bar file version (the live service rewrites the files about every 10 seconds).
"""
from __future__ import annotations

import threading
from datetime import timedelta

import pandas as pd

from scanner import watch
from scanner.intraday import data as idata, setups
from scanner.intraday.live import live_file, live_file_1m

from . import data
from ..paths import P
from ..util import now_ist, today_ist

_cache: dict = {}
_lock = threading.Lock()
LIMIT_MAX = 500


def _version(p) -> tuple | None:
    try:
        st = p.stat()
        return (str(p), st.st_mtime_ns, st.st_size)
    except OSError:
        return None


def _source() -> tuple[pd.DataFrame, int, str, str, tuple | None]:
    """(bars of one session, bar minutes, mode 'live' / 'last_session', day ISO, cache key)."""
    root = P.data / "intraday"
    today = today_ist()
    for p, step in ((live_file_1m(root, today), 1), (live_file(root, today), 5)):
        key = _version(p)
        if key is not None:
            try:
                df = pd.read_parquet(p)
            except Exception:
                continue
            if len(df):
                return df, step, "live", today.isoformat(), key
    store = idata.IntradayStore(P.intraday_bars)
    man = store.manifest("5m")
    months = store.months("5m")
    if not months:
        return idata.empty_bars(), 5, "none", today.isoformat(), None
    key = ("store", months[-1], str(man.get("months", {}).get(months[-1])))
    hit = _cache.get("store_frame")
    if hit and hit[0] == key:
        return hit[1], 5, "last_session", hit[2], key
    df = store.load("5m", start=today - timedelta(days=10))
    if df.empty:
        return df, 5, "none", today.isoformat(), None
    last = df["ts"].dt.normalize().max()
    df = df[df["ts"].dt.normalize() == last].reset_index(drop=True)
    _cache["store_frame"] = (key, df, last.date().isoformat())
    return df, 5, "last_session", last.date().isoformat(), key


def events() -> dict:
    bars, step, mode, day, key = _source()
    with _lock:
        hit = _cache.get("events")
        if hit and key is not None and hit[0] == key:
            return hit[1]
    try:
        prev = setups.previous_day(data.store(), pd.Timestamp(day))
    except Exception:
        prev = {}
    if len(bars):
        bars = bars[(bars["flags"] & idata.FLAG_FORMING) == 0] if "flags" in bars.columns else bars
    ev = setups.detect(bars, step, prev)
    uni = data.universe()
    names = dict(zip(uni["symbol"], uni["company"])) if len(uni) else {}
    for e in ev:
        e["company"] = names.get(e["symbol"])
    out = {"mode": mode, "day": day, "interval": f"{step}m", "symbols": int(bars["symbol"].nunique()) if len(bars) else 0,
           "last_bar": pd.to_datetime(bars["ts"]).max().isoformat() if len(bars) else None, "events": ev}
    with _lock:
        if key is not None:
            _cache["events"] = (key, out)
    return out


def view(kinds: list[str] | None = None, scope: str = "all", limit: int = 200) -> dict:
    base = events()
    ev = base["events"]
    if kinds:
        ev = [e for e in ev if e["kind"] in kinds]
    watched: set[str] = set()
    try:
        watched = {s for lst in watch.watchlists()["lists"] for s in lst["symbols"]}
        watched |= {str(s).upper() for s in data.holdings_df()["symbol"]}
    except Exception:
        pass
    if scope == "mine":
        ev = [e for e in ev if e["symbol"] in watched]
    counts = {k: sum(1 for e in base["events"] if e["kind"] == k) for k in setups.KINDS}
    notes = {
        "live": f"Live: today's {base['interval']} bars from the FYERS feed, completed bars only.",
        "last_session": f"The live service isn't running today: this is the last stored session ({base['day']}), "
                        "5-minute bars. Live setups need the day's FYERS login and the 09:14 live service.",
        "none": "No intraday bars yet: live setups need the day's FYERS login and the 09:14 live service.",
    }
    return {**{k: base[k] for k in ("mode", "day", "interval", "symbols", "last_bar")},
            "as_of": now_ist().isoformat(timespec="seconds"), "counts": counts, "total": len(base["events"]),
            "events": [{**e, "mine": e["symbol"] in watched} for e in ev[:max(1, min(limit, LIMIT_MAX))]],
            "labels": setups.LABELS, "note": notes[base["mode"]] + " Facts about the tape, not tested signals."}
