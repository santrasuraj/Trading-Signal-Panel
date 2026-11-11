// Market replay (web/api/routers/replay.py): past sessions bar by bar, and your practice record.

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { fetchJson } from './client'
import type { Bars, ExitReason, Side } from '@/lib/replay'

export type ReplayTf = '5m' | '15m' | '1d'
export interface ReplayData {
  symbol: string; tf: ReplayTf; date: string; start: number; bars: Bars; vwap: (number | null)[] | null; context: string[]
  square_off: number | null; costs: { product: 'CNC' | 'INTRADAY'; slippage_pct: number; charges_pct: number }
  qty: number; capital: number; note: string
}
export interface ReplayInfo { intraday_symbols: string[]; symbol?: string; sessions?: string[]; daily_first?: string; daily_last?: string }
export interface SavedTrade {
  side: Side; qty: number; entry_i: number; exit_i: number; entry_t: number; exit_t: number; entry: number; exit: number
  stop: number | null; target: number | null; reason: ExitReason; bars_held: number; gross: number; charges: number; net: number
  ret_pct: number | null; r: number | null
}
export interface SavedSession {
  id: string; at: string; symbol: string; tf: ReplayTf; date: string; blind: boolean; bars_seen: number; trades: SavedTrade[]
  net: number; capital: number; ret_pct: number | null; buy_hold_pct: number | null
}
export interface ReplayStats {
  trades: number; wins: number; win_rate: number | null; avg_win: number | null; avg_loss: number | null; profit_factor: number | null
  net: number; expectancy: number | null; expectancy_r: number | null; with_stop_pct: number | null; avg_bars_held: number | null
  exits: Record<string, number>
}
export interface ReplayHistory {
  sessions: number; overall: ReplayStats; by_tf: Record<ReplayTf, ReplayStats>
  recent: (Omit<SavedSession, 'trades' | 'capital'> & { trades: number })[]; note: string
}

export const useReplayInfo = (symbol?: string) =>
  useQuery({
    queryKey: ['replay', 'info', symbol ?? ''],
    queryFn: () => fetchJson<ReplayInfo>(`/api/replay/info${symbol ? `?symbol=${encodeURIComponent(symbol)}` : ''}`),
    staleTime: 10 * 60_000,
  })

export const useReplayBars = (p: { symbol: string; tf: ReplayTf; date: string } | null) =>
  useQuery({
    queryKey: ['replay', 'bars', p?.symbol, p?.tf, p?.date],
    queryFn: () => fetchJson<ReplayData>(`/api/replay/bars/${encodeURIComponent(p!.symbol)}?tf=${p!.tf}&date=${p!.date}`),
    enabled: !!p, staleTime: Infinity, retry: false,
  })

export const randomPick = (tf: ReplayTf) => fetchJson<{ symbol: string; date: string; tf: ReplayTf }>(`/api/replay/random?tf=${tf}`)

export const useReplayHistory = () =>
  useQuery({ queryKey: ['replay', 'results'], queryFn: () => fetchJson<ReplayHistory>('/api/replay/results'), staleTime: 30_000 })

export function useSaveReplay() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: { symbol: string; tf: ReplayTf; date: string; blind: boolean; last_i: number; trades: unknown[] }) =>
      fetchJson<SavedSession>('/api/replay/results', { method: 'POST', body: JSON.stringify(body) }),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ['replay', 'results'] }); void qc.invalidateQueries({ queryKey: ['coach'] }) },
  })
}
