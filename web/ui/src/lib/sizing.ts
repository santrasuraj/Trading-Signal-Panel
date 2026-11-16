// Client mirror of web/api/services/sizing.py (spec 6.7 + review A1). Used for instant what-if previews on the
// Signals page. The server stays the source of truth: whenever an /api/signals response for the
// same allocations arrives, its rows replace these.
//
//   alloc   = allocations ? capital * pct / 100 : capital
//   per_pos = alloc / max_positions
//   BUY     qty = floor(per_pos / price)
//           risk sizing (sizing == 'risk', stop < price):
//             qty = min(floor(alloc * risk_pct/100 / (price - stop)), floor(2 * per_pos / price))
//   SELL    qty = what the user holds ('your_holding'), else floor(alloc * weight_pct/100 / price) ('model_weight').
//           The backtest compounds, so its own share count is never shown as an order size.

import type { Allocation, Order, Side } from '@/api/types'

export interface SizingInput {
  action: Side
  price: number | null
  stop: number | null
  alloc: number
  max_positions: number
  sizing: 'equal' | 'risk'
  risk_pct: number | null
  min_position?: number
  you_hold_qty?: number | null
  weight_pct?: number | null
}

export interface SizedOrder {
  qty: number | null
  qty_basis: Order['qty_basis']
  amount: number | null
  stop_distance_pct: number | null
  risk_amount: number | null
  below_min_position: boolean
}

const good = (x: number | null | undefined): x is number => x != null && Number.isFinite(x)

export function sizeOrder(i: SizingInput): SizedOrder {
  const price = good(i.price) && i.price > 0 ? i.price : null
  const stop = good(i.stop) && i.stop > 0 ? i.stop : null
  const stop_distance_pct = price != null && stop != null ? (stop / price - 1) * 100 : null

  if (i.action === 'SELL') {
    if (good(i.you_hold_qty) && i.you_hold_qty > 0) {
      const qty = Math.floor(i.you_hold_qty)
      return { qty, qty_basis: 'your_holding', amount: price != null ? qty * price : null, stop_distance_pct, risk_amount: null, below_min_position: false }
    }
    if (price == null || !good(i.weight_pct) || i.weight_pct <= 0) {
      return { qty: null, qty_basis: 'model_weight', amount: null, stop_distance_pct, risk_amount: null, below_min_position: false }
    }
    const qty = Math.floor((i.alloc * i.weight_pct) / 100 / price)
    return { qty, qty_basis: 'model_weight', amount: qty * price, stop_distance_pct, risk_amount: null, below_min_position: false }
  }

  if (price == null || i.max_positions <= 0 || !(i.alloc > 0)) {
    return { qty: null, qty_basis: 'sized', amount: null, stop_distance_pct, risk_amount: null, below_min_position: false }
  }
  const perPos = i.alloc / i.max_positions
  let qty = Math.floor(perPos / price)
  if (i.sizing === 'risk' && stop != null && stop < price && good(i.risk_pct) && i.risk_pct > 0) {
    const byRisk = Math.floor((i.alloc * i.risk_pct) / 100 / (price - stop))
    const cap = Math.floor((2 * perPos) / price)
    qty = Math.min(byRisk, cap)
  }
  qty = Math.max(0, qty)
  const amount = qty * price
  const risk_amount = stop != null && stop < price ? qty * (price - stop) : null
  const below_min_position = (i.min_position ?? 0) > 0 && amount < (i.min_position ?? 0)
  return { qty, qty_basis: 'sized', amount, stop_distance_pct, risk_amount, below_min_position }
}

/** Capital available to one strategy. No allocations at all => every strategy is sized on the full capital. */
export function allocFor(key: string, capital: number, allocations: Allocation[] | Record<string, number>): number {
  const entries = Array.isArray(allocations)
    ? allocations.map((a) => [a.strategy_key, a.pct] as const)
    : Object.entries(allocations)
  if (entries.length === 0) return capital
  const hit = entries.find(([k]) => k === key)
  return hit ? (capital * hit[1]) / 100 : 0
}

/** 'momentum:60,earnings_gap:40' <-> { momentum: 60, earnings_gap: 40 } */
export function parseAllocations(s: string | null | undefined): Record<string, number> {
  const out: Record<string, number> = {}
  if (!s) return out
  for (const part of s.split(',')) {
    const [k, v] = part.split(':')
    const n = Number(v)
    if (k && k.trim() && Number.isFinite(n) && n >= 0) out[k.trim()] = Math.min(100, n)
  }
  return out
}

export function formatAllocations(a: Record<string, number>): string {
  return Object.entries(a)
    .filter(([, v]) => Number.isFinite(v) && v > 0)
    .map(([k, v]) => `${k}:${Math.round(v * 10) / 10}`)
    .join(',')
}

export function allocationTotal(a: Record<string, number>): number {
  return Object.values(a).reduce((s, v) => s + (Number.isFinite(v) ? v : 0), 0)
}

/** Totals row of the Signals page, computed from whatever rows are on screen. */
export function orderTotals(orders: Pick<Order, 'action' | 'amount' | 'risk_amount' | 'results_warning' | 'comparison_only'>[]) {
  let buy_count = 0, sell_count = 0, buy_amount = 0, sell_amount = 0, risk_amount = 0, results_warnings = 0
  let sellKnown = false
  for (const o of orders) {
    if (o.comparison_only) continue
    if (o.action === 'BUY') {
      buy_count++
      buy_amount += o.amount ?? 0
      risk_amount += o.risk_amount ?? 0
    } else {
      sell_count++
      if (o.amount != null) { sell_amount += o.amount; sellKnown = true }
    }
    if (o.results_warning) results_warnings++
  }
  return { buy_count, sell_count, buy_amount, sell_amount: sellKnown ? sell_amount : null, risk_amount, results_warnings }
}

/** Clipboard text for an order: 'BUY IGIL 141 @ MKT, SL 324.94'. */
export function orderClipboard(o: Pick<Order, 'action' | 'symbol' | 'qty' | 'stop'>): string {
  const q = o.qty != null ? ` ${o.qty}` : ''
  const sl = o.action === 'BUY' && o.stop != null ? `, SL ${o.stop.toFixed(2)}` : ''
  return `${o.action} ${o.symbol}${q} @ MKT${sl}`
}
