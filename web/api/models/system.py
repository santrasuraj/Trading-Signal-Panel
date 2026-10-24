"""1. system (+ 10. scan, 11. fyers status types used by AppStatus)."""
from __future__ import annotations

from typing import Literal

from .common import AsOf, ISODate, ISODateTime, Model

MarketSession = Literal["pre_open", "open", "post_close", "closed", "holiday", "weekend"]
ScanState = Literal["idle", "starting", "running", "done", "failed", "busy"]


class Health(Model):
    ok: bool
    version: str
    uptime_s: float


class MarketClock(Model):
    now: ISODateTime
    session: MarketSession
    is_trading_day: bool
    holiday_name: str | None = None
    next_open: ISODateTime | None = None
    last_completed_day: ISODate        # today if trading day and now >= 18:00, else previous trading day
    holidays_known: bool               # false if data/nse/holidays_<year>.json is missing


class ScanStatus(Model):
    state: ScanState
    running: bool
    progress_pct: float | None = None  # status.json 'progress' (0..1 fraction) x 100
    message: str | None = None
    started_at: ISODateTime | None = None
    by: str | None = None
    pid: int | None = None
    update: bool | None = None
    exit_code: int | None = None


class Features(Model):
    paper: bool
    pit: bool
    intraday: bool
    trades_artifact: bool
    screener_artifact: bool
    rejected_tested: bool
    config_edit: bool


class Ticker(Model):
    nifty: float | None = None
    nifty_change_pct: float | None = None
    nifty500: float | None = None
    nifty500_change_pct: float | None = None
    vix: float | None = None
    vix_change_pct: float | None = None
    advances: int
    declines: int
    label: Literal["Bullish", "Mixed", "Bearish"]


class FyersStatus(Model):
    configured: bool
    client_id_masked: str | None = None
    plan: Literal["standard", "prime"]
    data_source: Literal["auto", "yahoo"]
    token_present: bool
    token_created: ISODateTime | None = None
    logged_in_today: bool
    verified: bool | None = None
    verified_at: ISODateTime | None = None
    user_name: str | None = None
    redirect_uri: str
    login_modes: list[Literal["paste", "window"]]
    note: str


class AppStatus(Model):
    server_version: str
    latest: AsOf | None = None          # null => onboarding
    scan: ScanStatus
    fyers: FyersStatus
    clock: MarketClock
    features: Features
    ticker: Ticker | None = None
    config_changed_since_scan: bool
