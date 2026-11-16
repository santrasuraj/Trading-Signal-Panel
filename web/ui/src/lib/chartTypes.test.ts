import { describe, expect, it } from 'vitest'
import { anchoredVwap, heikinAshi, kagi, lineBreak, pnf, renko, volumeByPrice, type Ohlcv } from './chartTypes'

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

describe('point & figure, kagi, volume by price', () => {
  const series = (closes: number[]) => ({ t: closes.map((_, i) => `2026-01-${String(i + 1).padStart(2, '0')}`), o: closes, h: closes, l: closes, c: closes, v: closes.map(() => 100) })
  it('P&F reverses only after three boxes', () => {
    const { cols, boxPrice } = pnf(series([100, 104, 108, 110, 108, 106, 104, 100, 96]), 2, 3)
    expect(cols.map((c) => c.up)).toEqual([true, false])
    expect(boxPrice(cols[0].to)).toBeLessThanOrEqual(110)
    expect(cols[1].from).toBe(cols[0].to - 1)
  })
  it('kagi turns on a 4% reversal and thins below the last waist', () => {
    const segs = kagi(series([100, 106, 110, 104, 103, 108, 101, 95]), 4)
    expect(segs.length).toBeGreaterThanOrEqual(3)
    expect(segs[0].to).toBe(110)
    expect(segs[segs.length - 1].thick).toBe(false)
  })
  it('volume by price finds the busiest level', () => {
    const b = { t: ['a', 'b', 'c'], o: [10, 10, 20], h: [11, 11, 21], l: [10, 10, 20], c: [10, 10, 20], v: [1000, 1000, 10] }
    const r = volumeByPrice(b, 10)
    expect(r.poc).toBeLessThan(12)
    expect(r.va![0]).toBeLessThanOrEqual(r.poc!)
  })
})
