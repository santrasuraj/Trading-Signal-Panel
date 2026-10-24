// Candlestick chart with native v5 panes (spec 3.6 / 5.2): pane 0 candles + MAs + Bollinger + volume overlay
// (priceScaleId '' with scaleMargins top 0.8); pane 1 RSI 14 with 30/70 lines; pane 2 MACD (optional).
// Markers via createSeriesMarkers; price lines for model/order/your stops; crosshair legend with OHLC.

import { forwardRef, useEffect, useImperativeHandle, useMemo, useState } from 'react'
import {
  CandlestickSeries, HistogramSeries, LineSeries, LineStyle, PriceScaleMode, createSeriesMarkers, type IChartApi,
  type ISeriesApi, type MouseEventParams, type Time,
} from 'lightweight-charts'
import type { ChartResponse, IndicatorId, PriceLine } from '@/api/types'
import { toCandles, toLine, toMarkers, toSignedHistogram, toVolume } from '@/lib/chartMappers'
import { inrAxisPrice, palette } from '@/lib/chartTheme'
import { cn } from '@/lib/csv'
import { date, num, ok, pct, price, qty } from '@/lib/format'
import { useWidth } from '@/lib/useWidth'
import { useLwChart } from './useLwChart'

export interface PriceChartHandle { screenshot: () => HTMLCanvasElement | null; chart: () => IChartApi | null }

export interface PriceChartProps {
  data: ChartResponse
  indicators: Set<IndicatorId | 'volume'>
  markerStrategies: Set<string> | null
  showLines: boolean
  log: boolean
  height: number
  /** Phones: a one-line legend (symbol, date, close, change) so it doesn't cover the candles. */
  compactLegend?: boolean
}

const LINE_COLOR: Partial<Record<IndicatorId, 'warn' | 'accent' | 'violet' | 'info' | 'muted'>> = {
  sma20: 'warn', sma50: 'accent', sma200: 'violet', ema21: 'info', bb_upper: 'muted', bb_mid: 'muted', bb_lower: 'muted',
}
const LABEL: Partial<Record<IndicatorId, string>> = { sma20: 'SMA 20', sma50: 'SMA 50', sma200: 'SMA 200', ema21: 'EMA 21', bb_upper: 'BB up', bb_mid: 'BB mid', bb_lower: 'BB low' }

