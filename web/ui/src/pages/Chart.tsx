// Chart `/chart/:symbol` (spec 3.6): lightweight-charts v5 panes (candles + MAs + Bollinger + volume, RSI, MACD),
// strategy markers, price lines, crosshair legend; right panel with the stock snapshot.

import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { Camera, ChevronDown, ChevronLeft, ChevronRight, Layers, PanelRightClose, PanelRightOpen, Ruler, Search, SlidersHorizontal } from 'lucide-react'
import { useChart, useLiveQuotes, useStock, useSymbols } from '@/api/hooks'
import { useLevels, type LvChartPattern } from '@/api/levels'
import { useOutlook } from '@/api/outlook'
import type { ChartMarker, ChartRange, ChartTf, IndicatorId } from '@/api/types'
import { useUi } from '@/app/uiState'
import { LevelPill, ResultsChip, StatusDot } from '@/components/badges'
import { OSCILLATORS, PriceChart, type ChartOverlay, type LiveTick, type PriceChartHandle } from '@/components/charts/PriceChart'
import { AiAnalyst } from '@/components/AiAnalyst'
import { BigMoneyCard } from '@/components/BigMoney'
import { ChartOptions } from '@/components/ChartOptions'
import { VERDICT_STYLE } from '@/lib/verdict'
import { OutlookPanel } from '@/components/Outlook'
import { RangeBar52w } from '@/components/charts/svg'
import { ErrorState, Skeleton, SkeletonChart } from '@/components/feedback'
import { Money, Pct, Price } from '@/components/num'
import { SmartMoneyPanel } from '@/components/SmartMoneyPanel'
import { Button, Card, IconButton, KV, MenuCheck, Popover, Segmented, Switch } from '@/components/ui'
import { cn } from '@/lib/csv'
import { date, daysBetween, num, pct, price, qty, todayIST } from '@/lib/format'
import { patternDrawings, patternTone } from '@/lib/patternDrawing'
import { useLocalStorage } from '@/lib/useLocalStorage'
import { typingTarget, useIsMobile } from '@/lib/useMedia'
import { EvidenceBadge, PriceAction } from '@/components/PriceAction'
import { PriceStamp } from '@/components/LivePrice'
import { ActionPanel } from '@/components/ActionCard'
import { IntradayChart } from '@/components/charts/IntradayChart'
import { WatchButton, AlertButton } from '@/components/WatchButtons'
import { useDrawings, useIntradayChart, type IntradayTf } from '@/api/watch'
import { DrawTools } from '@/components/DrawTools'
import { levelOverlays, lineDrawings } from '@/lib/userDrawings'

const RANGES: ChartRange[] = ['3m', '6m', '1y', '2y', '5y', 'max']
type Ind = IndicatorId | 'volume' | 'donchian' | 'keltner' | 'stoch' | 'adx' | 'atr' | 'obv' | 'cci' | 'mfi' | 'willr' | 'roc'
const IND_MENU: { id: Ind; label: string }[] = [
  { id: 'sma20', label: 'SMA 20' }, { id: 'sma50', label: 'SMA 50' }, { id: 'sma100', label: 'SMA 100' }, { id: 'sma200', label: 'SMA 200' },
  { id: 'ema9', label: 'EMA 9' }, { id: 'ema21', label: 'EMA 21' }, { id: 'ema50', label: 'EMA 50' }, { id: 'ema200', label: 'EMA 200' },
  { id: 'bb_mid', label: 'Bollinger 20, 2' }, { id: 'keltner', label: 'Keltner 20, 2 ATR' }, { id: 'donchian', label: 'Donchian 20' },
  { id: 'supertrend', label: 'Supertrend 10, 3' }, { id: 'volume', label: 'Volume' },
]
const PANE_MENU: { id: Ind; label: string }[] = [
  { id: 'rsi14', label: 'RSI 14' }, { id: 'macd', label: 'MACD 12, 26, 9' },
  ...OSCILLATORS.map((o) => ({ id: o.id as Ind, label: o.label })),
]
const PANE_IDS = new Set<string>(PANE_MENU.map((m) => m.id))
const GROUPS: Partial<Record<Ind, IndicatorId[]>> = {
  bb_mid: ['bb_upper', 'bb_mid', 'bb_lower'], macd: ['macd', 'macd_signal', 'macd_hist'], donchian: ['dc_upper', 'dc_lower'],
  keltner: ['kc_upper', 'kc_mid', 'kc_lower'], ...Object.fromEntries(OSCILLATORS.map((o) => [o.id, o.series.map(([k]) => k)])),
}

