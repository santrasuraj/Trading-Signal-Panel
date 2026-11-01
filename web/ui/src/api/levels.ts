// Price action API (web/api/routers/levels.py): types mirroring web/api/models/levels.py and the query hook.

import { useQuery } from '@tanstack/react-query'
import { fetchJson } from './client'
import type { ISODate, ISODateTime } from './types'

export interface LvPattern { key: string; name: string; bias: 'bullish' | 'bearish' | 'neutral'; what: string; bars_ago: number; at: ISODateTime }
export interface LvChartPattern {
  key: string; name: string; bias: 'bullish' | 'bearish' | 'neutral'; status: 'forming' | 'confirmed'
  direction: 'up' | 'down' | null; confirmed_bars_ago: number | null; what: string; start: ISODate; end: ISODate
  breakout: number | null; invalidation: number | null; target: number | null; target_pct: number | null
  series: (number | null)[]; points: { i: number; price: number | null; label: string }[]
  lines: { i1: number; p1: number | null; i2: number; p2: number | null }[]
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

/** Refetches every minute so today's VWAP and opening range follow the live feed. */
export const useLevels = (symbol: string) =>
  useQuery({
    queryKey: ['levels', symbol],
    queryFn: () => fetchJson<LevelsResponse>(`/api/levels/${encodeURIComponent(symbol)}`),
    enabled: !!symbol,
    refetchInterval: 60_000,
  })
