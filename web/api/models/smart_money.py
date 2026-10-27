"""Smart money (docs/smart_money_spec.md): bulk/block deals, insider (SEBI PIT) trades, quarterly shareholding changes
and FII/DII flows, all from NSE disclosures. Money in rupees except the *_cr FII/DII fields (NSE publishes those in
crore); *_pct are percent of the company's shares (12.3 = 12.3%); *_pts / change_pts are percentage-point changes."""
from __future__ import annotations

from typing import Literal

from pydantic import Field

from .common import ISODate, ISODateTime, Model

__all__ = ["SmCategory", "SmCategoryFilter", "SmDealKind", "SmDealSide", "SmModeKind", "SmEventType", "SmExitKind",
           "SmSourceKind", "SmRunState", "SmSourceState", "SmFreshness", "SmRefreshRun", "SmSource", "SmSources",
           "SmStatus", "SmDeal", "SmDealCounts", "SmDealsResponse", "SmInsiderTrade", "SmInsiderCounts",
           "SmInsiderResponse", "SmEvent", "SmStock", "SmHoldingsResponse", "SmFlowDay", "SmFlowsResponse", "SmKpis",
           "SmOverview", "SmHoldingPeriod", "SmHolder", "SmStockResponse", "SmRefreshRequest", "SmRefreshAccepted"]

SmCategory = Literal["fii", "mf", "insurance", "bank", "pension", "aif", "promoter", "famous", "broker", "other"]
SmCategoryFilter = Literal["all", "big", "institutions", "fii", "mf", "insurance", "bank", "pension", "aif", "promoter",
                           "famous", "broker", "other"]
SmDealKind = Literal["bulk", "block", "both"]
SmDealSide = Literal["BUY", "SELL", "FLAT"]
SmModeKind = Literal["market", "pledge", "pledge_invoked", "off_market", "esop", "gift", "inter_se", "preferential",
                     "other"]
SmEventType = Literal["deal_buy", "deal_sell", "insider_buy", "insider_sell", "insider_exit", "pledge_invoked",
                      "new_holder", "holder_added", "holder_cut", "holder_dropped", "category_up", "category_down",
                      "category_exit"]
SmExitKind = Literal["full_exit", "below_1pct", "sold_part", "category_exit"]
SmSourceKind = Literal["bulk", "block", "insider", "shareholding"]
SmRunState = Literal["idle", "running", "done", "failed"]
SmSourceState = Literal["ok", "partial", "failed", "skipped", "never"]


# ------------------------------------------------------------------ status
class SmFreshness(Model):
    deals: ISODate | None = None             # newest bulk/block deal date stored
    insider: ISODate | None = None           # newest insider disclosure date stored
    flows: ISODate | None = None             # newest FII/DII day stored
    holdings_period: ISODate | None = None   # newest shareholding quarter end stored
    refreshed_at: ISODateTime | None = None  # when the last refresh finished
    stale: bool                              # never refreshed, or newest deals > 5 days before today (IST)


class SmRefreshRun(Model):
    state: SmRunState
    running: bool
    message: str | None = None
    started_at: ISODateTime | None = None
    finished_at: ISODateTime | None = None
    errors: list[str]


class SmSource(Model):
    status: SmSourceState
    message: str | None = None
    rows_added: int = 0
    last_ok_at: ISODateTime | None = None
    latest_date: ISODate | None = None


class SmSources(Model):
    deals: SmSource
    insider: SmSource
    flows: SmSource
    holdings: SmSource


class SmStatus(Model):
    run: SmRefreshRun
    freshness: SmFreshness
    sources: SmSources
    errors: list[str]                        # the last refresh's problems, plain English


# ------------------------------------------------------------------ bulk / block deals
class SmDeal(Model):
    """One client's net bulk/block trading in one stock on one day (NSE's rows for that client summed)."""
    id: str
    date: ISODate
    symbol: str
    company: str | None = None
    kind: SmDealKind
    side: SmDealSide                         # sign of net_qty; FLAT = bought and sold the same number
    client: str                              # name exactly as filed with NSE
    client_key: str                          # normalised parent name (one fund house's schemes together)
    category: SmCategory
    category_label: str
    sub_label: str | None = None
    investor: str | None = None              # well-known investor's display name (category 'famous')
    round_trip: bool                         # bought and sold about the same quantity the same day (intraday)
    buy_qty: int
    sell_qty: int
    net_qty: int
    buy_value: float                         # rupees
    sell_value: float
    net_value: float
    avg_price: float | None = None           # rupees per share
    pct_equity: float | None = None          # shares traded as % of all the company's shares (null = unknown)
    counterparties: list[str]                # block deals: clients on the other side the same day


class SmDealCounts(Model):
    buys: int
    sells: int
    intraday: int
    by_category: dict[str, int]


