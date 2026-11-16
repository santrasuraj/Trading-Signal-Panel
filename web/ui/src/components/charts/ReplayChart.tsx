// Replay chart: the context bars and the replay revealed up to `upto` (one bar added per step, without redrawing the
// rest), the session VWAP for intraday, your entries / exits as markers and the open position's entry, stop and target
// as price lines. Blind mode keeps the dates off the axis (intraday shows only the time of day).

import { useEffect, useMemo, useRef } from 'react'
import {
  CandlestickSeries, HistogramSeries, LineSeries, LineStyle, createSeriesMarkers, type IPriceLine, type ISeriesApi,
  type ISeriesMarkersPluginApi, type SeriesMarker, type Time, type UTCTimestamp,
} from 'lightweight-charts'
import type { ReplayData } from '@/api/replay'
import { crosshairTimeLabel, inrAxisPrice, palette, tickMarkLabel } from '@/lib/chartTheme'
import type { ClosedTrade, Position } from '@/lib/replay'
import { useLwChart } from './useLwChart'

const pad2 = (n: number) => String(n).padStart(2, '0')
const hhmm = (t: Time) => (typeof t === 'number' ? `${pad2(Math.floor((t % 86400) / 3600))}:${pad2(Math.floor((t % 3600) / 60))}` : '')
const VISIBLE = { intraday: 140, daily: 160 }

