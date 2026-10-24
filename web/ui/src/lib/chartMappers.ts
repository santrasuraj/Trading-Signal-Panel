// Pure mappers from API payloads to lightweight-charts v5 data. No DOM access here so they are unit-testable.
//
// Time handling (spec 4.6):
//   daily / weekly bars use 'YYYY-MM-DD' strings (BusinessDay semantics), so there is no timezone shift at all;
//   intraday bars use UTCTimestamp of the IST wall clock treated as UTC (epoch of IST + 19800 s), so the axis reads
//   09:15-15:30 without any timezone code. toLwcTime() implements the second rule.

import type { CandlestickData, HistogramData, LineData, SeriesMarker, Time, UTCTimestamp, WhitespaceData } from 'lightweight-charts'
import type { ChartMarker, ChartResponse, ISODate, TimeSeries } from '@/api/types'

export const IST_OFFSET_S = 19800

/** Real epoch seconds (or ms) -> IST wall clock expressed as a UTC timestamp. */
export function toLwcTime(epoch: number, unit: 's' | 'ms' = 's'): UTCTimestamp {
  const s = unit === 'ms' ? Math.floor(epoch / 1000) : Math.floor(epoch)
  return (s + IST_OFFSET_S) as UTCTimestamp
}

/** 'YYYY-MM-DD' + 'HH:MM' (IST) -> IST-as-UTC timestamp. */
export function istWallClockToLwc(d: ISODate, hhmm: string): UTCTimestamp {
  const [y, m, day] = d.split('-').map(Number)
  const [hh, mm] = hhmm.split(':').map(Number)
  return (Date.UTC(y, m - 1, day, hh, mm) / 1000) as UTCTimestamp
}

export interface CandlePalette { up: string; down: string; upVol: string; downVol: string }

export function toCandles(bars: ChartResponse['bars']): CandlestickData<Time>[] {
  const out: CandlestickData<Time>[] = []
  for (let i = 0; i < bars.t.length; i++) {
    out.push({ time: bars.t[i], open: bars.o[i], high: bars.h[i], low: bars.l[i], close: bars.c[i] })
  }
  return out
}

export function toVolume(bars: ChartResponse['bars'], pal: CandlePalette): HistogramData<Time>[] {
  const out: HistogramData<Time>[] = []
  for (let i = 0; i < bars.t.length; i++) {
    const up = bars.c[i] >= bars.o[i]
    out.push({ time: bars.t[i], value: bars.v[i] ?? 0, color: up ? pal.upVol : pal.downVol })
  }
  return out
}

/** Line data aligned to t; nulls become whitespace points so gaps render as gaps (never forward-filled). */
export function toLine(t: (string | number)[], v: (number | null | undefined)[], f?: (x: number, i: number) => number | null): (LineData<Time> | WhitespaceData<Time>)[] {
  const out: (LineData<Time> | WhitespaceData<Time>)[] = []
  for (let i = 0; i < t.length; i++) {
    const raw = v[i]
    const x = raw == null || !Number.isFinite(raw) ? null : f ? f(raw, i) : raw
    out.push(x == null || !Number.isFinite(x) ? { time: t[i] as Time } : { time: t[i] as Time, value: x })
  }
  return out
}

/** Histogram data for MACD histogram with sign colours. */
export function toSignedHistogram(t: string[], v: (number | null)[], pos: string, neg: string): (HistogramData<Time> | WhitespaceData<Time>)[] {
  return t.map((time, i) => {
    const x = v[i]
    return x == null || !Number.isFinite(x) ? { time } : { time, value: x, color: x >= 0 ? pos : neg }
  })
}

export interface MarkerPalette { profit: string; loss: string; neutral: string; warn: string }

/** API markers -> lightweight-charts markers. Sorted by time (the library requires ascending order). */
export function toMarkers(markers: ChartMarker[], pal: MarkerPalette, visible?: Set<string>): SeriesMarker<Time>[] {
  return markers
    .filter((m) => !visible || m.strategy_key == null || visible.has(m.strategy_key))
    .map((m, i) => ({
      id: `${m.kind}:${m.t}:${i}`,
      time: m.t as Time,
      position: m.position,
      shape: m.shape,
      color: pal[m.tone],
      text: m.text,
      size: m.kind === 'results' ? 0.6 : m.kind === 'corporate_action' ? 0.8 : 1,
    }))
    .sort((a, b) => (String(a.time) < String(b.time) ? -1 : String(a.time) > String(b.time) ? 1 : 0))
}

