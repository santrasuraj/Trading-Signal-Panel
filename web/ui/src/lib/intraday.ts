// Intraday research helpers (pure, unit-tested in intraday.test.ts).

import type { IntradayStrategy } from '@/api/types'

export interface NoEdge { grossLo: number; grossHi: number; costLo: number; costHi: number }

/** Why no intraday strategy works, in numbers: the range of the average trade BEFORE costs (next to nothing = no edge
 *  to keep) and the range of what costs take per trade. Null when a strategy has a real edge (positive and beyond
 *  luck after costs) or the numbers are missing - then there is nothing to explain. */
export function whyNoEdge(strategies: IntradayStrategy[]): NoEdge | null {
  if (!strategies.length) return null
  if (strategies.some((s) => s.metrics.significant && (s.metrics.return_pct ?? 0) > 0)) return null
  const rows = strategies.filter((s) => s.metrics.avg_trade_gross_pct != null && s.metrics.avg_trade_pct != null)
  if (!rows.length) return null
  const gross = rows.map((s) => s.metrics.avg_trade_gross_pct as number)
  const cost = rows.map((s) => (s.metrics.avg_trade_gross_pct as number) - (s.metrics.avg_trade_pct as number))
  return { grossLo: Math.min(...gross), grossHi: Math.max(...gross), costLo: Math.min(...cost), costHi: Math.max(...cost) }
}