class SmDealsResponse(Model):
    freshness: SmFreshness
    days: int
    since: ISODate | None = None
    until: ISODate | None = None
    intraday: bool
    total: int
    page: int
    page_size: int
    rows: list[SmDeal]
    counts: SmDealCounts
    note: str


# ------------------------------------------------------------------ insider (SEBI PIT) trades
class SmInsiderTrade(Model):
    id: str
    symbol: str
    company: str | None = None
    person: str
    role: Literal["promoter", "insider", "other"]
    person_category: str | None = None       # as filed, e.g. 'Promoter Group'
    category: SmCategory
    category_label: str
    sub_label: str | None = None
    investor: str | None = None
    side: Literal["BUY", "SELL"] | None = None
    mode: str | None = None                  # as filed, e.g. 'Market Purchase'
    mode_kind: SmModeKind
    is_market: bool                          # an open-market buy/sell: the only real buy/sell decision
    qty: int | None = None
    value: float | None = None               # rupees
    avg_price: float | None = None
    before_pct: float | None = None
    after_pct: float | None = None
    change_pts: float | None = None
    before_shares: int | None = None
    after_shares: int | None = None
    trade_from: ISODate | None = None
    trade_to: ISODate | None = None
    disclosed: ISODate | None = None
    delay_days: int | None = None            # calendar days from the trade to the NSE filing
    fully_exited: bool
    xbrl: str | None = None


class SmInsiderCounts(Model):
    buys: int
    sells: int
    buy_value: float
    sell_value: float
    pledge_invoked: int
    full_exits: int


class SmInsiderResponse(Model):
    freshness: SmFreshness
    days: int
    since: ISODate | None = None
    until: ISODate | None = None
    total: int
    page: int
    page_size: int
    rows: list[SmInsiderTrade]
    counts: SmInsiderCounts
    note: str


# ------------------------------------------------------------------ events, per-stock signals, holdings view
class SmEvent(Model):
    """One thing a big investor did that the disclosures show (server-written plain-English `text`)."""
    id: str
    date: ISODate                            # when it became public
    symbol: str
    company: str | None = None
    event: SmEventType
    direction: Literal["up", "down"]
    source: SmSourceKind
    who: str | None = None                   # name as filed (null for a whole-category change)
    investor: str | None = None
    category: SmCategory
    category_label: str
    sub_label: str | None = None
    value: float | None = None               # rupees
    qty: int | None = None
    pct_before: float | None = None
    pct_after: float | None = None
    change_pts: float | None = None
    pct_equity: float | None = None
    period: ISODate | None = None            # shareholding quarter end
    prev_period: ISODate | None = None
    exit_kind: SmExitKind | None = None
    text: str


class SmStock(Model):
    symbol: str
    company: str | None = None
    direction: Literal["up", "down", "mixed"]
    up_events: int
    down_events: int
    up_score: int
    down_score: int
    deal_buy_value: float                    # rupees: big-money bulk/block net buys in the window (no intraday)
    deal_sell_value: float
    deal_net_value: float
    inst_buyers: int                         # distinct institutions net buying via deals
    inst_sellers: int
    famous_buyers: list[str]
    famous_sellers: list[str]
    insider_buy_value: float                 # open-market promoter/insider buys disclosed in the window
    insider_sell_value: float
    promoter_buying: bool
    promoter_selling: bool
    pledge_invoked: bool
    exits: int
    fii_chg_pts: float | None = None         # latest quarter vs the one before
    dii_chg_pts: float | None = None
    mf_chg_pts: float | None = None
    promoter_chg_pts: float | None = None
    period: ISODate | None = None
    last_date: ISODate
    reasons: list[str]                       # up to 4 plain-English lines, most important first


class SmHoldingsResponse(Model):
    freshness: SmFreshness
    view: Literal["accumulating", "exiting", "all"]
    days: int
    since: ISODate | None = None
    latest_period: ISODate | None = None
    previous_period: ISODate | None = None
    coverage: int                            # stocks with shareholding data
    stocks: list[SmStock]
    events: list[SmEvent]
    note: str


# ------------------------------------------------------------------ FII/DII flows (market-wide, Rs crore)
class SmFlowDay(Model):
    date: ISODate
    fii_buy_cr: float | None = None          # rupees crore
    fii_sell_cr: float | None = None
    fii_net_cr: float | None = None
    dii_buy_cr: float | None = None
    dii_sell_cr: float | None = None
    dii_net_cr: float | None = None


class SmFlowsResponse(Model):
    freshness: SmFreshness
    days: int
    since: ISODate | None = None
    first_date: ISODate | None = None        # history starts here (NSE gives one day at a time)
    rows: list[SmFlowDay]                    # newest first
    fii_net_cr_total: float | None = None
    dii_net_cr_total: float | None = None
    fii_streak: int                          # +3 = 3 buying days in a row up to the latest, -2 = 2 selling days
    dii_streak: int
    note: str