export type CurveMode = 'log' | 'pct' | 'inr'

/**
 * Transform a growth-of-1 series for the equity chart.
 *   log: value as is, chart uses a logarithmic price scale
 *   pct: (v - 1) * 100 (percent return since range start)
 *   inr: v * capital
 */
export function curveValue(v: number, mode: CurveMode, capital: number): number {
  if (mode === 'pct') return (v - 1) * 100
  if (mode === 'inr') return v * capital
  return v
}

/** Rebase every series to 1.0 at the first index where it has a value (used after client-side range slicing). */
export function rebase(ts: TimeSeries): TimeSeries {
  return {
    t: ts.t,
    series: ts.series.map((s) => {
      const first = s.v.find((x) => x != null && Number.isFinite(x) && x !== 0)
      return { ...s, v: s.v.map((x) => (x == null || first == null ? null : x / first)) }
    }),
  }
}

/** Drawdown in percent (<= 0) of a growth series: v / cummax - 1. */
export function drawdownPct(v: (number | null)[]): (number | null)[] {
  let peak = -Infinity
  return v.map((x) => {
    if (x == null || !Number.isFinite(x)) return null
    if (x > peak) peak = x
    return peak > 0 ? (x / peak - 1) * 100 : null
  })
}

/** Evenly sample up to n points, always keeping the last one. */
export function sample<T>(arr: T[], n: number): T[] {
  if (arr.length <= n) return arr.slice()
  const out: T[] = []
  const step = (arr.length - 1) / (n - 1)
  for (let i = 0; i < n; i++) out.push(arr[Math.round(i * step)])
  return out
}

/** Slice a columnar series to the last `days` calendar days (approx: by ISO date string compare). */
export function sliceFrom(ts: TimeSeries, fromDate: ISODate | null): TimeSeries {
  if (!fromDate) return ts
  const i = ts.t.findIndex((d) => d >= fromDate)
  if (i <= 0) return ts
  return { t: ts.t.slice(i), series: ts.series.map((s) => ({ ...s, v: s.v.slice(i) })) }
}

/** Values of each series at the index whose time equals `time` (crosshair legend). */
export function valuesAt(ts: TimeSeries, time: string | null): Record<string, number | null> | null {
  if (!time) return null
  const i = ts.t.indexOf(time)
  if (i < 0) return null
  const out: Record<string, number | null> = {}
  for (const s of ts.series) out[s.id] = s.v[i] ?? null
  return out
}

// ------------------------------------------------------------------ heatmap bucketing (spec 4.1)
// Diverging 7-bucket scale: loss 40/25/12% alpha, neutral, profit 12/25/40% alpha. Clamp +-40 (yearly) / +-10 (monthly).

export type HeatBucket = -3 | -2 | -1 | 0 | 1 | 2 | 3

export function heatBucket(x: number | null | undefined, clamp: number): HeatBucket | null {
  if (x == null || !Number.isFinite(x)) return null
  const c = Math.max(-clamp, Math.min(clamp, x))
  const r = Math.abs(c) / clamp
  const mag = Math.abs(x) < clamp * 0.02 ? 0 : r < 1 / 3 ? 1 : r < 2 / 3 ? 2 : 3
  return (Math.sign(c) * mag) as HeatBucket
}

export const HEAT_ALPHA: Record<number, number> = { 1: 0.12, 2: 0.25, 3: 0.4 }

// ------------------------------------------------------------------ histogram bins (trades)
export function binReturns(rets: number[], width = 2, lo = -30, hi = 100) {
  const bins: { bin_lo: number; bin_hi: number; count: number }[] = []
  for (let b = lo; b < hi; b += width) bins.push({ bin_lo: b, bin_hi: b + width, count: 0 })
  for (const r of rets) {
    if (!Number.isFinite(r)) continue
    const c = Math.max(lo, Math.min(hi - 1e-9, r))
    const idx = Math.floor((c - lo) / width)
    bins[idx].count++
  }
  return bins
}
