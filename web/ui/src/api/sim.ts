// Practice account on live prices and market depth (web/api/routers/sim.py).

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { fetchJson } from './client'

export interface SimPosition { symbol: string; qty: number; avg: number; product: 'CNC' | 'INTRADAY'; stop: number | null; target: number | null; price: number | null; source: string | null; value: number; pnl: number | null; opened?: string }
export interface SimOrder { id: string; symbol: string; side: 'BUY' | 'SELL'; qty: number; type: 'MARKET' | 'LIMIT'; product: string; limit_price: number | null; status: 'open' | 'filled' | 'cancelled'; created: string; fill_price?: number; filled_at?: string; charges?: number; note?: string; auto?: string }
export interface SimTrade { symbol: string; side: 'LONG' | 'SHORT'; qty: number; entry: number; exit: number; pnl: number; charges: number; reason: string; opened?: string; closed: string; product: string }
export interface SimAccount {
  cash: number; start_cash: number; equity: number; pnl: number; charges: number; positions: SimPosition[]; orders: SimOrder[]; trades: SimTrade[]
  stats: { trades: number; wins: number; win_rate: number | null; realised: number }; session: string | null; created: string | null; note: string
}
export interface SimTicket { symbol: string; side: 'BUY' | 'SELL'; qty: number; type: 'MARKET' | 'LIMIT'; product: 'CNC' | 'INTRADAY'; limit_price: number | null; stop?: number | null; target?: number | null }
export interface Depth { symbol: string; bids: { price: number; qty: number; orders: number }[]; asks: { price: number; qty: number; orders: number }[]; total_buy: number; total_sell: number; ltp: number | null; at: number }

const post = <T,>(path: string, body: unknown = {}) => fetchJson<T>(path, { method: 'POST', body: JSON.stringify(body) })

export const useSim = (poll = true) => useQuery({ queryKey: ['sim'], queryFn: () => fetchJson<SimAccount>('/api/sim'), staleTime: 2_000, refetchInterval: poll ? 5_000 : false })

export function useSimActions() {
  const qc = useQueryClient()
  const done = () => { void qc.invalidateQueries({ queryKey: ['sim'] }) }
  return {
    order: useMutation({ mutationFn: (t: SimTicket) => post<SimOrder>('/api/sim/order', t), onSuccess: done }),
    cancel: useMutation({ mutationFn: (id: string) => post<SimOrder>(`/api/sim/cancel/${id}`), onSuccess: done }),
    close: useMutation({ mutationFn: (sym: string) => post<SimOrder>(`/api/sim/close/${encodeURIComponent(sym)}`), onSuccess: done }),
    levels: useMutation({ mutationFn: (v: { symbol: string; stop: number | null; target: number | null }) => post(`/api/sim/levels/${encodeURIComponent(v.symbol)}`, { stop: v.stop, target: v.target }), onSuccess: done }),
    reset: useMutation({ mutationFn: (cash: number | null) => post<SimAccount>('/api/sim/reset', { cash }), onSuccess: done }),
  }
}

export const useDepth = (symbol: string, enabled: boolean) =>
  useQuery({ queryKey: ['depth', symbol], queryFn: () => fetchJson<Depth>(`/api/depth/${encodeURIComponent(symbol)}`), enabled: enabled && !!symbol, refetchInterval: 2_000, retry: false, staleTime: 1_000 })