# ------------------------------------------------------------------ overview
class SmKpis(Model):
    days: int
    since: ISODate | None = None
    big_buy_value: float
    big_sell_value: float
    inst_net_value: float
    stocks_bought: int
    stocks_sold: int
    insider_buy_value: float
    insider_sell_value: float
    exits: int
    intraday_rows: int
    fii_net_cr: float | None = None
    dii_net_cr: float | None = None
    flows_date: ISODate | None = None


class SmOverview(Model):
    freshness: SmFreshness
    run: SmRefreshRun
    days: int
    kpis: SmKpis
    top_bought: list[SmStock]
    top_sold: list[SmStock]
    latest_deals_date: ISODate | None = None
    latest_deals: list[SmDeal]
    latest_insider: list[SmInsiderTrade]
    exits: list[SmEvent]
    flows: list[SmFlowDay]
    has_data: bool
    errors: list[str]
    note: str


# ------------------------------------------------------------------ one stock (Chart side panel)
class SmHoldingPeriod(Model):
    period: ISODate
    broadcast: ISODate | None = None
    source: Literal["xbrl", "master"]
    total_shares: int | None = None
    promoter_pct: float | None = None
    public_pct: float | None = None
    fii_pct: float | None = None
    dii_pct: float | None = None
    mf_pct: float | None = None
    insurance_pct: float | None = None
    banks_pct: float | None = None
    pension_pct: float | None = None
    aif_pct: float | None = None


class SmHolder(Model):
    holder: str
    holder_key: str
    group: Literal["promoter", "public"]
    category: SmCategory
    category_label: str
    sub_label: str | None = None
    investor: str | None = None
    pct: float | None = None
    prev_pct: float | None = None
    change_pts: float | None = None
    shares: int | None = None
    status: Literal["new", "added", "cut", "same", "dropped"]


class SmStockResponse(Model):
    symbol: str
    company: str | None = None
    freshness: SmFreshness
    days: int
    has_data: bool
    summary: SmStock | None = None
    deals: list[SmDeal]
    insider: list[SmInsiderTrade]
    holdings: list[SmHoldingPeriod]
    holders_period: ISODate | None = None
    holders_prev_period: ISODate | None = None
    holders: list[SmHolder]
    events: list[SmEvent]
    note: str


# ------------------------------------------------------------------ refresh
class SmRefreshRequest(Model):
    days: int = Field(365, ge=30, le=730)    # history depth for the first backfill


class SmRefreshAccepted(Model):
    accepted: bool
    run: SmRefreshRun


# ------------------------------------------------------------------ Big money live (scanner/footprints.py)
class SmLivePrints(Model):
    count: int
    value_cr: float
    buy_cr: float                                 # traded at or above the ask (buyer-initiated)
    sell_cr: float                                # at or below the bid (seller-initiated)


class SmLiveBlock(Model):
    client: str | None = None
    side: str | None = None
    value_cr: float


class SmLiveDisclosures(Model):
    direction: Literal["up", "down", "mixed"]     # what the last 30 days of disclosures say about the stock
    reasons: list[str]
    deal_net_value: float
    insider_buy_value: float
    insider_sell_value: float
    promoter_buying: bool
    promoter_selling: bool


class SmLiveRow(Model):
    symbol: str
    company: str | None = None
    last: float
    change_pct: float | None = None
    vwap: float | None = None
    rvol: float | None = None                     # today's volume so far / normal for this time of day
    value_cr: float
    direction: Literal["up", "down", "mixed"]     # price vs the previous close and VWAP
    kinds: list[Literal["volume", "prints", "block"]]
    reasons: list[str]
    prints: SmLivePrints
    book_ratio: float | None = None               # pending buy / sell quantity (FYERS feed)
    blocks: list[SmLiveBlock]
    disclosures: SmLiveDisclosures | None = None
    agree: bool                                   # the live move and the disclosures point the same way


class SmLiveStats(Model):
    alerts: int
    hit_rate: float | None = None                 # % that kept moving the alert's way by the next close
    avg_move_pct: float | None = None


class SmLiveAlert(Model):
    date: str
    time: str
    symbol: str
    price: float
    direction: Literal["up", "down", "mixed"]
    kinds: list[str]
    next_date: str | None = None
    move_pct: float | None = None                 # next close vs the alert price, in the alert's direction


class SmLiveTrack(Model):
    min_to_judge: int
    all: SmLiveStats
    with_agreement: SmLiveStats
    verdict: str
    recent: list[SmLiveAlert]


class SmLiveResponse(Model):
    generated_at: str | None = None
    market_open: bool
    fresh: bool
    source: str | None = None
    delayed: bool
    note: str
    thresholds: dict[str, float]
    universe: int
    rows: list[SmLiveRow]
    track: SmLiveTrack
