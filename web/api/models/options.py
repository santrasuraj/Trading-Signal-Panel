"""Option chains (scanner/options.py): one chain's analysis, the day's series, status and the refresh job."""
from __future__ import annotations

from typing import Literal

from .common import ISODate, ISODateTime, Model

OptBuildup = Literal["long_buildup", "short_buildup", "short_covering", "long_unwinding"]
OptRunState = Literal["idle", "running", "done", "failed"]


class OptLeg(Model):
    ltp: float | None = None
    chg: float | None = None                      # price change since yesterday's close
    oi: int | None = None                         # open interest, contracts
    oi_chg: int | None = None                     # since yesterday
    oi_chg_pct: float | None = None
    oi_chg_window: int | None = None              # over the last `window_minutes` of stored chains
    volume: int | None = None                     # contracts traded today
    iv_pct: float | None = None                   # implied volatility on the forward (Black-76)
    iv_nse_pct: float | None = None               # NSE's own figure (on the spot), for reference
    bid: float | None = None
    ask: float | None = None
    buy_qty: int | None = None                    # pending buy / sell quantity at NSE
    sell_qty: int | None = None
    delta: float | None = None
    gamma: float | None = None
    theta: float | None = None                    # per calendar day
    vega: float | None = None                     # per volatility point
    buildup: OptBuildup | None = None


class OptRow(Model):
    strike: float
    atm: bool
    ce: OptLeg
    pe: OptLeg


class OptLevel(Model):
    strike: float
    oi: int | None = None
    oi_chg: int | None = None


class OptLevels(Model):
    resistance: list[OptLevel]                    # most call OI at or above the spot
    support: list[OptLevel]                       # most put OI at or below the spot
    call_adds: list[OptLevel]                     # largest call OI additions since yesterday
    put_adds: list[OptLevel]


class OptSummary(Model):
    pcr_oi: float | None = None
    pcr_volume: float | None = None
    max_pain: float | None = None
    max_pain_gap_pct: float | None = None         # max pain vs the spot
    atm_iv_pct: float | None = None
    straddle: float | None = None                 # at-the-money call + put
    expected_move_pct: float | None = None        # straddle / spot
    one_sd_pts: float | None = None               # forward x ATM IV x sqrt(time)
    range_low: float | None = None
    range_high: float | None = None
    skew_25d: float | None = None                 # 25-delta put IV - call IV, volatility points
    ce_oi: int | None = None
    ce_oi_chg: int | None = None
    ce_volume: int | None = None
    pe_oi: int | None = None
    pe_oi_chg: int | None = None
    pe_volume: int | None = None


class OptUnusual(Model):
    strike: float
    side: Literal["ce", "pe"]
    ltp: float | None = None
    volume: int | None = None
    oi: int | None = None
    vol_oi: float | None = None                   # contracts traded today / open contracts
    oi_chg_window: int | None = None
    oi_chg_window_pct: float | None = None
    value_cr: float | None = None                 # premium traded today, Rs crore (needs the lot size)
    why: list[str]


class OptChainResponse(Model):
    symbol: str
    expiry: ISODate
    expiries: list[ISODate]                       # every stored expiry of this symbol (for the picker)
    time: ISODateTime                             # NSE's own stamp of the chain
    source: str
    stale: bool                                   # market open and the chain is over 10 minutes old
    spot: float | None = None
    forward: float | None = None
    atm: float | None = None
    days_to_expiry: float | None = None
    summary: OptSummary
    levels: OptLevels
    readings: list[str]
    window_minutes: int
    window_since: ISODateTime | None = None       # None: no chain that old today yet
    lot: int | None = None                        # contract size, from NSE's F&O bhavcopy (None until fetched)
    unusual: list[OptUnusual]
    rows: list[OptRow]
    note: str


class OptHistoryResponse(Model):
    symbol: str
    expiry: ISODate
    day: ISODate
    t: list[ISODateTime]
    spot: list[float | None]
    max_pain: list[float | None]
    pcr_oi: list[float | None]
    atm_iv_pct: list[float | None]
    straddle: list[float | None]
    support: list[float | None]
    resistance: list[float | None]


class OptChainRef(Model):
    symbol: str
    expiry: ISODate
    day: ISODate
    time: ISODateTime
    spot: float | None = None


class OptRefreshRun(Model):
    state: OptRunState
    running: bool
    message: str | None = None
    started_at: ISODateTime | None = None
    finished_at: ISODateTime | None = None
    errors: list[str]


class OptLastRefresh(Model):
    started_at: ISODateTime | None = None
    chains: int
    refused: bool
    errors: list[str]


class OptStatus(Model):
    run: OptRefreshRun
    live_running: bool                            # the scheduled job (intraday_sync.py --options) is running
    market_open: bool
    interval_seconds: int
    underlyings: list[str]                        # config.yaml options.underlyings
    chains: list[OptChainRef]
    last_refresh: OptLastRefresh | None = None
    note: str


class OptClaim(Model):
    n: int                                        # days the claim could be checked on
    verdict: str


class OptMaxPainClaim(OptClaim):
    hit_pct: float | None = None                  # % of days the expiry close ended nearer max pain than the spot
    fair_pct: float


class OptExpectedMoveClaim(OptClaim):
    inside_pct: float | None = None               # % of days the expiry close landed inside spot +- straddle
    fair_pct: float


class OptPcrClaim(OptClaim):
    corr: float | None = None                     # rank correlation of PCR with the next day's move
    top_minus_bottom_pct: float | None = None     # next-day move after the highest third of PCR minus the lowest


class OptStudy(Model):
    symbol: str
    days: int
    first_day: ISODate | None = None
    max_pain: OptMaxPainClaim
    expected_move: OptExpectedMoveClaim
    pcr: OptPcrClaim


class OptResearchResponse(Model):
    min_days: int
    studies: list[OptStudy]
    note: str


class OptRefreshRequest(Model):
    symbols: list[str] | None = None              # default: config.yaml options.underlyings


class OptRefreshAccepted(Model):
    accepted: bool
    run: OptRefreshRun


__all__ = ["OptBuildup", "OptRunState", "OptLeg", "OptRow", "OptLevel", "OptLevels", "OptSummary", "OptUnusual",
           "OptClaim", "OptMaxPainClaim", "OptExpectedMoveClaim", "OptPcrClaim", "OptStudy", "OptResearchResponse",
           "OptChainResponse", "OptHistoryResponse", "OptChainRef", "OptRefreshRun", "OptLastRefresh", "OptStatus",
           "OptRefreshRequest", "OptRefreshAccepted"]
