// Holdings marked to the live price: value, P&L, today's P&L and a live stop / target check between scans.
// The scan's numbers stay the fallback for a holding without a live quote (market shut, no trade yet).

import type { HoldingRow, HoldingsResponse, Quote } from '@/api/types'

export function liveRow(r: HoldingRow, q: Quote | undefined): HoldingRow {
  if (!q || r.qty == null) return r
  const price = q.price
  const value = price * r.qty
  const pnl = r.buy_price != null ? (price - r.buy_price) * r.qty : r.pnl_amount
  const pnlPct = r.buy_price ? (price / r.buy_price - 1) * 100 : r.pnl_pct
  const dayPnl = q.prev_close != null ? (price - q.prev_close) * r.qty : r.day_pnl
  const alerts = [...r.alerts]
  let level = r.level
  if (r.stop_price != null && price <= r.stop_price) {
    if (!alerts.some((a) => a.startsWith('Live price below stop'))) alerts.unshift(`Live price below stop-loss ₹${r.stop_price.toFixed(2)}`)
    level = 'danger'
  } else if (r.target_price != null && price >= r.target_price) {
    if (!alerts.some((a) => a.startsWith('Live price at target'))) alerts.unshift(`Live price at target ₹${r.target_price.toFixed(2)}`)
    if (level === 'ok') level = 'watch'
  }
  return { ...r, price, change_pct: q.change_pct, value, pnl_amount: pnl, pnl_pct: pnlPct, day_pnl: dayPnl, alerts, level }
}

export function liveHoldings(h: HoldingsResponse, quotes: Record<string, Quote>): HoldingsResponse {
  if (!Object.keys(quotes).length) return h
  const rows = h.rows.map((r) => liveRow(r, quotes[r.symbol]))
  const sum = (f: (r: HoldingRow) => number | null) => {
    let s = 0, any = false
    for (const r of rows) { const v = f(r); if (v != null) { s += v; any = true } }
    return any ? s : null
  }
  const value = sum((r) => r.value)
  const invested = h.totals.invested
  const pnl = value != null && invested != null ? value - invested : h.totals.pnl
  const total = value ?? 0
  const withWeights = rows.map((r) => ({ ...r, weight_pct: r.value != null && total > 0 ? (r.value / total) * 100 : r.weight_pct }))
  return {
    ...h,
    rows: withWeights,
    totals: {
      ...h.totals, value, pnl,
      pnl_pct: pnl != null && invested ? (pnl / invested) * 100 : h.totals.pnl_pct,
      day_pnl: sum((r) => r.day_pnl),
      danger: rows.filter((r) => r.level === 'danger').length,
      watch: rows.filter((r) => r.level === 'watch').length,
    },
  }
}
