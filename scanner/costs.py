"""Indian equity-delivery trading costs (per order), used by the backtest engine.

All percentages are in percent of traded value. Defaults reflect NSE delivery charges in 2025-26;
override any of them under `costs:` in config.yaml if your broker's rates differ.
"""
from __future__ import annotations

from dataclasses import dataclass, fields


@dataclass(frozen=True)
class CostModel:
    brokerage_pct: float = 0.3        # broker fee as % of order value ...
    brokerage_max: float = 20.0       # ... capped at this many rupees per order
    stt_pct: float = 0.1              # Securities Transaction Tax, delivery: buy and sell
    exchange_pct: float = 0.00297     # NSE transaction charge
    sebi_pct: float = 0.0001          # SEBI turnover fee (Rs 10 per crore)
    stamp_buy_pct: float = 0.015      # stamp duty, buy side only
    gst_pct: float = 18.0             # GST on brokerage + exchange + SEBI fees
    dp_per_sell: float = 15.34        # depository charge per scrip per sell day (incl. GST)
    slippage_pct: float = 0.10        # assumed execution slippage per side

    @classmethod
    def from_config(cls, cfg: dict | None) -> "CostModel":
        cfg = cfg or {}
        known = {f.name for f in fields(cls)}
        return cls(**{k: float(v) for k, v in cfg.items() if k in known})

    def _fees(self, value: float) -> float:
        brokerage = min(value * self.brokerage_pct / 100, self.brokerage_max)
        exchange = value * self.exchange_pct / 100
        sebi = value * self.sebi_pct / 100
        gst = (brokerage + exchange + sebi) * self.gst_pct / 100
        stt = value * self.stt_pct / 100
        return brokerage + exchange + sebi + gst + stt

    def buy_cost(self, value: float) -> float:
        """Rupees paid on top of `value` for a buy order (excludes slippage, which moves the fill price)."""
        return self._fees(value) + value * self.stamp_buy_pct / 100

    def sell_cost(self, value: float) -> float:
        """Rupees deducted from `value` for a sell order."""
        return self._fees(value) + self.dp_per_sell

    def round_trip_pct(self, value: float) -> float:
        """Total round-trip cost incl. slippage as % of `value` (for display)."""
        rupees = self.buy_cost(value) + self.sell_cost(value) + 2 * value * self.slippage_pct / 100
        return rupees / value * 100
