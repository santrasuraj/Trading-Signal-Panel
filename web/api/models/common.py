"""Shared pydantic models: the 1:1 transcription of the "Final API contract" in docs/ui_spec_review.md.

Wire rules: snake_case; every declared field is always present (unknown = null); NaN/inf -> null;
percent fields end in _pct (12.3 = 12.3%); money in rupees; ISODate 'YYYY-MM-DD'; ISODateTime +05:30.
Time series are columnar (TimeSeries), never arrays of {t, v} objects.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

ISODate = str
ISODateTime = str
Horizon = Literal["intraday", "swing", "longterm"]
StrategyKind = Literal["rank", "event"]
StrategyStatus = Literal["working", "mixed", "not-working", "unknown"]
Lifecycle = Literal["active", "disabled", "rejected"]
Evidence = Literal["STRONG", "MODERATE", "WEAK", "FOLKLORE", "EXPERIMENTAL"]
Tone = Literal["good", "neutral", "bad"]
Side = Literal["BUY", "SELL"]
AssetUniverse = Literal["stocks", "etfs"]
ErrorCode = Literal["NO_SCAN", "NOT_FOUND", "VALIDATION", "SCAN_BUSY", "FYERS_NOT_CONFIGURED",
                    "FYERS_LOGIN_REQUIRED", "FYERS_AUTH", "FYERS_RATE_LIMIT", "FEATURE_UNAVAILABLE",
                    "CSRF", "FORBIDDEN_HOST", "INTERNAL"]


class Model(BaseModel):
    # json_schema_serialization_defaults_required: response schemas list every field as required, so the
    # generated TypeScript has no optional (`?`) fields - matching "every declared field always present".
    model_config = ConfigDict(extra="ignore", ser_json_inf_nan="null", populate_by_name=True,
                              json_schema_serialization_defaults_required=True)


class ApiErrorBody(Model):
    code: ErrorCode
    message: str
    hint: str | None = None
    details: dict[str, Any] | None = None


class ApiError(Model):
    error: ApiErrorBody


class Series(Model):
    id: str
    label: str
    role: Literal["strategy", "benchmark", "factor", "paper"]
    v: list[float | None]


class TimeSeries(Model):
    """Columnar series sharing one time axis. v[i] aligns with t[i]."""
    t: list[ISODate]
    series: list[Series]


class AsOf(Model):
    scan_id: str
    generated_at: ISODateTime
    elapsed_s: float
    data_date: ISODate
    live: bool
    live_source: str | None = None
    complete_upto: ISODate | None = None
    stale: bool
    legacy_producer: bool
    backtest_universe: Literal["current_list", "point_in_time"] = "current_list"
    universe_note: str
    tradable: int
    capital: float
    min_position: float
    costs_round_trip_pct: float


class PerfStats(Model):
    return_pct: float | None = None
    cagr_pct: float | None = None
    max_dd_pct: float | None = None
    sharpe: float | None = None
    vol_pct: float | None = None
    after_tax_cagr_pct: float | None = None


class TradeStats(Model):
    trades: int = 0
    win_rate: float | None = None
    avg_win_pct: float | None = None
    avg_loss_pct: float | None = None
    expectancy_pct: float | None = None
    profit_factor: float | None = None
    avg_days: float | None = None


class WindowMetrics(PerfStats, TradeStats):
    benchmark: PerfStats | None = None
    ew_benchmark: PerfStats | None = None
    n500_benchmark: PerfStats | None = None
    factor_benchmark: PerfStats | None = None


class FullMetrics(WindowMetrics):
    exposure_pct: float | None = None
    start: ISODate
    end: ISODate
    after_tax_return_pct: float | None = None
    cagr_range: tuple[float, float] | None = None
    te_n500_pct: float | None = None
    factor_benchmark_name: str | None = None


class StrategyMetrics(Model):
    full: FullMetrics
    m12: WindowMetrics | None = None
    m6: WindowMetrics | None = None
    m3: WindowMetrics | None = None
