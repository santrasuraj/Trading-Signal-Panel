// Hand-rolled SVG / CSS visuals (spec 4.6: heatmaps, timing bar, histogram, sparklines; no chart library).

import type { MonthlyRow, YearlyRow } from '@/api/types'
import { cn } from '@/lib/csv'
import { HEAT_ALPHA, heatBucket } from '@/lib/chartMappers'
import { MONTH_SHORT, num, ok, pct } from '@/lib/format'
import { useWidth } from '@/lib/useWidth'

// ------------------------------------------------------------------ Sparkline (80x24 default)
/** `fluid`: fills its box (give it flex-1 / max-w via className) and draws at the measured width, so a narrow
 *  tile gets a narrower sparkline instead of one that spills into its neighbour. */
export function Sparkline(p: {
  values: (number | null)[]; width?: number; height?: number; className?: string; tone?: 'auto' | 'muted' | 'accent'; area?: boolean; fluid?: boolean
}) {
  if (p.fluid) return <FluidSparkline {...p} />
  return <SparkSvg {...p} />
}

function FluidSparkline({ height = 24, className, ...rest }: Parameters<typeof Sparkline>[0]) {
  const [ref, w] = useWidth<HTMLDivElement>()
  return (
    <div ref={ref} className={cn('block', className)} style={{ height }} aria-hidden>
      {w > 8 && <SparkSvg {...rest} width={w} height={height} />}
    </div>
  )
}

function SparkSvg({ values, width = 80, height = 24, className, tone, area }: {
  values: (number | null)[]; width?: number; height?: number; className?: string; tone?: 'auto' | 'muted' | 'accent'; area?: boolean
}) {
  const pts = values.map((v, i) => [i, v] as const).filter((p): p is readonly [number, number] => ok(p[1]))
  if (pts.length < 2) return <svg width={width} height={height} className={className} aria-hidden />
  const xs = values.length - 1 || 1
  let lo = Infinity, hi = -Infinity
  for (const [, v] of pts) { lo = Math.min(lo, v); hi = Math.max(hi, v) }
  const span = hi - lo || 1
  const pad = 2
  const X = (i: number) => pad + (i / xs) * (width - pad * 2)
  const Y = (v: number) => pad + (1 - (v - lo) / span) * (height - pad * 2)
  const d = pts.map(([i, v], k) => `${k ? 'L' : 'M'}${X(i).toFixed(1)},${Y(v).toFixed(1)}`).join('')
  const first = pts[0][1], last = pts[pts.length - 1][1]
  const lastCls = tone === 'accent' ? 'fill-accent' : last > first ? 'fill-profit' : last < first ? 'fill-loss' : 'fill-muted'
  const strokeCls = tone === 'accent' ? 'stroke-accent' : 'stroke-muted'
  const [li, lv] = pts[pts.length - 1]
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} className={cn('block overflow-visible', className)} aria-hidden>
      {area && <path d={`${d}L${X(li).toFixed(1)},${height}L${X(pts[0][0]).toFixed(1)},${height}Z`} className="fill-accent/10" />}
      <path d={d} fill="none" strokeWidth={1.25} strokeLinejoin="round" strokeLinecap="round" className={strokeCls} vectorEffect="non-scaling-stroke" />
      <circle cx={X(li)} cy={Y(lv)} r={2} className={lastCls} />
    </svg>
  )
}

