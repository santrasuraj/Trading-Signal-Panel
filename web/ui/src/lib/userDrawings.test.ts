import { describe, expect, it } from 'vitest'
import { fibPrices, levelOverlays, lineDrawings, timeToISO, lineLevel } from './userDrawings'

describe('user drawings', () => {
  it('reads every chart time format as a date', () => {
    expect(timeToISO('2026-11-11')).toBe('2026-11-11')
    expect(timeToISO({ year: 2026, month: 3, day: 4 })).toBe('2026-03-04')
    expect(timeToISO(Date.UTC(2026, 0, 2) / 1000 as never)).toBe('2026-01-02')
    expect(timeToISO(undefined)).toBeNull()
  })

  it('puts Fibonacci 0% at the second swing and 100% back at the first', () => {
    const f = fibPrices(100, 200)
    expect(f[0]).toEqual({ level: 0, price: 200 })
    expect(f.find((x) => x.level === 0.618)!.price).toBeCloseTo(138.2)
    expect(f[f.length - 1]).toEqual({ level: 1, price: 100 })
  })

  it('turns levels into price lines and lines into drawings', () => {
    const ds = [
      { id: 'a', kind: 'hline' as const, price: 1300 },
      { id: 'b', kind: 'trend' as const, a: { t: '2026-03-01', v: 10 }, b: { t: '2026-01-01', v: 5 } },
      { id: 'c', kind: 'fib' as const, a: { t: '2026-01-01', v: 100 }, b: { t: '2026-02-01', v: 200 } },
    ]
    expect(levelOverlays(ds)).toHaveLength(1)
    const lines = lineDrawings(ds, '2026-11-10')
    expect(lines.map((l) => l.name)).toEqual(['Trendline', 'Fibonacci'])
    expect(lines[0].lines[0].points[0].t).toBe('2026-01-01')                 // ordered by date
    expect(lines[1].lines).toHaveLength(7)
    expect(lines[1].lines[0].points[1].t).toBe('2026-11-10')                 // Fibonacci levels run to the last bar
  })
})

describe('zones, notes, anchored VWAP and trendline levels', () => {
  it('draws a zone as its top, bottom and middle', () => {
    const d = lineDrawings([{ id: 'z', kind: 'rect', a: { t: '2026-01-02', v: 110 }, b: { t: '2026-02-02', v: 100 } }], null)
    expect(d[0].lines.map((l) => l.points[0].v)).toEqual([110, 100, 105])
  })
  it('puts a note as a label at its point', () => {
    const d = lineDrawings([{ id: 'n', kind: 'text', a: { t: '2026-01-02', v: 100 }, note: 'results' }], null)
    expect(d[0].lines[0].labels[0].text).toBe('results')
  })
  it('draws an anchored VWAP only with the chart bars', () => {
    const bars = { t: ['2026-01-01', '2026-01-02', '2026-01-03'], o: [10, 20, 30], h: [10, 20, 30], l: [10, 20, 30], c: [10, 20, 30], v: [1, 1, 1] }
    const ds = [{ id: 'v', kind: 'avwap' as const, a: { t: '2026-01-02', v: 20 } }]
    expect(lineDrawings(ds, null)).toEqual([])
    expect(lineDrawings(ds, null, bars)[0].lines[0].points.map((p) => p.v)).toEqual([20, 25])
  })
  it('extends a trendline by calendar days', () => {
    expect(lineLevel({ t: '2026-10-01', v: 100 }, { t: '2026-11-01', v: 131 }, '2026-11-11')).toBeCloseTo(141)
  })
})
