// Chart `/chart/:symbol` (spec 3.6): lightweight-charts v5 panes (candles + MAs + Bollinger + volume, RSI, MACD),
// strategy markers, price lines, crosshair legend; right panel with the stock snapshot.

import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { Camera, ChevronDown, ChevronLeft, ChevronRight, Layers, PanelRightClose, PanelRightOpen, Search, SlidersHorizontal } from 'lucide-react'
import { useChart, useStock, useSymbols } from '@/api/hooks'
import type { ChartRange, ChartTf, IndicatorId } from '@/api/types'
import { useUi } from '@/app/uiState'
import { LevelPill, ResultsChip, StatusDot } from '@/components/badges'
import { PriceChart, type PriceChartHandle } from '@/components/charts/PriceChart'
import { RangeBar52w } from '@/components/charts/svg'
import { ErrorState, Skeleton, SkeletonChart } from '@/components/feedback'
import { Money, Pct, Price } from '@/components/num'
import { Button, Card, IconButton, KV, MenuCheck, Popover, Segmented, Switch } from '@/components/ui'
import { cn } from '@/lib/csv'
import { date, daysBetween, num, qty, todayIST } from '@/lib/format'
import { useLocalStorage } from '@/lib/useLocalStorage'
import { typingTarget, useIsMobile } from '@/lib/useMedia'

const RANGES: ChartRange[] = ['3m', '6m', '1y', '2y', '5y', 'max']
type Ind = IndicatorId | 'volume'
const IND_MENU: { id: Ind; label: string }[] = [
  { id: 'sma20', label: 'SMA 20' }, { id: 'sma50', label: 'SMA 50' }, { id: 'sma200', label: 'SMA 200' }, { id: 'ema21', label: 'EMA 21' },
  { id: 'bb_mid', label: 'Bollinger 20, 2' }, { id: 'volume', label: 'Volume' }, { id: 'rsi14', label: 'RSI 14 pane' }, { id: 'macd', label: 'MACD pane' },
]

function apiIndicators(sel: Ind[]): IndicatorId[] {
  const out = new Set<IndicatorId>(['vol_avg20'])
  for (const s of sel) {
    if (s === 'volume') continue
    if (s === 'bb_mid') { out.add('bb_upper'); out.add('bb_mid'); out.add('bb_lower') } else if (s === 'macd') { out.add('macd'); out.add('macd_signal'); out.add('macd_hist') } else out.add(s)
  }
  return [...out].sort()
}

