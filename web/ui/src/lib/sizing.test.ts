import { describe, expect, it } from 'vitest'
import { allocFor, allocationTotal, formatAllocations, orderClipboard, orderTotals, parseAllocations, sizeOrder } from './sizing'

// Parity fixtures from data/results/latest.json of 23 Oct 2026 09:18 (daily.sized output).
describe('sizeOrder BUY, equal sizing (parity with daily.sized)', () => {
  it('IGIL earnings_gap: 10 x 50,000 on 5,00,000', () => {
    const r = sizeOrder({ action: 'BUY', price: 353.2, stop: 324.94, alloc: 500000, max_positions: 10, sizing: 'equal', risk_pct: null })
    expect(r.qty).toBe(141)
    expect(r.amount).toBeCloseTo(49801.2, 1)
    expect(r.qty_basis).toBe('sized')
    expect(r.stop_distance_pct).toBeCloseTo(-8.0, 1)
    expect(r.risk_amount).toBeCloseTo(141 * (353.2 - 324.94), 6)
  })
  it('momentum: 15 x 33,333', () => {
    const r = sizeOrder({ action: 'BUY', price: 800.85, stop: null, alloc: 500000, max_positions: 15, sizing: 'equal', risk_pct: null })
    expect(r.qty).toBe(41)
    expect(r.risk_amount).toBeNull()
  })
  it('allocation shrinks the size', () => {
    const r = sizeOrder({ action: 'BUY', price: 353.2, stop: null, alloc: allocFor('earnings_gap', 500000, { earnings_gap: 40, momentum: 60 }), max_positions: 10, sizing: 'equal', risk_pct: null })
    expect(r.qty).toBe(56)
  })
  it('flags positions below the minimum', () => {
    const r = sizeOrder({ action: 'BUY', price: 1000, stop: null, alloc: 100000, max_positions: 20, sizing: 'equal', risk_pct: null, min_position: 10000 })
    expect(r.qty).toBe(5)
    expect(r.below_min_position).toBe(true)
  })
  it('cannot size without a price', () => {
    const r = sizeOrder({ action: 'BUY', price: null, stop: null, alloc: 500000, max_positions: 10, sizing: 'equal', risk_pct: null })
    expect(r.qty).toBeNull()
    expect(r.amount).toBeNull()
  })
})

describe('sizeOrder BUY, risk sizing', () => {
  it('risk budget binds', () => {
    // alloc 5L, risk 1% = 5,000; price 100, stop 90 -> 500 by risk; cap 2 * 50,000 / 100 = 1,000
    const r = sizeOrder({ action: 'BUY', price: 100, stop: 90, alloc: 500000, max_positions: 10, sizing: 'risk', risk_pct: 1 })
    expect(r.qty).toBe(500)
    expect(r.risk_amount).toBe(5000)
  })
  it('2x per-position cap binds on tight stops', () => {
    const r = sizeOrder({ action: 'BUY', price: 100, stop: 99, alloc: 500000, max_positions: 10, sizing: 'risk', risk_pct: 1 })
    expect(r.qty).toBe(1000)
  })
  it('falls back to equal sizing when the stop is above the price', () => {
    const r = sizeOrder({ action: 'BUY', price: 100, stop: 110, alloc: 500000, max_positions: 10, sizing: 'risk', risk_pct: 1 })
    expect(r.qty).toBe(500)
  })
})

describe('sizeOrder SELL (review A1: never the compounded backtest qty)', () => {
  it('uses what the user holds', () => {
    const r = sizeOrder({ action: 'SELL', price: 320.05, stop: null, alloc: 500000, max_positions: 15, sizing: 'equal', risk_pct: null, you_hold_qty: 120, weight_pct: 9 })
    expect(r.qty).toBe(120)
    expect(r.qty_basis).toBe('your_holding')
    expect(r.amount).toBeCloseTo(120 * 320.05, 6)
  })
  it('falls back to the model weight', () => {
    const r = sizeOrder({ action: 'SELL', price: 320.05, stop: null, alloc: 500000, max_positions: 15, sizing: 'equal', risk_pct: null, weight_pct: 6.5 })
    expect(r.qty).toBe(Math.floor((500000 * 0.065) / 320.05))
    expect(r.qty_basis).toBe('model_weight')
  })
  it('returns null qty when nothing is known', () => {
    const r = sizeOrder({ action: 'SELL', price: 320.05, stop: null, alloc: 500000, max_positions: 15, sizing: 'equal', risk_pct: null })
    expect(r.qty).toBeNull()
  })
})

describe('allocations', () => {
  it('parses and formats the query string form', () => {
    expect(parseAllocations('momentum:60,earnings_gap:40')).toEqual({ momentum: 60, earnings_gap: 40 })
    expect(parseAllocations('momentum:abc,,x:150')).toEqual({ x: 100 })
    expect(formatAllocations({ momentum: 60, low_vol: 0, earnings_gap: 40 })).toBe('momentum:60,earnings_gap:40')
    expect(allocationTotal({ a: 60, b: 25 })).toBe(85)
  })
  it('no allocations means full capital per strategy; unlisted strategies get none', () => {
    expect(allocFor('momentum', 500000, {})).toBe(500000)
    expect(allocFor('momentum', 500000, { momentum: 60 })).toBe(300000)
    expect(allocFor('low_vol', 500000, { momentum: 60 })).toBe(0)
  })
})

describe('totals and clipboard', () => {
  it('sums only non-comparison rows', () => {
    const t = orderTotals([
      { action: 'BUY', amount: 49801, risk_amount: 3985, results_warning: false, comparison_only: false },
      { action: 'BUY', amount: 1000, risk_amount: 10, results_warning: true, comparison_only: true },
      { action: 'SELL', amount: null, risk_amount: null, results_warning: true, comparison_only: false },
    ])
    expect(t).toEqual({ buy_count: 1, sell_count: 1, buy_amount: 49801, sell_amount: null, risk_amount: 3985, results_warnings: 1 })
  })
  it('builds the copy text', () => {
    expect(orderClipboard({ action: 'BUY', symbol: 'IGIL', qty: 141, stop: 324.94 })).toBe('BUY IGIL 141 @ MKT, SL 324.94')
    expect(orderClipboard({ action: 'SELL', symbol: 'CUPID', qty: null, stop: null })).toBe('SELL CUPID @ MKT')
  })
})
