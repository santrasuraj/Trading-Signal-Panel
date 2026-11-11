import { describe, expect, it } from 'vitest'
import { fibPrices, levelOverlays, lineDrawings, timeToISO } from './userDrawings'

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
