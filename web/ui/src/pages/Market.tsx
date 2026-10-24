// Market `/market/:tab` (spec 3.9): movers, sectors (NSE indices + universe industries), factor-index gallery,
// results calendar, breadth.

import { useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useBreadth, useFactors, useMovers, useResults, useSectors, useSparklines } from '@/api/hooks'
import type { IndexRow, IndustryRow, Mover, ResultsEvent } from '@/api/types'
import { LinesChart, type LineDef } from '@/components/charts/LinesChart'
import { SignedBars, Sparkline } from '@/components/charts/svg'
import { DataTable, SymbolCell, type Col } from '@/components/DataTable'
import { PageHeader, ResultsWhy } from '@/components/domain'
import { EmptyState, ErrorState, SkeletonChart, SkeletonRows } from '@/components/feedback'
import { Pct, Price, Risk } from '@/components/num'
import { Card, Segmented, Switch, Tabs } from '@/components/ui'
import { cn } from '@/lib/csv'
import { date, daysUntil, num, pct } from '@/lib/format'

type Tab = 'movers' | 'sectors' | 'factors' | 'results' | 'breadth'

function MoverTable({ id, rows, spark }: { id: string; rows: Mover[]; spark?: Record<string, (number | null)[]> }) {
  const nav = useNavigate()
  // Fixed widths + table-layout fixed: the Gainers / Losers / Volume tables line up when stacked. Sector steps aside
  // on narrow cards so Change (the key number) is never the column that gets cut.
  const cols: Col<Mover>[] = [
    { id: 'sym', header: 'Symbol', value: (r) => r.symbol, cell: (r) => <SymbolCell symbol={r.symbol} company={r.company} />, sticky: true, width: 220, mobile: 'primary', search: (r) => `${r.symbol} ${r.company ?? ''}`, csvExtra: { label: 'Company', value: (r) => r.company } },
    { id: 'ind', header: 'Sector', value: (r) => r.industry, cell: (r) => <span className="block truncate text-muted" title={r.industry ?? undefined}>{r.industry ?? '—'}</span>, width: 180, hideBelow: 760 },
    { id: 'price', header: 'Price ₹', align: 'right', value: (r) => r.price, cell: (r) => <Price v={r.price} />, width: 104, mobile: 'value' },
    { id: 'chg', header: 'Change', align: 'right', value: (r) => r.change_pct, cell: (r) => <Pct v={r.change_pct} dp={2} />, width: 96, mobile: 'change' },
    { id: 'vr', header: 'Volume ×', title: 'Volume vs its 20-day average', align: 'right', value: (r) => r.vol_ratio, cell: (r) => <span className="num">{num(r.vol_ratio, 1)}×</span>, width: 100, mobile: 'secondary', label: 'Vol ×' },
    { id: 'spark', header: '60D', value: () => null, sortable: false, cell: (r) => <Sparkline values={spark?.[r.symbol] ?? []} width={72} height={22} />, width: 100 },
  ]
  return <DataTable id={`market.${id}`} data={rows} columns={cols} rowKey={(r) => r.symbol} onRowClick={(r) => nav(`/chart/${r.symbol}`)} fixedLayout />
}

function Movers() {
  const q = useMovers()
  const syms = useMemo(() => (q.data ? [...q.data.gainers, ...q.data.losers, ...q.data.volume_spikes].map((m) => m.symbol) : []), [q.data])
  const spark = useSparklines([...new Set(syms)])
  if (q.error) return <div className="card"><ErrorState error={q.error} onRetry={() => void q.refetch()} /></div>
  if (!q.data) return <div className="card"><SkeletonRows /></div>
  return (
    // as many side by side as fit at ~720 px each (three 540 px cards cut the Change column at 1920)
    <div className="grid gap-3 grid-cols-[repeat(auto-fit,minmax(min(100%,720px),1fr))]">
      <Card title="Gainers" flush><MoverTable id="gainers" rows={q.data.gainers} spark={spark.data?.series} /></Card>
      <Card title="Losers" flush><MoverTable id="losers" rows={q.data.losers} spark={spark.data?.series} /></Card>
      <Card title="Volume spikes" flush><MoverTable id="volume" rows={q.data.volume_spikes} spark={spark.data?.series} /></Card>
    </div>
  )
}

