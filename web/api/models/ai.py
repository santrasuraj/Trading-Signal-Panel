"""AI analyst (POST /api/ai/analyze): Claude explains one symbol from this platform's own data.
AI forecasts (GET /api/ai/forecasts, POST /api/ai/forecast): Claude's option-chain forecasts, journalled and scored
against NSE's official closes (scanner/ai_forecast.py)."""
from __future__ import annotations

from typing import Literal

from pydantic import Field

from .common import ISODate, ISODateTime, Model


class AiAnalyzeRequest(Model):
    symbol: str = Field(min_length=1, max_length=20)
    question: str | None = Field(default=None, max_length=1000)


class AiAnalysis(Model):
    symbol: str
    question: str | None = None
    answer: str | None = None                     # None when the model declined (refused)
    refused: bool
    stop_reason: str | None = None
    model: str
    data_date: ISODate | None = None              # the last price bar the analysis read
    generated_at: ISODateTime
    cached: bool                                  # the same question on the same data within 15 minutes
    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_read_tokens: int | None = None
    note: str


class AiStatus(Model):
    configured: bool                              # ANTHROPIC_API_KEY is set in .env (the key itself never leaves the server)
    model: str
    running: bool
    note: str


# ------------------------------------------------------------------ option-chain forecasts
ForecastKind = Literal["evening", "on_demand"]
ForecastStatus = Literal["pending", "ok", "refused", "error"]
TrackStatus = Literal["unproven", "beats_coin_flip", "no_edge"]


class AiForecastRequest(Model):
    symbol: str = Field(min_length=1, max_length=20, pattern=r"^[A-Za-z0-9&-]+$")


class AiHorizonForecast(Model):
    p_up: float                                   # 0-100: chance the close ends above the spot Claude saw
    low: float                                    # the range Claude expects the close in about 2 times out of 3
    high: float


class AiPriceRange(Model):
    low: float
    high: float


class AiKeyLevel(Model):
    price: float
    kind: Literal["support", "resistance", "pivot"]
    why: str


class AiReason(Model):
    text: str
    evidence: list[str]                           # snapshot fields the reason rests on
    tested: bool                                  # Claude's claim that the reading was tested here


class AiForecastBody(Model):
    view: Literal["up", "down", "sideways", "no_view"]
    confidence: Literal["low", "medium", "high"]
    summary: str
    next_close: AiHorizonForecast
    expiry: AiHorizonForecast
    invalidation: float | None = None
    key_levels: list[AiKeyLevel]
    reasons: list[AiReason]


class AiBaselines(Model):
    next_close: AiPriceRange | None = None        # the options-implied 1-SD range for each horizon
    expiry: AiPriceRange | None = None


class AiOutcome(Model):
    date: ISODate                                 # the official close that settled it
    close: float
    move_pct: float
    up: bool
    call: Literal["up", "down"] | None = None     # None: p_up was exactly 50
    hit: bool | None = None
    brier: float                                  # (p - outcome)^2; a coin flip scores 0.25
    in_range: bool
    width_pct: float
    base_in_range: bool | None = None
    base_width_pct: float | None = None


class AiOutcomes(Model):
    next_close: AiOutcome | None = None
    expiry: AiOutcome | None = None


class AiUsage(Model):
    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_read_tokens: int | None = None


class AiForecast(Model):
    id: str
    kind: ForecastKind
    symbol: str
    settle: Literal["index", "store"]             # settled by NSE's index file or the price store
    created_at: ISODateTime
    answered_at: ISODateTime | None = None
    chain_time: ISODateTime                       # NSE's time stamp of the chain Claude read
    expiry: ISODate
    spot: float
    model: str
    effort: str
    status: ForecastStatus
    error: str | None = None
    forecast: AiForecastBody | None = None
    baseline: AiBaselines
    snapshot_sha256: str                          # data/results/ai_forecast_snapshots/<sha>.json
    usage: AiUsage | None = None
    batch_id: str | None = None
    outcome: AiOutcomes | None = None             # null right after a POST (scored on GET /api/ai/forecasts)
    cached: bool = False                          # the same chain asked again within 15 minutes


class AiHorizonTrack(Model):
    settled: int
    calls: int
    hits: int
    hit_pct: float | None = None
    p_value: float | None = None                  # two-sided exact binomial vs a coin flip
    brier: float | None = None
    coin_brier: float
    always_up_hit_pct: float | None = None
    range_hit_pct: float | None = None
    range_width_pct: float | None = None
    base_range_hit_pct: float | None = None
    base_width_pct: float | None = None
    status: TrackStatus
    why: str


class AiTrackHorizons(Model):
    next_close: AiHorizonTrack
    expiry: AiHorizonTrack


class AiTrack(Model):
    kind: ForecastKind
    forecasts: int
    ok: int
    pending: int
    refused: int
    errors: int
    horizons: AiTrackHorizons


class AiPendingBatch(Model):
    id: str
    submitted_at: ISODateTime
    symbols: list[str]


class AiForecastReport(Model):
    configured: bool
    model: str
    effort: str
    underlyings: list[str]                        # config.yaml ai_forecast.underlyings (evening run)
    symbol: str | None = None
    proven_min: int
    p_max: float
    track: list[AiTrack]
    latest: list[AiForecast]                      # the newest answered forecast per underlying
    rows: list[AiForecast]                        # newest first
    pending_batches: list[AiPendingBatch]
    note: str
