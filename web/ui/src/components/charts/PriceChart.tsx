// Candlestick chart with native v5 panes (spec 3.6 / 5.2): pane 0 candles + MAs + Bollinger + volume overlay
// (priceScaleId '' with scaleMargins top 0.8); pane 1 RSI 14 with 30/70 lines; pane 2 MACD (optional).
// Markers via createSeriesMarkers; price lines for model/order/your stops; crosshair legend with OHLC.

import { forwardRef, useEffect, useImperativeHandle, useMemo, useRef, useState } from 'react'
import {
  CandlestickSeries, HistogramSeries, LineSeries, LineStyle, PriceScaleMode, createSeriesMarkers, type IChartApi,
  type ISeriesApi, type MouseEventParams, type Time,
} from 'lightweight-charts'
import type { ChartMarker, ChartResponse, IndicatorId, PriceLine } from '@/api/types'
import { toCandles, toLine, toMarkers, toSignedHistogram, toVolume } from '@/lib/chartMappers'
import type { PatternDrawing } from '@/lib/patternDrawing'
import { inrAxisPrice, palette } from '@/lib/chartTheme'
import { cn } from '@/lib/csv'
import { date, num, ok, pct, price, qty } from '@/lib/format'
import { useWidth } from '@/lib/useWidth'
import { useLwChart } from './useLwChart'

export interface PriceChartHandle { screenshot: () => HTMLCanvasElement | null; chart: () => IChartApi | null; series: () => ISeriesApi<'Candlestick'> | null }

/** A horizontal level drawn across the chart (support / resistance, pivots, option walls, expected range). */
export interface ChartOverlay {
  price: number; label: string
  tone: 'profit' | 'loss' | 'accent' | 'warn' | 'violet' | 'info' | 'muted' | 'faint'
  style?: 'solid' | 'dashed' | 'dotted'; width?: 1 | 2 | 3; axis?: boolean
}
/** The latest live price: updates (or opens) today's candle without rebuilding the chart. */
export interface LiveTick { date: string; price: number }
const LINE_STYLE = { solid: LineStyle.Solid, dashed: LineStyle.Dashed, dotted: LineStyle.Dotted } as const

export interface PriceChartProps {
  data: ChartResponse
  indicators: Set<string>
  markerStrategies: Set<string> | null
  showLines: boolean
  log: boolean
  height: number
  /** Phones: a one-line legend (symbol, date, close, change) so it doesn't cover the candles. */
  compactLegend?: boolean
  overlays?: ChartOverlay[]
  /** Markers added by the page (candle / chart patterns): drawn with the strategy markers. */
  extraMarkers?: ChartMarker[]
  /** Chart patterns drawn on the candles (lib/patternDrawing): shape, lines, target / void levels, labels. */
  drawings?: PatternDrawing[]
  live?: LiveTick | null
}

const LINE_COLOR: Partial<Record<IndicatorId, 'warn' | 'accent' | 'violet' | 'info' | 'muted' | 'profit' | 'loss' | 'fg'>> = {
  sma20: 'warn', sma50: 'accent', sma200: 'violet', ema21: 'info', bb_upper: 'muted', bb_mid: 'muted', bb_lower: 'muted',
  ema9: 'info', ema50: 'accent', ema200: 'violet', sma100: 'muted', supertrend: 'warn', dc_upper: 'profit', dc_lower: 'loss',
  kc_upper: 'info', kc_mid: 'info', kc_lower: 'info',
}
const LABEL: Partial<Record<IndicatorId, string>> = {
  sma20: 'SMA 20', sma50: 'SMA 50', sma200: 'SMA 200', ema21: 'EMA 21', bb_upper: 'BB up', bb_mid: 'BB mid', bb_lower: 'BB low',
  ema9: 'EMA 9', ema50: 'EMA 50', ema200: 'EMA 200', sma100: 'SMA 100', supertrend: 'Supertrend',
}
/** Price-pane lines: [indicator, the menu item that switches it on] */
const OVERLAYS: [IndicatorId, string][] = [
  ['sma20', 'sma20'], ['sma50', 'sma50'], ['sma100', 'sma100'], ['sma200', 'sma200'], ['ema9', 'ema9'], ['ema21', 'ema21'],
  ['ema50', 'ema50'], ['ema200', 'ema200'], ['bb_upper', 'bb_mid'], ['bb_mid', 'bb_mid'], ['bb_lower', 'bb_mid'],
  ['supertrend', 'supertrend'], ['dc_upper', 'donchian'], ['dc_lower', 'donchian'], ['kc_upper', 'keltner'], ['kc_mid', 'keltner'], ['kc_lower', 'keltner'],
]
type Tone = 'accent' | 'warn' | 'profit' | 'loss' | 'fg' | 'info'
/** Oscillator panes below the price, in this order: the series, their colours, reference lines and a fixed range. */
export const OSCILLATORS: { id: string; label: string; series: [IndicatorId, Tone][]; lines?: number[]; range?: [number, number] }[] = [
  { id: 'stoch', label: 'Stochastic 14, 3', series: [['stoch_k', 'accent'], ['stoch_d', 'warn']], lines: [20, 80], range: [0, 100] },
  { id: 'adx', label: 'ADX 14 (+DI / -DI)', series: [['adx14', 'fg'], ['plus_di', 'profit'], ['minus_di', 'loss']], lines: [25] },
  { id: 'atr', label: 'ATR 14', series: [['atr14', 'accent']] },
  { id: 'obv', label: 'On-balance volume', series: [['obv', 'accent']] },
  { id: 'cci', label: 'CCI 20', series: [['cci20', 'accent']], lines: [-100, 100] },
  { id: 'mfi', label: 'Money flow 14', series: [['mfi14', 'accent']], lines: [20, 80], range: [0, 100] },
  { id: 'willr', label: 'Williams %R 14', series: [['willr14', 'accent']], lines: [-80, -20], range: [-100, 0] },
  { id: 'roc', label: 'Rate of change 12', series: [['roc12', 'accent']], lines: [0] },
]

