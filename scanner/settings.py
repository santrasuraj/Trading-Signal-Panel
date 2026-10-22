"""Paths, config loading and Indian-market time helpers."""
from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
HISTORY_DIR = DATA_DIR / "history"
RESULTS_DIR = DATA_DIR / "results"
LOG_DIR = DATA_DIR / "logs"
TOKEN_FILE = DATA_DIR / "fyers_token.json"
HOLDINGS_FILE = ROOT / "holdings.csv"
CONFIG_FILE = ROOT / "config.yaml"

for _d in (DATA_DIR, HISTORY_DIR, RESULTS_DIR, LOG_DIR):
    _d.mkdir(parents=True, exist_ok=True)

load_dotenv(ROOT / ".env")

# IST has no daylight saving, so a fixed offset is exact (and avoids tzdata issues on Windows).
IST = timezone(timedelta(hours=5, minutes=30))
SESSION_START = (9, 15)
SESSION_END = (15, 30)
# After this time the day's daily candle is treated as final and saved to the cache.
CANDLE_FINAL_AFTER = (16, 0)


def env(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


def load_config() -> dict:
    with open(CONFIG_FILE, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def ist_now() -> datetime:
    return datetime.now(IST)


def ist_today() -> date:
    return ist_now().date()


def market_session_fraction(now: datetime | None = None) -> float | None:
    """Fraction of today's trading session elapsed, or None outside market hours / weekends."""
    now = now or ist_now()
    if now.weekday() >= 5:
        return None
    start = now.replace(hour=SESSION_START[0], minute=SESSION_START[1], second=0, microsecond=0)
    end = now.replace(hour=SESSION_END[0], minute=SESSION_END[1], second=0, microsecond=0)
    if not (start <= now < end):
        return None
    return (now - start).total_seconds() / (end - start).total_seconds()