export function ReplayChart({ data, upto, blind, trades, pos, height }: {
  data: ReplayData; upto: number; blind: boolean; trades: ClosedTrade[]; pos: Position | null; height: number
}) {
  const intraday = data.tf !== '1d'
  const { ref, chart, version } = useLwChart({ timeScale: { timeVisible: intraday, secondsVisible: false, rightOffset: 10 } })
  const pal = useMemo(() => palette(), [version]) // eslint-disable-line react-hooks/exhaustive-deps
  const s = useRef<{ candles: ISeriesApi<'Candlestick'>; vol: ISeriesApi<'Histogram'>; vwap: Map<number, ISeriesApi<'Line'>>; markers: ISeriesMarkersPluginApi<Time> } | null>(null)
  const shown = useRef(-1)
  const b = data.bars
  const time = (i: number) => b.t[i] as UTCTimestamp
  const candle = (i: number) => ({ time: time(i), open: b.o[i], high: b.h[i], low: b.l[i], close: b.c[i] })
  const volume = (i: number) => ({ time: time(i), value: b.v[i], color: b.c[i] >= b.o[i] ? pal.upVol : pal.downVol })
  const day = (i: number) => Math.floor(b.t[i] / 86400)

  // series, rebuilt for a new session or theme
  useEffect(() => {
    if (!chart) return
    const candles = chart.addSeries(CandlestickSeries, {
      upColor: pal.up, downColor: pal.down, borderUpColor: pal.up, borderDownColor: pal.down, wickUpColor: pal.up, wickDownColor: pal.down,
      priceLineVisible: true, priceLineColor: pal.faint, priceLineStyle: LineStyle.Dotted,
      priceFormat: { type: 'custom', formatter: inrAxisPrice, minMove: 0.05 },
    }, 0)
    chart.priceScale('right', 0).applyOptions({ scaleMargins: { top: 0.08, bottom: 0.22 } })
    const vol = chart.addSeries(HistogramSeries, { priceScaleId: '', priceFormat: { type: 'volume' }, priceLineVisible: false, lastValueVisible: false }, 0)
    vol.priceScale().applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } })
    const vwap = new Map<number, ISeriesApi<'Line'>>()
    if (data.vwap) {
      for (const d of [...new Set(b.t.map((t) => Math.floor(t / 86400)))]) {
        vwap.set(d, chart.addSeries(LineSeries, { color: pal.info, lineWidth: 2, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false }, 0))
      }
    }
    s.current = { candles, vol, vwap, markers: createSeriesMarkers(candles, []) }
    shown.current = -1
    return () => {
      s.current = null
      for (const x of [candles, vol, ...vwap.values()]) { try { chart.removeSeries(x) } catch { /* chart gone */ } }
    }
  }, [chart, data, pal]) // eslint-disable-line react-hooks/exhaustive-deps

  // reveal: one bar appended per step; anything else (start, jump, finish) redraws
  useEffect(() => {
    const x = s.current
    if (!x || !chart) return
    const last = Math.min(upto, b.t.length - 1)
    if (last === shown.current + 1 && shown.current >= 0) {
      x.candles.update(candle(last))
      x.vol.update(volume(last))
      const v = data.vwap?.[last]
      if (v != null) x.vwap.get(day(last))?.update({ time: time(last), value: v })
    } else if (last !== shown.current) {
      const idx = Array.from({ length: last + 1 }, (_, i) => i)
      x.candles.setData(idx.map(candle))
      x.vol.setData(idx.map(volume))
      for (const [d, ser] of x.vwap) ser.setData(idx.filter((i) => day(i) === d && data.vwap?.[i] != null).map((i) => ({ time: time(i), value: data.vwap![i]! })))
      const n = intraday ? VISIBLE.intraday : VISIBLE.daily
      chart.timeScale().setVisibleLogicalRange({ from: Math.max(0, last - n), to: last + 10 })
    }
    shown.current = last
  }) // every render: cheap when nothing changed

  // your trades
  useEffect(() => {
    const x = s.current
    if (!x) return
    const m: SeriesMarker<Time>[] = []
    const add = (i: number, long: boolean, entry: boolean, text: string, color: string) => {
      if (i > upto) return
      m.push({ time: time(i), position: long === entry ? 'belowBar' : 'aboveBar', shape: entry ? (long ? 'arrowUp' : 'arrowDown') : 'circle', color, text })
    }
    for (const t of trades) {
      const long = t.side === 'LONG'
      add(t.entry_i, long, true, long ? 'Buy' : 'Short', pal.accent)
      add(t.exit_i, long, false, `${t.net >= 0 ? '+' : '−'}₹${Math.abs(Math.round(t.net)).toLocaleString('en-IN')}`, t.net >= 0 ? pal.profit : pal.loss)
    }
    if (pos) add(pos.entry_i, pos.side === 'LONG', true, pos.side === 'LONG' ? 'Buy' : 'Short', pal.accent)
    m.sort((a, z) => (a.time as number) - (z.time as number))
    x.markers.setMarkers(m)
  }, [trades, pos, upto, pal, data]) // eslint-disable-line react-hooks/exhaustive-deps

  // the open position's levels
  useEffect(() => {
    const x = s.current
    if (!x || !pos) return
    const lines: IPriceLine[] = [x.candles.createPriceLine({ price: pos.entry, color: pal.accent, lineWidth: 1, lineStyle: LineStyle.Solid, axisLabelVisible: true, title: pos.side === 'LONG' ? 'Long' : 'Short' })]
    if (pos.stop != null) lines.push(x.candles.createPriceLine({ price: pos.stop, color: pal.loss, lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: 'Stop' }))
    if (pos.target != null) lines.push(x.candles.createPriceLine({ price: pos.target, color: pal.profit, lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: 'Target' }))
    return () => { for (const l of lines) { try { x.candles.removePriceLine(l) } catch { /* series gone */ } } }
  }, [pos, pal, data])

  // blind: no dates on the axis or the crosshair
  useEffect(() => {
    if (!chart) return
    chart.applyOptions(blind
      ? { timeScale: { tickMarkFormatter: (t: Time) => (intraday ? hhmm(t) : '') }, localization: { timeFormatter: (t: Time) => (intraday ? hhmm(t) : '') } }
      : { timeScale: { tickMarkFormatter: (t: Time, type: number) => tickMarkLabel(t, type) }, localization: { timeFormatter: crosshairTimeLabel } })
  }, [chart, blind, intraday, version])

  return <div ref={ref} style={{ height }} className="w-full" />
}
