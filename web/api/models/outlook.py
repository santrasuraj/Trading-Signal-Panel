"""Outlook for one symbol (GET /api/outlook/{symbol}): its setup today, what happened next in similar setups
(scanner/outlook.py on the point-in-time top 500), expected ranges, the levels above and below, every signal with its
tested record, and the derivatives positioning. Descriptive base rates - never a forecast."""
from __future__ import annotations

from typing import Literal

from .common import ISODate, ISODateTime, Model, Tone

OlVerdict = Literal["better", "worse", "same", "unknown"]
OlBias = Literal["bullish", "bearish", "neutral"]
OlSource = Literal["strategy", "pattern", "chart_pattern", "trend", "volume", "options", "futures", "intraday", "event"]


class OlFeature(Model):
    feature: str                                  # trend | mom | rsi | high52 | vol
    code: int
    label: str
    short: str


class OlDist(Model):
    """Returns from the next open to the close `days` later, in %."""
    n: int
    mean_pct: float | None = None
    median_pct: float | None = None
    up_pct: float | None = None                   # % of cases that ended higher
    p10_pct: float | None = None
    p25_pct: float | None = None
    p75_pct: float | None = None
    p90_pct: float | None = None
    excess_pct: float | None = None               # mean return minus the average stock's over the same days
    beat_pct: float | None = None                 # % of cases that beat the average stock
    t: float | None = None                        # on monthly averages of the excess


class OlHorizon(Model):
    days: int
    setup: OlDist | None = None
    base: OlDist | None = None                    # every stock on every day: the "normal" outcome
    verdict: OlVerdict
    after_cost_excess_pct: float | None = None    # excess minus a round trip of costs
    price_p10: float | None = None                # today's close moved by the setup's percentiles
    price_p25: float | None = None
    price_median: float | None = None
    price_p75: float | None = None
    price_p90: float | None = None
    own_n: int | None = None                      # the same setup in this stock's own past (few cases)
    own_median_pct: float | None = None
    own_up_pct: float | None = None


class OlTouch(Model):
    days: int
    pct: float
    up_pct: float | None = None                   # % of cases whose high reached +pct within `days`
    down_pct: float | None = None                 # ... whose low reached -pct


class OlAnalogs(Model):
    level: list[str]                              # the features the match uses
    dropped: list[str]                            # features dropped for lack of cases
    n: int
    months: int
    first_day: ISODate | None = None
    last_day: ISODate | None = None
    universe: str
    horizons: list[OlHorizon]
    touch: OlTouch
    base_touch: OlTouch
    cost_pct: float
    generated_at: ISODateTime | None = None


class OlRange(Model):
    source: Literal["options", "realized", "analogs"]
    label: str
    days: int
    low: float | None = None
    high: float | None = None
    pct: float | None = None                      # half-width in % of the close
    prob_pct: float | None = None                 # the share of outcomes expected inside (68 = 1 SD, 80 = p10-p90)


class OlExpected(Model):
    close: float | None = None
    atr: float | None = None
    atr_pct: float | None = None
    realized_vol_pct: float | None = None         # 20-day, annualised
    iv_pct: float | None = None                   # at-the-money implied volatility of the stored option chain
    iv_expiry: ISODate | None = None
    ranges: list[OlRange]


class OlLevel(Model):
    price: float
    label: str
    kind: str                                     # resistance | support | pivot | sma | high_52w | low_52w | ...
    dist_pct: float | None = None
    strength: int | None = None                   # swing touches (support / resistance)


class OlScenarios(Model):
    above: list[OlLevel]                          # nearest first
    below: list[OlLevel]                          # nearest first
    flips: list[str]                              # plain-language trend-change levels


class OlSignal(Model):
    source: OlSource
    bias: OlBias
    title: str
    detail: str
    tested: str | None = None                     # how this kind of signal did when tested here, or None
    tone: Tone | None = None                      # good = tested edge / working strategy, bad = tested to fail
    when: ISODate | None = None


class OlChain(Model):
    symbol: str
    expiry: ISODate
    time: ISODateTime
    stale: bool                                   # the market is open and the chain is over 10 minutes old
    day: ISODate                                  # the day it was stored
    old: bool                                     # stored before the chart's last bar: levels / IV not used above
    spot: float | None = None
    forward: float | None = None
    days_to_expiry: float | None = None
    pcr_oi: float | None = None
    max_pain: float | None = None
    max_pain_gap_pct: float | None = None
    atm_iv_pct: float | None = None
    expected_move_pct: float | None = None
    range_low: float | None = None
    range_high: float | None = None
    call_wall: float | None = None
    put_wall: float | None = None
    readings: list[str]


class OlFutures(Model):
    date: ISODate
    close: float | None = None
    chg_pct: float | None = None
    oi_chg_pct: float | None = None
    basis_pct: float | None = None
    buildup: str | None = None
    pcr: float | None = None
    call_wall: float | None = None
    put_wall: float | None = None


class OvCandidate(Model):
    side: Literal["ce", "pe"]
    strike: float | None = None
    moneyness: str
    premium: float | None = None                  # the ask when quoted, else the last traded price
    bid: float | None = None
    ask: float | None = None
    quoted: bool                                  # a live bid and ask existed
    spread_pct: float | None = None
    oi: int | None = None
    iv_pct: float | None = None
    delta: float | None = None
    breakeven: float | None = None                # strike +/- the premium with costs
    breakeven_pct: float | None = None
    fair: float | None = None                     # its value on this stock's own history of moves
    edge_pct: float | None = None                 # fair vs the price paid plus costs
    prob_profit_pct: float | None = None          # chance of ending beyond the breakeven at expiry
    prob_itm_pct: float | None = None
    exp_return_pct: float | None = None
    ok: bool
    fails: list[str]


