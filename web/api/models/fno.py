"""F&O positioning (scanner/fno.py): participant-wise open interest and the day's futures build-ups."""
from __future__ import annotations

from typing import Literal

from .common import ISODate, ISODateTime, Model

FnoClient = Literal["fii", "dii", "pro", "client"]
FnoBuildup = Literal["long_buildup", "short_buildup", "short_covering", "long_unwinding"]


class FnoClientSeries(Model):
    """Columnar, one value per date in FnoPositionsResponse.dates (contracts)."""
    fut_long: list[float | None]                  # index futures, long
    fut_short: list[float | None]
    fut_net: list[float | None]                   # long - short
    fut_net_chg: list[float | None]               # vs the day before
    fut_long_pct: list[float | None]              # long / (long + short)
    call_net: list[float | None]                  # index calls, long - short
    put_net: list[float | None]                   # index puts, long - short
    stk_fut_net: list[float | None]               # stock futures, long - short


class FnoPositionsResponse(Model):
    dates: list[ISODate]
    clients: dict[str, FnoClientSeries]
    note: str


class FnoFuture(Model):
    symbol: str
    kind: Literal["index", "stock"]
    close: float | None = None                    # nearest-month future
    chg_pct: float | None = None
    oi_contracts: int | None = None               # all expiries
    oi_chg_contracts: int | None = None
    oi_chg_pct: float | None = None
    volume: int | None = None                     # contracts
    value_cr: float | None = None
    lot: int | None = None
    basis_pct: float | None = None                # future vs the underlying
    buildup: FnoBuildup | None = None
    pcr: float | None = None                      # options, all expiries
    call_wall: float | None = None                # strike with the most call OI, nearest expiry
    put_wall: float | None = None


class FnoFuturesResponse(Model):
    date: ISODate | None = None
    dates: list[ISODate]                          # stored days, newest first
    counts: dict[str, int]                        # build-up -> number of underlyings
    rows: list[FnoFuture]
    note: str


class FnoRefreshRun(Model):
    state: Literal["idle", "running", "done", "failed"]
    running: bool
    message: str | None = None
    started_at: ISODateTime | None = None
    finished_at: ISODateTime | None = None
    errors: list[str]


class FnoStatus(Model):
    run: FnoRefreshRun
    days: int
    first_day: ISODate | None = None
    last_day: ISODate | None = None
    last_refresh_at: ISODateTime | None = None
    pending: list[str]                            # days whose files NSE has not published yet
    errors: list[str]


class FnoRefreshAccepted(Model):
    accepted: bool
    run: FnoRefreshRun


class FnoLiveRow(Model):
    """One underlying during the session: all its futures AND options open interest (NSE OI spurts) and its price."""
    symbol: str
    kind: Literal["index", "stock"]
    price: float | None = None
    prev_close: float | None = None
    chg_pct: float | None = None
    price_source: Literal["fyers", "yahoo", "nse_rounded", "close"] | None = None
    oi: float | None = None                       # contracts, futures + options, all expiries
    prev_oi: float | None = None
    oi_chg: float | None = None
    oi_chg_pct: float | None = None
    volume: float | None = None                   # contracts traded today
    buildup: FnoBuildup | None = None             # price vs all-contract OI, 5%+ OI change
    eod_buildup: FnoBuildup | None = None         # the futures-only build-up of eod_date (bhavcopy)


class FnoLiveResponse(Model):
    nse_time: ISODateTime | None = None           # NSE's own time stamp of the OI figures
    trade_date: ISODate | None = None
    prev_date: ISODate | None = None
    eod_date: ISODate | None = None               # the futures-only end-of-day table eod_buildup comes from
    fetched_at: ISODateTime | None = None
    price_source: str | None = None               # fyers | yahoo | close
    session: str                                  # market clock: open, closed, ...
    running: bool
    error: str | None = None
    counts: dict[str, int]
    rows: list[FnoLiveRow]
    note: str


class FnoLiveAccepted(Model):
    accepted: bool                                # False: a fetch ran less than 90 s ago or is running
    running: bool
    message: str


__all__ = ["FnoClient", "FnoBuildup", "FnoClientSeries", "FnoPositionsResponse", "FnoFuture", "FnoFuturesResponse",
           "FnoRefreshRun", "FnoStatus", "FnoRefreshAccepted", "FnoLiveRow", "FnoLiveResponse", "FnoLiveAccepted"]
