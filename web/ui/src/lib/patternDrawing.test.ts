import { describe, expect, it } from 'vitest'
import type { LvChartPattern } from '@/api/levels'
import { clipAtStart, patternDrawings, patternTone } from './patternDrawing'

// 30 daily bars, 2026-10-01 .. ; the pattern's last bar is the chart's last bar
const T = Array.from({ length: 30 }, (_, i) => `2026-10-${String(i + 1).padStart(2, '0')}`)
const day = (ago: number) => T[T.length - 1 - ago]

/** A confirmed double bottom: lows 20 and 12 bars ago, the neckline high 16 bars ago, broke out 3 bars ago. */
function doubleBottom(over: Partial<LvChartPattern> = {}): LvChartPattern {
  return {
    key: 'double_bottom', name: 'Double bottom', bias: 'bullish', status: 'confirmed', direction: null,
    confirmed_bars_ago: 3, confirmed_on: day(3), what: '', start: day(20), end: day(0),
    breakout: 110, invalidation: 100, target: 120, target_pct: 8, series: [],
    points: [
      { i: 0, price: 100, label: '1', t: day(20), ago: 20, side: 'low' },
      { i: 4, price: 110, label: 'N', t: day(16), ago: 16, side: 'high' },
      { i: 8, price: 100.5, label: '2', t: day(12), ago: 12, side: 'low' },
    ],
    lines: [{ i1: 4, p1: 110, i2: 20, p2: 110, t1: day(16), t2: day(0), ago1: 16, ago2: 0 }],
    evidence: null,
    ...over,
  }
}

describe('patternTone', () => {
  it('follows the bias, and a neutral pattern its breakout', () => {
    expect(patternTone({ bias: 'bullish', direction: null })).toBe('profit')
    expect(patternTone({ bias: 'bearish', direction: null })).toBe('loss')
    expect(patternTone({ bias: 'neutral', direction: null })).toBe('info')
    expect(patternTone({ bias: 'neutral', direction: 'down' })).toBe('loss')
  })
})

describe('clipAtStart', () => {
  it('cuts a line at bar 0 keeping its slope', () => {
    expect(clipAtStart([{ idx: -10, v: 100 }, { idx: 10, v: 120 }])).toEqual([{ idx: 0, v: 110 }, { idx: 10, v: 120 }])
    expect(clipAtStart([{ idx: -5, v: 1 }, { idx: -1, v: 2 }])).toEqual([])
    expect(clipAtStart([{ idx: 0, v: 1 }, { idx: 3, v: 2 }])).toEqual([{ idx: 0, v: 1 }, { idx: 3, v: 2 }])
  })
})

