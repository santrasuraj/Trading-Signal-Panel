// Watchlists, price alerts, many action cards at once, and intraday candles (web/api/routers/watch.py, lookup.py).

import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { fetchJson } from './client'
import type { ActionCardData } from './action'
import type { UserDrawing } from '@/lib/userDrawings'

export interface Watchlist { name: string; symbols: string[] }
export type AlertKind = 'above' | 'below' | 'change_above' | 'change_below' | 'line_above' | 'line_below' | 'rsi_above' | 'rsi_below' | 'sma_above' | 'sma_below' | 'scan_hit' | 'pattern'
export interface PriceAlert {
  id: string; symbol: string; kind: AlertKind; value: number; note: string; created: string; active: boolean
  fired_at: string | null; fired_price: number | null; source: string | null
  a?: { t: string; v: number } | null; b?: { t: string; v: number } | null; ref?: string | null; detail?: string | null
}
export interface FiredAlert extends PriceAlert { text: string }

export const ALERT_KIND_LABEL: Record<AlertKind, string> = {
  above: 'Price at or above', below: 'Price at or below', change_above: 'Day change % at or above', change_below: 'Day change % at or below',
  line_above: 'Price above trendline', line_below: 'Price below trendline',
  rsi_above: 'RSI(14) at or above', rsi_below: 'RSI(14) at or below',
  sma_above: 'Price above its N-day average', sma_below: 'Price below its N-day average',
  scan_hit: 'Saved scan gets a new stock', pattern: 'Candle pattern with a tested edge',
}
/** Kinds the alert form offers (trendline alerts are set from a drawn line on the chart). */
export const FORM_KINDS: AlertKind[] = ['above', 'below', 'change_above', 'change_below', 'rsi_above', 'rsi_below', 'sma_above', 'sma_below', 'pattern', 'scan_hit']
/** The alert's value as text: "1,234.50", "+2.00%", "RSI 70", "200-day", or "" when it has none. */
export function alertValueText(a: Pick<PriceAlert, 'kind' | 'value'>): string {
  const n = (x: number, dp = 2) => x.toLocaleString('en-IN', { minimumFractionDigits: dp, maximumFractionDigits: dp })
  if (a.kind.startsWith('change')) return `${a.value >= 0 ? '+' : ''}${n(a.value)}%`
  if (a.kind.startsWith('rsi')) return `${a.value}`
  if (a.kind.startsWith('sma')) return `${a.value}-day`
  if (a.kind === 'scan_hit' || a.kind === 'pattern') return ''
  return n(a.value)
}

export const useWatchlists = () =>
  useQuery({ queryKey: ['watchlists'], queryFn: () => fetchJson<{ lists: Watchlist[] }>('/api/watchlists'), staleTime: 30_000 })

export function useSaveWatchlists() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (lists: Watchlist[]) => fetchJson<{ lists: Watchlist[] }>('/api/watchlists', { method: 'PUT', body: JSON.stringify({ lists }) }),
    onSuccess: (r) => { qc.setQueryData(['watchlists'], r) },
  })
}

export const useAlerts = () =>
  useQuery({ queryKey: ['alerts'], queryFn: () => fetchJson<{ alerts: PriceAlert[]; fired: FiredAlert[]; note: string }>('/api/alerts'), staleTime: 10_000 })

export function useAlertMutations() {
  const qc = useQueryClient()
  const done = () => { void qc.invalidateQueries({ queryKey: ['alerts'] }) }
  return {
    create: useMutation({
      mutationFn: (a: { symbol: string; kind: AlertKind; value?: number; note?: string; a?: { t: string; v: number }; b?: { t: string; v: number }; ref?: string }) =>
        fetchJson<PriceAlert>('/api/alerts', { method: 'POST', body: JSON.stringify({ note: '', ...a }) }),
      onSuccess: done,
    }),
    setActive: useMutation({
      mutationFn: (v: { id: string; active: boolean }) =>
        fetchJson<PriceAlert>(`/api/alerts/${v.id}`, { method: 'PATCH', body: JSON.stringify({ active: v.active }) }),
      onSuccess: done,
    }),
    remove: useMutation({
      mutationFn: (id: string) => fetchJson<{ deleted: boolean }>(`/api/alerts/${id}`, { method: 'DELETE' }),
      onSuccess: done,
    }),
  }
}

/** One tested answer per symbol (scan-derived: refreshed by the ScanWatcher). */
export const useActions = (symbols: string[]) => {
  const key = [...new Set(symbols)].sort().slice(0, 100).join(',')
  return useQuery({
    queryKey: ['actions', key], enabled: !!key, staleTime: Infinity, placeholderData: keepPreviousData,
    queryFn: () => fetchJson<{ cards: ActionCardData[] }>(`/api/actions?symbols=${encodeURIComponent(key)}`),
  })
}

export type IntradayTf = '1m' | '5m' | '15m'
export interface IntradayChartData {
  symbol: string; tf: IntradayTf; days: number; sessions: string[]
  bars: { t: number[]; o: number[]; h: number[]; l: number[]; c: number[]; v: number[] }
  vwap: (number | null)[]; forming: boolean; sources: string[]; note: string
}

/** Intraday candles: refreshed every minute while the page is open (the live price moves the last one in between). */
export const useIntradayChart = (symbol: string, tf: IntradayTf, days: number, enabled = true) =>
  useQuery({
    queryKey: ['intraday-chart', symbol, tf, days], enabled: enabled && !!symbol, retry: false,
    queryFn: () => fetchJson<IntradayChartData>(`/api/chart/${encodeURIComponent(symbol)}/intraday?tf=${tf}&days=${days}`),
    staleTime: 30_000, refetchInterval: 60_000, placeholderData: keepPreviousData,
  })


export const useDrawings = (symbol: string) =>
  useQuery({ queryKey: ['drawings', symbol], enabled: !!symbol, staleTime: Infinity,
    queryFn: () => fetchJson<{ symbol: string; drawings: UserDrawing[] }>(`/api/drawings/${encodeURIComponent(symbol)}`) })

export function useSaveDrawings(symbol: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (drawings: UserDrawing[]) => fetchJson<{ symbol: string; drawings: UserDrawing[] }>(`/api/drawings/${encodeURIComponent(symbol)}`, { method: 'PUT', body: JSON.stringify({ drawings }) }),
    onSuccess: (r) => { qc.setQueryData(['drawings', symbol], r) },
  })
}
