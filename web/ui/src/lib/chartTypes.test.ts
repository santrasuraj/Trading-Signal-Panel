import { describe, expect, it } from 'vitest'
import { anchoredVwap, heikinAshi, lineBreak, renko, type Ohlcv } from './chartTypes'

const bars = (c: number[], v = 100): Ohlcv => ({
  t: c.map((_, i) => `2026-01-${String(i + 1).padStart(2, '0')}`), o: c, h: c.map((x) => x + 1), l: c.map((x) => x - 1), c, v: c.map(() => v),
})

describe('chart types', () => {
  it('Heikin Ashi averages the bar and smooths the open', () => {
    const b = { t: ['a', 'b'], o: [10, 12], h: [14, 15], l: [9, 11], c: [12, 14], v: [1, 1] }
    const ha = heikinAshi(b)
    expect(ha.c).toEqual([11.25, 13])
    expect(ha.o).toEqual([11, 11.13])            // (10+12)/2, then (11 + 11.25)/2
    expect(ha.h[1]).toBe(15)
  })

  it('Renko draws a brick per full box and needs two to reverse', () => {
    const { bricks, box } = renko(bars([100, 101, 104, 106, 105, 103, 99]), 2)
    expect(box).toBe(2)
    const moves = bricks.map((k) => k.c - k.o)
    expect(moves.slice(0, 3)).toEqual([2, 2, 2])                    // 100 -> 106
    expect(moves.slice(3)).toEqual([-2, -2])                        // 99 reverses: 104 -> 100 (two bricks below 106)
    expect(new Set(bricks.map((k) => k.t)).size).toBe(bricks.length)   // unique, increasing times
  })

  it('three-line break reverses only past the last three lines', () => {
    const lb = lineBreak(bars([10, 11, 12, 13, 12.5, 9.5]))
    expect(lb.map((x) => x.c)).toEqual([11, 12, 13, 9.5])            // 12.5 breaks nothing; 9.5 breaks the 3-line low
  })

  it('anchored VWAP starts at the anchor', () => {
    const b = bars([10, 20, 30])
    const av = anchoredVwap(b, '2026-01-02')
    expect(av.map((x) => x.t)).toEqual(['2026-01-02', '2026-01-03'])
    expect(av[1].v).toBe(25)
    expect(anchoredVwap({ ...b, v: [0, 0, 0] }, '2026-01-01')).toEqual([])
  })
})