class OvCheck(Model):
    name: str
    ok: bool
    detail: str


class OvExit(Model):
    stop_underlying: float | None = None
    target_underlying: float | None = None
    note: str


class OvDirection(Model):
    bias: Literal["bullish", "bearish", "none"]
    reasons: list[str]


class OvTrack(Model):
    """Every journalled verdict so far, scored at its expiry, next to 'always buy the ATM call / put'."""
    recorded: int
    settled: int
    open: int
    buys: int
    buy_wins: int
    buy_avg_return_pct: float | None = None
    no_trades: int
    atm_call_avg_return_pct: float | None = None
    atm_put_avg_return_pct: float | None = None
    first_day: ISODate | None = None


class OptVerdict(Model):
    verdict: Literal["BUY_CALL", "BUY_PUT", "NO_TRADE", "NO_DATA"]
    headline: str
    symbol: str | None = None
    expiry: ISODate | None = None
    chain_time: ISODateTime | None = None
    spot: float | None = None
    days_to_expiry: float | None = None
    trading_days: int
    iv_pct: float | None = None
    hv20_pct: float | None = None
    hv252_pct: float | None = None
    vol_used_pct: float | None = None
    iv_vs_hv: float | None = None
    direction: OvDirection
    pick: OvCandidate | None = None
    calls: list[OvCandidate]
    puts: list[OvCandidate]
    checks: list[OvCheck]
    exit: OvExit | None = None
    edge_min_pct: float
    prob_min_pct: float
    cost_pct: float
    track: OvTrack
    note: str


class OlDerivatives(Model):
    fno: bool                                     # has stock / index options on NSE
    options_symbol: str | None = None             # NSE's name for the underlying (NIFTY50 -> NIFTY)
    chain: OlChain | None = None
    futures: OlFutures | None = None
    verdict: OptVerdict | None = None             # BUY CALL / BUY PUT / NO TRADE for the nearest expiry


class BmPledge(Model):
    quarter: ISODate | None = None
    broadcast: ISODateTime | None = None
    promoter_pct: float | None = None             # promoter holding, % of the company
    promoter_pledged_pct: float | None = None     # promoter shares pledged / encumbered, % of the promoter holding
    promoter_pledged_total_pct: float | None = None
    promoter_pledged_shares: float | None = None
    depository_pledged_pct: float | None = None   # every pledged share in demat (any holder, e.g. margin), % of demat
    depository_pledged_shares: float | None = None
    source: str


class BmFiling(Model):
    """One SEBI SAST Reg 29 disclosure: someone crossed 5% of the company, or moved 2% beyond it."""
    filed: ISODateTime | None = None
    period: str | None = None
    acquirer: str
    side: Literal["BUY", "SELL"]
    mode: str | None = None
    security: str | None = None
    promoter: bool
    regulation: str | None = None
    shares: float | None = None
    pct: float | None = None                      # % of the company bought / sold in this filing
    after_pct: float | None = None                # the acquirer's holding after it
    link: str | None = None                       # the filing on NSE


class BmDelivEvent(Model):
    date: ISODate
    kind: Literal["accumulation", "distribution"]
    ratio: float | None = None
    deliv_pct: float | None = None
    chg_pct: float | None = None


class BmTested(Model):
    """How the delivery spike did on 8 years of the point-in-time top 500, 10 days later vs the average stock."""
    n: int
    months: int
    verdict: str
    excess_pct: float | None = None
    hit_pct: float | None = None
    t: float | None = None
    after_cost_pct: float | None = None


class BmDelivery(Model):
    date: ISODate
    deliv_pct: float | None = None
    deliv_pct_avg20: float | None = None
    deliv_qty: float | None = None
    deliv_ratio: float | None = None
    state: Literal["accumulation", "distribution", "normal"]
    events: list[BmDelivEvent]
    tested_accumulation: BmTested | None = None
    tested_distribution: BmTested | None = None
    rule: str | None = None


class BmBan(Model):
    trade_date: ISODate | None = None
    in_ban: bool
    symbols: list[str]
    source: str


class BigMoney(Model):
    pledge: BmPledge | None = None
    pledge_checked: bool                          # NSE was asked (pledge None then = no record)
    filings: list[BmFiling]
    filings_note: str | None = None
    ban: BmBan | None = None
    delivery: BmDelivery | None = None
    refreshed_at: ISODateTime | None = None
    refreshing: bool
    note: str


class OlEvent(Model):
    date: ISODate
    kind: Literal["results", "expiry", "corporate_action"]
    label: str


class OutlookResponse(Model):
    symbol: str
    kind: Literal["stock", "etf", "index"]
    date: ISODate
    close: float | None = None
    provisional: bool                             # the last bar is today's live candle, not NSE's official close
    setup: list[OlFeature]
    headline: str
    analogs: OlAnalogs | None = None
    study_hint: str | None = None                 # why analogs is null
    expected: OlExpected
    scenarios: OlScenarios
    signals: list[OlSignal]
    derivatives: OlDerivatives
    big_money: BigMoney
    events: list[OlEvent]
    note: str


class BigMoneyRefreshAccepted(Model):
    accepted: bool
    running: bool
    symbol: str
