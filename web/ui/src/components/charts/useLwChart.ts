import { useEffect, useRef, useState } from 'react'
import { createChart, type DeepPartial, type ChartOptions, type IChartApi } from 'lightweight-charts'
import { chartOptions } from '@/lib/chartTheme'
import { useTheme } from '@/lib/theme'

/**
 * Creates one lightweight-charts instance in `ref`, keeps it themed from the CSS tokens (re-applied whenever the
 * theme, colour-blind mode or density changes) and removes it on unmount. Series are added by the caller in its own
 * effects, keyed on `chart` (and `version` for colours).
 */
export function useLwChart(extra?: DeepPartial<ChartOptions>) {
  const ref = useRef<HTMLDivElement>(null)
  const [chart, setChart] = useState<IChartApi | null>(null)
  const { version } = useTheme()
  // Merge the price-scale objects one level deep so e.g. { leftPriceScale: { visible } } keeps the themed borderColor.
  const opts = (): DeepPartial<ChartOptions> => {
    const b = chartOptions()
    return {
      ...b, ...extra,
      leftPriceScale: { ...b.leftPriceScale, ...extra?.leftPriceScale },
      rightPriceScale: { ...b.rightPriceScale, ...extra?.rightPriceScale },
    }
  }

  useEffect(() => {
    if (!ref.current) return
    const c = createChart(ref.current, opts())
    setChart(c)
    return () => {
      setChart(null)
      // Series effects of the caller clean up in the same commit, after this one (React runs cleanups in
      // declaration order), and they still need the chart: remove it once that commit has finished.
      queueMicrotask(() => c.remove())
    }
    // created once per mount; options are applied below
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (chart) chart.applyOptions(opts())
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chart, version])

  // Refit the time scale when the chart's WIDTH changes (window resize, rail toggle, side panel): with
  // lockVisibleTimeRangeOnResize + fixLeftEdge alone, widening the window cut the first months off the left and left
  // an empty band before the right price scale.
  useEffect(() => {
    const el = ref.current
    if (!chart || !el || typeof ResizeObserver === 'undefined') return
    let w = el.clientWidth
    let timer = 0
    const ro = new ResizeObserver(() => {
      const nw = el.clientWidth
      if (Math.abs(nw - w) < 2) return
      w = nw
      window.clearTimeout(timer)
      timer = window.setTimeout(() => chart.timeScale().fitContent(), 120)
    })
    ro.observe(el)
    return () => { ro.disconnect(); window.clearTimeout(timer) }
  }, [chart])

  return { ref, chart, version }
}

/** Top offset (px) of each pane inside the chart and the left price-scale width, kept current; for captions drawn
 *  over panes 1+ (pane 0's legend sits above the chart). `key` changes when series/panes are rebuilt. */
export function usePaneLayout(chart: IChartApi | null, key: unknown): { tops: number[]; left: number } {
  const [lay, setLay] = useState<{ tops: number[]; left: number }>({ tops: [], left: 0 })
  useEffect(() => {
    if (!chart) return
    const measure = () => {
      const tops: number[] = []
      let y = 0
      for (const p of chart.panes()) { tops.push(y); y += p.getHeight() + 1 }
      const left = chart.priceScale('left').width()
      setLay((o) => (o.left === left && o.tops.length === tops.length && o.tops.every((v, i) => v === tops[i]) ? o : { tops, left }))
    }
    const raf = requestAnimationFrame(measure)
    const ts = chart.timeScale()
    ts.subscribeSizeChange(measure)
    return () => { cancelAnimationFrame(raf); ts.unsubscribeSizeChange(measure) }
  }, [chart, key])
  return lay
}