type LevelId = 'sr' | 'pivots' | 'intraday' | 'options' | 'range' | 'chart_patterns' | 'candles'
const LEVEL_MENU: { id: LevelId; label: string; hint: string }[] = [
  { id: 'chart_patterns', label: 'Chart patterns (drawn)', hint: 'double tops / bottoms, head & shoulders, triangles, wedges, rectangles, flags: shape, lines, target (1D chart)' },
  { id: 'sr', label: 'Support & resistance', hint: 'swing highs / lows of the last year; thicker = formed more often' },
  { id: 'pivots', label: 'Pivots (next session)', hint: 'P, R1-R2, S1-S2 from the last completed day' },
  { id: 'intraday', label: 'Today: VWAP, opening range, POC', hint: 'from 5-minute bars, when the stock has them' },
  { id: 'options', label: 'Option walls & max pain', hint: 'from a current NSE option chain (F&O symbols)' },
  { id: 'range', label: 'Expected 5-day range', hint: 'options-implied when a current chain exists, else recent volatility' },
  { id: 'candles', label: 'Candle patterns', hint: 'engulfing, hammer, doji ... as markers on the last 3 bars' },
]
const LEVEL_DEFAULT: LevelId[] = ['chart_patterns', 'sr', 'intraday', 'options', 'range']
/** Saved before chart patterns were drawn, 'patterns' meant candle + chart pattern markers: now the drawn patterns. */
const levelList = (saved: string[]): LevelId[] =>
  [...new Set(saved.map((x) => (x === 'patterns' ? 'chart_patterns' : x)))].filter((x): x is LevelId => LEVEL_MENU.some((m) => m.id === x))

function apiIndicators(sel: Ind[]): IndicatorId[] {
  const out = new Set<IndicatorId>(['vol_avg20'])
  for (const s of sel) {
    if (s === 'volume') continue
    for (const k of GROUPS[s] ?? [s as IndicatorId]) out.add(k)
  }
  return [...out].sort()
}

const TONE_TEXT = { profit: 'text-profit', loss: 'text-loss', info: 'text-info', warn: 'text-warn' } as const

/** The chart patterns drawn on the chart, top right: name (in the drawing's colour), status, levels, tested record. */
function PatternLegend({ patterns, drawn, compact }: { patterns: LvChartPattern[]; drawn: boolean; compact: boolean }) {
  const chip = 'rounded bg-panel/85 px-1.5 py-0.5'
  return (
    <div className="absolute right-[76px] top-2 z-10 flex max-w-[min(380px,calc(100%-96px))] flex-col items-end gap-1 text-2xs">
      {patterns.length === 0 ? (
        <span className={cn(chip, 'pointer-events-none text-faint')}>No chart pattern on the last bars</span>
      ) : !drawn ? (
        <span className={cn(chip, 'text-muted')}>{patterns.length} chart pattern{patterns.length > 1 ? 's' : ''}: shown on the 1D chart</span>
      ) : patterns.map((p) => (
        <div key={`${p.key}:${p.start}`} title={p.what} className={cn(chip, 'flex flex-wrap items-center justify-end gap-x-1.5')}>
          <span className={cn('font-semibold', TONE_TEXT[patternTone(p)])}>{p.name}</span>
          <span className="text-muted">
            {p.status === 'confirmed' ? `confirmed${p.confirmed_bars_ago ? ` ${p.confirmed_bars_ago} bar${p.confirmed_bars_ago > 1 ? 's' : ''} ago` : ' today'}` : 'forming'}
          </span>
          {!compact && (
            <span className="num text-muted">
              {p.status === 'forming' && p.breakout != null ? `breaks at ${price(p.breakout)}` : ''}
              {p.status === 'forming' && p.breakout != null && p.target != null ? ' · ' : ''}
              {p.target != null ? `target ${price(p.target)}${p.target_pct != null ? ` (${pct(p.target_pct)})` : ''}` : ''}
              {p.invalidation != null && p.breakout != null ? ` · void ${p.invalidation < p.breakout ? 'below' : 'above'} ${price(p.invalidation)}` : ''}
            </span>
          )}
          {!compact && <EvidenceBadge e={p.evidence} />}
        </div>
      ))}
    </div>
  )
}

