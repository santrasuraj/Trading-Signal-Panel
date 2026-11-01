// Option chains API (web/api/routers/options.py): types mirroring web/api/models/options.py, fetchers and TanStack
// Query hooks. Chains change only when the scheduled job or a refresh stores a new one: while the market is open the
// chain polls every minute; /status polls every 3 s only while a refresh runs.

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { fetchJson } from './client'
import type { ISODate, ISODateTime } from './types'

// ------------------------------------------------------------------ types (mirror web/api/models/options.py)
export type OptBuildup = 'long_buildup' | 'short_buildup' | 'short_covering' | 'long_unwinding'
export type OptRunState = 'idle' | 'running' | 'done' | 'failed'

export interface OptLeg {
  ltp: number | null; chg: number | null; oi: number | null; oi_chg: number | null; oi_chg_pct: number | null
  oi_chg_window: number | null; volume: number | null; iv_pct: number | null; iv_nse_pct: number | null
  bid: number | null; ask: number | null; buy_qty: number | null; sell_qty: number | null
  delta: number | null; gamma: number | null; theta: number | null; vega: number | null; buildup: OptBuildup | null
}
export interface OptRow { strike: number; atm: boolean; ce: OptLeg; pe: OptLeg }
export interface OptLevel { strike: number; oi: number | null; oi_chg: number | null }
export interface OptLevels { resistance: OptLevel[]; support: OptLevel[]; call_adds: OptLevel[]; put_adds: OptLevel[] }
export interface OptSummary {
  pcr_oi: number | null; pcr_volume: number | null; max_pain: number | null; max_pain_gap_pct: number | null
  atm_iv_pct: number | null; straddle: number | null; expected_move_pct: number | null; one_sd_pts: number | null
  range_low: number | null; range_high: number | null; skew_25d: number | null
  ce_oi: number | null; ce_oi_chg: number | null; ce_volume: number | null
  pe_oi: number | null; pe_oi_chg: number | null; pe_volume: number | null
}
export interface OptUnusual {
  strike: number; side: 'ce' | 'pe'; ltp: number | null; volume: number | null; oi: number | null; vol_oi: number | null
  oi_chg_window: number | null; oi_chg_window_pct: number | null; value_cr: number | null; why: string[]
}
export interface OptChainResponse {
  symbol: string; expiry: ISODate; expiries: ISODate[]; time: ISODateTime; source: string; stale: boolean
  spot: number | null; forward: number | null; atm: number | null; days_to_expiry: number | null
  summary: OptSummary; levels: OptLevels; readings: string[]; window_minutes: number
  window_since: ISODateTime | null; lot: number | null; unusual: OptUnusual[]; rows: OptRow[]; note: string
}
export interface OptClaim { n: number; verdict: string }
export interface OptStudy {
  symbol: string; days: number; first_day: ISODate | null
  max_pain: OptClaim & { hit_pct: number | null; fair_pct: number }
  expected_move: OptClaim & { inside_pct: number | null; fair_pct: number }
  pcr: OptClaim & { corr: number | null; top_minus_bottom_pct: number | null }
}
export interface OptResearchResponse { min_days: number; studies: OptStudy[]; note: string }
export interface OptHistoryResponse {
  symbol: string; expiry: ISODate; day: ISODate; t: ISODateTime[]; spot: (number | null)[]; max_pain: (number | null)[]
  pcr_oi: (number | null)[]; atm_iv_pct: (number | null)[]; straddle: (number | null)[]
  support: (number | null)[]; resistance: (number | null)[]
}
export interface OptChainRef { symbol: string; expiry: ISODate; day: ISODate; time: ISODateTime; spot: number | null }
export interface OptRefreshRun {
  state: OptRunState; running: boolean; message: string | null; started_at: ISODateTime | null
  finished_at: ISODateTime | null; errors: string[]
}
export interface OptLastRefresh { started_at: ISODateTime | null; chains: number; refused: boolean; errors: string[] }
export interface OptStatus {
  run: OptRefreshRun; live_running: boolean; market_open: boolean; interval_seconds: number; underlyings: string[]
  chains: OptChainRef[]; last_refresh: OptLastRefresh | null; note: string
}
export interface OptRefreshAccepted { accepted: boolean; run: OptRefreshRun }

