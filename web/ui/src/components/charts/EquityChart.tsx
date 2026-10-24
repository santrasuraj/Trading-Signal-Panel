// Strategy growth chart with a synced drawdown pane (spec 3.3): one lightweight-charts v5 chart, two panes, one
// time scale and one crosshair. Strategy = accent 2 px; Nifty 500 = muted dashed; Average stock = amber dotted;
// Nifty 50 = faint dotted; factor index = violet. Drawdown: strategy area in loss tint + Nifty 500 thin line.

import { useEffect, useMemo, useState } from 'react'
import { AreaSeries, LineSeries, LineStyle, PriceScaleMode, type ISeriesApi, type MouseEventParams, type Time } from 'lightweight-charts'
import type { TimeSeries } from '@/api/types'
import { curveValue, toLine, type CurveMode } from '@/lib/chartMappers'
import { palette } from '@/lib/chartTheme'
import { cn } from '@/lib/csv'
import { date, money, num, ok, pct } from '@/lib/format'
import { useLwChart, usePaneLayout } from './useLwChart'

type Style = { color: string; width: 1 | 2 | 3; style: LineStyle }

function styleFor(role: string, id: string, pal: ReturnType<typeof palette>): Style {
  if (role === 'strategy') return { color: pal.accent, width: 2, style: LineStyle.Solid }
  if (role === 'factor') return { color: pal.violet, width: 1, style: LineStyle.Solid }
  if (id === 'NIFTY 500') return { color: pal.muted, width: 1, style: LineStyle.Dashed }
  if (id === 'Average stock') return { color: pal.warn, width: 1, style: LineStyle.Dotted }
  return { color: pal.faint, width: 1, style: LineStyle.Dotted }
}

