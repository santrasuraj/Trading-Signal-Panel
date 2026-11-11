// One answer per stock (GET /api/action/{symbol}) and today's actions (GET /api/today): web/api/services/action_svc.py.
// Scan-derived: never stale on a timer; the ScanWatcher refreshes them when a new scan lands.

import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { fetchJson } from './client'
import type { AsOf, Horizon, Side, StrategyStatus } from './types'

export type ActionState = 'BUY' | 'SELL' | 'HOLD' | 'NO_EDGE'

export interface ActionOrder {
  strategy_key: string; strategy_name: string; status: StrategyStatus; horizon: Horizon
  cagr_pct: number | null; after_tax_cagr_pct: number | null; max_dd_pct: number | null; trades: number | null
  timing_low_pct: number | null; timing_high_pct: number | null
  live_level: 'good' | 'bad' | 'unknown'; live_verdict: string
  action: Side; price: number | null; qty: number | null; amount: number | null; stop: number | null
  stop_distance_pct: number | null; risk_amount: number | null; reason: string
  provisional: boolean; below_min_position: boolean; strength_score: number | null; strength_grade: string | null
}

export interface ActionCardData {
  symbol: string; company: string | null; industry: string | null
  state: ActionState; headline: string; provisional: boolean
  primary: ActionOrder | null; others: ActionOrder[]; unproven: ActionOrder[]; exits: ActionOrder[]
  holding: { qty: number | null; buy_price: number | null; price: number | null; pnl_pct: number | null; pnl_amount: number | null
             stop_price: number | null; target_price: number | null; level: string | null; alerts: string[] } | null
  near: string[]
  risks: { kind: 'results' | 'ban' | 'regime' | 'provisional'; text: string }[]
  as_of: AsOf; note: string
}

export interface TodayData {
  as_of: AsOf; actions: ActionCardData[]; holds: ActionCardData[]
  counts: { buy: number; sell: number; hold: number }
  unproven_strategies: string[]; history: { sessions: number; with_actions: number }
  empty_note: string | null; note: string
}

export const useAction = (symbol: string) =>
  useQuery({ queryKey: ['action', symbol], queryFn: () => fetchJson<ActionCardData>(`/api/action/${encodeURIComponent(symbol)}`),
    staleTime: Infinity, placeholderData: keepPreviousData, enabled: !!symbol })

export const useToday = () =>
  useQuery({ queryKey: ['today'], queryFn: () => fetchJson<TodayData>('/api/today'), staleTime: Infinity })
