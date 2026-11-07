// Claude's option-chain forecasts (web/api/routers/ai.py, models/ai.py): types mirroring the pydantic models and the
// query / mutation hooks. GET is files only; POST costs money on the user's Anthropic account (roughly Rs 8-13).

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { fetchJson } from './client'
import type { ISODate, ISODateTime } from './types'

export type FcKind = 'evening' | 'on_demand'
export type FcStatus = 'pending' | 'ok' | 'refused' | 'error'
export type FcTrackStatus = 'unproven' | 'beats_coin_flip' | 'no_edge'
export type FcHorizon = 'next_close' | 'expiry'

export interface FcHorizonForecast { p_up: number; low: number; high: number }
export interface FcRange { low: number; high: number }
export interface FcBody {
  view: 'up' | 'down' | 'sideways' | 'no_view'; confidence: 'low' | 'medium' | 'high'; summary: string
  next_close: FcHorizonForecast; expiry: FcHorizonForecast; invalidation: number | null
  key_levels: { price: number; kind: 'support' | 'resistance' | 'pivot'; why: string }[]
  reasons: { text: string; evidence: string[]; tested: boolean }[]
}
export interface FcOutcome {
  date: ISODate; close: number; move_pct: number; up: boolean; call: 'up' | 'down' | null; hit: boolean | null; brier: number
  in_range: boolean; width_pct: number; base_in_range: boolean | null; base_width_pct: number | null
}
export interface Forecast {
  id: string; kind: FcKind; symbol: string; settle: 'index' | 'store'; created_at: ISODateTime; answered_at: ISODateTime | null
  chain_time: ISODateTime; expiry: ISODate; spot: number; model: string; effort: string; status: FcStatus; error: string | null
  forecast: FcBody | null; baseline: { next_close: FcRange | null; expiry: FcRange | null }; snapshot_sha256: string
  usage: { input_tokens: number | null; output_tokens: number | null; cache_read_tokens: number | null } | null
  batch_id: string | null; outcome: { next_close: FcOutcome | null; expiry: FcOutcome | null } | null; cached: boolean
}
export interface FcHorizonTrack {
  settled: number; calls: number; hits: number; hit_pct: number | null; p_value: number | null; brier: number | null; coin_brier: number
  always_up_hit_pct: number | null; range_hit_pct: number | null; range_width_pct: number | null
  base_range_hit_pct: number | null; base_width_pct: number | null; status: FcTrackStatus; why: string
}
export interface FcTrack {
  kind: FcKind; forecasts: number; ok: number; pending: number; refused: number; errors: number
  horizons: Record<FcHorizon, FcHorizonTrack>
}
export interface ForecastReport {
  configured: boolean; model: string; effort: string; underlyings: string[]; symbol: string | null; proven_min: number; p_max: number
  track: FcTrack[]; latest: Forecast[]; rows: Forecast[]; pending_batches: { id: string; submitted_at: ISODateTime; symbols: string[] }[]
  note: string
}

export const forecastKeys = { report: (symbol: string) => ['ai', 'forecasts', symbol] as const }

/** The journal for one underlying, scored (refetched every 5 minutes: the evening batch lands in the background). */
export const useForecasts = (symbol: string) =>
  useQuery({
    queryKey: forecastKeys.report(symbol),
    queryFn: () => fetchJson<ForecastReport>(`/api/ai/forecasts?symbol=${encodeURIComponent(symbol)}`),
    enabled: !!symbol,
    refetchInterval: 300_000,
  })

/** One forecast now. Never retried (each call costs money); the journal reloads after it. */
export function useForecastNow(symbol: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => fetchJson<Forecast>('/api/ai/forecast', { method: 'POST', body: JSON.stringify({ symbol }) }),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: forecastKeys.report(symbol) }) },
  })
}
