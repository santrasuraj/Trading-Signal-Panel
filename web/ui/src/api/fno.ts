// F&O positioning API (web/api/routers/fno.py): types mirroring web/api/models/fno.py, fetchers and hooks. The data
// changes once a day (after NSE's evening files); /status polls every 3 s only while a refresh runs.

import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { fetchJson } from './client'
import type { ISODate, ISODateTime } from './types'

export type FnoClient = 'fii' | 'dii' | 'pro' | 'client'
export type FnoBuildup = 'long_buildup' | 'short_buildup' | 'short_covering' | 'long_unwinding'
type Col = (number | null)[]

export interface FnoClientSeries {
  fut_long: Col; fut_short: Col; fut_net: Col; fut_net_chg: Col; fut_long_pct: Col; call_net: Col; put_net: Col; stk_fut_net: Col
}
export interface FnoPositionsResponse { dates: ISODate[]; clients: Record<FnoClient, FnoClientSeries>; note: string }
export interface FnoFuture {
  symbol: string; kind: 'index' | 'stock'; close: number | null; chg_pct: number | null; oi_contracts: number | null
  oi_chg_contracts: number | null; oi_chg_pct: number | null; volume: number | null; value_cr: number | null; lot: number | null
  basis_pct: number | null; buildup: FnoBuildup | null; pcr: number | null; call_wall: number | null; put_wall: number | null
}
export interface FnoFuturesResponse { date: ISODate | null; dates: ISODate[]; counts: Record<string, number>; rows: FnoFuture[]; note: string }
export interface FnoRefreshRun {
  state: 'idle' | 'running' | 'done' | 'failed'; running: boolean; message: string | null
  started_at: ISODateTime | null; finished_at: ISODateTime | null; errors: string[]
}
export interface FnoStatus {
  run: FnoRefreshRun; days: number; first_day: ISODate | null; last_day: ISODate | null
  last_refresh_at: ISODateTime | null; pending: string[]; errors: string[]
}
export interface FnoFuturesParams {
  date?: string; kind?: 'all' | 'stock' | 'index'; buildup?: 'all' | FnoBuildup; sort?: 'oi_chg' | 'chg' | 'value' | 'pcr'
}

const qs = (p: object) => {
  const s = new URLSearchParams()
  for (const [k, v] of Object.entries(p)) if (v !== undefined && v !== '' && v !== 'all') s.set(k, String(v))
  const str = s.toString()
  return str ? `?${str}` : ''
}

export const fnoApi = {
  status: () => fetchJson<FnoStatus>('/api/fno/status'),
  positions: (days: number) => fetchJson<FnoPositionsResponse>(`/api/fno/positions?days=${days}`),
  futures: (p: FnoFuturesParams) => fetchJson<FnoFuturesResponse>(`/api/fno/futures${qs(p)}`),
  refresh: () => fetchJson<{ accepted: boolean; run: FnoRefreshRun }>('/api/fno/refresh', { method: 'POST' }),
}

export const fnoKeys = {
  all: ['fno'] as const,
  status: ['fno', 'status'] as const,
  positions: (d: number) => ['fno', 'positions', d] as const,
  futures: (p: FnoFuturesParams) => ['fno', 'futures', p] as const,
}

export const useFnoStatus = () =>
  useQuery({ queryKey: fnoKeys.status, queryFn: fnoApi.status, refetchInterval: (q) => (q.state.data?.run.running ? 3000 : 60_000) })
export const useFnoPositions = (days: number) =>
  useQuery({ queryKey: fnoKeys.positions(days), queryFn: () => fnoApi.positions(days), placeholderData: keepPreviousData })
export const useFnoFutures = (p: FnoFuturesParams) =>
  useQuery({ queryKey: fnoKeys.futures(p), queryFn: () => fnoApi.futures(p), placeholderData: keepPreviousData })

// ------------------------------------------------------------------ live (during the session)
export interface FnoLiveRow {
  symbol: string; kind: 'index' | 'stock'; price: number | null; prev_close: number | null; chg_pct: number | null
  price_source: 'fyers' | 'yahoo' | 'nse_rounded' | 'close' | null; oi: number | null; prev_oi: number | null
  oi_chg: number | null; oi_chg_pct: number | null; volume: number | null; buildup: FnoBuildup | null; eod_buildup: FnoBuildup | null
}
export interface FnoLiveResponse {
  nse_time: ISODateTime | null; trade_date: ISODate | null; prev_date: ISODate | null; eod_date: ISODate | null
  fetched_at: ISODateTime | null; price_source: string | null; session: string; running: boolean; error: string | null
  counts: Record<string, number>; rows: FnoLiveRow[]; note: string
}
export interface FnoLiveParams { kind?: 'all' | 'stock' | 'index'; buildup?: 'all' | FnoBuildup; sort?: 'oi_chg' | 'chg' | 'oi' | 'volume' }

export const fnoLiveApi = {
  live: (p: FnoLiveParams) => fetchJson<FnoLiveResponse>(`/api/fno/live${qs(p)}`),
  refresh: () => fetchJson<{ accepted: boolean; running: boolean; message: string }>('/api/fno/live/refresh', { method: 'POST' }),
}

/** The stored live snapshot: every 3 s while a fetch runs, every 30 s while the market is open. */
export const useFnoLive = (p: FnoLiveParams, open: boolean) =>
  useQuery({
    queryKey: ['fno', 'live', p], queryFn: () => fnoLiveApi.live(p), placeholderData: keepPreviousData,
    refetchInterval: (q) => (q.state.data?.running ? 3000 : open ? 30_000 : false),
  })

export function useFnoLiveRefresh() {
  const qc = useQueryClient()
  return useMutation({ mutationFn: fnoLiveApi.refresh, onSuccess: () => void qc.invalidateQueries({ queryKey: ['fno', 'live'] }) })
}

export function useFnoRefresh() {
  const qc = useQueryClient()
  return useMutation({ mutationFn: fnoApi.refresh, onSuccess: () => void qc.invalidateQueries({ queryKey: fnoKeys.status }) })
}