describe('patternDrawings', () => {
  it('draws the W through the swing points with labels on the right side', () => {
    const [d] = patternDrawings([doubleBottom()], T)
    const shape = d.lines.find((l) => l.role === 'shape')!
    expect(shape.points).toEqual([{ t: day(20), v: 100 }, { t: day(16), v: 110 }, { t: day(12), v: 100.5 }])
    expect(shape.labels.map((l) => [l.text, l.position])).toEqual([
      ['1', 'atPriceBottom'], ['N', 'atPriceTop'], ['2 · Double bottom ✓', 'atPriceBottom'],
    ])
    expect(shape.tone).toBe('profit')
  })

  it('draws the neckline solid once confirmed, dashed while forming', () => {
    const neck = (p: LvChartPattern) => patternDrawings([p], T)[0].lines.find((l) => l.role === 'line')!
    expect(neck(doubleBottom()).style).toBe('solid')
    expect(neck(doubleBottom()).points).toEqual([{ t: day(16), v: 110 }, { t: day(0), v: 110 }])
    const forming = doubleBottom({ status: 'forming', confirmed_bars_ago: null, confirmed_on: null })
    expect(neck(forming).style).toBe('dashed')
    expect(patternDrawings([forming], T)[0].lines[0].labels.at(-1)?.text).toBe('2 · Double bottom (forming)')
  })

  it('draws the target from the breakout bar and the void level under the lows, named on the axis', () => {
    const lines = patternDrawings([doubleBottom()], T)[0].lines
    const target = lines.find((l) => l.role === 'target')!
    expect(target.points).toEqual([{ t: day(3), v: 120 }, { t: day(0), v: 120 }])
    expect(target.axisLabel).toBe('Double bottom target')
    expect(target.labels).toEqual([])                                   // no text over the candles
    const stop = lines.find((l) => l.role === 'stop')!
    expect(stop.points[0]).toEqual({ t: day(3), v: 100 })
    expect(stop.axisLabel).toBe('Double bottom void')
    expect(stop.tone).toBe('warn')
  })

  it('draws a two-line pattern by its lines only, named at the upper line', () => {
    const wedge = doubleBottom({
      key: 'falling_wedge', name: 'Falling wedge', invalidation: 95,
      points: [
        { i: 0, price: 120, label: '', t: day(25), ago: 25, side: 'high' },
        { i: 5, price: 100, label: '', t: day(20), ago: 20, side: 'low' },
        { i: 10, price: 112, label: '', t: day(15), ago: 15, side: 'high' },
        { i: 15, price: 96, label: '', t: day(10), ago: 10, side: 'low' },
      ],
      lines: [
        { i1: 0, p1: 120, i2: 25, p2: 104, t1: day(25), t2: day(0), ago1: 25, ago2: 0 },
        { i1: 0, p1: 102, i2: 25, p2: 95, t1: day(25), t2: day(0), ago1: 25, ago2: 0 },
      ],
    })
    const [d] = patternDrawings([wedge], T)
    expect(d.lines.some((l) => l.role === 'shape')).toBe(false)
    const [upper, lower] = d.lines.filter((l) => l.role === 'line')
    expect(upper.width).toBe(2)
    // bars 4 .. 29 of the chart: the name goes on the middle bar (17, 12 bars ago), on the line itself
    expect(upper.points.map((p) => p.t)).toEqual([day(25), day(12), day(0)])
    expect(upper.points[1].v).toBeCloseTo(120 - (16 * 13) / 25, 6)
    expect(upper.labels).toEqual([{ t: day(12), price: upper.points[1].v, text: 'Falling wedge ✓', position: 'atPriceTop' }])
    expect(lower.labels).toEqual([])
    expect(lower.points).toHaveLength(2)
    expect(d.lines.some((l) => l.role === 'stop')).toBe(false)          // the lower line already shows it
  })

  it('uses a short name on the chart for head and shoulders', () => {
    const hs = doubleBottom({ key: 'inverse_head_shoulders', name: 'Inverse head and shoulders' })
    const shape = patternDrawings([hs], T)[0].lines.find((l) => l.role === 'shape')!
    expect(shape.labels.at(-1)?.text).toBe('2 · Inverse H&S ✓')
  })

  it('skips the void level when a pattern line already shows it (a triangle, a flag)', () => {
    const tri = doubleBottom({ invalidation: 110 })                     // equals the line's end
    expect(patternDrawings([tri], T)[0].lines.some((l) => l.role === 'stop')).toBe(false)
  })

  it('cuts the shape and lines at the first bar of a shorter chart range', () => {
    const short = T.slice(-15)                                         // the 15 most recent bars only
    const [d] = patternDrawings([doubleBottom()], short)
    const shape = d.lines.find((l) => l.role === 'shape')!
    // bar 0 of the short chart is 14 bars ago: between N (16 ago, 110) and 2 (12 ago, 100.5)
    expect(shape.points[0]).toEqual({ t: short[0], v: 105.25 })
    expect(shape.points.at(-1)).toEqual({ t: day(12), v: 100.5 })
    expect(shape.labels.map((l) => l.text)).toEqual(['2 · Double bottom ✓'])  // labels only on bars shown
    const neck = d.lines.find((l) => l.role === 'line')!
    expect(neck.points[0]).toEqual({ t: short[0], v: 110 })
  })

  it('draws nothing when the chart does not reach the pattern', () => {
    expect(patternDrawings([doubleBottom()], T.slice(0, 20))).toEqual([])
    expect(patternDrawings([doubleBottom({ end: '2026-11-30' })], T)).toEqual([])
  })

  it('keeps every drawn line in strictly increasing time (lightweight-charts requires it)', () => {
    for (const d of patternDrawings([doubleBottom()], T)) {
      for (const l of d.lines) {
        for (let k = 1; k < l.points.length; k++) expect(l.points[k].t > l.points[k - 1].t).toBe(true)
      }
    }
  })
})
