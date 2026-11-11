// Your own chart drawings (levels, trendlines, Fibonacci retracements), turned into the daily chart's price lines and
// line drawings. Pure, so it is unit-tested.

import type { Time } from 'lightweight-charts'
import type { ChartOverlay } from '@/components/charts/PriceChart'
import type { DrawLine, PatternDrawing } from '@/lib/patternDrawing'

export type DrawKind = 'hline' | 'trend' | 'fib'
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

/** Trendlines and Fibonacci sets as line drawings; Fibonacci levels run from A to the last bar of the chart. */
export function lineDrawings(ds: UserDrawing[], lastT: string | null): PatternDrawing[] {
  const out: PatternDrawing[] = []
  for (const d of ds) {
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
    }
  }
  return out
}

export function newId(): string {
  return Math.random().toString(16).slice(2, 14).padEnd(12, '0')
}
