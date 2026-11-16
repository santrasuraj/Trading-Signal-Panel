"""Order flow from the normal FYERS data feed (no tick-by-tick subscription needed): for every streamed stock, the volume
traded at each price level in each minute, split into buyer- and seller-initiated.

Each tick carries the day's cumulative volume, the last price and the best bid / ask. The volume since the previous tick
is classified by the quote rule - at or above the ask = bought by an aggressive buyer, at or below the bid = sold by an
aggressive seller - and, between the two, by the tick rule (above the previous trade price = buy, below = sell, the same
= the previous side). This is the standard estimate of who was the aggressor (Lee & Ready); FYERS' tick-by-tick feed
(Prime plan) would be exact, but a tick here can bundle several trades, so treat it as an estimate.

The live service (live.py) writes today's table to data/intraday/live/orderflow_YYYYMMDD.parquet every few seconds:
    ts (the minute), symbol, price (the level), buy, sell   - shares
web/api/services/orderflow_svc.py turns it into per-bar delta, cumulative delta and the session's volume profile.
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime

import pandas as pd

from ..settings import IST

COLS = ["ts", "symbol", "price", "buy", "sell"]


def level_step(price: float) -> float:
    """Price-level size: about 0.05% of the price on a 0.05 grid (Rs 0.65 on a Rs 1,300 stock), so a session has a
    few dozen levels, not hundreds."""
    return max(0.05, round(price * 0.0005 / 0.05) * 0.05)


def file_name(day) -> str:
    return f"orderflow_{day:%Y%m%d}.parquet"


class OrderFlowBuilder:
    def __init__(self):
        self.cum: dict[str, float] = {}
        self.last_px: dict[str, float] = {}
        self.last_side: dict[str, int] = {}
        self.step: dict[str, float] = {}
        self.cells: dict[tuple, list[float]] = defaultdict(lambda: [0.0, 0.0])
        self.dirty = False

    def on_tick(self, msg: dict) -> None:
        sym, ltp = msg.get("symbol"), msg.get("ltp")
        t = msg.get("last_traded_time") or msg.get("exch_feed_time")
        if not sym or ltp is None or not t or float(ltp) <= 0:
            return
        ltp = float(ltp)
        cum = float(msg.get("vol_traded_today") or 0)
        prev = self.cum.get(sym)
        self.cum[sym] = max(cum, prev or 0)
        if prev is None or cum <= prev:                 # the first tick (the day so far) or nothing new traded
            self.last_px.setdefault(sym, ltp)
            return
        dv = cum - prev
        bid, ask = float(msg.get("bid_price") or 0), float(msg.get("ask_price") or 0)
        if ask and ltp >= ask:
            side = 1
        elif bid and ltp <= bid:
            side = -1
        else:
            last = self.last_px.get(sym, ltp)
            side = 1 if ltp > last else -1 if ltp < last else self.last_side.get(sym, 1)
        self.last_px[sym], self.last_side[sym] = ltp, side
        step = self.step.setdefault(sym, level_step(ltp))
        level = round(math.floor(ltp / step + 1e-9) * step, 2)
        minute = datetime.fromtimestamp(int(t), IST).replace(second=0, tzinfo=None)
        cell = self.cells[(minute, sym, level)]
        cell[0 if side > 0 else 1] += dv
        self.dirty = True

    def frame(self) -> pd.DataFrame:
        if not self.cells:
            return pd.DataFrame(columns=COLS)
        rows = [(k[0], k[1], k[2], v[0], v[1]) for k, v in self.cells.items()]
        df = pd.DataFrame(rows, columns=COLS)
        df["ts"] = pd.to_datetime(df["ts"])
        return df.sort_values(["symbol", "ts", "price"]).reset_index(drop=True)

    def write(self, live_dir, day, replace) -> bool:
        """Today's table (rewritten whole: a few hundred thousand small rows at most). True when written."""
        if not self.dirty:
            return False
        p = live_dir / file_name(day)
        tmp = p.with_suffix(".oftmp")
        self.frame().to_parquet(tmp, index=False)
        replace(tmp, p)
        self.dirty = False
        return True


KEEP_DAYS = 10


def cleanup(live_dir, keep: int = KEEP_DAYS) -> int:
    """Delete order-flow files older than the newest `keep` (a few MB a day). Returns how many were removed."""
    files = sorted(live_dir.glob("orderflow_*.parquet"))
    old = files[:-keep] if len(files) > keep else []
    for f in old:
        try:
            f.unlink()
        except OSError:
            pass
    return len(old)