function SidePanel({ symbol }: { symbol: string }) {
  const q = useStock(symbol)
  const s = q.data
  if (q.error) return <ErrorState error={q.error} compact />
  if (!s) return <div className="space-y-3 p-4"><Skeleton className="h-6 w-28" /><Skeleton className="h-3 w-full" /><Skeleton className="h-24 w-full" /></div>
  const today = todayIST()
  const stock = s.kind === 'stock'
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
          <span className="num text-[22px] font-semibold"><Price v={s.price} /></span>
          <Pct v={s.change_pct} dp={2} className="text-[13px]" />
        </div>
        <div className="mt-0.5 line-clamp-2 text-xs text-muted" title={`${s.company ?? ''}${s.industry ? ` · ${s.industry}` : ''}`}>{s.company}{s.industry ? ` · ${s.industry}` : ''}</div>
        <div className="mt-3"><div className="mb-1 text-2xs text-muted">52-week range{s.pct_from_52w_high != null && <> · <Pct v={s.pct_from_52w_high} color={false} /> from high</>}</div><RangeBar52w low={s.low_52w} high={s.high_52w} value={s.price} /></div>
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
            <div className="flex justify-between"><span className="text-muted">P&amp;L</span><span><Money v={s.your_holding.pnl_amount} signed color /> <Pct v={s.your_holding.pnl_pct} /></span></div>
            {s.your_holding.alerts.map((a) => <div key={a} className="text-xs text-warn">{a}</div>)}
          </div>
        ) : <div className="text-xs text-muted">None. <Link to="/portfolio" className="link">Add holdings</Link></div>}
      </div>
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
  const tf = (sp.get('tf') as ChartTf | null) ?? '1d'
  const range = (sp.get('range') as ChartRange | null) ?? '1y'
  const strategyParam = sp.get('s')
  const set = (k: string, v: string | null) => setSp((p) => { const n = new URLSearchParams(p); if (v) n.set(k, v); else n.delete(k); return n }, { replace: true })
  const mobile = useIsMobile()
  const [ind, setInd] = useLocalStorage<Ind[]>('qd.chart.ind', ['sma20', 'sma50', 'sma200', 'volume', 'rsi14'])
  const [log, setLog] = useLocalStorage('qd.chart.log', false)
  const [lines, setLines] = useLocalStorage('qd.chart.lines', true)
  const [panel, setPanel] = useLocalStorage('qd.chart.panel', true)
  const indSet = useMemo(() => new Set<Ind>(mobile ? ind.filter((i) => i !== 'rsi14' && i !== 'macd') : ind), [ind, mobile])
  const params = useMemo(() => ({ tf, range, indicators: apiIndicators(ind) }), [tf, range, ind])
  const q = useChart(symbol, params)
  const symbols = useSymbols()
  const { setPalette } = useUi()
  const nav = useNavigate()
  const ref = useRef<PriceChartHandle>(null)

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
  const height = mobile ? 300 + (indSet.has('macd') ? 80 : 0) : Math.max(460, (typeof window !== 'undefined' ? window.innerHeight : 800) - 250)
  const d = q.data

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
            <Segmented<ChartTf | '5m'> ariaLabel="Timeframe" value={tf} onChange={(v) => v !== '5m' && set('tf', v === '1d' ? null : v)} items={[{ id: '1d', label: '1D' }, { id: '1w', label: '1W' }, { id: '5m', label: '5m', disabled: true, title: 'Intraday chart comes with the intraday store' }]} />
            <Segmented<ChartRange> ariaLabel="Range" value={range} onChange={(v) => set('range', v === '1y' ? null : v)} items={RANGES.map((r) => ({ id: r, label: r.toUpperCase() === 'MAX' ? 'Max' : r.toUpperCase() }))} />
          </div>
          <Popover align="right" width={248} trigger={({ toggle, open }) => <Button icon={<SlidersHorizontal className="h-3.5 w-3.5" />} onClick={toggle} aria-expanded={open} aria-label="Indicators" title="Indicators" className="max-sm:px-2.5"><span className="max-sm:hidden">Indicators</span></Button>}>
            <div className="py-1">
              {IND_MENU.map((m) => <MenuCheck key={m.id} checked={ind.includes(m.id)} onChange={(on) => setInd(on ? [...ind, m.id] : ind.filter((x) => x !== m.id))}>{m.label}</MenuCheck>)}
              <div className="mx-2.5 my-1 border-t border-line" />
              <div className="px-2.5 py-1.5"><Switch checked={log} onChange={setLog} label="Log scale" /></div>
              <div className="px-2.5 py-1.5"><Switch checked={lines} onChange={setLines} label="Price lines (stops, entries, 52w)" /></div>
            </div>
          </Popover>
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
          <IconButton label="Save chart as PNG" onClick={screenshot} className="max-sm:hidden"><Camera className="h-4 w-4" /></IconButton>
          <IconButton label={panel ? 'Hide side panel' : 'Show side panel'} onClick={() => setPanel(!panel)} className="max-md:hidden">{panel ? <PanelRightClose className="h-4 w-4" /> : <PanelRightOpen className="h-4 w-4" />}</IconButton>
        </div>
      </div>
      {/* The side panel sits beside the chart from xl; below that it goes under the chart, so the chart keeps the
          full width (at 800 px it was squeezed to ~370 px). self-start: the chart card hugs the chart. */}
      <div className={cn('grid gap-3', panel && 'xl:grid-cols-[minmax(0,1fr)_320px]')}>
        <Card flush className="min-w-0 self-start overflow-hidden">
          {q.error && !d ? <ErrorState error={q.error} onRetry={() => void q.refetch()} /> : !d ? <SkeletonChart height={height} /> : (
            <PriceChart ref={ref} data={d} indicators={indSet} markerStrategies={markerSet} showLines={lines} log={log} height={height} compactLegend={mobile} />
          )}
        </Card>
        {panel && <Card flush className="min-w-0 self-start"><SidePanel symbol={symbol} /></Card>}
      </div>
      <p className="text-2xs text-faint">Daily candles from the local store{d ? ` (to ${date(d.source_date)})` : ''}, adjusted for splits, bonuses and demergers with NSE data. Markers: ▲ model buy, ▼ model sell, ● open model position, ■ corporate action, small ● results day. Keys: 1-6 range, d/w timeframe, [ ] symbol.</p>
    </div>
  )
}