function indexCols(withRank: boolean): Col<IndexRow>[] {
  return [
    ...(withRank ? [{ id: 'rank', header: '#', align: 'right', value: (r: IndexRow) => r.rank, cell: (r: IndexRow) => <span className="num text-muted">{r.rank ?? '—'}</span>, width: 44 } as Col<IndexRow>] : []),
    { id: 'name', header: 'Index', value: (r) => r.name, cell: (r) => <span className="font-medium">{r.name}</span>, sticky: true, minWidth: 200, mobile: 'primary' },
    { id: 'last', header: 'Last', align: 'right', value: (r) => r.last, cell: (r) => <span className="num">{num(r.last, 2)}</span>, mobile: 'value' },
    { id: 'd1', header: '1D', align: 'right', value: (r) => r.chg_1d, cell: (r) => <Pct v={r.chg_1d} dp={2} />, mobile: 'change' },
    { id: 'm1', header: '1M', align: 'right', value: (r) => r.ret_1m, cell: (r) => <Pct v={r.ret_1m} /> },
    { id: 'm3', header: '3M', align: 'right', value: (r) => r.ret_3m, cell: (r) => <Pct v={r.ret_3m} />, mobile: 'secondary', label: '3M' },
    { id: 'm6', header: '6M', align: 'right', value: (r) => r.ret_6m, cell: (r) => <Pct v={r.ret_6m} /> },
    { id: 'y1', header: '1Y', align: 'right', value: (r) => r.ret_1y, cell: (r) => <Pct v={r.ret_1y} />, mobile: 'secondary', label: '1Y' },
    { id: 'cagr', header: 'CAGR', align: 'right', value: (r) => r.cagr, cell: (r) => <Pct v={r.cagr} signed={false} /> },
    { id: 'dd', header: 'Max DD', align: 'right', value: (r) => r.max_dd, cell: (r) => <Risk v={r.max_dd} /> },
    { id: 'since', header: 'Since', value: (r) => r.since, cell: (r) => <span className="num text-muted">{date(r.since, { year: true })}</span> },
    { id: 'a50', header: '>50-DMA', align: 'center', value: (r) => r.above_50dma, cell: (r) => (r.above_50dma == null ? <span className="text-faint">—</span> : <span title={r.above_50dma ? 'Above its 50-day average' : 'Below its 50-day average'} className={cn('inline-block h-2 w-2 rounded-full', r.above_50dma ? 'bg-profit' : 'bg-loss')} />) },
  ]
}

function Sectors() {
  const q = useSectors()
  const nav = useNavigate()
  if (q.error) return <div className="card"><ErrorState error={q.error} onRetry={() => void q.refetch()} /></div>
  if (!q.data) return <div className="card"><SkeletonRows /></div>
  const d = q.data
  const indCols: Col<IndustryRow>[] = [
    { id: 'ind', header: 'Industry', value: (r) => r.industry, cell: (r) => <span className="font-medium">{r.industry}</span>, sticky: true, minWidth: 200, mobile: 'primary' },
    { id: 'n', header: 'Stocks', align: 'right', value: (r) => r.members, cell: (r) => <span className="num text-muted">{r.members}</span> },
    { id: 'b', header: '>50-DMA', title: 'Share of members above their 50-day average', align: 'right', value: (r) => r.breadth_50, cell: (r) => <Pct v={r.breadth_50} signed={false} color={false} dp={0} />, mobile: 'value' },
    { id: 'ad', header: 'A / D', align: 'right', value: (r) => r.advances - r.declines, cell: (r) => <span className="num"><span className="text-profit">{r.advances}</span><span className="text-faint">/</span><span className="text-loss">{r.declines}</span></span> },
    { id: 'd1', header: '1D', align: 'right', value: (r) => r.ret_1d_pct, cell: (r) => <Pct v={r.ret_1d_pct} dp={2} /> },
    { id: 'w1', header: '1W', align: 'right', value: (r) => r.ret_1w_pct, cell: (r) => <Pct v={r.ret_1w_pct} />, hideBelow: 1240 },
    { id: 'm1', header: '1M', align: 'right', value: (r) => r.ret_1m_pct, cell: (r) => <Pct v={r.ret_1m_pct} /> },
    { id: 'm3', header: '3M', align: 'right', value: (r) => r.ret_3m_pct, cell: (r) => <Pct v={r.ret_3m_pct} />, mobile: 'change' },
    { id: 'm6', header: '6M', align: 'right', value: (r) => r.ret_6m_pct, cell: (r) => <Pct v={r.ret_6m_pct} />, hideBelow: 1180 },
    { id: 'lead', header: 'Leaders (3M)', value: (r) => r.leaders.map((l) => l.symbol).join(' '), sortable: false, cell: (r) => (
      <span className="flex gap-2">{r.leaders.map((l) => <Link key={l.symbol} to={`/chart/${l.symbol}`} onClick={(e) => e.stopPropagation()} className="whitespace-nowrap text-xs hover:underline"><span className="font-medium">{l.symbol}</span> <Pct v={l.ret_3m_pct} dp={0} className="text-2xs" /></Link>)}</span>
    ) },
  ]
  const bars = [...d.nse_sectors].sort((a, b) => (b.ret_3m ?? -1e9) - (a.ret_3m ?? -1e9)).map((s) => ({ label: s.name, value: s.ret_3m }))
  return (
    <div className="space-y-3">
      <div className="grid gap-3 2xl:grid-cols-3">
        <Card title="NSE sector indices" subtitle="Ranked by the scan; returns from the official NSE index file" flush className="2xl:col-span-2">
          <DataTable id="market.sectors" data={d.nse_sectors} columns={indexCols(true)} rowKey={(r) => r.name} exportName="nse-sectors" />
        </Card>
        <Card title="3-month return by sector"><SignedBars items={bars} /></Card>
      </div>
      <Card title="Universe industries" subtitle={`Equal-weight across the liquid stocks of the scan list (the same stocks as the top bar's A/D) · prices ${date(d.industries_source_date)}`} flush>
        <DataTable id="market.industries" data={d.industries} columns={indCols} rowKey={(r) => r.industry} initialSort={[{ id: 'm3', desc: true }]} onRowClick={(r) => nav(`/screener?preset=all&industry=${encodeURIComponent(r.industry)}`)} exportName="industries" />
      </Card>
    </div>
  )
}

