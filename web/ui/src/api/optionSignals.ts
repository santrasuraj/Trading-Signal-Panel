// Options signals (GET /api/options/signals, POST /api/options/signals/refresh, GET /api/options/vol-test;
// scanner/option_signals.py): intraday and stock signals as option trades, volatility (IV rank) trades and the index
// verdicts, each with its contract, premiums, lot, capital, maximum loss and record. Practice only.

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { fetchJson } from '@/api/client'
import type { SignalProof } from '@/api/types'

export type OptSource = 'intraday' | 'stock' | 'volatility' | 'index'
export interface OptLeg { action: 'buy' | 'sell'; type: 'CE' | 'PE'; strike: number; expiry: string; premium: number | null; iv: number | null; delta: number | null }
export interface OptSignal {
  id: string; source: Exclude<OptSource, 'index'>; symbol: string; direction: 'LONG' | 'SHORT' | 'NEUTRAL'; kind: 'debit' | 'credit'
  structure: string; legs: OptLeg[]; expiry: string; lot: number; entry: number; stop: number | null; target: number | null
  capital: number | null; max_loss: number | null; max_gain: number | null; charges_in: number | null; breakevens?: (number | null)[]
  underlying: { price: number | null; stop: number | null; target: number | null }
  strategy: { key: string | null; name: string | null; status: SignalProof | string | null; proven: boolean; entry_time?: string }
  iv_rank?: { rank: number; percentile: number; iv: number }
  day: string; opened_at: string; chain_time: string; state: 'open' | 'closed'; mark: number | null; marked_at: string | null
  unrealized?: number | null; exit?: number | null; exit_reason?: string; exit_src?: string; closed_at?: string
  pnl?: number | null; ret_pct?: number | null; charges?: number | null
}
/** Where closed bought options' P&L came from (rupees, they add up to it): the stock's move, time decay, volatility, the spread and charges. */
export interface OptPnlParts { move: number; decay: number; vol: number; spread: number; charges: number }
/** A strategy's closed options of the last few weeks; `paused` = clearly losing, no new option until it recovers. */
export interface OptLiveRecord { trades: number; pnl: number; t: number | null; since: string; paused: boolean }
export interface OptStrategyRecord { key: string; name: string; status: string | null; trades: number; wins: number; pnl: number; open: number
  parts?: OptPnlParts | null; parts_n?: number; live?: OptLiveRecord | null }
export interface OptRecord { source: OptSource; label: string; trades: number; win_rate: number | null; avg_ret_pct: number | null; pnl: number; open: number; verdict: string
  /** Each strategy's own live record inside the source (an untested strategy's only test). */
  by_strategy?: OptStrategyRecord[] }
export interface OptVerdictRow { symbol: string; expiry: string; verdict: string; side: string | null; strike: number | null; premium: number | null; breakeven: number | null; headline?: string | null; bias?: string | null; lot?: number | null; spot?: number | null }
export interface OptSignalsView {
  signals: OptSignal[]; record: OptRecord[]; market_open: boolean; note: string
  verdicts: { day: string | null; rows: OptVerdictRow[]; track: Record<string, unknown> | null }
  loop: { last_run: string | null; last_error: string | null; runs?: number; last_trigger?: string | null }
  /** Signals not opened as options on `skipped_day`, by reason (a lost strategy, a repeat, ...). */
  skipped?: Record<string, { label: string; count: number; examples: string[] }>; skipped_day?: string; cancelled?: number
  /** Which strategies may open an option (config.yaml option_signals.evidence). */
  evidence?: { rule: 'not_lost' | 'proven' | 'all'; allowed: string[] | null }
  rules: { delta_near: number; delta_month: number; iv_high: number; iv_low: number; vol_target_pct: number; vol_stop_pct: number
    live_days?: number; live_min_trades?: number; live_t?: number; no_new_intraday?: string }
}
export interface VolStats { trades: number; win_rate?: number; total?: number; avg?: number; max_drawdown?: number; profit_factor?: number | null; worst?: number; first?: string; last?: string }
export interface VolTest { tests: { symbol: string; error?: string; days_with_rank?: number; high_days?: number; always?: VolStats; when_high?: VolStats; first?: string | null; last?: string | null }[]; note: string }

const KEY = ['option-signals'] as const

export const useOptionSignals = () =>
  useQuery({ queryKey: KEY, queryFn: () => fetchJson<OptSignalsView>('/api/options/signals'), staleTime: 30_000,
             refetchInterval: (q) => (q.state.data?.market_open ? 60_000 : false) })

export const useVolTest = (enabled: boolean) =>
  useQuery({ queryKey: ['option-vol-test'], queryFn: () => fetchJson<VolTest>('/api/options/vol-test'), staleTime: 30 * 60_000, enabled })

export function useRefreshOptionSignals() {
  const qc = useQueryClient()
  return useMutation({ mutationFn: () => fetchJson<OptSignalsView>('/api/options/signals/refresh', { method: 'POST', body: '{}' }),
                       onSuccess: (v) => qc.setQueryData(KEY, v) })
}
