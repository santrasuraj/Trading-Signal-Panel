// GET /api/options/indices (web/api/services/options_svc.indices): every NSE index's nearest two option expiries with
// the scan's latest verdict. Used by the Signals page's Index options tab and its count.

import { useQuery } from '@tanstack/react-query'
import { fetchJson } from '@/api/client'
import type { OvPlan, OvTrack } from '@/api/outlook'

export type IndexVerdict = 'BUY_CALL' | 'BUY_PUT' | 'NO_TRADE' | 'NO_DATA'
export interface IndexOptionRow {
  symbol: string; name: string; expiry: string; days_to_expiry: number | null; spot: number | null; chain_time: string
  stale: boolean; atm: number | null; atm_call: number | null; atm_put: number | null; atm_iv_pct: number | null
  expected_move_pct: number | null; range_low: number | null; range_high: number | null; pcr_oi: number | null
  max_pain: number | null; verdict: IndexVerdict | null; verdict_day: string | null; headline: string | null
  bias: 'bullish' | 'bearish' | 'none' | null
  pick: { side: 'ce' | 'pe'; strike: number | null; premium: number | null; breakeven: number | null } | null
  /** BUY: the premiums to trade it with (Black-76 re-pricing of the underlying's stop / target), per lot after charges. */
  plan: OvPlan | null
  exit: { stop_underlying: number | null; target_underlying: number | null; note: string } | null
  /** The option nearest to passing (NO TRADE: how far it is, and why it fails). Never traded. */
  closest: IndexClosest | null
  checks: { name: string; ok: boolean; detail: string }[]
  /** The direction's tested sources. */
  reasons: string[]
  lot: number | null
}
export interface IndexClosest {
  side: 'ce' | 'pe'; strike: number | null; moneyness: string | null; premium: number | null; fair: number | null
  edge_pct: number | null; prob_profit_pct: number | null; breakeven: number | null; spread_pct: number | null
  oi: number | null; iv_pct: number | null; ok: boolean; fails: string[]
}
export type IndexVerdictTrack = OvTrack
export interface IndexOptionsResponse {
  generated_at: string; rows: IndexOptionRow[]; missing: string[]; track: IndexVerdictTrack; note: string
}

export const useIndexOptions = () =>
  useQuery({ queryKey: ['options', 'indices'], queryFn: () => fetchJson<IndexOptionsResponse>('/api/options/indices'), staleTime: 60_000, refetchInterval: 5 * 60_000 })

export const isBuy = (v: IndexVerdict | null) => v === 'BUY_CALL' || v === 'BUY_PUT'
