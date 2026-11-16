// Multi-chart `/charts`: 1, 2 or 4 charts side by side, each with its own stock and timeframe, or one stock on four
// timeframes at once (weekly, daily, 15 and 5 minutes: the multi-timeframe view). Saved on this PC.

import { useMemo } from 'react'
import { Link } from 'react-router-dom'
import { Columns2, Grid2x2, Layers, Square } from 'lucide-react'
import { useChart, useLiveQuotes, useSymbols } from '@/api/hooks'
import type { ChartRange, ChartTf, IndicatorId } from '@/api/types'
import { useIntradayChart, type IntradayTf } from '@/api/watch'
import { IntradayChart } from '@/components/charts/IntradayChart'
import { PriceChart } from '@/components/charts/PriceChart'
import { PageHeader } from '@/components/domain'
import { ErrorState, SkeletonChart } from '@/components/feedback'
import { Button, Segmented } from '@/components/ui'
import { cn } from '@/lib/csv'
import { num } from '@/lib/format'
import { useLocalStorage } from '@/lib/useLocalStorage'

type PaneTf = ChartTf | IntradayTf
interface PaneCfg { symbol: string; tf: PaneTf }
const TFS: { id: PaneTf; label: string }[] = [{ id: '1w', label: '1W' }, { id: '1d', label: '1D' }, { id: '15m', label: '15m' }, { id: '5m', label: '5m' }, { id: '1m', label: '1m' }]
const IND: IndicatorId[] = ['sma20', 'sma50']
const IND_SET = new Set<string>(IND)
const NO_MARKERS = new Set<string>()
const DEFAULT: PaneCfg[] = [{ symbol: 'NIFTY50', tf: '1d' }, { symbol: 'RELIANCE', tf: '1d' }, { symbol: 'HDFCBANK', tf: '1d' }, { symbol: 'TCS', tf: '1d' }]

function Pane({ cfg, onChange, height }: { cfg: PaneCfg; onChange: (c: PaneCfg) => void; height: number }) {
  const daily = cfg.tf === '1d' || cfg.tf === '1w'
  const params = useMemo(() => ({ tf: (daily ? cfg.tf : '1d') as ChartTf, range: (cfg.tf === '1w' ? '5y' : '1y') as ChartRange, indicators: IND }), [cfg.tf, daily])
  const q = useChart(daily ? cfg.symbol : '', params)
  const iq = useIntradayChart(cfg.symbol, (daily ? '5m' : cfg.tf) as IntradayTf, cfg.tf === '1m' ? 1 : 3, !daily)
  const lq = useLiveQuotes([cfg.symbol])
  const quote = lq.quotes[cfg.symbol]
  const err = daily ? q.error : iq.error
  return (
    <div className="card min-w-0 overflow-hidden">
      <div className="flex flex-wrap items-center gap-2 border-b border-line px-2.5 py-1.5">
        <input aria-label="Stock" defaultValue={cfg.symbol} key={cfg.symbol} list="symbols-list"
          onKeyDown={(e) => { if (e.key === 'Enter') onChange({ ...cfg, symbol: (e.target as HTMLInputElement).value.trim().toUpperCase() || cfg.symbol }) }}
          onBlur={(e) => { const v = e.target.value.trim().toUpperCase(); if (v && v !== cfg.symbol) onChange({ ...cfg, symbol: v }) }}
          className="input h-7 w-32 px-2 text-xs font-semibold uppercase" />
        <Segmented<PaneTf> size="xs" ariaLabel="Timeframe" value={cfg.tf} onChange={(tf) => onChange({ ...cfg, tf })} items={TFS} />
        <span className="ml-auto text-xs text-muted">{quote ? <span className="num text-fg">{num(quote.price, 2)}</span> : null}</span>
        <Link to={`/chart/${cfg.symbol}${cfg.tf !== '1d' ? `?tf=${cfg.tf}` : ''}`} className="link text-2xs">Open</Link>
      </div>
      {err ? <div className="p-3"><ErrorState error={err} compact /></div>
        : daily ? (q.data && q.data.symbol === cfg.symbol
          ? <PriceChart data={q.data} indicators={IND_SET} markerStrategies={NO_MARKERS} showLines={false} log={false} height={height} compactLegend />
          : <SkeletonChart height={height} />)
        : iq.data && iq.data.symbol === cfg.symbol ? <IntradayChart data={iq.data} live={quote} height={height} /> : <SkeletonChart height={height} />}
    </div>
  )
}

export default function Charts() {
  const [layout, setLayout] = useLocalStorage<'1' | '2' | '4'>('qd.charts.layout', '4')
  const [panes, setPanes] = useLocalStorage<PaneCfg[]>('qd.charts.panes', DEFAULT)
  const syms = useSymbols()
  const n = Number(layout)
  const list = [...panes, ...DEFAULT].slice(0, 4)
  const height = n === 4 ? 300 : n === 2 ? 460 : 560
  const set = (i: number, c: PaneCfg) => setPanes(list.map((p, k) => (k === i ? c : p)))
  const mtf = () => { const s = list[0].symbol; setPanes([{ symbol: s, tf: '1w' }, { symbol: s, tf: '1d' }, { symbol: s, tf: '15m' }, { symbol: s, tf: '5m' }]); setLayout('4') }
  return (
    <div className="space-y-3">
      <PageHeader title="Multi-chart" subtitle="Several stocks side by side, or one stock on four timeframes. Type a symbol and press Enter."
        right={<>
          <Segmented<'1' | '2' | '4'> ariaLabel="Layout" value={layout} onChange={setLayout} items={[
            { id: '1', label: <Square className="h-3.5 w-3.5" />, title: 'One chart' }, { id: '2', label: <Columns2 className="h-3.5 w-3.5" />, title: 'Two charts' },
            { id: '4', label: <Grid2x2 className="h-3.5 w-3.5" />, title: 'Four charts' }]} />
          <Button size="sm" icon={<Layers className="h-3.5 w-3.5" />} onClick={mtf} title="The first chart's stock on weekly, daily, 15-minute and 5-minute charts">{list[0].symbol} on 4 timeframes</Button>
        </>} />
      <datalist id="symbols-list">{(syms.data?.symbols ?? []).map((x) => <option key={x.symbol} value={x.symbol} />)}</datalist>
      <div className={cn('grid gap-3', n === 2 && 'lg:grid-cols-2', n === 4 && 'lg:grid-cols-2')}>
        {list.slice(0, n).map((c, i) => <Pane key={i} cfg={c} onChange={(x) => set(i, x)} height={height} />)}
      </div>
    </div>
  )
}