export const PriceChart = forwardRef<PriceChartHandle, PriceChartProps>(function PriceChart({ data, indicators, markerStrategies, showLines, log, height, compactLegend }, handle) {
  const { ref, chart, version } = useLwChart()
  const pal = useMemo(() => palette(), [version]) // eslint-disable-line react-hooks/exhaustive-deps
  const [hoverIdx, setHoverIdx] = useState<number | null>(null)
  // The full two-row legend needs ~700 px; on a narrower chart (phone, split window, side panel open) it wrapped to
  // 3-4 lines over the candles, so the one-line legend is used there.
  const [boxRef, boxW] = useWidth<HTMLDivElement>()
  const compact = compactLegend || (boxW > 0 && boxW < 700)

  useImperativeHandle(handle, () => ({ screenshot: () => (chart ? chart.takeScreenshot() : null), chart: () => chart }), [chart])

  const showRsi = indicators.has('rsi14') && !!data.indicators.rsi14
  const showMacd = indicators.has('macd') && !!data.indicators.macd

  useEffect(() => {
    if (!chart) return
    const created: ISeriesApi<'Line' | 'Candlestick' | 'Histogram'>[] = []
    const t = data.bars.t
    const candles = chart.addSeries(CandlestickSeries, {
      upColor: pal.up, downColor: pal.down, borderUpColor: pal.up, borderDownColor: pal.down, wickUpColor: pal.up, wickDownColor: pal.down,
      priceLineVisible: true, priceLineColor: pal.faint, priceLineStyle: LineStyle.Dotted,
      priceFormat: { type: 'custom', formatter: inrAxisPrice, minMove: 0.01 },
    }, 0)
    candles.setData(toCandles(data.bars))
    created.push(candles)
    chart.priceScale('right', 0).applyOptions({ mode: log ? PriceScaleMode.Logarithmic : PriceScaleMode.Normal, scaleMargins: { top: 0.08, bottom: indicators.has('volume') && data.kind !== 'index' ? 0.22 : 0.06 } })

    if (indicators.has('volume') && data.kind !== 'index') {
      const vol = chart.addSeries(HistogramSeries, { priceScaleId: '', priceFormat: { type: 'volume' }, priceLineVisible: false, lastValueVisible: false }, 0)
      vol.priceScale().applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } })
      vol.setData(toVolume(data.bars, { up: pal.up, down: pal.down, upVol: pal.upVol, downVol: pal.downVol }))
      created.push(vol)
    }

    for (const id of ['sma20', 'sma50', 'sma200', 'ema21', 'bb_upper', 'bb_mid', 'bb_lower'] as IndicatorId[]) {
      const on = id.startsWith('bb_') ? indicators.has('bb_mid') : indicators.has(id)
      const v = data.indicators[id]
      if (!on || !v) continue
      const color = pal[LINE_COLOR[id] ?? 'muted']
      const s = chart.addSeries(LineSeries, {
        color, lineWidth: 1, lineStyle: id.startsWith('bb_') ? LineStyle.Dashed : LineStyle.Solid, priceLineVisible: false,
        lastValueVisible: false, crosshairMarkerVisible: false,
      }, 0)
      s.setData(toLine(t, v))
      created.push(s)
    }

    let pane = 1
    if (showRsi) {
      const r = chart.addSeries(LineSeries, { color: pal.accent, lineWidth: 1, priceLineVisible: false, lastValueVisible: true, crosshairMarkerRadius: 3 }, pane)
      r.setData(toLine(t, data.indicators.rsi14!))
      r.createPriceLine({ price: 70, color: pal.faint, lineStyle: LineStyle.Dashed, lineWidth: 1, axisLabelVisible: false, title: '' })
      r.createPriceLine({ price: 30, color: pal.faint, lineStyle: LineStyle.Dashed, lineWidth: 1, axisLabelVisible: false, title: '' })
      // explicit Normal: the log mode of pane 0's 'right' scale is copied into panes created after it (RSI is 0-100)
      r.priceScale().applyOptions({ mode: PriceScaleMode.Normal, autoScale: false, scaleMargins: { top: 0.1, bottom: 0.1 } })
      r.applyOptions({ autoscaleInfoProvider: () => ({ priceRange: { minValue: 0, maxValue: 100 } }) })
      created.push(r)
      pane++
    }
    if (showMacd) {
      const h = chart.addSeries(HistogramSeries, { priceLineVisible: false, lastValueVisible: false }, pane)
      h.setData(toSignedHistogram(t, data.indicators.macd_hist ?? [], pal.upVol, pal.downVol))
      const m = chart.addSeries(LineSeries, { color: pal.accent, lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false }, pane)
      m.setData(toLine(t, data.indicators.macd!))
      const sg = chart.addSeries(LineSeries, { color: pal.warn, lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false }, pane)
      sg.setData(toLine(t, data.indicators.macd_signal ?? []))
      h.priceScale().applyOptions({ mode: PriceScaleMode.Normal })     // MACD is negative half the time: never log
      created.push(h, m, sg)
    }
    const panes = chart.panes()
    panes[0]?.setStretchFactor(1)
    for (let i = 1; i < panes.length; i++) panes[i].setStretchFactor(0.28)

    const markers = createSeriesMarkers(candles, toMarkers(data.markers, { profit: pal.profit, loss: pal.loss, neutral: pal.muted, warn: pal.warn }, markerStrategies ?? undefined))
    if (showLines) {
      const tone = (k: PriceLine['kind']) => (k.includes('stop') ? pal.loss : k === 'your_target' ? pal.profit : k === 'high_52w' || k === 'low_52w' ? pal.faint : pal.accent)
      for (const pl of data.price_lines) {
        if (pl.strategy_key && markerStrategies && !markerStrategies.has(pl.strategy_key)) continue
        candles.createPriceLine({
          price: pl.price, color: tone(pl.kind), lineWidth: 1, lineStyle: pl.kind.startsWith('your') ? LineStyle.Solid : LineStyle.Dashed,
          axisLabelVisible: !pl.kind.endsWith('52w'), title: pl.label,
        })
      }
    }
    chart.timeScale().fitContent()

    const index = new Map(t.map((d, i) => [d, i]))
    const onMove = (p: MouseEventParams<Time>) => setHoverIdx(p.time && typeof p.time === 'string' ? index.get(p.time) ?? null : null)
    chart.subscribeCrosshairMove(onMove)
    return () => {
      chart.unsubscribeCrosshairMove(onMove)
      markers.detach()
      for (const s of created) chart.removeSeries(s)
    }
  }, [chart, data, indicators, markerStrategies, showLines, log, pal, showRsi, showMacd])

  const i = hoverIdx ?? data.bars.t.length - 1
  const b = data.bars
  const prev = i > 0 ? b.c[i - 1] : null
  const chg = ok(prev) && prev ? (b.c[i] / prev - 1) * 100 : null
  const volAvg = data.indicators.vol_avg20?.[i]
  const up = b.c[i] >= b.o[i]
  return (
    <div ref={boxRef} className="relative" style={{ height }}>
      <div ref={ref} className="absolute inset-0" />
      {b.t.length > 0 && (
        <div className="pointer-events-none absolute left-3 top-2 z-10 max-w-[calc(100%-96px)] space-y-0.5 rounded bg-panel/80 px-1.5 py-0.5 text-2xs">
          {compact ? (
            <div className="flex items-center gap-x-2 whitespace-nowrap">
              <span className="font-semibold text-fg">{data.symbol}</span>
              <span className="num text-muted">{date(b.t[i], { year: false })}</span>
              <span className="num"><span className="text-faint">C</span> <span className={up ? 'text-profit' : 'text-loss'}>{price(b.c[i])}</span></span>
              <span className={cn('num', chg == null ? 'text-muted' : chg >= 0 ? 'text-profit' : 'text-loss')}>{pct(chg, { dp: 2 })}</span>
            </div>
          ) : (<>
          <div className="flex flex-wrap items-center gap-x-2.5">
            <span className="font-semibold text-fg">{data.symbol}</span>
            <span className="text-faint">NSE · {data.tf === '1w' ? '1W' : '1D'}</span>
            <span className="num text-muted">{date(b.t[i])}</span>
            {(['o', 'h', 'l', 'c'] as const).map((k) => (
              <span key={k} className="num"><span className="text-faint">{k.toUpperCase()}</span> <span className={up ? 'text-profit' : 'text-loss'}>{price(b[k][i])}</span></span>
            ))}
            <span className={cn('num', chg == null ? 'text-muted' : chg >= 0 ? 'text-profit' : 'text-loss')}>{pct(chg, { dp: 2 })}</span>
            {data.kind !== 'index' && (
              <span className="num text-muted">Vol {qty(b.v[i])}{ok(volAvg) && volAvg > 0 ? <span className="text-faint"> · {num(b.v[i] / volAvg, 1)}× avg</span> : null}</span>
            )}
          </div>
          <div className="flex flex-wrap items-center gap-x-2.5">
            {(['sma20', 'sma50', 'sma200', 'ema21'] as IndicatorId[]).filter((k) => indicators.has(k) && data.indicators[k]).map((k) => (
              <span key={k} className="num"><span style={{ color: pal[LINE_COLOR[k] ?? 'muted'] }}>{LABEL[k]}</span> <span className="text-fg">{price(data.indicators[k]![i])}</span></span>
            ))}
            {showRsi && <span className="num"><span className="text-accent">RSI 14</span> <span className="text-fg">{num(data.indicators.rsi14![i], 1)}</span></span>}
            {showMacd && <span className="num"><span className="text-accent">MACD</span> <span className="text-fg">{num(data.indicators.macd![i], 2)}</span> <span className="text-warn">{num(data.indicators.macd_signal?.[i], 2)}</span></span>}
          </div>
          </>)}
        </div>
      )}
    </div>
  )
})
