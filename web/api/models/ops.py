"""10. scan, 11. fyers, 12. config / costs / data health, 13. intraday."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from .common import Evidence, ISODate, ISODateTime, Model, StrategyStatus, TimeSeries
from .system import FyersStatus, ScanStatus


# ------------------------------------------------------------------ scan
class ScanRequest(Model):
    update: bool = True                          # false = re-check with stored prices (no download, ~15 s)


class ScanAccepted(Model):
    accepted: bool
    status: ScanStatus


class ScanHistoryItem(Model):
    scan_id: ISODateTime
    file: str
    data_date: ISODate | None = None
    live: bool | None = None
    elapsed_s: float | None = None
    strategies: int | None = None


class ScanHistory(Model):
    scans: list[ScanHistoryItem]


class ScanLog(Model):
    path: str
    lines: list[str]


# ------------------------------------------------------------------ fyers
class FyersLoginRequest(Model):
    mode: Literal["paste", "window"] = "paste"


class FyersLoginResponse(Model):
    mode: Literal["paste", "window"]
    login_url: str | None = None
    expires_at: ISODateTime | None = None
    instructions: list[str]


class FyersLoginCompleteRequest(Model):
    redirect_url: str


class FyersLoginCompleteResponse(Model):
    ok: bool
    user_name: str | None = None
    status: FyersStatus


# ------------------------------------------------------------------ config and costs
class CostConfig(Model):
    brokerage_pct: float
    brokerage_max: float
    stt_pct: float
    exchange_pct: float
    sebi_pct: float
    stamp_buy_pct: float
    gst_pct: float
    dp_per_sell: float
    slippage_pct: float
    slippage_illiquid_pct: float
    illiquid_below_cr: float


class TaxConfig(Model):
    stcg_pct: float
    ltcg_pct: float
    ltcg_exempt: float


class AccountConfig(Model):
    capital: float
    min_position: float


class FiltersConfig(Model):
    min_price: float
    min_turnover_cr: float


class HoldingDefaultsConfig(Model):
    stop_loss_pct: float
    target_pct: float


class ResultsConfig(Model):
    warn_days: int


class StrategyConfig(Model):
    enabled: bool
    params: dict[str, Any]


class TelegramConfig(Model):
    top_n: int
    configured: bool


class ConfigView(Model):
    account: AccountConfig
    data_source: Literal["auto", "yahoo"]
    fyers_plan: Literal["standard", "prime"]
    universe: Literal["nifty50", "nifty100", "nifty200", "nifty500"]
    lookback_days: int
    filters: FiltersConfig
    holdings_defaults: HoldingDefaultsConfig
    results: ResultsConfig
    movers_count: int
    etfs: list[str]
    costs: CostConfig
    tax: TaxConfig
    allocations: dict[str, float]
    strategies: dict[str, StrategyConfig]
    telegram: TelegramConfig


class ConfigResponse(Model):
    values: ConfigView
    file_mtime: ISODateTime
    needs_rescan: bool


class CostBreakdown(Model):
    value: float
    side: Literal["buy", "sell"]
    brokerage: float
    stt: float
    exchange: float
    sebi: float
    stamp: float
    gst: float
    dp: float
    slippage: float
    total: float
    total_pct: float


class CostPreview(Model):
    value: float
    buy: CostBreakdown
    sell: CostBreakdown
    round_trip_pct: float


# ------------------------------------------------------------------ data health
class StoreHealth(Model):
    version: str
    first_date: ISODate
    last_date: ISODate
    symbols: int
    trading_days: int
    fields: list[str]
    size_mb: float


class NseHealth(Model):
    status: str | None = None
    complete_upto: ISODate | None = None


class FailedSymbol(Model):
    count: int
    last_try: ISODate


class CorporateActionRow(Model):
    symbol: str
    date: ISODate
    factor: float
    reason: str


class IndexHistoryHealth(Model):
    last_date: ISODate | None = None
    columns: int


class ResultsCalendarHealth(Model):
    note: str | None = None
    cached_on: ISODate | None = None


class UniverseHealth(Model):
    name: str
    note: str
    size: int


class PitHealth(Model):
    built: bool
    note: str


class JournalHealth(Model):
    exists: bool
    days: int | None = None
    size_kb: float | None = None


class LogsHealth(Model):
    path: str
    size_kb: float
    last_error: str | None = None


class ScansHealth(Model):
    count: int
    newest: ISODateTime | None = None
    oldest: ISODateTime | None = None
    mixed_producers: bool


class DataHealth(Model):
    store: StoreHealth
    nse: NseHealth
    failed_symbols: dict[str, FailedSymbol]
    stale_symbols: list[str]
    errors: dict[str, str]
    corporate_actions_recent: list[CorporateActionRow]
    corporate_actions_total: int
    index_history: IndexHistoryHealth | None = None
    results_calendar: ResultsCalendarHealth
    universe: UniverseHealth
    pit: PitHealth | None = None
    journal: JournalHealth
    logs: LogsHealth
    scans: ScansHealth


# ------------------------------------------------------------------ intraday
class IntradayTrade(Model):
    symbol: str
    date: ISODate
    side: Literal["LONG", "SHORT"]
    entry_time: str
    entry: float
    stop: float | None = None
    exit_time: str
    exit: float
    reason: str
    qty: int
    pnl: float
    ret_pct: float
    open_now: bool | None = None


class IntradayMetrics(Model):
    days: int
    trades: int
    trades_per_day: float | None = None
    return_pct: float | None = None
    after_tax_return_pct: float | None = None
    annualised_pct: float | None = None
    sharpe: float | None = None
    max_dd_pct: float | None = None
    win_rate: float | None = None
    avg_trade_pct: float | None = None
    profit_factor: float | None = None
    avg_day_pct: float | None = None
    ci95_day_pct: tuple[float, float] | None = None
    t_stat: float | None = None
    significant: bool
    start: ISODate | None = None
    end: ISODate | None = None


class IntradayStrategy(Model):
    key: str
    name: str
    description: str
    evidence: Evidence
    horizon: Literal["intraday"] = "intraday"
    status: StrategyStatus
    metrics: IntradayMetrics
    equity: TimeSeries                            # rupees
    recent_trades: list[IntradayTrade]
    today: list[IntradayTrade]


class IntradayData(Model):
    source: str
    interval: Literal["5m"]
    from_: ISODate = Field(alias="from")
    to: ISODate
    sessions: int
    symbols: int
    note: str


class SebiFacts(Model):
    source: str
    url: str
    points: list[str]


class IntradayCostPreview(Model):
    value: float
    round_trip_pct: float


class IntradayRun(Model):
    """Background re-run of the intraday backtest (POST /api/intraday/run)."""
    state: Literal["idle", "running", "done", "failed"]
    running: bool
    message: str | None = None
    started_at: ISODateTime | None = None
    pid: int | None = None
    exit_code: int | None = None


class IntradayResponse(Model):
    available: bool
    reason: str | None = None
    generated_at: ISODateTime | None = None
    elapsed_s: float | None = None
    data: IntradayData | None = None
    rules: dict[str, str]
    sebi: SebiFacts
    costs: IntradayCostPreview | None = None
    strategies: list[IntradayStrategy]
    summary: str                                  # honest one-liner computed from the results (server text)
    run: IntradayRun


class IntradayRunRequest(Model):
    update: bool = True                           # false = re-test on the stored 5-minute bars only


class IntradayRunAccepted(Model):
    accepted: bool
    run: IntradayRun
