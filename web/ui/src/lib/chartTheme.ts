// lightweight-charts theme built from the CSS tokens at runtime (spec 4.6), re-applied on theme change.
//
// Time handling: daily/weekly series use 'YYYY-MM-DD' strings (no timezone shift). Intraday series use the IST wall
// clock expressed as a UTC timestamp (epoch of IST + 19800 s) so the axis reads 09:15-15:30 with no timezone code;
// see toLwcTime() in chartMappers.ts.

import { ColorType, CrosshairMode, LineStyle, type DeepPartial, type ChartOptions, type Time } from 'lightweight-charts'
import { MONTH_SHORT } from './format'

/** Parts of a chart time: 'YYYY-MM-DD' strings, BusinessDay objects, or IST-as-UTC timestamps (intraday). */
function timeParts(t: Time): { y: number; m: number; d: number; hh?: number; mm?: number } | null {
  if (typeof t === 'number') {
    const x = new Date(t * 1000)
    return { y: x.getUTCFullYear(), m: x.getUTCMonth() + 1, d: x.getUTCDate(), hh: x.getUTCHours(), mm: x.getUTCMinutes() }
  }
  if (typeof t === 'string') {
    const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(t)
    return m ? { y: +m[1], m: +m[2], d: +m[3] } : null
  }
  return { y: t.year, m: t.month, d: t.day }
}
const pad2 = (n: number) => String(n).padStart(2, '0')

/** Time-axis labels with the app's 3-letter months (the en-IN locale writes September as 'Sept'). */
export function tickMarkLabel(t: Time, type: number): string | null {
  const p = timeParts(t)
  if (!p) return null
  if (type === 0) return String(p.y)                       // TickMarkType.Year
  if (type === 1) return MONTH_SHORT[p.m - 1]              // TickMarkType.Month
  if (type === 2 || p.hh == null) return String(p.d)       // TickMarkType.DayOfMonth
  return `${pad2(p.hh)}:${pad2(p.mm ?? 0)}`                // Time / TimeWithSeconds (intraday)
}

/** Crosshair time label: "22 Sep '26" (+ " 09:15" on intraday bars). */
export function crosshairTimeLabel(t: Time): string {
  const p = timeParts(t)
  if (!p) return ''
  const base = `${p.d} ${MONTH_SHORT[p.m - 1]} '${String(p.y).slice(2)}`
  return typeof t === 'number' && p.hh != null && (p.hh || p.mm) ? `${base} ${pad2(p.hh)}:${pad2(p.mm ?? 0)}` : base
}

export type Token =
  | 'bg' | 'panel' | 'raised' | 'line' | 'line-strong' | 'fg' | 'muted' | 'faint' | 'accent' | 'profit' | 'loss' | 'warn'
  | 'info' | 'violet' | 'candle-up' | 'candle-down'

/** rgb()/rgba() string for a token, read from the live CSS variables. */
export function tok(name: Token, alpha = 1): string {
  const raw = getComputedStyle(document.documentElement).getPropertyValue(`--${name}`).trim() || '128 128 128'
  const [r, g, b] = raw.split(/\s+/).map(Number)
  return alpha >= 1 ? `rgb(${r}, ${g}, ${b})` : `rgba(${r}, ${g}, ${b}, ${alpha})`
}

const IN0 = new Intl.NumberFormat('en-IN', { maximumFractionDigits: 0 })
const IN2 = new Intl.NumberFormat('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
/** Indian-grouped axis price (₹ symbol left off to keep the axis narrow). Use as a series' custom priceFormat. */
export const inrAxisPrice = (p: number) => (Math.abs(p) >= 1000 ? IN0 : IN2).format(p).replace('-', '−')

// No localization.priceFormatter here: lightweight-charts would use it for EVERY price scale and ignore each
// series' own priceFormat (the ₹ / % / × equity modes, breadth %). Series set their own formatter instead.
export function chartOptions(): DeepPartial<ChartOptions> {
  return {
    autoSize: true,
    layout: {
      background: { type: ColorType.Solid, color: tok('panel') },
      textColor: tok('muted'),
      fontFamily: '"Inter Variable", Inter, system-ui, sans-serif',
      fontSize: 11,
      attributionLogo: true,
      panes: { separatorColor: tok('line'), separatorHoverColor: tok('line-strong'), enableResize: true },
    },
    grid: {
      vertLines: { color: tok('line', 0.5) },
      horzLines: { color: tok('line', 0.5) },
    },
    crosshair: {
      mode: CrosshairMode.Normal,
      vertLine: { color: tok('line-strong'), width: 1, style: LineStyle.Dashed, labelBackgroundColor: tok('raised') },
      horzLine: { color: tok('line-strong'), width: 1, style: LineStyle.Dashed, labelBackgroundColor: tok('raised') },
    },
    rightPriceScale: { borderColor: tok('line'), scaleMargins: { top: 0.08, bottom: 0.08 } },
    leftPriceScale: { borderColor: tok('line') },
    // minBarSpacing 0.1 (default 0.5): 'Max' on daily bars (~2,000) must fit a ~800 px pane, or fitContent cuts 2018-20
    timeScale: {
      borderColor: tok('line'), rightOffset: 4, fixLeftEdge: true, fixRightEdge: false, lockVisibleTimeRangeOnResize: true, minBarSpacing: 0.1,
      tickMarkFormatter: (t: Time, type: number) => tickMarkLabel(t, type),
    },
    localization: { locale: 'en-IN', timeFormatter: crosshairTimeLabel },
    handleScale: { axisPressedMouseMove: { time: true, price: true } },
  }
}

export const palette = () => ({
  accent: tok('accent'),
  muted: tok('muted'),
  faint: tok('faint'),
  warn: tok('warn'),
  violet: tok('violet'),
  info: tok('info'),
  profit: tok('profit'),
  loss: tok('loss'),
  fg: tok('fg'),
  up: tok('candle-up'),
  down: tok('candle-down'),
  upVol: tok('candle-up', 0.45),
  downVol: tok('candle-down', 0.45),
  lossFill: tok('loss', 0.22),
  lossFill0: tok('loss', 0.02),
  accentFill: tok('accent', 0.18),
  accentFill0: tok('accent', 0.0),
})
