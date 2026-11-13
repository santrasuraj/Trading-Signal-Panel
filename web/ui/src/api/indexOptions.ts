// GET /api/options/indices (web/api/services/options_svc.indices): every NSE index's nearest two option expiries with
// the scan's latest verdict. Used by the Signals page's Index options tab and its count.

import { useQuery } from '@tanstack/react-query'
import { fetchJson } from '@/api/client'

export type IndexVerdict = 'BUY_CALL' | 'BUY_PUT' | 'NO_TRADE' | 'NO_DATA'
export interface IndexOptionRow {
  symbol: string; name: string; expiry: string; days_to_expiry: number | null; spot: number | null; chain_time: string
  stale: boolean; atm: number | null; atm_call: number | null; atm_put: number | null; atm_iv_pct: number | null
  expected_move_pct: number | null; range_low: number | null; range_high: number | null; pcr_oi: number | null
  max_pain: number | null; verdict: IndexVerdict | null; verdict_day: string | null; headline: string | null
  bias: 'bullish' | 'bearish' | 'none' | null
  pick: { side: 'ce' | 'pe'; strike: number | null; premium: number | null; breakeven: number | null } | null
}
export interface IndexVerdictTrack {
  recorded: number; settled: number; open: number; buys: number; buy_wins: number; buy_avg_return_pct: number | null
  no_trades: number; atm_call_avg_return_pct: number | null; atm_put_avg_return_pct: number | null; first_day: string | null
}
export interface IndexOptionsResponse {
  generated_at: string; rows: IndexOptionRow[]; missing: string[]; track: IndexVerdictTrack; note: string
}

export const useIndexOptions = () =>
  useQuery({ queryKey: ['options', 'indices'], queryFn: () => fetchJson<IndexOptionsResponse>('/api/options/indices'), staleTime: 60_000, refetchInterval: 5 * 60_000 })

export const isBuy = (v: IndexVerdict | null) => v === 'BUY_CALL' || v === 'BUY_PUT'