// ------------------------------------------------------------------ Timing-luck range bar
export function TimingRangeBar({ low, high, base, consistent, compact, domain }: {
  low: number | null; high: number | null; base: number | null; consistent: boolean; compact?: boolean; domain?: [number, number]
}) {
  if (!ok(low) || !ok(high)) return null
  const lo = Math.min(low, high, base ?? low)
  const hi = Math.max(low, high, base ?? high)
  const [d0, d1] = domain ?? [lo - (hi - lo) * 0.25 - 0.5, hi + (hi - lo) * 0.25 + 0.5]
  const P = (v: number) => `${Math.max(0, Math.min(100, ((v - d0) / (d1 - d0 || 1)) * 100))}%`
  return (
    <div className={cn('relative w-full', compact ? 'h-2' : 'h-3')} title={`Timing range ${num(low, 1)}% to ${num(high, 1)}%; base ${num(base, 1)}%${consistent ? '' : ' (range out of date)'}`}>
      <div className="absolute inset-x-0 top-1/2 h-px -translate-y-1/2 bg-line" />
      <div
        className={cn('absolute top-1/2 h-1.5 -translate-y-1/2 rounded-full', consistent ? 'bg-accent/35' : 'bg-warn/35')}
        style={{ left: P(Math.min(low, high)), width: `calc(${P(Math.max(low, high))} - ${P(Math.min(low, high))})`, minWidth: 2 }}
      />
      {ok(base) && (
        <div
          className={cn('absolute top-1/2 w-0.5 -translate-x-1/2 -translate-y-1/2 rounded-full', consistent ? 'bg-accent' : 'bg-warn', compact ? 'h-2.5' : 'h-3.5')}
          style={{ left: P(base) }}
        />
      )}
    </div>
  )
}

// ------------------------------------------------------------------ Heat cell
export function heatStyle(v: number | null | undefined, clamp: number): React.CSSProperties {
  const b = heatBucket(v, clamp)
  if (b == null) return {}
  if (b === 0) return { background: 'rgb(var(--raised))' }
  const a = HEAT_ALPHA[Math.abs(b)]
  return { background: `rgb(var(${b > 0 ? '--profit' : '--loss'}) / ${a})` }
}

