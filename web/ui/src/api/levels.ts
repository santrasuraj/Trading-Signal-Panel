// Price action API (web/api/routers/levels.py): types mirroring web/api/models/levels.py and the query hook.

import { useQuery } from '@tanstack/react-query'
import { fetchJson } from './client'
import type { ISODate, ISODateTime } from './types'

export type LvVerdict = 'edge' | 'edge_before_costs' | 'no_edge' | 'opposite' | 'no_direction' | 'too_few'
export interface LvStats {
  n: number; months: number; excess_pct: number | null; median_pct: number | null; hit_pct: number | null
  t: number | null; after_cost_pct: number | null
}
export interface LvEvidence extends LvStats { verdict: LvVerdict; horizon_days: number }
export interface LvPattern {
  key: string; name: string; bias: 'bullish' | 'bearish' | 'neutral'; what: string; bars_ago: number; at: ISODateTime
  evidence: LvEvidence | null
}
export interface LvStudyRow {
  key: string; family: 'candle' | 'chart'; name: string; bias: 'bullish' | 'bearish' | 'neutral'; verdict: LvVerdict
  primary: number; horizons: Record<string, LvStats>
}
export interface PatternEvidenceResponse {
  generated_at: ISODateTime | null; first_day: ISODate | null; last_day: ISODate | null; events: number | null
  cost_pct: number | null; min_events: number | null; min_months: number | null; patterns: LvStudyRow[]; note: string
}
/** One swing point of a chart pattern. `i`: bar within `series` (the sketch); `t` / `ago`: its date and bars before
 *  the pattern's last bar (`end`), for drawing on the price chart; `side`: a swing high (label above) or low. */
export interface LvPatternPoint { i: number; price: number | null; label: string; t: ISODate; ago: number; side: 'high' | 'low' }
export interface LvPatternLine {
  i1: number; p1: number | null; i2: number; p2: number | null; t1: ISODate; t2: ISODate; ago1: number; ago2: number
}
export interface LvChartPattern {
  key: string; name: string; bias: 'bullish' | 'bearish' | 'neutral'; status: 'forming' | 'confirmed'
  direction: 'up' | 'down' | null; confirmed_bars_ago: number | null; confirmed_on: ISODate | null
  what: string; start: ISODate; end: ISODate
  breakout: number | null; invalidation: number | null; target: number | null; target_pct: number | null
  series: (number | null)[]; points: LvPatternPoint[]; lines: LvPatternLine[]
  evidence: LvEvidence | null
}
export interface LvLevel { price: number | null; touches: number; last: ISODate; dist_pct: number | null }
export interface LvDaily {
  date: ISODate; close: number | null; atr: number | null; atr_pct: number | null
  day: { open: number | null; high: number | null; low: number | null; close: number | null; prev_close: number | null; prev_high: number | null; prev_low: number | null }
  pivots: { p: number | null; bc: number | null; tc: number | null; r1: number | null; r2: number | null; r3: number | null; s1: number | null; s2: number | null; s3: number | null }
  cpr_width_pct: number | null; high_52w: number | null; low_52w: number | null; from_high_52w_pct: number | null
  levels: { resistance: LvLevel[]; support: LvLevel[] }
  trend: {
    above_sma20: boolean | null; above_sma50: boolean | null; above_sma200: boolean | null
    sma20: number | null; sma50: number | null; sma200: number | null
    structure: 'up' | 'down' | 'mixed'; supertrend: number | null; supertrend_dir: 'up' | 'down' | null
  }
  patterns: LvPattern[]
  chart_patterns: LvChartPattern[]
}
export interface LvIntraday {
  date: ISODate; bars: number; last_bar: ISODateTime; last: number | null; open: number | null; high: number | null; low: number | null
  vwap: number | null; vwap_upper: number | null; vwap_lower: number | null; above_vwap: boolean | null
  or_high: number | null; or_low: number | null; or_state: 'above' | 'below' | 'inside' | null
  profile: { poc: number | null; vah: number | null; val: number | null } | null
  patterns: LvPattern[]
}
export interface LevelsResponse { symbol: string; daily: LvDaily | null; intraday: LvIntraday | null; intraday_source: string | null; note: string }

/** The pattern study's table (changes only when python -m scanner.pattern_study runs again). */
export const usePatternEvidence = (enabled: boolean) =>
  useQuery({
    queryKey: ['levels', 'evidence'],
    queryFn: () => fetchJson<PatternEvidenceResponse>('/api/levels/evidence'),
    staleTime: 3_600_000,
    enabled,
  })

/** Refetches every minute so today's VWAP and opening range follow the live feed. */
export const useLevels = (symbol: string) =>
  useQuery({
    queryKey: ['levels', symbol],
    queryFn: () => fetchJson<LevelsResponse>(`/api/levels/${encodeURIComponent(symbol)}`),
    enabled: !!symbol,
    refetchInterval: 60_000,
  })
