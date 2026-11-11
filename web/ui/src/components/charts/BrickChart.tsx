// Renko and three-line break (lib/chartTypes.ts): price moves only, time left out, so the bricks get their own simple
// chart without indicators or markers. Each brick's date is the day that completed it (on the crosshair).

import { useEffect, useMemo } from 'react'
import { CandlestickSeries, type Time, type UTCTimestamp } from 'lightweight-charts'
import { inrAxisPrice, palette } from '@/lib/chartTheme'
import type { Brick } from '@/lib/chartTypes'
import { useLwChart } from './useLwChart'

export function BrickChart({ bricks, height }: { bricks: Brick[]; height: number }) {
  const { ref, chart, version } = useLwChart({ timeScale: { timeVisible: false, rightOffset: 4 } })
  const pal = useMemo(() => palette(), [version]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!chart) return
    const s = chart.addSeries(CandlestickSeries, {
      upColor: pal.up, downColor: pal.down, borderUpColor: pal.up, borderDownColor: pal.down, wickUpColor: pal.up, wickDownColor: pal.down,
      priceFormat: { type: 'custom', formatter: inrAxisPrice, minMove: 0.05 },
    }, 0)
    s.setData(bricks.map((b) => ({ time: b.t as UTCTimestamp, open: b.o, high: b.h, low: b.l, close: b.c })))
    const day = new Map(bricks.map((b) => [b.t, b.day]))
    chart.applyOptions({ localization: { timeFormatter: (t: Time) => day.get(t as number) ?? '' } })
    chart.timeScale().fitContent()
    return () => { try { chart.removeSeries(s) } catch { /* chart gone */ } }
  }, [chart, bricks, pal])
  return <div ref={ref} style={{ height }} className="w-full" />
}
