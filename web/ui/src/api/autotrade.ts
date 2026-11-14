// High-speed auto-trader on the practice account (GET /api/autotrade, POST /api/autotrade/settings | /stop | /reset;
// web/api/services/autotrade_svc.py). Nothing is ever sent to FYERS.

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { fetchJson } from '@/api/client'
import type { SignalProof } from '@/api/types'

export interface AutoSettings {
  on: boolean; mode: 'all' | 'proven'; intraday: boolean; oi: boolean; options: boolean; daily: boolean
  max_positions: number; max_trades_per_day: number; daily_loss_pct: number; max_late_min: number
}
interface Timing { slippage_bps: number | null; react_ms: number | null; signal_lag_s: number | null }
export interface AutoPosition extends Timing {
  symbol: string; strategy_key: string; strategy_name: string; strategy_status: SignalProof; proven: boolean
  side: 'LONG' | 'SHORT'; qty: number; fill: number; signal_entry: number; signal_time: string; stop: number | null
  target: number | null; opened_at: string; last: number | null; unrealized: number | null; detail: string | null
}
export interface AutoTrade extends AutoPosition {
  exit: number; exit_reason: string; closed_at: string; pnl_gross: number; charges: number; pnl_net: number
  ret_pct: number | null; quote_age_s: number | null; source: string | null
}
export interface AutoSummary extends Timing {
  trades: number; wins: number; win_rate: number | null; pnl_net: number; charges: number; quote_age_s: number | null
}
export interface AutoRecordRow extends AutoSummary { strategy_key: string; strategy_name: string; strategy_status: SignalProof | null }
export interface AutoOption {
  id: string; symbol: string; expiry: string; side: 'ce' | 'pe'; strike: number; lot: number; premium: number
  cost_unit: number; verdict_day: string; opened_at: string; mark?: number; value_net?: number; settle?: number
  pnl_net?: number; closed_at?: string
}
export interface AutoLog { at: string; kind: string; text: string; symbol?: string; strategy?: string }
export interface AutoView {
  settings: AutoSettings; running: boolean; session: string; feed: 'live' | 'fyers' | 'yahoo' | null
  last_loop: string | null; signals_at: string | null; capital: number; cash: number; equity: number; today_pnl: number
  positions: AutoPosition[]; trades_today: AutoTrade[]; skipped_today: { key: string; why: string }[]
  today: AutoSummary; all_time: AutoSummary; record: AutoRecordRow[]
  options: { open: AutoOption[]; closed: AutoOption[] }
  daily: { on: boolean; strategies: { key: string; name: string; on: boolean; status: string }[]; last_run: unknown }
  log: AutoLog[]; note: string
}

const KEY = ['autotrade'] as const

export const useAutoTrade = () =>
  useQuery({ queryKey: KEY, queryFn: () => fetchJson<AutoView>('/api/autotrade'), refetchInterval: (q) => (q.state.data?.session === 'open' ? 2_000 : 30_000) })

export function useAutoTradeActions() {
  const qc = useQueryClient()
  const set = (v: AutoView) => qc.setQueryData(KEY, v)
  return {
    save: useMutation({ mutationFn: (s: Partial<AutoSettings>) => fetchJson<AutoView>('/api/autotrade/settings', { method: 'POST', body: JSON.stringify(s) }), onSuccess: set }),
    stop: useMutation({ mutationFn: () => fetchJson<AutoView>('/api/autotrade/stop', { method: 'POST' }), onSuccess: set }),
    reset: useMutation({ mutationFn: () => fetchJson<AutoView>('/api/autotrade/reset', { method: 'POST' }), onSuccess: set }),
  }
}