export function YearlyHeatmap({ rows }: { rows: YearlyRow[] }) {
  const series: { key: keyof YearlyRow; label: string; strong?: boolean }[] = [
    { key: 'strategy', label: 'Strategy', strong: true },
    { key: 'nifty500', label: 'Nifty 500' },
    { key: 'average_stock', label: 'Average stock' },
    { key: 'nifty50', label: 'Nifty 50' },
  ]
  return (
    <div className="scroll-x">
      <table className="w-full border-separate border-spacing-[3px] text-xs">
        <thead>
          <tr>
            <th className="w-[110px]" />
            {rows.map((r) => (
              <th key={r.year} className="num px-1 pb-1 text-center text-2xs font-semibold text-muted" title={r.partial ? 'Partial year' : undefined}>
                {r.year}{r.partial && <span className="text-faint">*</span>}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {series.map((s) => (
            <tr key={s.key}>
              <th scope="row" className={cn('whitespace-nowrap pr-2 text-left text-xs font-medium', s.strong ? 'text-fg' : 'text-muted')}>{s.label}</th>
              {rows.map((r) => {
                const v = r[s.key] as number | null
                return (
                  <td key={r.year} className={cn('num h-8 min-w-[54px] rounded text-center', s.strong ? 'font-semibold text-fg' : 'text-fg/90')} style={heatStyle(v, 40)}>
                    {ok(v) ? pct(v, { dp: 1 }) : <span className="text-faint">—</span>}
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function MonthlyHeatmap({ rows }: { rows: MonthlyRow[] }) {
  return (
    <div className="scroll-x">
      <table className="w-full border-separate border-spacing-[2px] text-2xs">
        <thead>
          <tr>
            <th className="w-8" />
            {MONTH_SHORT.map((m) => <th key={m} className="pb-1 text-center font-semibold text-muted">{m}</th>)}
            <th className="pb-1 text-center font-semibold text-muted">Year</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.year}>
              <th scope="row" className="num pr-1 text-left font-medium text-muted">{r.year}</th>
              {r.months.map((v, i) => (
                // 40 px with no side padding: twelve months plus the Year total fit a 640 px card (800 px window)
                <td key={i} className="num h-7 min-w-[40px] whitespace-nowrap rounded px-0 text-center text-fg/90" style={heatStyle(v, 10)}>
                  {ok(v) ? pct(v, { dp: 1 }) : ''}
                </td>
              ))}
              <td className="num h-7 min-w-[54px] whitespace-nowrap rounded px-1 text-center font-semibold" style={heatStyle(r.total, 40)}>
                {ok(r.total) ? pct(r.total, { dp: 1 }) : '—'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ------------------------------------------------------------------ Trade return histogram
export function ReturnHistogram({ bins, height = 120 }: { bins: { bin_lo: number; bin_hi: number; count: number }[]; height?: number }) {
  const used = bins.filter((b) => b.count > 0)
  if (!used.length) return null
  const lo = Math.max(-30, Math.min(...used.map((b) => b.bin_lo)) - 4)
  const hi = Math.min(100, Math.max(...used.map((b) => b.bin_hi)) + 4)
  const shown = bins.filter((b) => b.bin_lo >= lo && b.bin_hi <= hi)
  const max = Math.max(...shown.map((b) => b.count))
  const W = 100 / shown.length
  const zero = shown.findIndex((b) => b.bin_lo >= 0)
  return (
    <div>
      <svg viewBox={`0 0 100 ${height}`} preserveAspectRatio="none" className="block w-full" style={{ height }} role="img" aria-label="Distribution of trade returns">
        {shown.map((b, i) => {
          const h = (b.count / max) * (height - 4)
          return (
            <rect key={b.bin_lo} x={i * W + W * 0.12} width={W * 0.76} y={height - h} height={h}
              className={b.bin_lo >= 0 ? 'fill-profit/70' : 'fill-loss/70'}>
              {/* the API clips returns into [-30, 100): the end bins hold every trade beyond them */}
              <title>{`${b.bin_hi >= 100 ? `${b.bin_lo}% or more` : b.bin_lo <= -30 ? `${b.bin_hi}% or less` : `${b.bin_lo}% to ${b.bin_hi}%`}: ${b.count} trades`}</title>
            </rect>
          )
        })}
        {zero > 0 && <line x1={zero * W} x2={zero * W} y1={0} y2={height} className="stroke-line-strong" strokeWidth={0.3} strokeDasharray="1 1" />}
      </svg>
      <div className="num relative mt-1 flex h-4 justify-between text-2xs text-faint">
        <span>{lo <= -30 ? `≤ ${pct(lo, { dp: 0 })}` : pct(lo, { dp: 0 })}</span>
        {/* under the zero line, only when zero is inside the axis (an all-loss filter has no 0%) */}
        {zero > 0 && zero * W > 8 && zero * W < 92 && <span className="absolute -translate-x-1/2" style={{ left: `${zero * W}%` }}>0%</span>}
        <span>{hi >= 100 ? `${pct(hi, { dp: 0 })}+` : pct(hi, { dp: 0 })}</span>
      </div>
    </div>
  )
}

// ------------------------------------------------------------------ Paper evidence meter
export function EvidenceMeter({ excess, expected, haircut, noise }: { excess: number | null; expected: number | null; haircut: number | null; noise: number | null }) {
  const vals = [excess, expected, haircut, ok(expected) && ok(noise) ? expected + noise : null, ok(expected) && ok(noise) ? expected - noise : null].filter(ok)
  const span = Math.max(2, ...vals.map((v) => Math.abs(v))) * 1.25
  const P = (v: number) => `${((v + span) / (2 * span)) * 100}%`
  return (
    <div className="space-y-2">
      <div className="relative h-8">
        <div className="absolute inset-x-0 top-1/2 h-px bg-line" />
        <div className="absolute top-1/2 h-4 w-px -translate-y-1/2 bg-line-strong" style={{ left: '50%' }} title="Same as Nifty 500" />
        {ok(expected) && ok(noise) && (
          <div className="absolute top-1/2 h-3 -translate-y-1/2 rounded bg-accent/15" style={{ left: P(expected - noise), width: `calc(${P(expected + noise)} - ${P(expected - noise)})` }} title={`Noise band ±${num(noise, 1)} pts`} />
        )}
        {ok(haircut) && <div className="absolute top-1/2 h-4 w-0.5 -translate-x-1/2 -translate-y-1/2 bg-muted" style={{ left: P(haircut) }} title={`After survivorship haircut ${pct(haircut)}`} />}
        {ok(expected) && <div className="absolute top-1/2 h-4 w-0.5 -translate-x-1/2 -translate-y-1/2 bg-accent" style={{ left: P(expected) }} title={`Backtest expected ${pct(expected)}`} />}
        {ok(excess) && (
          <div className={cn('absolute top-1/2 h-3 w-3 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-panel', excess >= 0 ? 'bg-profit' : 'bg-loss')} style={{ left: P(excess) }} title={`Paper vs Nifty 500 ${pct(excess)}`} />
        )}
      </div>
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-2xs text-muted">
        <span className="inline-flex items-center gap-1.5"><span className="h-2 w-2 rounded-full bg-profit" />Paper vs Nifty 500</span>
        <span className="inline-flex items-center gap-1.5"><span className="h-2.5 w-0.5 bg-accent" />Backtest expected</span>
        {ok(haircut) && <span className="inline-flex items-center gap-1.5"><span className="h-2.5 w-0.5 bg-muted" />After bias haircut</span>}
        <span className="inline-flex items-center gap-1.5"><span className="h-2 w-3 rounded-sm bg-accent/15" />Noise band</span>
      </div>
    </div>
  )
}

// ------------------------------------------------------------------ A/D bar, 52-week range, bars
export function AdBar({ advances, declines }: { advances: number; declines: number }) {
  const t = advances + declines || 1
  return (
    <div className="flex h-2 w-full overflow-hidden rounded-full bg-raised" title={`${advances} advancing, ${declines} declining`}>
      <div className="bg-profit" style={{ width: `${(advances / t) * 100}%` }} />
      <div className="ml-px bg-loss" style={{ width: `${(declines / t) * 100}%` }} />
    </div>
  )
}

export function RangeBar52w({ low, high, value }: { low: number | null; high: number | null; value: number | null }) {
  if (!ok(low) || !ok(high) || !ok(value) || high <= low) return null
  const p = Math.max(0, Math.min(100, ((value - low) / (high - low)) * 100))
  return (
    <div className="space-y-1">
      <div className="relative h-1.5 rounded-full bg-raised">
        <div className="absolute inset-y-0 left-0 rounded-full bg-accent/30" style={{ width: `${p}%` }} />
        <div className="absolute top-1/2 h-3 w-0.5 -translate-x-1/2 -translate-y-1/2 rounded bg-fg" style={{ left: `${p}%` }} />
      </div>
      <div className="num flex justify-between text-2xs text-muted"><span>{num(low)}</span><span>{num(high)}</span></div>
    </div>
  )
}

/** Horizontal signed bars for a ranked list (sector 3M returns etc.). */
export function SignedBars({ items, dp = 1 }: { items: { label: string; value: number | null; sub?: string }[]; dp?: number }) {
  const max = Math.max(1, ...items.map((i) => Math.abs(i.value ?? 0)))
  return (
    // capped width: on a full-width card the value labels would sit hundreds of px away from short bars
    <div className="max-w-[720px] space-y-1">
      {items.map((it) => {
        const v = it.value ?? 0
        const w = (Math.abs(v) / max) * 50
        return (
          <div key={it.label} className="grid grid-cols-[minmax(0,150px)_1fr_64px] items-center gap-2 text-xs">
            <span className="truncate text-muted" title={it.label}>{it.label}</span>
            <div className="relative h-3.5">
              <div className="absolute inset-y-0 left-1/2 w-px bg-line" />
              <div className={cn('absolute inset-y-0.5 rounded-sm', v >= 0 ? 'bg-profit/60' : 'bg-loss/60')} style={v >= 0 ? { left: '50%', width: `${w}%` } : { right: '50%', width: `${w}%` }} />
            </div>
            <span className={cn('num text-right', v > 0 ? 'text-profit' : v < 0 ? 'text-loss' : 'text-muted')}>{pct(it.value, { dp })}</span>
          </div>
        )
      })}
    </div>
  )
}

/** Weight bars (portfolio by sector). */
export function WeightBars({ items }: { items: { label: string; value: number }[] }) {
  const max = Math.max(1, ...items.map((i) => i.value))
  return (
    <div className="space-y-1.5">
      {items.map((it) => (
        <div key={it.label} className="grid grid-cols-[minmax(0,1fr)_minmax(0,2fr)_48px] items-center gap-2 text-xs">
          <span className="truncate text-muted">{it.label}</span>
          <div className="h-2 rounded-full bg-raised"><div className="h-2 rounded-full bg-accent/60" style={{ width: `${(it.value / max) * 100}%` }} /></div>
          <span className="num text-right text-fg">{pct(it.value, { signed: false })}</span>
        </div>
      ))}
    </div>
  )
}