export function EquityChart({ curve, drawdown, mode, capital, height = 420, hidden }: {
  curve: TimeSeries; drawdown: TimeSeries; mode: CurveMode; capital: number; height?: number; hidden?: Set<string>
}) {
  const { ref, chart, version } = useLwChart()
  const [hover, setHover] = useState<{ time: string; values: Record<string, number | null>; dd: Record<string, number | null> } | null>(null)
  const pal = useMemo(() => palette(), [version]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!chart) return
    const lines = new Map<string, ISeriesApi<'Line'>>()
    for (const s of curve.series) {
      if (hidden?.has(s.id)) continue
      const st = styleFor(s.role, s.id, pal)
      const ser = chart.addSeries(LineSeries, {
        color: st.color, lineWidth: st.width, lineStyle: st.style, priceLineVisible: false, lastValueVisible: s.role === 'strategy',
        crosshairMarkerRadius: s.role === 'strategy' ? 4 : 3, title: '',
        priceFormat: mode === 'inr' ? { type: 'custom', formatter: (v: number) => money(v) } : mode === 'pct' ? { type: 'custom', formatter: (v: number) => pct(v, { dp: 0 }) } : { type: 'custom', formatter: (v: number) => `${num(v, 2)}×` },
      }, 0)
      ser.setData(toLine(curve.t, s.v, (x) => curveValue(x, mode, capital)))
      lines.set(s.id, ser)
    }
    chart.priceScale('right', 0).applyOptions({ mode: mode === 'log' ? PriceScaleMode.Logarithmic : PriceScaleMode.Normal })

    const ddStrat = drawdown.series[0]
    const ddBench = drawdown.series.find((s) => s.role !== 'strategy')
    const area = chart.addSeries(AreaSeries, {
      lineColor: pal.loss, lineWidth: 1, topColor: pal.lossFill0, bottomColor: pal.lossFill, invertFilledArea: true,
      priceLineVisible: false, lastValueVisible: false, priceFormat: { type: 'custom', formatter: (v: number) => pct(v, { dp: 0 }) },
    }, 1)
    if (ddStrat) area.setData(toLine(drawdown.t, ddStrat.v))
    let bench: ISeriesApi<'Line'> | null = null
    if (ddBench) {
      bench = chart.addSeries(LineSeries, { color: pal.muted, lineWidth: 1, lineStyle: LineStyle.Solid, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false }, 1)
      bench.setData(toLine(drawdown.t, ddBench.v))
    }
    // The drawdown pane (values <= 0) is never log: lightweight-charts copies the log mode set on pane 0's 'right'
    // scale into panes created after it, which drew the drawdown as spikes in Log mode.
    if (chart.panes().length > 1) chart.priceScale('right', 1).applyOptions({ mode: PriceScaleMode.Normal })
    const panes = chart.panes()
    if (panes[1]) panes[1].setStretchFactor(0.32)
    if (panes[0]) panes[0].setStretchFactor(1)
    chart.timeScale().fitContent()

    const idx = new Map(curve.t.map((t, i) => [t, i]))
    const ddIdx = new Map(drawdown.t.map((t, i) => [t, i]))
    const onMove = (p: MouseEventParams<Time>) => {
      if (!p.time || typeof p.time !== 'string') return setHover(null)
      const i = idx.get(p.time)
      const j = ddIdx.get(p.time)
      if (i == null) return setHover(null)
      const values: Record<string, number | null> = {}
      for (const s of curve.series) values[s.id] = s.v[i] ?? null
      const dd: Record<string, number | null> = {}
      if (j != null) for (const s of drawdown.series) dd[s.id] = s.v[j] ?? null
      setHover({ time: p.time, values, dd })
    }
    chart.subscribeCrosshairMove(onMove)
    return () => {
      chart.unsubscribeCrosshairMove(onMove)
      for (const s of lines.values()) chart.removeSeries(s)
      chart.removeSeries(area)
      if (bench) chart.removeSeries(bench)
    }
  }, [chart, curve, drawdown, mode, capital, pal, hidden])
  const layout = usePaneLayout(chart, curve)

  // legend shows hovered values, else the last values
  const lastI = curve.t.length - 1
  const shown = hover ?? {
    time: curve.t[lastI],
    values: Object.fromEntries(curve.series.map((s) => [s.id, s.v[lastI] ?? null])),
    dd: Object.fromEntries(drawdown.series.map((s) => [s.id, s.v[drawdown.t.length - 1] ?? null])),
  }
  const fmt = (v: number | null) => (!ok(v) ? '—' : mode === 'inr' ? money(v * capital) : mode === 'pct' ? pct((v - 1) * 100) : `${num(v, 2)}×`)
  const worst = useMemo(() => {
    const s = drawdown.series[0]
    if (!s) return null
    let w = 0
    for (const v of s.v) if (v != null && v < w) w = v
    return w
  }, [drawdown])

  // The legend is a row above the plot (it used to sit over the curves and wrap onto them on narrow cards); the
  // drawdown caption sits at the top-left of the drawdown pane on a panel-coloured backing.
  return (
    <div>
      <div className="flex min-h-[28px] flex-wrap items-center gap-x-3 gap-y-0.5 px-3 py-1.5 text-2xs">
        <span className="num text-muted">{date(shown.time)}</span>
        {curve.series.filter((s) => !hidden?.has(s.id)).map((s) => {
          const st = styleFor(s.role, s.id, pal)
          return (
            <span key={s.id} className="inline-flex items-center gap-1 whitespace-nowrap">
              <span className="inline-block h-0.5 w-3 rounded" style={{ background: st.color }} />
              <span className={cn(s.role === 'strategy' ? 'font-semibold text-fg' : 'text-muted')}>{s.label}</span>
              <span className="num text-fg">{fmt(shown.values[s.id] ?? null)}</span>
            </span>
          )
        })}
      </div>
      <div className="relative" style={{ height }}>
        <div ref={ref} className="absolute inset-0" />
        {layout.tops.length > 1 && (
          <div className="pointer-events-none absolute left-2 z-10 rounded bg-panel/85 px-1.5 py-0.5 text-2xs text-muted" style={{ top: layout.tops[1] + 4 }}>
            <span className="eyebrow mr-2">Drawdown</span>
            <span className="num text-loss">{pct(shown.dd[drawdown.series[0]?.id ?? ''] ?? null)}</span>
            {worst != null && <span className="num ml-2 text-faint">worst {pct(worst)}</span>}
          </div>
        )}
      </div>
    </div>
  )
}