function Factors() {
  const q = useFactors()
  if (q.error) return <div className="card"><ErrorState error={q.error} onRetry={() => void q.refetch()} /></div>
  if (!q.data) return <div className="card"><SkeletonRows /></div>
  return (
    <div className="space-y-3">
      <div className="rounded-lg border border-info/25 bg-info/[0.06] px-4 py-3 text-[13px]">
        <div className="font-medium text-fg">{q.data.note}</div>
        <div className="mt-0.5 text-xs text-muted">If a strategy can't beat its matching factor index after costs and tax, buying the index is the simpler choice.</div>
      </div>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {q.data.factors.map((f) => (
          <div key={f.name} className="card p-4">
            <div className="flex items-start justify-between gap-2">
              <span className="text-[13px] font-semibold leading-5">{f.name}</span>
              {f.above_50dma != null && <span className={cn('mt-1.5 h-2 w-2 shrink-0 rounded-full', f.above_50dma ? 'bg-profit' : 'bg-loss')} title={f.above_50dma ? 'Above its 50-DMA' : 'Below its 50-DMA'} />}
            </div>
            <div className="mt-3 flex items-baseline gap-2">
              <span className="num text-[22px] font-semibold">{pct(f.cagr, { signed: false })}</span>
              <span className="text-2xs text-muted">CAGR since {date(f.since, { year: true })}</span>
            </div>
            <div className="num mt-3 grid grid-cols-3 gap-2 border-t border-line pt-2.5 text-xs">
              <div><div className="text-2xs text-muted">1Y</div><Pct v={f.ret_1y} /></div>
              <div><div className="text-2xs text-muted">3M</div><Pct v={f.ret_3m} /></div>
              <div><div className="text-2xs text-muted">Max DD</div><Risk v={f.max_dd} /></div>
            </div>
          </div>
        ))}
      </div>
      <Card title="All factor indices" flush>
        <DataTable id="market.factors" data={q.data.factors} columns={indexCols(false)} rowKey={(r) => r.name} exportName="factor-indices" />
      </Card>
    </div>
  )
}

