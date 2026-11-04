"""AI analyst (POST /api/ai/analyze): Claude explains one symbol from this platform's own data."""
from __future__ import annotations

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