export const PriceChart = forwardRef<PriceChartHandle, PriceChartProps>(function PriceChart({ data, indicators, markerStrategies, showLines, log, height, compactLegend, overlays, extraMarkers, drawings, live }, handle) {
  const { ref, chart, version } = useLwChart()
  const [candleSeries, setCandleSeries] = useState<ISeriesApi<'Candlestick'> | null>(null)
  const liveBar = useRef<{ t: string; o: number; h: number; l: number } | null>(null)
  const pal = useMemo(() => palette(), [version]) // eslint-disable-line react-hooks/exhaustive-deps
  const [hoverIdx, setHoverIdx] = useState<number | null>(null)
  // The full two-row legend needs ~700 px; on a narrower chart (phone, split window, side panel open) it wrapped to
  // 3-4 lines over the candles, so the one-line legend is used there.
  const [boxRef, boxW] = useWidth<HTMLDivElement>()
  const compact = compactLegend || (boxW > 0 && boxW < 700)

  useImperativeHandle(handle, () => ({ screenshot: () => (chart ? chart.takeScreenshot() : null), chart: () => chart, series: () => candleSeries }), [chart, candleSeries])

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
    liveBar.current = null
    chart.priceScale('right', 0).applyOptions({ mode: log ? PriceScaleMode.Logarithmic : PriceScaleMode.Normal, scaleMargins: { top: 0.08, bottom: indicators.has('volume') && data.kind !== 'index' ? 0.22 : 0.06 } })

    if (indicators.has('volume') && data.kind !== 'index') {
      const vol = chart.addSeries(HistogramSeries, { priceScaleId: '', priceFormat: { type: 'volume' }, priceLineVisible: false, lastValueVisible: false }, 0)
      vol.priceScale().applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } })
      vol.setData(toVolume(data.bars, { up: pal.up, down: pal.down, upVol: pal.upVol, downVol: pal.downVol }))
      created.push(vol)
    }

    for (const [id, menu] of OVERLAYS) {
      const on = indicators.has(menu)
      const v = data.indicators[id]
      if (!on || !v) continue
      const color = pal[LINE_COLOR[id] ?? 'muted']
      const dashed = id.startsWith('bb_') || id.startsWith('kc_') || id.startsWith('dc_')
      const s = chart.addSeries(LineSeries, {
        color, lineWidth: id === 'supertrend' ? 2 : 1, lineStyle: dashed ? LineStyle.Dashed : id === 'supertrend' ? LineStyle.Dotted : LineStyle.Solid, priceLineVisible: false,
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
      pane++
    }
    for (const o of OSCILLATORS) {
      if (!indicators.has(o.id) || !o.series.every(([k]) => data.indicators[k])) continue
      o.series.forEach(([k, tone], j) => {
        const s = chart.addSeries(LineSeries, { color: pal[tone], lineWidth: 1, priceLineVisible: false, lastValueVisible: j === 0, crosshairMarkerVisible: false, title: j === 0 ? o.label : '' }, pane)
        s.setData(toLine(t, data.indicators[k]!))
        if (j === 0) {
          for (const lv of o.lines ?? []) s.createPriceLine({ price: lv, color: pal.faint, lineStyle: LineStyle.Dashed, lineWidth: 1, axisLabelVisible: false, title: '' })
          s.priceScale().applyOptions({ mode: PriceScaleMode.Normal, scaleMargins: { top: 0.1, bottom: 0.1 } })
          if (o.range) s.applyOptions({ autoscaleInfoProvider: () => ({ priceRange: { minValue: o.range![0], maxValue: o.range![1] } }) })
        }
        created.push(s)
      })
      pane++
    }
    const panes = chart.panes()
    panes[0]?.setStretchFactor(1)
    for (let i = 1; i < panes.length; i++) panes[i].setStretchFactor(0.28)

    const allMarkers = extraMarkers?.length ? [...data.markers, ...extraMarkers.filter((m) => data.bars.t.includes(m.t))] : data.markers
    const markers = createSeriesMarkers(candles, toMarkers(allMarkers, { profit: pal.profit, loss: pal.loss, neutral: pal.muted, warn: pal.warn }, markerStrategies ?? undefined))
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
    setCandleSeries(candles)

    const index = new Map(t.map((d, i) => [d, i]))
    const onMove = (p: MouseEventParams<Time>) => setHoverIdx(p.time && typeof p.time === 'string' ? index.get(p.time) ?? null : null)
    chart.subscribeCrosshairMove(onMove)
    return () => {
      chart.unsubscribeCrosshairMove(onMove)
      markers.detach()
      setCandleSeries(null)
      for (const s of created) chart.removeSeries(s)
    }
  }, [chart, data, indicators, markerStrategies, showLines, log, pal, showRsi, showMacd, extraMarkers])

  // Levels are their own price lines: toggling them never rebuilds the chart or resets the zoom.
  useEffect(() => {
    if (!candleSeries || !overlays?.length) return
    const made = overlays.map((o) => candleSeries.createPriceLine({
      price: o.price, color: pal[o.tone], lineWidth: o.width ?? 1, lineStyle: LINE_STYLE[o.style ?? 'dashed'],
      axisLabelVisible: o.axis ?? true, title: o.label,
    }))
    return () => {
      for (const l of made) {
        try { candleSeries.removePriceLine(l) } catch { /* the series went with a rebuild */ }
      }
    }
  }, [candleSeries, overlays, pal])

  // Chart patterns: one line series per drawn line on the candle pane, after the candles (so on top of them). They
  // never move the price scale (a far target stays off-screen rather than squashing the candles), and toggling them
  // never rebuilds the chart or resets the zoom.
  useEffect(() => {
    if (!chart || !candleSeries || !drawings?.length) return
    const made: ISeriesApi<'Line'>[] = []
    const prims: { detach: () => void }[] = []
    for (const d of drawings) {
      for (const ln of d.lines) {
        if (ln.points.length < 2) continue
        const color = pal[ln.tone]
        const s = chart.addSeries(LineSeries, {
          color, lineWidth: ln.width, lineStyle: LINE_STYLE[ln.style], priceLineVisible: false, lastValueVisible: false,
          crosshairMarkerVisible: false, autoscaleInfoProvider: () => null,
        }, 0)
        s.setData(ln.points.map((p) => ({ time: p.t as Time, value: p.v })))
        if (ln.axisLabel) {
          s.createPriceLine({ price: ln.points[0].v, color, lineVisible: false, axisLabelVisible: true, title: ln.axisLabel, lineWidth: 1, lineStyle: LINE_STYLE[ln.style] })
        }
        made.push(s)
        if (ln.labels.length) {
          prims.push(createSeriesMarkers(s, ln.labels.map((l, k) => ({
            id: `${ln.id}:${k}`, time: l.t as Time, position: l.position, price: l.price, shape: 'circle' as const, color, text: l.text,
            size: ln.role === 'shape' ? 0.5 : 0.01,
          }))))
        }
      }
    }
    return () => {
      for (const p of prims) {
        try { p.detach() } catch { /* the series went with a rebuild */ }
      }
      for (const s of made) {
        try { chart.removeSeries(s) } catch { /* the series went with a rebuild */ }
      }
    }
  }, [chart, candleSeries, drawings, pal])

  // Live price: update the last candle when it is today's, else open today's candle from the last close.
  useEffect(() => {
    if (!candleSeries || !live || data.tf !== '1d') return
    const t = data.bars.t
    const n = t.length
    if (!n || live.date < t[n - 1]) return
    let bar = liveBar.current
    if (!bar || bar.t !== live.date) {
      bar = live.date === t[n - 1]
        ? { t: live.date, o: data.bars.o[n - 1], h: data.bars.h[n - 1], l: data.bars.l[n - 1] }
        : { t: live.date, o: data.bars.c[n - 1], h: data.bars.c[n - 1], l: data.bars.c[n - 1] }
    }
    bar = { ...bar, h: Math.max(bar.h, live.price), l: Math.min(bar.l, live.price) }
    liveBar.current = bar
    try {
      candleSeries.update({ time: bar.t as Time, open: bar.o, high: bar.h, low: bar.l, close: live.price })
    } catch { /* an older bar than the series' last: ignored */ }
  }, [candleSeries, live, data])

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
            {(['sma20', 'sma50', 'sma100', 'sma200', 'ema9', 'ema21', 'ema50', 'ema200', 'supertrend'] as IndicatorId[]).filter((k) => indicators.has(k) && data.indicators[k]).map((k) => (
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