function Results() {
  const [relevant, setRelevant] = useState(false)
  const [days, setDays] = useState(14)
  const q = useResults(days, relevant)
  const groups = useMemo(() => {
    const m = new Map<string, ResultsEvent[]>()
    for (const e of q.data?.events ?? []) m.set(e.date, [...(m.get(e.date) ?? []), e])
    return [...m.entries()]
  }, [q.data])
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-3">
        <Segmented size="sm" ariaLabel="Days ahead" value={String(days)} onChange={(v) => setDays(Number(v))} items={[{ id: '7', label: '7 days' }, { id: '14', label: '14 days' }]} />
        <Switch checked={relevant} onChange={setRelevant} label="Only relevant to me" />
        {q.data && <span className="ml-auto text-xs text-muted">{q.data.note}{q.data.cached_on ? ` · NSE calendar of ${date(q.data.cached_on)}` : ''}</span>}
      </div>
      {q.error ? <div className="card"><ErrorState error={q.error} onRetry={() => void q.refetch()} /></div> : !q.data ? <div className="card"><SkeletonRows /></div> : groups.length === 0 ? (
        <div className="card"><EmptyState title="No results scheduled in this window" /></div>
      ) : (
        // items-start: a 1-company day is not stretched to the height of the 8-company day beside it
        <div className="grid items-start gap-3 lg:grid-cols-2 2xl:grid-cols-3">
          {groups.map(([d, evs]) => (
            <Card key={d} title={<span className="flex items-center gap-2">{date(d)}<span className={cn('text-xs font-normal', evs[0].days_until <= 1 ? 'text-loss' : 'text-muted')}>{daysUntil(evs[0].days_until)}</span></span>} subtitle={`${evs.length} compan${evs.length === 1 ? 'y' : 'ies'}`} flush>
              <ul className="max-h-[320px] divide-y divide-line/70 overflow-auto">
                {evs.map((e) => (
                  <li key={e.symbol}>
                    <Link to={`/chart/${e.symbol}`} className="flex items-center gap-2 px-4 py-1.5 text-[13px] hover:bg-raised" title={e.purpose}>
                      <span className="flex min-w-0 flex-1 flex-col leading-tight">
                        <span className="flex items-baseline gap-2"><span className="font-semibold">{e.symbol}</span><span className="min-w-0 truncate text-2xs text-muted">{e.industry}</span></span>
                        <span className="truncate text-2xs text-faint">{[e.company, e.purpose].filter(Boolean).join(' · ')}</span>
                      </span>
                      <span className="flex shrink-0 flex-wrap justify-end gap-1"><ResultsWhy e={e} /></span>
                    </Link>
                  </li>
                ))}
              </ul>
            </Card>
          ))}
        </div>
      )}
    </div>
  )
}

function Breadth() {
  const [range, setRange] = useState<'1y' | '3y' | 'all'>('1y')
  const q = useBreadth(range)
  const top: LineDef[] | null = useMemo(() => {
    const b = q.data
    if (!b) return null
    return [
      { id: 'b', label: '% above 50-DMA', v: b.breadth_50, color: 'accent', width: 2, format: (v) => `${num(v, 0)}%`, refLines: [{ price: 50 }] },
      { id: 'n', label: 'Nifty 50', v: b.nifty, color: 'muted', scale: 'left', format: (v) => num(v, 0) },
      { id: 's', label: '200-DMA', v: b.nifty_sma200, color: 'violet', scale: 'left', style: 'dashed', format: (v) => num(v, 0) },
      { id: 'ad', label: 'A/D line', v: b.ad_line, color: 'info', pane: 1, format: (v) => num(v, 0) },
      { id: 'vix', label: 'India VIX', v: b.vix, color: 'warn', pane: 2, format: (v) => num(v, 1), refLines: [{ price: 20, label: '20' }] },
    ]
  }, [q.data])
  return (
    <Card
      title="Market breadth"
      subtitle="Top: % of stocks above their 50-DMA (right scale) with Nifty 50 and its 200-DMA (left scale). Middle pane: cumulative advance/decline line. Bottom pane: India VIX."
      right={<Segmented size="xs" ariaLabel="Range" value={range} onChange={setRange} items={[{ id: '1y', label: '1Y' }, { id: '3y', label: '3Y' }, { id: 'all', label: 'All' }]} />}
      flush
    >
      {q.error ? <ErrorState error={q.error} onRetry={() => void q.refetch()} /> : !q.data || !top ? <SkeletonChart height={560} /> : <LinesChart t={q.data.t} lines={top} height={560} paneFactors={[1, 0.45, 0.4]} />}
    </Card>
  )
}

export default function Market() {
  const { tab = 'movers' } = useParams()
  const t = (['movers', 'sectors', 'factors', 'results', 'breadth'].includes(tab) ? tab : 'movers') as Tab
  return (
    <div>
      <PageHeader title="Market" subtitle="Context for the strategies: who moved, which sectors lead, what the real indices did, who reports soon" />
      <div className="mb-3 border-b border-line">
        <Tabs<Tab> value={t} items={[
          { id: 'movers', label: 'Movers', to: '/market/movers' },
          { id: 'sectors', label: 'Sectors', to: '/market/sectors' },
          { id: 'factors', label: 'Factor indices', to: '/market/factors' },
          { id: 'results', label: 'Results calendar', to: '/market/results' },
          { id: 'breadth', label: 'Breadth', to: '/market/breadth' },
        ]} />
      </div>
      {t === 'movers' && <Movers />}
      {t === 'sectors' && <Sectors />}
      {t === 'factors' && <Factors />}
      {t === 'results' && <Results />}
      {t === 'breadth' && <Breadth />}
    </div>
  )
}
