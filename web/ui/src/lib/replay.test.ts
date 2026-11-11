import { describe, expect, it } from 'vitest'
import { checkLevels, enter, exit, finish, marketFill, openPnl, start, step, summarize, type Bars, type SimCosts } from './replay'

const C: SimCosts = { slippage_pct: 0.1, charges_pct: 0.05 }
const NONE: SimCosts = { slippage_pct: 0, charges_pct: 0 }

// bar i: open, high, low, close
const bars = (rows: [number, number, number, number][]): Bars => ({
  t: rows.map((_, i) => 1000 + i * 300), o: rows.map((r) => r[0]), h: rows.map((r) => r[1]), l: rows.map((r) => r[2]), c: rows.map((r) => r[3]), v: rows.map(() => 0),
})

describe('replay fills', () => {
  it('market orders pay the slippage', () => {
    expect(marketFill(100, true, C)).toBe(100.1)
    expect(marketFill(100, false, C)).toBe(99.9)
  })

  it('a long entered at the close, closed manually later, with charges on both sides', () => {
    const b = bars([[100, 101, 99, 100], [100, 106, 100, 105]])
    let s = enter(start(0), b, 'LONG', 10, null, null, C)
    expect(s.pos?.entry).toBe(100.1)
    s = step(s, b, C, null)
    s = exit(s, b, 'manual', C)
    const t = s.trades[0]
    expect(t.exit).toBe(104.9)
    expect(t.gross).toBe(48)
    expect(t.charges).toBeCloseTo(1.025, 1)   // (100.1 + 104.9) * 10 * 0.05%
    expect(t.net).toBeCloseTo(46.975, 1)
  })

  it('the stop fills at the stop, or at the open when the price gaps through it', () => {
    const b = bars([[100, 100, 100, 100], [99, 99.5, 94, 95], [90, 91, 88, 89]])
    let s = enter(start(0), b, 'LONG', 1, 96, null, NONE)
    s = step(s, b, NONE, null)
    expect(s.trades[0]).toMatchObject({ exit: 96, reason: 'stop', exit_i: 1 })
    let g = enter(start(1), b, 'LONG', 1, 92, null, NONE)
    g = step(g, b, NONE, null)
    expect(g.trades[0]).toMatchObject({ exit: 90, reason: 'stop' })          // gapped below 92: the open
  })

  it('a bar touching both the stop and the target takes the stop (the worse case)', () => {
    const b = bars([[100, 100, 100, 100], [100, 110, 90, 100]])
    const s = step(enter(start(0), b, 'LONG', 1, 95, 105, NONE), b, NONE, null)
    expect(s.trades[0].reason).toBe('stop')
  })

  it('targets fill at the target (a limit order) and shorts mirror longs', () => {
    const b = bars([[100, 100, 100, 100], [100, 100.5, 94, 95]])
    const s = step(enter(start(0), b, 'SHORT', 2, 103, 96, C), b, C, null)
    expect(s.trades[0]).toMatchObject({ side: 'SHORT', exit: 96, reason: 'target' })
    expect(s.trades[0].gross).toBe(r(((99.9 - 96) * 2)))
  })

  it('intraday positions are squared off on the session last bar', () => {
    const b = bars([[100, 100, 100, 100], [100, 101, 99, 101], [101, 102, 100, 102]])
    let s = enter(start(0), b, 'LONG', 1, null, null, NONE)
    s = step(s, b, NONE, 2)
    expect(s.pos).not.toBeNull()
    s = step(s, b, NONE, 2)
    expect(s.pos).toBeNull()
    expect(s.trades[0]).toMatchObject({ exit: 102, reason: 'square_off' })
    expect(step(s, b, NONE, 2)).toBe(s)                                     // no bar after the last
  })

  it('reversing closes the open position first; the same side again is ignored', () => {
    const b = bars([[100, 100, 100, 100]])
    let s = enter(start(0), b, 'LONG', 5, null, null, NONE)
    expect(enter(s, b, 'LONG', 5, null, null, NONE)).toBe(s)
    s = enter(s, b, 'SHORT', 3, null, null, NONE)
    expect(s.trades).toHaveLength(1)
    expect(s.pos).toMatchObject({ side: 'SHORT', qty: 3 })
  })

  it('open P&L, finish and the summary', () => {
    const b = bars([[100, 100, 100, 100], [100, 103, 99, 102]])
    let s = enter(start(0), b, 'LONG', 10, null, null, NONE)
    s = step(s, b, NONE, null)
    expect(openPnl(s, b, NONE)).toBe(20)
    s = finish(s, b, NONE, false)
    expect(s.trades[0].reason).toBe('end')
    expect(summarize(s.trades)).toMatchObject({ trades: 1, wins: 1, net: 20, winRate: 100 })
  })

  it('checks the stop and target are on the right side of the price', () => {
    expect(checkLevels('LONG', 100, 95, 110)).toBeNull()
    expect(checkLevels('LONG', 100, 101, null)).toMatch(/below/)
    expect(checkLevels('SHORT', 100, 95, null)).toMatch(/above/)
    expect(checkLevels('SHORT', 100, 105, 101)).toMatch(/below/)
  })
})

function r(x: number) { return Math.round(x * 100) / 100 }
