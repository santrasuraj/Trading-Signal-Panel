// Orders on your own FYERS account (web/api/routers/orders.py). Two steps: preview (sends nothing), then place with
// the preview id. Every mutation carries the X-Quant-Desk header (client.ts), so no other page can trigger one.

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { fetchJson } from './client'

export type OrderSide = 'BUY' | 'SELL'
export type OrderType = 'LIMIT' | 'MARKET' | 'SL-M' | 'SL-L'
export interface Ticket {
  symbol: string; side: OrderSide; qty: number; type: OrderType; product: 'CNC' | 'INTRADAY'
  limit_price: number | null; trigger_price?: number | null; stop?: number | null; target?: number | null
  ref_price?: number | null; strategy_key?: string | null; source?: string
}
export interface OrderCheck { key: string; name: string; ok: boolean; detail: string; blocking: boolean }
export interface Preview {
  preview_id: string | null; ok: boolean; ticket: Ticket; payload: Record<string, unknown>; checks: OrderCheck[]
  last: { price: number; source: string } | null; value: number; risk_if_stopped: number | null; charges: number
  slippage_estimate: number; expires_in_s: number; note: string
}
export interface PlaceResult { ok: boolean; unknown: boolean; order_id: string | null; message: string | null; next: string | null }
export interface OrdersView {
  enabled: boolean; kill: boolean; kill_at: string | null; kill_reason: string | null; today_count: number; logged_in: boolean
  limits: Record<string, number | boolean | string>
  orders: { id: string; symbol: string; side: OrderSide; qty: number; filled: number; type: string; limit_price: number | null
    avg_price: number | null; status: string; pending: boolean; product: string; time: string; message: string | null }[]
  positions: { symbol: string; qty: number; avg: number | null; ltp: number | null; pl: number | null; product: string }[]
  pnl_today: number | null; gtt: { id: string; symbol: string; status: string | number; info: unknown }[]
  errors: string[]; audit: { ts: string; event: string; [k: string]: unknown }[]
  reconciliation: { id: string; symbol: string; side: OrderSide; ref_price: number; fill: number; slippage_pct: number; strategy_key: string | null }[]
  note: string
}

const post = <T,>(path: string, body: unknown) => fetchJson<T>(path, { method: 'POST', body: JSON.stringify(body) })

export const useOrdersView = (poll = true) =>
  useQuery({ queryKey: ['orders'], queryFn: () => fetchJson<OrdersView>('/api/orders'), staleTime: 3_000, refetchInterval: poll ? 5_000 : false, retry: false })

export function useOrderActions() {
  const qc = useQueryClient()
  const done = () => { void qc.invalidateQueries({ queryKey: ['orders'] }) }
  return {
    preview: useMutation({ mutationFn: (t: Ticket) => post<Preview>('/api/orders/preview', t) }),
    place: useMutation({ mutationFn: (id: string) => post<PlaceResult>('/api/orders/place', { preview_id: id, confirm: true }), onSuccess: done }),
    cancel: useMutation({ mutationFn: (id: string) => post<{ ok: boolean; message: string | null }>(`/api/orders/cancel/${encodeURIComponent(id)}`, {}), onSuccess: done }),
    kill: useMutation({ mutationFn: (v: { on: boolean; reason?: string }) => post<{ kill: boolean; cancelled: unknown[]; errors: unknown[] }>('/api/orders/kill', { reason: '', ...v }), onSuccess: done }),
    enable: useMutation({ mutationFn: (v: { on: boolean; phrase?: string }) => post<{ enabled: boolean }>('/api/orders/enable', { phrase: '', ...v }), onSuccess: done }),
    protect: useMutation({
      mutationFn: (v: { symbol: string; qty: number; stop: number; target: number }) => post<{ ok: boolean; id: string | null; message: string | null }>('/api/orders/protect', { ...v, confirm: true }),
      onSuccess: done,
    }),
  }
}