// ------------------------------------------------------------------ fetchers + hooks
const q = (p: Record<string, string | number | undefined>) => {
  const s = new URLSearchParams()
  for (const [k, v] of Object.entries(p)) if (v !== undefined && v !== '') s.set(k, String(v))
  const str = s.toString()
  return str ? `?${str}` : ''
}

export const optApi = {
  status: () => fetchJson<OptStatus>('/api/options/status'),
  chain: (symbol: string, expiry: string | undefined, window: number) =>
    fetchJson<OptChainResponse>(`/api/options/chain/${encodeURIComponent(symbol)}${q({ expiry, window })}`),
  history: (symbol: string, expiry: string | undefined) =>
    fetchJson<OptHistoryResponse>(`/api/options/history/${encodeURIComponent(symbol)}${q({ expiry })}`),
  research: () => fetchJson<OptResearchResponse>('/api/options/research'),
  refresh: (symbols?: string[]) =>
    fetchJson<OptRefreshAccepted>('/api/options/refresh', { method: 'POST', body: JSON.stringify(symbols ? { symbols } : {}) }),
}

export const optKeys = {
  all: ['options'] as const,
  status: ['options', 'status'] as const,
  chain: (s: string, e: string | undefined, w: number) => ['options', 'chain', s, e ?? 'nearest', w] as const,
  history: (s: string, e: string | undefined) => ['options', 'history', s, e ?? 'nearest'] as const,
  research: ['options', 'research'] as const,
}

export const useOptStatus = () =>
  useQuery({
    queryKey: optKeys.status,
    queryFn: optApi.status,
    refetchInterval: (query) => (query.state.data?.run.running ? 3000 : 30_000),
  })

/** Keep showing the previous chain while another expiry or window loads - never another symbol's numbers. */
const sameSymbol = (symbol: string) => <T extends { symbol: string }>(prev: T | undefined) =>
  prev && prev.symbol === symbol.toUpperCase() ? prev : undefined

/** Polls every minute while the market is open (the scheduled job stores a new chain about that often). */
export const useOptChain = (symbol: string, expiry: string | undefined, window: number, live: boolean) =>
  useQuery({
    queryKey: optKeys.chain(symbol, expiry, window),
    queryFn: () => optApi.chain(symbol, expiry, window),
    enabled: !!symbol,
    placeholderData: sameSymbol(symbol),
    refetchInterval: live ? 60_000 : false,
  })

export const useOptHistory = (symbol: string, expiry: string | undefined, live: boolean) =>
  useQuery({
    queryKey: optKeys.history(symbol, expiry),
    queryFn: () => optApi.history(symbol, expiry),
    enabled: !!symbol,
    placeholderData: sameSymbol(symbol),
    refetchInterval: live ? 60_000 : false,
  })

export const useOptResearch = () => useQuery({ queryKey: optKeys.research, queryFn: optApi.research, staleTime: 300_000 })

export function useOptRefresh() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (symbols?: string[]) => optApi.refresh(symbols),
    onSuccess: () => void qc.invalidateQueries({ queryKey: optKeys.status }),
  })
}

export const BUILDUP_LABEL: Record<OptBuildup, string> = {
  long_buildup: 'Long build-up',
  short_buildup: 'Short build-up',
  short_covering: 'Short covering',
  long_unwinding: 'Long unwinding',
}
export const BUILDUP_HELP: Record<OptBuildup, string> = {
  long_buildup: 'Price up and open interest up since yesterday: new buyers of this option.',
  short_buildup: 'Price down and open interest up: new writers (sellers) of this option.',
  short_covering: 'Price up and open interest down: writers closing their positions.',
  long_unwinding: 'Price down and open interest down: buyers closing their positions.',
}
