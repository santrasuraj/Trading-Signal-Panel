// Generic multi-line chart over columnar series (breadth, paper equity in rupees, intraday equity, A/D line, VIX).
// Each series can sit on the right or left scale and in its own pane; optional horizontal reference lines.
// Pane 0's legend sits in a row ABOVE the plot (never over candles, axis labels or the right price scale, at any
// width); panes 1+ get a small caption at their top-left so each pane says what it shows.

import { useEffect, useMemo, useState } from 'react'
import { AreaSeries, LineSeries, LineStyle, type ISeriesApi, type MouseEventParams, type Time } from 'lightweight-charts'
import { toLine } from '@/lib/chartMappers'
import { palette } from '@/lib/chartTheme'
import { date, ok } from '@/lib/format'
import { useLwChart, usePaneLayout } from './useLwChart'

type PalKey = keyof ReturnType<typeof palette>

export interface LineDef {
  id: string
  label: string
  v: (number | null)[]
  color: PalKey
  width?: 1 | 2
  style?: 'solid' | 'dashed' | 'dotted'
  scale?: 'right' | 'left'
  pane?: number
  area?: boolean
  format: (v: number) => string
  /** Horizontal reference lines; the value shows on the price axis (no second title label next to it). */
  refLines?: { price: number; label?: string }[]
}

export function LinesChart({ t, lines, height = 260, paneFactors }: { t: string[]; lines: LineDef[]; height?: number; paneFactors?: number[] }) {
  const { ref, chart, version } = useLwChart({ leftPriceScale: { visible: lines.some((l) => l.scale === 'left') } })
  const pal = useMemo(() => palette(), [version]) // eslint-disable-line react-hooks/exhaustive-deps
  const [hover, setHover] = useState<number | null>(null)

  useEffect(() => {
    if (!chart) return
    const made: ISeriesApi<'Line' | 'Area'>[] = []
    for (const l of lines) {
      const style = l.style === 'dashed' ? LineStyle.Dashed : l.style === 'dotted' ? LineStyle.Dotted : LineStyle.Solid
      const common = {
        priceScaleId: l.scale === 'left' ? 'left' : 'right', priceLineVisible: false, lastValueVisible: (l.width ?? 1) > 1 || l.scale !== 'left',
        priceFormat: { type: 'custom' as const, formatter: l.format }, crosshairMarkerRadius: 3,
      }
      const s = l.area
        ? chart.addSeries(AreaSeries, { ...common, lineColor: pal[l.color], lineWidth: l.width ?? 1, topColor: pal.accentFill, bottomColor: pal.accentFill0 }, l.pane ?? 0)
        : chart.addSeries(LineSeries, { ...common, color: pal[l.color], lineWidth: l.width ?? 1, lineStyle: style }, l.pane ?? 0)
      s.setData(toLine(t, l.v))
      // axis label only: a title as well printed the level twice ('20' and '20.0' side by side)
      for (const r of l.refLines ?? []) s.createPriceLine({ price: r.price, color: pal.faint, lineStyle: LineStyle.Dashed, lineWidth: 1, axisLabelVisible: true, title: '' })
      made.push(s)
    }
    const panes = chart.panes()
    panes.forEach((p, i) => p.setStretchFactor(paneFactors?.[i] ?? (i === 0 ? 1 : 0.4)))
    chart.timeScale().fitContent()
    const idx = new Map(t.map((d, i) => [d, i]))
    const onMove = (p: MouseEventParams<Time>) => setHover(p.time && typeof p.time === 'string' ? idx.get(p.time) ?? null : null)
    chart.subscribeCrosshairMove(onMove)
    return () => {
      chart.unsubscribeCrosshairMove(onMove)
      for (const s of made) chart.removeSeries(s)
    }
  }, [chart, t, lines, pal, paneFactors])
  const layout = usePaneLayout(chart, lines)

  const i = hover ?? t.length - 1
  const item = (l: LineDef) => (
    <span key={l.id} className="inline-flex items-center gap-1 whitespace-nowrap">
      <span className="inline-block h-0.5 w-3 rounded" style={{ background: pal[l.color] }} />
      <span className="text-muted">{l.label}</span>
      <span className="num text-fg">{ok(l.v[i]) ? l.format(l.v[i] as number) : '—'}</span>
    </span>
  )
  const maxPane = Math.max(0, ...lines.map((l) => l.pane ?? 0))
  return (
    <div>
      <div className="flex min-h-[28px] flex-wrap items-center gap-x-3 gap-y-0.5 px-3 py-1.5 text-2xs">
        <span className="num text-muted">{date(t[i])}</span>
        {lines.filter((l) => (l.pane ?? 0) === 0).map(item)}
      </div>
      <div className="relative" style={{ height }}>
        <div ref={ref} className="absolute inset-0" />
        {maxPane > 0 && layout.tops.slice(1).map((top, k) => {
          const pane = k + 1
          const ls = lines.filter((l) => (l.pane ?? 0) === pane)
          if (!ls.length) return null
          return (
            <div key={pane} className="pointer-events-none absolute z-10 flex flex-wrap items-center gap-x-3 rounded bg-panel/80 px-1.5 py-0.5 text-2xs" style={{ top: top + 4, left: layout.left + 8 }}>
              {ls.map(item)}
            </div>
          )
        })}
      </div>
    </div>
  )
}
