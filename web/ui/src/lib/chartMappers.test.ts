import { describe, expect, it } from 'vitest'
import {
  binReturns, curveValue, drawdownPct, heatBucket, istWallClockToLwc, rebase, sample, sliceFrom, toCandles, toLine, toLwcTime,
  toMarkers, toVolume, valuesAt,
} from './chartMappers'
import type { ChartMarker, TimeSeries } from '@/api/types'

describe('time', () => {
  it('toLwcTime shifts real epoch to IST wall clock as UTC', () => {
    // 2026-10-23 09:15 IST == 03:45 UTC
    const real = Date.UTC(2026, 9, 23, 3, 45) / 1000
    const t = toLwcTime(real)
    const d = new Date(t * 1000)
    expect(d.getUTCHours()).toBe(9)
    expect(d.getUTCMinutes()).toBe(15)
    expect(toLwcTime(real * 1000, 'ms')).toBe(t)
  })
  it('istWallClockToLwc reads HH:MM as wall clock', () => {
    const t = istWallClockToLwc('2026-10-23', '15:00')
    expect(new Date(t * 1000).toISOString()).toBe('2026-10-23T15:00:00.000Z')
  })
})

const bars = { t: ['2026-10-21', '2026-10-22'], o: [100, 110], h: [112, 111], l: [99, 104], c: [110, 105], v: [1000, 0] }

describe('bars', () => {
  it('maps candles 1:1 with ISO date times', () => {
    expect(toCandles(bars)).toEqual([
      { time: '2026-10-21', open: 100, high: 112, low: 99, close: 110 },
      { time: '2026-10-22', open: 110, high: 111, low: 104, close: 105 },
    ])
  })
  it('colours volume by candle direction', () => {
    const v = toVolume(bars, { up: 'u', down: 'd', upVol: 'U', downVol: 'D' })
    expect(v.map((x) => x.color)).toEqual(['U', 'D'])
    expect(v[1].value).toBe(0)
  })
  it('turns nulls into whitespace, never forward-fills', () => {
    const l = toLine(['a', 'b', 'c'], [1, null, NaN])
    expect(l).toEqual([{ time: 'a', value: 1 }, { time: 'b' }, { time: 'c' }])
  })
})

describe('markers', () => {
  const ms: ChartMarker[] = [
    { t: '2026-10-22', position: 'aboveBar', shape: 'arrowDown', kind: 'exit', tone: 'loss', text: 'S −4.1%', detail: null, strategy_key: 'momentum' },
    { t: '2026-01-02', position: 'belowBar', shape: 'arrowUp', kind: 'entry', tone: 'profit', text: 'B · MOM', detail: null, strategy_key: 'momentum' },
    { t: '2026-05-05', position: 'inBar', shape: 'square', kind: 'corporate_action', tone: 'neutral', text: 'Bonus', detail: null, strategy_key: null },
    { t: '2026-03-03', position: 'belowBar', shape: 'arrowUp', kind: 'entry', tone: 'profit', text: 'B · PEAD', detail: null, strategy_key: 'earnings_gap' },
  ]
  const pal = { profit: 'G', loss: 'R', neutral: 'N', warn: 'W' }
  it('sorts ascending and maps colour by tone', () => {
    const out = toMarkers(ms, pal)
    expect(out.map((m) => m.time)).toEqual(['2026-01-02', '2026-03-03', '2026-05-05', '2026-10-22'])
    expect(out[3].color).toBe('R')
    expect(out[0].text).toBe('B · MOM')
  })
  it('filters by visible strategies but keeps strategy-less markers', () => {
    const out = toMarkers(ms, pal, new Set(['earnings_gap']))
    expect(out.map((m) => m.text)).toEqual(['B · PEAD', 'Bonus'])
  })
})

describe('curves', () => {
  const ts: TimeSeries = {
    t: ['2026-01-01', '2026-02-01', '2026-03-01', '2026-04-01'],
    series: [
      { id: 'momentum', label: 'Momentum', role: 'strategy', v: [2, 3, 1.5, 4] },
      { id: 'NIFTY 500', label: 'Nifty 500', role: 'benchmark', v: [null, 1.1, 1.0, 1.2] },
    ],
  }
  it('curve modes', () => {
    expect(curveValue(1.25, 'pct', 500000)).toBeCloseTo(25)
    expect(curveValue(1.25, 'inr', 500000)).toBe(625000)
    expect(curveValue(1.25, 'log', 500000)).toBe(1.25)
  })
  it('rebases each series at its first value', () => {
    const r = rebase(ts)
    expect(r.series[0].v).toEqual([1, 1.5, 0.75, 2])
    expect(r.series[1].v[0]).toBeNull()
    expect(r.series[1].v[1]).toBe(1)
  })
  it('drawdown', () => {
    expect(drawdownPct([1, 2, 1, null, 3])).toEqual([0, 0, -50, null, 0])
  })
  it('slices from a date', () => {
    const s = sliceFrom(ts, '2026-02-15')
    expect(s.t).toEqual(['2026-03-01', '2026-04-01'])
    expect(s.series[0].v).toEqual([1.5, 4])
  })
  it('values at a crosshair time', () => {
    expect(valuesAt(ts, '2026-03-01')).toEqual({ momentum: 1.5, 'NIFTY 500': 1.0 })
    expect(valuesAt(ts, '2027-01-01')).toBeNull()
  })
  it('samples evenly, keeping the last point', () => {
    const a = Array.from({ length: 1000 }, (_, i) => i)
    const s = sample(a, 120)
    expect(s.length).toBe(120)
    expect(s[0]).toBe(0)
    expect(s[119]).toBe(999)
  })
})

describe('heatmap and histogram', () => {
  it('buckets symmetrically with clamping', () => {
    expect(heatBucket(null, 40)).toBeNull()
    expect(heatBucket(0.1, 40)).toBe(0)
    expect(heatBucket(5, 40)).toBe(1)
    expect(heatBucket(-20, 40)).toBe(-2)
    expect(heatBucket(93.6, 40)).toBe(3)
    expect(heatBucket(-16.3, 40)).toBe(-2)
    expect(heatBucket(-12, 10)).toBe(-3)
  })
  it('bins trade returns into 2% bins, clamped', () => {
    const b = binReturns([-50, -29, 0.5, 1.9, 28.5, 500])
    expect(b.length).toBe(65)
    expect(b[0]).toEqual({ bin_lo: -30, bin_hi: -28, count: 2 })
    expect(b.find((x) => x.bin_lo === 0)!.count).toBe(2)
    expect(b[b.length - 1].count).toBe(1)
  })
})
