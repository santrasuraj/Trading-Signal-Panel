// Your own chart drawings (levels, trendlines, Fibonacci retracements), turned into the daily chart's price lines and
// line drawings. Pure, so it is unit-tested.

import type { Time } from 'lightweight-charts'
import type { ChartOverlay } from '@/components/charts/PriceChart'
import type { DrawLine, PatternDrawing } from '@/lib/patternDrawing'
import { anchoredVwap, type Ohlcv } from '@/lib/chartTypes'

export type DrawKind = 'hline' | 'trend' | 'fib' | 'rect' | 'text' | 'avwap'
export interface DrawPt { t: string; v: number }
export interface UserDrawing { id: string; kind: DrawKind; note?: string; price?: number; a?: DrawPt; b?: DrawPt }

export const FIB_LEVELS = [0, 0.236, 0.382, 0.5, 0.618, 0.786, 1]

/** 'YYYY-MM-DD' from any lightweight-charts time (string, business day or UTC seconds). */
export function timeToISO(t: Time | undefined | null): string | null {
  if (t == null) return null
  if (typeof t === 'string') return t.slice(0, 10)
  if (typeof t === 'number') return new Date(t * 1000).toISOString().slice(0, 10)
  const p = (n: number) => String(n).padStart(2, '0')
  return `${t.year}-${p(t.month)}-${p(t.day)}`
}

/** Fibonacci retracement prices from swing A to swing B: 0% at B, 100% back at A. */
export function fibPrices(a: number, b: number): { level: number; price: number }[] {
  return FIB_LEVELS.map((l) => ({ level: l, price: b - (b - a) * l }))
}

export function levelOverlays(ds: UserDrawing[]): ChartOverlay[] {
  return ds.filter((d) => d.kind === 'hline' && d.price != null).map((d) => ({
    price: d.price!, label: d.note ? `▸ ${d.note}` : '▸ level', tone: 'warn', style: 'dashed', width: 1, axis: true,
  }))
}

/** Trendlines, Fibonacci sets, zones, notes and anchored VWAPs as line drawings; Fibonacci levels run from A to the
 *  last bar of the chart, an anchored VWAP from its anchor to the last bar (needs the chart's `bars`). */
export function lineDrawings(ds: UserDrawing[], lastT: string | null, bars?: Ohlcv | null): PatternDrawing[] {
  const out: PatternDrawing[] = []
  for (const d of ds) {
    if (d.kind === 'text' && d.a) {
      out.push({ key: `u:${d.id}`, name: 'Note', tone: 'info', status: 'confirmed', lines: [{
        id: `u:${d.id}`, role: 'line', points: [d.a], tone: 'info', style: 'solid', width: 1,
        labels: [{ t: d.a.t, price: d.a.v, text: d.note || 'note', position: 'atPriceTop' }],
      }] })
      continue
    }
    if (d.kind === 'avwap' && d.a && bars) {
      const pts = anchoredVwap(bars, d.a.t)
      if (pts.length > 1) {
        out.push({ key: `u:${d.id}`, name: 'Anchored VWAP', tone: 'warn', status: 'confirmed', lines: [{
          id: `u:${d.id}`, role: 'line', points: pts, tone: 'warn', style: 'solid', width: 2, labels: [], axisLabel: 'AVWAP',
        }] })
      }
      continue
    }
    if (!d.a || !d.b) continue
    const [a, b] = d.a.t <= d.b.t ? [d.a, d.b] : [d.b, d.a]
    if (d.kind === 'trend') {
      if (a.t === b.t) continue
      out.push({ key: `u:${d.id}`, name: 'Trendline', tone: 'info', status: 'confirmed', lines: [{
        id: `u:${d.id}`, role: 'line', points: [a, b], tone: 'info', style: 'solid', width: 2, labels: [],
      }] })
    } else if (d.kind === 'fib') {
      const end = lastT && lastT > a.t ? lastT : b.t
      if (end === a.t) continue
      const lines: DrawLine[] = fibPrices(d.a.v, d.b.v).map(({ level, price }) => ({
        id: `u:${d.id}:${level}`, role: 'target', points: [{ t: a.t, v: price }, { t: end, v: price }],
        tone: level === 0.618 || level === 0.5 ? 'warn' : 'info', style: level === 0 || level === 1 ? 'solid' : 'dotted', width: 1,
        labels: [], axisLabel: `${(level * 100).toFixed(1).replace('.0', '')}%`,
      }))
      out.push({ key: `u:${d.id}`, name: 'Fibonacci', tone: 'info', status: 'confirmed', lines })
    } else if (d.kind === 'rect') {
      if (a.t === b.t) continue
      const hi = Math.max(d.a.v, d.b.v), lo = Math.min(d.a.v, d.b.v)
      out.push({ key: `u:${d.id}`, name: 'Zone', tone: 'warn', status: 'confirmed', lines: [
        { id: `u:${d.id}:hi`, role: 'line', points: [{ t: a.t, v: hi }, { t: b.t, v: hi }], tone: 'warn', style: 'solid', width: 1,
          labels: [{ t: a.t, price: hi, text: d.note || 'zone', position: 'atPriceTop' }] },
        { id: `u:${d.id}:lo`, role: 'line', points: [{ t: a.t, v: lo }, { t: b.t, v: lo }], tone: 'warn', style: 'solid', width: 1, labels: [] },
        { id: `u:${d.id}:mid`, role: 'line', points: [{ t: a.t, v: (hi + lo) / 2 }, { t: b.t, v: (hi + lo) / 2 }], tone: 'warn', style: 'dotted', width: 1, labels: [] },
      ] })
    }
  }
  return out
}

/** A trendline's price on `day` (straight line through its two points by calendar days, extended): the level a
 *  trendline alert compares the live price with (same rule as scanner/watch.py line_level). */
export function lineLevel(a: DrawPt, b: DrawPt, day: string): number {
  const d = (x: string) => Date.parse(`${x}T00:00:00Z`) / 86_400_000
  const span = d(b.t) - d(a.t)
  return span === 0 ? a.v : a.v + ((b.v - a.v) * (d(day) - d(a.t))) / span
}

export function newId(): string {
  return Math.random().toString(16).slice(2, 14).padEnd(12, '0')
}