function SidePanel({ symbol }: { symbol: string }) {
  const q = useStock(symbol)
  const s = q.data
  const lq = useLiveQuotes([symbol])
  const live = lq.quotes[symbol]
  if (q.error) return <ErrorState error={q.error} compact />
  if (!s) return <div className="space-y-3 p-4"><Skeleton className="h-6 w-28" /><Skeleton className="h-3 w-full" /><Skeleton className="h-24 w-full" /></div>
  const today = todayIST()
  const stock = s.kind === 'stock'
  const px = live?.price ?? s.price
  const hold = s.your_holding
  const holdPnl = hold && live && hold.buy_price != null && hold.qty != null ? (live.price - hold.buy_price) * hold.qty : hold?.pnl_amount
  const holdPct = hold && live && hold.buy_price ? (live.price / hold.buy_price - 1) * 100 : hold?.pnl_pct
  // Beside the chart (xl+) one column; stacked under the chart (md to lg) two columns, so the KV rows don't stretch
  // across the whole page.
  return (
    <div className="grid md:grid-cols-2 xl:grid-cols-1">
    <div className="divide-y divide-line">
      <div className="p-4">
        <div className="flex items-baseline justify-between gap-2">
          <span className="text-[13px] font-semibold">{s.symbol}</span>
          <span className="text-2xs text-faint">{s.kind.toUpperCase()} · {date(s.data_date, { year: false })}</span>
        </div>
        <div className="mt-1 flex items-baseline gap-2">
          <span className="num text-[22px] font-semibold"><Price v={px} /></span>
          <Pct v={live ? live.change_pct : s.change_pct} dp={2} className="text-[13px]" />
        </div>
        <div className="mt-0.5"><PriceStamp q={live} session={lq.data?.session} fallbackDate={s.data_date} /></div>
        <div className="mt-0.5 line-clamp-2 text-xs text-muted" title={`${s.company ?? ''}${s.industry ? ` · ${s.industry}` : ''}`}>{s.company}{s.industry ? ` · ${s.industry}` : ''}</div>
        <div className="mt-3"><div className="mb-1 text-2xs text-muted">52-week range{s.pct_from_52w_high != null && <> · <Pct v={s.pct_from_52w_high} color={false} /> from high</>}</div><RangeBar52w low={Math.min(s.low_52w ?? px, px)} high={Math.max(s.high_52w ?? px, px)} value={px} /></div>
        {s.results_on && <div className="mt-3"><ResultsChip on={s.results_on} inDays={daysBetween(today, s.results_on)} /></div>}
      </div>
      <div className="px-4 py-2">
        {/* stock-only facts are left out for an index (they were a column of dashes) */}
        {stock && <KV k="RS (1-99)" v={num(s.rs, 0)} />}
        {stock && <KV k="Momentum rank" v={s.momentum_rank != null ? `#${s.momentum_rank}` : '—'} />}
        <KV k="1M / 3M" v={<><Pct v={s.ret_1m_pct} /> <span className="text-faint">/</span> <Pct v={s.ret_3m_pct} /></>} />
        <KV k="6M / 12M" v={<><Pct v={s.ret_6m_pct} /> <span className="text-faint">/</span> <Pct v={s.ret_12m_pct} /></>} />
        <KV k="SMA 50 / 200" v={<><Price v={s.sma50} /> <span className="text-faint">/</span> <Price v={s.sma200} /></>} />
        {(stock || s.turnover_cr != null) && <KV k="Turnover (20 d)" v={s.turnover_cr != null ? `₹${num(s.turnover_cr, 0)} cr` : '—'} />}
        {(stock || s.deliv_pct != null) && <KV k="Delivery" v={s.deliv_pct != null ? `${num(s.deliv_pct, 0)}%` : '—'} />}
        {(stock || s.vol_ratio != null) && <KV k="Volume vs avg" v={s.vol_ratio != null ? `${num(s.vol_ratio, 1)}×` : '—'} />}
      </div>
    </div>
    <div className="divide-y divide-line border-t border-line md:border-l md:border-t-0 xl:border-l-0 xl:border-t">
      <div className="p-4">
        <div className="eyebrow mb-2">In strategies</div>
        {s.strategies.length === 0 ? <div className="text-xs text-muted">Not held, ordered or ranked by any strategy.</div> : (
          <ul className="space-y-1.5">{s.strategies.map((x, i) => (
            // name on the first line, the detail (with its return) in full on the second: neither is cut
            <li key={`${x.key}${x.role}${i}`}><Link to={`/strategies/${x.key}`} title={`${x.name}: ${x.detail}`} className="group flex items-start gap-2 text-[13px]"><StatusDot status={x.status} className="mt-0.5" /><span className="min-w-0 flex-1"><span className="block truncate group-hover:underline">{x.name}</span><span className="block text-2xs text-muted">{x.detail}</span></span></Link></li>
          ))}</ul>
        )}
      </div>
      <div className="p-4">
        <div className="eyebrow mb-2">Your holding</div>
        {s.your_holding ? (
          <div className="space-y-1 text-[13px]">
            <div className="flex justify-between"><span className="text-muted">{qty(s.your_holding.qty)} @ <Price v={s.your_holding.buy_price} /></span><LevelPill level={s.your_holding.level} /></div>
            <div className="flex justify-between"><span className="text-muted">P&amp;L{live ? ' (live)' : ''}</span><span><Money v={holdPnl} signed color /> <Pct v={holdPct} /></span></div>
            {s.your_holding.alerts.map((a) => <div key={a} className="text-xs text-warn">{a}</div>)}
          </div>
        ) : <div className="text-xs text-muted">None. <Link to="/portfolio" className="link">Add holdings</Link></div>}
      </div>
      {stock && <div className="p-4"><SmartMoneyPanel symbol={s.symbol} /></div>}
      {s.corporate_actions.length > 0 && (
        <div className="p-4">
          <div className="eyebrow mb-2">Corporate actions</div>
          <ul className="space-y-1 text-xs">{s.corporate_actions.map((c) => <li key={c.date} className="flex justify-between gap-2"><span className="num shrink-0 text-muted">{date(c.date)}</span><span className="truncate" title={`${c.reason} ×${num(c.factor, 3)}`}>{c.reason} ×{num(c.factor, 3)}</span></li>)}</ul>
        </div>
      )}
    </div>
    </div>
  )
}

