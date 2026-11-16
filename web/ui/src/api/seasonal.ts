// GET /api/seasonal?period=11 | budget | fy_end | summer | monsoon | festive | year_end (web/api/services/seasonal_svc.py,
// scanner/seasonal.py): which stocks and sectors have tended to rise or fall in a month or season against the NIFTY 500,
// how many such records chance alone gives, and a walk-forward test of buying them (point-in-time top 500, after costs).

import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { fetchJson } from '@/api/client'
import type { SignalProof } from '@/api/types'

export type SeasonStrength = 'consistent' | 'lean' | 'noise'
export interface SeasonPeriod { key: string; kind: 'month' | 'season'; name: string; short: string; months: number[]; why?: string | null }
export interface SeasonRow {
  symbol: string; company: string | null; industry: string | null; side: 'bullish' | 'bearish'; n: number
  /** Years above / below the NIFTY 500 (exact counts). */
  beat_years: number; lag_years: number
  avg_pct: number | null; median_pct: number | null; excess_pct: number | null; median_excess_pct: number | null
  beat_pct: number | null; up_pct: number | null; t: number | null; strength: SeasonStrength
  /** Each year's return over the NIFTY 500, by year. */
  years: Record<string, number | null>
  so_far_pct: number | null; so_far_excess_pct: number | null
}
export interface SeasonTestRow {
  year: number; label: string; eligible: number; top: string[]; bottom: string[]
  top_excess_pct: number | null; bottom_excess_pct: number | null; all_excess_pct: number | null; bench_pct: number | null
}
export interface SeasonSummary {
  n: number; status: SignalProof; top_avg_pct?: number | null; top_t?: number | null; top_hit_pct?: number | null
  top_total_pct?: number | null; bottom_avg_pct?: number | null; bottom_t?: number | null; bottom_hit_pct?: number | null
  first?: string | number | null; last?: string | number | null
}
export interface SectorCell { period: string; n: number; excess_pct: number | null; beat_pct: number | null; t: number | null }
export interface SeasonView {
  period: SeasonPeriod; periods: SeasonPeriod[]; current: { month: string; season: string }; bench: string
  first_year: number | null; last_year: number | null; as_of: string
  market: { n: number; avg_pct: number | null; median_pct: number | null; up_pct: number | null; t: number | null; years: Record<string, number | null> }
  rows: SeasonRow[]; in_progress: boolean; market_so_far_pct: number | null
  counts: {
    bullish: { consistent: number; lean: number }; bearish: { consistent: number; lean: number }; min_years: number
    chance: { bullish: number; bearish: number; bullish_p95: number; bearish_p95: number; permutations: number }
  }
  test: { rows: SeasonTestRow[]; summary: SeasonSummary; pooled: SeasonSummary; universe: 'point_in_time' | 'current'; cost_pct: number; top_n: number; train_min_years: number }
  sectors: { industry: string; stocks: number; cells: SectorCell[] }[]
  /** Stock-months left out: the two NSE-based price histories disagree there (demergers). */
  data: { left_out: number; tolerance_pts: number; examples: string[] }
  note: string
}

export const useSeasonal = (period: string | null) =>
  useQuery({ queryKey: ['seasonal', period ?? 'now'], queryFn: () => fetchJson<SeasonView>(`/api/seasonal${period ? `?period=${encodeURIComponent(period)}` : ''}`),
             staleTime: 30 * 60_000, placeholderData: keepPreviousData })
