// Intraday candles (5 / 15 minutes) with each session's VWAP and volume; the last candle follows the live price
// between the minute refreshes (a new candle opens when the live price passes into the next slot).

import { useEffect, useMemo, useRef } from 'react'
import { CandlestickSeries, HistogramSeries, LineSeries, LineStyle, type ISeriesApi, type UTCTimestamp } from 'lightweight-charts'
import type { IntradayChartData } from '@/api/watch'
import type { LiveQuote } from '@/api/liveQuotes'
import { inrAxisPrice, palette } from '@/lib/chartTheme'
import { useLwChart } from './useLwChart'

const IST_OFFSET_S = 5.5 * 3600

/** The live price's slot start (IST wall-clock seconds, like the bars) for a `stepMin` chart, or null outside 09:15-15:30. */
export function liveSlot(nowMs: number, stepMin: number): number | null {
  const ist = Math.floor(nowMs / 1000) + IST_OFFSET_S
  const day = ist - (ist % 86400)
  const minute = Math.floor((ist - day) / 60)
  if (minute < 555 || minute >= 930) return null
  return day + (555 + Math.floor((minute - 555) / stepMin) * stepMin) * 60
}

/** Order flow under the candles (api orderflow): per-bar delta (buy - sell volume) and the session's cumulative delta. */
export interface FlowBars { t: number[]; delta: number[]; cum_delta: number[] }

export function IntradayChart({ data, live, height, flow }: { data: IntradayChartData; live?: LiveQuote; height: number; flow?: FlowBars | null }) {
  const { ref, chart, version } = useLwChart({ timeScale: { timeVisible: true, secondsVisible: false } })
  const pal = useMemo(() => palette(), [version]) // eslint-disable-line react-hooks/exhaustive-deps
  const candles = useRef<ISeriesApi<'Candlestick'> | null>(null)
  const last = useRef<{ time: number; open: number; high: number; low: number; close: number } | null>(null)
  const step = ({ '1m': 1, '5m': 5, '15m': 15, '30m': 30, '1h': 60 } as Record<string, number>)[data.tf] ?? 5

  useEffect(() => {
    if (!chart) return
    const b = data.bars
    const c = chart.addSeries(CandlestickSeries, {
      upColor: pal.up, downColor: pal.down, borderUpColor: pal.up, borderDownColor: pal.down, wickUpColor: pal.up, wickDownColor: pal.down,
      priceLineVisible: true, priceLineColor: pal.faint, priceLineStyle: LineStyle.Dotted,
      priceFormat: { type: 'custom', formatter: inrAxisPrice, minMove: 0.05 },
    }, 0)
    const rows = b.t.map((t, i) => ({ time: t as UTCTimestamp, open: b.o[i], high: b.h[i], low: b.l[i], close: b.c[i] }))
    c.setData(rows)
    candles.current = c
    // the daily chart's levels (previous session's high / low / close, daily SMAs): higher-timeframe context
    const toneColor = { profit: pal.up, loss: pal.down, muted: pal.faint, info: pal.info }
    for (const lv of data.daily_levels ?? []) {
      c.createPriceLine({ price: lv.price, color: toneColor[lv.tone] ?? pal.faint, lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: lv.label })
    }
    last.current = rows.length ? { ...rows[rows.length - 1], time: rows[rows.length - 1].time as number } : null
    chart.priceScale('right', 0).applyOptions({ scaleMargins: { top: 0.08, bottom: 0.22 } })
    const vol = chart.addSeries(HistogramSeries, { priceScaleId: '', priceFormat: { type: 'volume' }, priceLineVisible: false, lastValueVisible: false }, 0)
    vol.priceScale().applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } })
    vol.setData(b.t.map((t, i) => ({ time: t as UTCTimestamp, value: b.v[i], color: b.c[i] >= b.o[i] ? pal.upVol : pal.downVol })))
    // VWAP: one line per session, so it breaks between days instead of joining them
    const byDay = new Map<number, { time: UTCTimestamp; value: number }[]>()
    b.t.forEach((t, i) => {
      const v = data.vwap[i]
      if (v == null) return
      const day = Math.floor(t / 86400)
      if (!byDay.has(day)) byDay.set(day, [])
      byDay.get(day)!.push({ time: t as UTCTimestamp, value: v })
    })
    const days = [...byDay.keys()].sort((x, y) => x - y)
    const vws = days.map((day, k) => {
      const last = k === days.length - 1
      const s = chart.addSeries(LineSeries, { color: pal.info, lineWidth: 2, priceLineVisible: false, lastValueVisible: last, crosshairMarkerVisible: false, title: last ? 'VWAP' : '' }, 0)
      s.setData(byDay.get(day)!)
      return s
    })
    chart.timeScale().fitContent()
    return () => {
      candles.current = null
      for (const s of [c, vol, ...vws]) { try { chart.removeSeries(s) } catch { /* chart already gone */ } }
    }
  }, [chart, data, pal])

  // order flow: delta bars and cumulative delta in a pane under the candles
  useEffect(() => {
    if (!chart || !flow || !flow.t.length) return
    const d = chart.addSeries(HistogramSeries, { priceLineVisible: false, lastValueVisible: false, priceFormat: { type: 'volume' }, title: 'Delta' }, 1)
    d.setData(flow.t.map((t, i) => ({ time: t as UTCTimestamp, value: flow.delta[i], color: flow.delta[i] >= 0 ? pal.upVol : pal.downVol })))
    const c = chart.addSeries(LineSeries, { color: pal.info, lineWidth: 2, priceLineVisible: false, priceScaleId: 'left', title: 'Cum. delta', priceFormat: { type: 'volume' } }, 1)
    c.setData(flow.t.map((t, i) => ({ time: t as UTCTimestamp, value: flow.cum_delta[i] })))
    chart.priceScale('left', 1).applyOptions({ visible: true })
    const panes = chart.panes()
    if (panes[1]) panes[1].setHeight(Math.round(height * 0.28))
    return () => { for (const x of [d, c]) { try { chart.removeSeries(x) } catch { /* chart gone */ } } }
  }, [chart, flow, pal, height])

  // the live price moves the last candle, or opens the next one
  useEffect(() => {
    const c = candles.current
    if (!c || !live || live.source === 'close') return
    const slot = liveSlot(Date.now() - (live.source === 'yahoo' ? 15 * 60_000 : 0), step)
    if (slot == null) return
    const l = last.current
    const p = live.price
    if (l && l.time === slot) {
      const bar = { ...l, high: Math.max(l.high, p), low: Math.min(l.low, p), close: p }
      last.current = bar
      c.update({ ...bar, time: bar.time as UTCTimestamp })
    } else if (!l || slot > l.time) {
      const bar = { time: slot, open: p, high: p, low: p, close: p }
      last.current = bar
      c.update({ ...bar, time: slot as UTCTimestamp })
    }
  }, [live, step])

  return <div ref={ref} style={{ height }} className="w-full" />
}