export default function ChartPage() {
  const { symbol: raw = 'NIFTY50' } = useParams()
  const symbol = raw.toUpperCase()
  const [sp, setSp] = useSearchParams()
  const tfRaw = (sp.get('tf') as ChartTf | IntradayTf | null) ?? '1d'
  const intraTf: IntradayTf | null = tfRaw === '1m' || tfRaw === '5m' || tfRaw === '15m' ? tfRaw : null
  const tf: ChartTf = intraTf ? '1d' : (tfRaw as ChartTf)        // the daily chart query keeps running underneath
  const range = (sp.get('range') as ChartRange | null) ?? '1y'
  const days = Math.min(20, Math.max(1, Number(sp.get('days')) || 3))
  const strategyParam = sp.get('s')
  const set = (k: string, v: string | null) => setSp((p) => { const n = new URLSearchParams(p); if (v) n.set(k, v); else n.delete(k); return n }, { replace: true })
  const mobile = useIsMobile()
  const [ind, setInd] = useLocalStorage<Ind[]>('qd.chart.ind', ['sma20', 'sma50', 'sma200', 'volume', 'rsi14'])
  const [log, setLog] = useLocalStorage('qd.chart.log', false)
  const [lines, setLines] = useLocalStorage('qd.chart.lines', true)
  const [panel, setPanel] = useLocalStorage('qd.chart.panel', true)
  const indSet = useMemo(() => new Set<string>(mobile ? ind.filter((i) => !PANE_IDS.has(i)) : ind), [ind, mobile])
  const params = useMemo(() => ({ tf, range, indicators: apiIndicators(ind) }), [tf, range, ind])
  const q = useChart(symbol, params)
  const symbols = useSymbols()
  const { setPalette } = useUi()
  const nav = useNavigate()
  const ref = useRef<PriceChartHandle>(null)
  const [lvSaved, setLvSel] = useLocalStorage<string[]>('qd.chart.levels', LEVEL_DEFAULT)
  const lvSel = useMemo(() => levelList(lvSaved), [lvSaved])
  const lvOn = useMemo(() => new Set(lvSel), [lvSel])
  const lv = useLevels(symbol).data
  const liveQ = useLiveQuotes([symbol])
  const quote = liveQ.quotes[symbol]
  const liveTick = useMemo<LiveTick | null>(() => (quote ? { date: todayIST(), price: quote.price } : null), [quote])
  const olq = useOutlook(symbol, liveQ.live)
  const iq = useIntradayChart(symbol, intraTf ?? '5m', days, !!intraTf)
  const ol = olq.data?.symbol === symbol ? olq.data : undefined

  const available = q.data?.strategies_available ?? []
  const [markerSel, setMarkerSel] = useState<string[] | null>(null)
  useEffect(() => { setMarkerSel(null) }, [symbol])
  const markerSet = useMemo(() => {
    if (markerSel) return new Set(markerSel)
    if (strategyParam && available.some((a) => a.key === strategyParam)) return new Set([strategyParam])
    return null
  }, [markerSel, strategyParam, available])

  const list = useMemo(() => symbols.data?.symbols.map((s) => s.symbol) ?? [], [symbols.data])
  const idx = list.indexOf(symbol)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (typingTarget(e) || e.ctrlKey || e.metaKey || e.altKey) return
      const n = Number(e.key)
      if (n >= 1 && n <= 6) { set('range', RANGES[n - 1] === '1y' ? null : RANGES[n - 1]); return }
      if (e.key === 'd') set('tf', null)
      if (e.key === 'w') set('tf', '1w')
      if (e.key === 'i') set('tf', '5m')
      if (e.key === '[' && idx > 0) nav(`/chart/${list[idx - 1]}?${sp.toString()}`)
      if (e.key === ']' && idx >= 0 && idx < list.length - 1) nav(`/chart/${list[idx + 1]}?${sp.toString()}`)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })

  const screenshot = () => {
    const c = ref.current?.screenshot()
    if (!c) return
    const a = document.createElement('a')
    a.href = c.toDataURL('image/png')
    a.download = `${symbol}-${tf}-${range}.png`
    a.click()
  }
  const overlays = useMemo<ChartOverlay[]>(() => {
    const out: ChartOverlay[] = []
    const dl = lv?.daily
    if (dl && lvOn.has('sr')) {
      for (const l of dl.levels.resistance) if (l.price != null) out.push({ price: l.price, label: `R ${l.touches}×`, tone: 'loss', width: l.touches >= 3 ? 2 : 1, style: 'solid' })
      for (const l of dl.levels.support) if (l.price != null) out.push({ price: l.price, label: `S ${l.touches}×`, tone: 'profit', width: l.touches >= 3 ? 2 : 1, style: 'solid' })
    }
    if (dl && lvOn.has('pivots')) {
      const pv = dl.pivots
      const add = (v: number | null, label: string, tone: ChartOverlay['tone']) => { if (v != null) out.push({ price: v, label, tone, style: 'dotted', axis: false }) }
      add(pv.r2, 'R2', 'loss'); add(pv.r1, 'R1', 'loss'); add(pv.p, 'Pivot', 'accent'); add(pv.s1, 'S1', 'profit'); add(pv.s2, 'S2', 'profit')
    }
    const it = lv?.intraday
    if (it && lvOn.has('intraday') && it.date === todayIST()) {
      if (it.vwap != null) out.push({ price: it.vwap, label: 'VWAP', tone: 'info', style: 'solid', width: 2 })
      if (it.or_high != null) out.push({ price: it.or_high, label: 'OR high', tone: 'warn', style: 'dashed', axis: false })
      if (it.or_low != null) out.push({ price: it.or_low, label: 'OR low', tone: 'warn', style: 'dashed', axis: false })
      if (it.profile?.poc != null) out.push({ price: it.profile.poc, label: 'POC', tone: 'violet', style: 'dotted', axis: false })
    }
    const ch = ol?.derivatives.chain
    if (ch && !ch.old && lvOn.has('options')) {
      if (ch.call_wall != null) out.push({ price: ch.call_wall, label: 'Call wall', tone: 'loss', width: 3, style: 'solid' })
      if (ch.put_wall != null) out.push({ price: ch.put_wall, label: 'Put wall', tone: 'profit', width: 3, style: 'solid' })
      if (ch.max_pain != null) out.push({ price: ch.max_pain, label: 'Max pain', tone: 'warn', style: 'dashed' })
    }
    const vd = ol?.derivatives.verdict
    if (vd?.pick && lvOn.has('options')) {
      const call = vd.pick.side === 'ce'
      const tag = `${num(vd.pick.strike, 0)} ${vd.pick.side.toUpperCase()}`
      if (vd.pick.breakeven != null) out.push({ price: vd.pick.breakeven, label: `Breakeven ${tag}`, tone: call ? 'profit' : 'loss', width: 2, style: 'dashed' })
      if (vd.exit?.stop_underlying != null) out.push({ price: vd.exit.stop_underlying, label: `Stop (${tag})`, tone: 'loss', style: 'dotted' })
      if (vd.exit?.target_underlying != null) out.push({ price: vd.exit.target_underlying, label: `Target (${tag})`, tone: 'profit', style: 'dotted' })
    }
    if (ol && lvOn.has('range')) {
      const r = ol.expected.ranges.find((x) => x.days === 5 && x.source === 'options') ?? ol.expected.ranges.find((x) => x.days === 5 && x.source === 'realized')
      if (r?.low != null && r.high != null) {
        const tag = r.source === 'options' ? '5d implied' : '5d range'
        out.push({ price: r.high, label: `${tag} +${num(r.pct, 1)}%`, tone: 'violet', style: 'dotted' }, { price: r.low, label: `${tag} −${num(r.pct, 1)}%`, tone: 'violet', style: 'dotted' })
      }
    }
    return out
  }, [lv, ol, lvOn])
  const patternMarkers = useMemo<ChartMarker[]>(() => {
    const dl = lv?.daily
    if (!dl) return []
    const out: ChartMarker[] = []
    if (lvOn.has('candles')) {
      for (const p of dl.patterns) {
        const bull = p.bias === 'bullish', bear = p.bias === 'bearish'
        // green / red only for a pattern whose own test found an edge after costs; the rest are grey: a shape, not a signal
        const proven = p.evidence?.verdict === 'edge'
        out.push({ t: p.at.slice(0, 10), position: bear ? 'aboveBar' : 'belowBar', shape: bull ? 'arrowUp' : bear ? 'arrowDown' : 'circle', kind: 'pattern',
          tone: proven ? (bull ? 'profit' : bear ? 'loss' : 'neutral') : 'neutral',
          text: proven ? p.name : `${p.name} (no edge)`, detail: p.what, strategy_key: null })
      }
    }
    if (lvOn.has('chart_patterns')) {
      // the breakout bar of a confirmed chart pattern (the pattern itself is drawn: see `drawings`)
      for (const p of dl.chart_patterns) {
        if (p.status !== 'confirmed') continue
        const up = p.direction ? p.direction === 'up' : p.bias === 'bullish'
        out.push({ t: p.confirmed_on ?? p.end, position: up ? 'belowBar' : 'aboveBar', shape: up ? 'arrowUp' : 'arrowDown', kind: 'pattern',
          tone: up ? 'profit' : 'loss', text: '', detail: `${p.name} breakout: ${p.what}`, strategy_key: null })
      }
    }
    return out
  }, [lv, lvOn])
  const height = mobile ? 300 + (indSet.has('macd') ? 80 : 0) : Math.max(460, (typeof window !== 'undefined' ? window.innerHeight : 800) - 250)
  const d = q.data
  const chartPatterns = useMemo(() => (lvOn.has('chart_patterns') ? lv?.daily?.chart_patterns ?? [] : []), [lv, lvOn])
  // Patterns are found on daily bars: drawn on the 1D chart only (on 1W the legend says so)
  const drawings = useMemo(() => (d && d.tf === '1d' && chartPatterns.length ? patternDrawings(chartPatterns, d.bars.t) : []), [d, chartPatterns])
  // your own drawings (DrawTools): levels as price lines, trendlines / Fibonacci as line drawings
  const dq = useDrawings(symbol)
  const allOverlays = useMemo(() => [...overlays, ...levelOverlays(dq.data?.drawings ?? [])], [overlays, dq.data])
  const allDrawings = useMemo(() => [...drawings, ...lineDrawings(dq.data?.drawings ?? [], d ? d.bars.t[d.bars.t.length - 1] : null)], [drawings, dq.data, d])

  return (
    <div className="flex flex-col gap-3">
      {/* One control height (32 px) across the toolbar. On phones: symbol + arrows + icon buttons on one line, the
          timeframe/range pickers on a scrolling line, the company name last. */}
      <div className="flex flex-wrap items-center gap-2">
        <span className="inline-flex shrink-0 items-center gap-1">
          <button type="button" onClick={() => setPalette(true)} aria-label={`${symbol}: change symbol (Ctrl K)`} title="Change symbol (Ctrl K)" className="focus-ring inline-flex h-8 items-center gap-2 rounded-md border border-line bg-panel px-3 hover:border-line-strong">
            <Search className="h-3.5 w-3.5 text-faint" />
            <span className="text-[15px] font-semibold">{symbol}</span>
            <ChevronDown className="h-3.5 w-3.5 text-faint" />
          </button>
          <IconButton label="Previous symbol ([)" disabled={idx <= 0} onClick={() => nav(`/chart/${list[idx - 1]}?${sp.toString()}`)}><ChevronLeft className="h-4 w-4" /></IconButton>
          <IconButton label="Next symbol (])" disabled={idx < 0 || idx >= list.length - 1} onClick={() => nav(`/chart/${list[idx + 1]}?${sp.toString()}`)}><ChevronRight className="h-4 w-4" /></IconButton>
        </span>
        {d && (d.company || d.industry) && (
          <div className="min-w-0 truncate text-xs text-muted max-md:order-last max-md:basis-full md:max-w-[240px] xl:max-w-[420px]" title={`${d.company ?? ''}${d.industry ? ` · ${d.industry}` : ''}`}>
            {`${d.company ?? ''}${d.industry ? ` · ${d.industry}` : ''}`}
          </div>
        )}
        {/* Phones: this group dissolves (contents) into the toolbar row, so the Indicators / Markers icons sit on the
            symbol's line (pushed right by the spacer) instead of alone on a second line; the picker strip then takes
            its own full-width line and the company name comes last. */}
        <div className="ml-auto flex min-w-0 flex-wrap items-center justify-end gap-2 max-md:contents">
          <span className="flex-1 md:hidden" aria-hidden />
          <div className="scroll-x no-scrollbar flex min-w-0 items-center gap-2 max-md:order-[50] max-md:w-full">
            <Segmented<ChartTf | IntradayTf> ariaLabel="Timeframe" value={intraTf ?? tf} onChange={(v) => set('tf', v === '1d' ? null : v)} items={[{ id: '1m', label: '1m', title: '1-minute candles with VWAP (from the live FYERS feed: the symbols it streams)' }, { id: '5m', label: '5m', title: '5-minute candles with VWAP (FYERS feed and history)' }, { id: '15m', label: '15m' }, { id: '1d', label: '1D' }, { id: '1w', label: '1W' }]} />
            {intraTf
              ? <Segmented<string> ariaLabel="Sessions" value={String(days)} onChange={(v) => set('days', v === '3' ? null : v)} items={['1', '3', '5', '10'].map((n) => ({ id: n, label: `${n}D`, title: `Last ${n} session${n === '1' ? '' : 's'}` }))} />
              : <Segmented<ChartRange> ariaLabel="Range" value={range} onChange={(v) => set('range', v === '1y' ? null : v)} items={RANGES.map((r) => ({ id: r, label: r.toUpperCase() === 'MAX' ? 'Max' : r.toUpperCase() }))} />}
          </div>
          <Popover align="right" width={248} trigger={({ toggle, open }) => <Button icon={<SlidersHorizontal className="h-3.5 w-3.5" />} onClick={toggle} aria-expanded={open} aria-label="Indicators" title="Indicators" className="max-sm:px-2.5"><span className="max-sm:hidden">Indicators</span></Button>}>
            <div className="py-1">
              {IND_MENU.map((m) => <MenuCheck key={m.id} checked={ind.includes(m.id)} onChange={(on) => setInd(on ? [...ind, m.id] : ind.filter((x) => x !== m.id))}>{m.label}</MenuCheck>)}
              <div className="mx-2.5 my-1 border-t border-line" />
              <div className="px-2.5 pt-1 text-2xs font-semibold uppercase tracking-[0.04em] text-faint">Panes below the chart</div>
              {PANE_MENU.map((m) => <MenuCheck key={m.id} checked={ind.includes(m.id)} onChange={(on) => setInd(on ? [...ind, m.id] : ind.filter((x) => x !== m.id))}>{m.label}</MenuCheck>)}
              <div className="mx-2.5 my-1 border-t border-line" />
              <div className="px-2.5 py-1.5"><Switch checked={log} onChange={setLog} label="Log scale" /></div>
              <div className="px-2.5 py-1.5"><Switch checked={lines} onChange={setLines} label="Price lines (stops, entries, 52w)" /></div>
            </div>
          </Popover>
          <DrawTools symbol={symbol} chartRef={ref} price={quote?.price ?? null} enabled={!intraTf && !!d} />
          <Popover align="right" width={260} trigger={({ toggle, open }) => <Button icon={<Layers className="h-3.5 w-3.5" />} onClick={toggle} aria-expanded={open} aria-label="Markers" title="Strategy markers" className="max-sm:px-2.5"><span className="max-sm:hidden">Markers</span>{markerSet ? ` · ${markerSet.size}` : ''}</Button>}>
            <div className="py-1">
              {available.length === 0 ? <div className="px-2.5 py-2 text-xs text-muted">No strategy traded this symbol in the recent trades. Full history needs trades.parquet (next scan).</div> : (
                <>
                  <MenuCheck checked={!markerSet} onChange={() => setMarkerSel(null)}>All strategies</MenuCheck>
                  {available.map((a) => (
                    <MenuCheck key={a.key} checked={!!markerSet?.has(a.key)} onChange={(on) => {
                      const base = markerSet ? [...markerSet] : []
                      setMarkerSel(on ? [...base, a.key] : base.filter((x) => x !== a.key))
                    }}>{a.name} <span className="text-faint">({a.trades})</span></MenuCheck>
                  ))}
                  <MenuCheck checked={!!markerSet && markerSet.size === 0} onChange={() => setMarkerSel([])}>None</MenuCheck>
                </>
              )}
            </div>
          </Popover>
          <Popover align="right" width={300} trigger={({ toggle, open }) => <Button icon={<Ruler className="h-3.5 w-3.5" />} onClick={toggle} aria-expanded={open} aria-label="Levels" title="Support / resistance, pivots, option walls, ranges" className="max-sm:px-2.5"><span className="max-sm:hidden">Levels</span>{lvSel.length ? ` · ${lvSel.length}` : ''}</Button>}>
            <div className="py-1">
              {LEVEL_MENU.map((m) => (
                <MenuCheck key={m.id} checked={lvOn.has(m.id)} onChange={(on) => setLvSel(on ? [...lvSel, m.id] : lvSel.filter((x) => x !== m.id))}>
                  <span className="block">{m.label}</span><span className="block text-2xs text-faint">{m.hint}</span>
                </MenuCheck>
              ))}
            </div>
          </Popover>
          {liveQ.data && quote && (
            <span title={liveQ.data.note}
              className={cn('inline-flex h-8 items-center gap-1.5 rounded-md border px-2 text-2xs font-medium', quote.delayed ? 'border-loss/40' : 'border-profit/40')}>
              <PriceStamp q={quote} session={liveQ.data.session} /><span className="num text-fg">{num(quote.price, 2)}</span> <Pct v={quote.change_pct} dp={2} />
            </span>
          )}
          <WatchButton symbol={symbol} />
          <AlertButton symbol={symbol} price={quote?.price ?? null} />
          <IconButton label="Save chart as PNG" onClick={screenshot} className="max-sm:hidden"><Camera className="h-4 w-4" /></IconButton>
          <IconButton label={panel ? 'Hide side panel' : 'Show side panel'} onClick={() => setPanel(!panel)} className="max-md:hidden">{panel ? <PanelRightClose className="h-4 w-4" /> : <PanelRightOpen className="h-4 w-4" />}</IconButton>
        </div>
      </div>
      {/* the one tested answer for this stock, above everything else: BUY / SELL (exit) / HOLD / NO EDGE */}
      <ActionPanel symbol={symbol} />
      {/* The side panel sits beside the chart from xl; below that it goes under the chart, so the chart keeps the
          full width (at 800 px it was squeezed to ~370 px). self-start: the chart card hugs the chart. */}
      <div className={cn('grid gap-3', panel && 'xl:grid-cols-[minmax(0,1fr)_320px]')}>
        <Card flush className="min-w-0 self-start overflow-hidden">
          {intraTf ? (
            iq.data && iq.data.symbol === symbol ? <IntradayChart data={iq.data} live={quote} height={height} />
              : iq.error ? <div className="p-4"><ErrorState error={iq.error} compact /></div> : <SkeletonChart height={height} />
          ) : q.error && !d ? <ErrorState error={q.error} onRetry={() => void q.refetch()} /> : !d ? <SkeletonChart height={height} /> : (
            <div className="relative">
              <PriceChart ref={ref} data={d} indicators={indSet} markerStrategies={markerSet} showLines={lines} log={log} height={height} compactLegend={mobile}
                overlays={allOverlays} extraMarkers={patternMarkers} drawings={allDrawings} live={liveTick} />
              {lvOn.has('chart_patterns') && lv?.daily && <PatternLegend patterns={chartPatterns} drawn={d.tf === '1d'} compact={mobile} />}
              {ol?.derivatives.verdict && (
                <button type="button" title={ol.derivatives.verdict.headline}
                  onClick={() => document.getElementById('chart-options')?.scrollIntoView({ behavior: 'smooth', block: 'start' })}
                  className={cn('absolute bottom-10 left-3 z-10 rounded-md border px-2 py-1 text-2xs font-bold tracking-wide shadow-sm', VERDICT_STYLE[ol.derivatives.verdict.verdict].cls)}>
                  Options: {VERDICT_STYLE[ol.derivatives.verdict.verdict].label}
                  {ol.derivatives.verdict.pick ? ` ${num(ol.derivatives.verdict.pick.strike, 0)} ${ol.derivatives.verdict.pick.side.toUpperCase()}` : ''}
                </button>
              )}
            </div>
          )}
        </Card>
        {panel && <Card flush className="min-w-0 self-start"><SidePanel symbol={symbol} /></Card>}
      </div>
      <AiAnalyst symbol={symbol} />
      <OutlookPanel symbol={symbol} livePrice={quote?.price ?? null} />
      {ol && <ChartOptions d={ol.derivatives} live={liveQ.live} lastDay={ol.date} />}
      {ol && <BigMoneyCard symbol={symbol} b={ol.big_money} kind={ol.kind} />}
      <PriceAction symbol={symbol} />
      <p className="text-2xs text-faint">Daily candles from the local store{d ? ` (to ${date(d.source_date)})` : ''}, adjusted for splits, bonuses and demergers with NSE data; while the market is open the last candle follows the live price. Chart patterns (Levels menu, 1D): the pattern's shape through its swing points, its lines (dashed while forming, solid once a close broke through), the textbook target and the level that voids it; ▲▼ Breakout marks the confirming bar. Markers: ▲ model buy / bullish candle pattern, ▼ model sell / bearish candle pattern, ● open model position, ■ corporate action, small ● results day. Lines (Levels menu): red resistance / call wall, green support / put wall, blue VWAP, violet expected range. Intraday (5m / 15m): FYERS 5-minute candles of the ~150 most liquid F&O stocks and of the symbols the live feed streams (add a stock to a watchlist), each session's VWAP in blue; the last candle follows the live price. Keys: 1-6 range, d/w/i timeframe, [ ] symbol.</p>
    </div>
  )
}
