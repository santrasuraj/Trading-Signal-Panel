"""Intraday (MIS) strategies on 5-minute bars.

  data.py        fetch (FYERS history / Yahoo), clean, store (data/intraday/bars), tick -> bar builder
  fyers_sync.py  resumable FYERS backfill + daily after-close archive (shared rate limiter)
  live.py        real-time bars from the FYERS WebSocket during market hours
  engine.py      backtest rules: next-bar fills, stop-first, forced square-off, FYERS intraday costs
  strategies.py  the intraday strategies
  run.py         pipeline: universe -> bars -> backtests + today's setups -> data/results/intraday.json
Entry point for scheduled/manual jobs: intraday_sync.py in the project root.
"""
