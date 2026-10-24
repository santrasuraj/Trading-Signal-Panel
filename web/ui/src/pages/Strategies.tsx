// Strategies leaderboard `/strategies` (spec 3.2): grouped by horizon (Long-term / Swing / Intraday), evidence and
// status badges, CAGR with the timing-luck range, after-tax, edge vs the average stock (or Nifty 50 for ETFs), vs the
// matching NSE factor index, risk, recent windows, equity spark, orders; survivorship callout; Tested & rejected.

import { useMemo, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import type { SortingState } from '@tanstack/react-table'
import { ArrowRight, Ban, ChevronDown, LayoutGrid, Rows3 } from 'lucide-react'
import { useIntraday, useStrategies } from '@/api/hooks'
import type { Evidence, Horizon, IntradayStrategy, RejectedEntry, StrategyListResponse, StrategyStatus, StrategySummary } from '@/api/types'
import { EdgeVerdict, EtfChip, EvidenceChip, HorizonChip, LifecycleBadge, StatusBadge, edgeVerdict } from '@/components/badges'
import { Sparkline, TimingRangeBar } from '@/components/charts/svg'
import { ColumnChooser, DataTable, type Col } from '@/components/DataTable'
import { BiasNote, Help, PageHeader } from '@/components/domain'
import { ErrorState, Skeleton, SkeletonRows } from '@/components/feedback'
import { Pct, Pts, Ratio, Risk } from '@/components/num'
import { Button, Card, MenuCheck, Popover, Segmented, SelectButton, Tabs } from '@/components/ui'
import { cn } from '@/lib/csv'
import { date, num, pct } from '@/lib/format'
import { useWidth } from '@/lib/useWidth'
import { EVIDENCE, HORIZON, HORIZONS, STATUS } from '@/lib/vocab'

type View = 'table' | 'cards'
const STATUSES: StrategyStatus[] = ['working', 'mixed', 'not-working', 'unknown']
const EVIDENCES: Evidence[] = ['STRONG', 'MODERATE', 'WEAK', 'FOLKLORE', 'EXPERIMENTAL']

const primaryEdge = (s: StrategySummary) => (s.edges.primary === 'ew' ? s.edges.vs_ew_cagr_pct : s.edges.vs_nifty_cagr_pct)

function CagrCell({ s }: { s: StrategySummary }) {
  const t = s.timing
  return (
    <div className="ml-auto flex w-[118px] flex-col items-end gap-1">
      <span className="num font-semibold text-fg">{pct(s.headline.cagr_pct, { signed: false })}</span>
      {t && t.low != null && t.high != null ? (
        <div className="flex w-full items-center gap-1.5" title={`Timing luck: ${num(t.low, 1)}% to ${num(t.high, 1)}%${t.consistent ? '' : ' (range computed on older data; re-scan)'}`}>
          <TimingRangeBar low={t.low} high={t.high} base={t.base_cagr_pct} consistent={t.consistent} compact />
          {!t.consistent && <span className="text-[10px] font-semibold text-warn">!</span>}
        </div>
      ) : <span className="h-2" />}
    </div>
  )
}

/** Edge with a fixed-width slot for the ETF asterisk on EVERY row, so the digits stay right-aligned in one column. */
function EdgeValue({ s, className }: { s: StrategySummary; className?: string }) {
  return (
    <span className={cn('num whitespace-nowrap', className)}>
      <Pts v={primaryEdge(s)} />
      <span className="inline-block w-2 text-left text-faint" title={s.edges.primary === 'nifty' ? 'vs Nifty 50 (ETF strategy)' : undefined}>{s.edges.primary === 'nifty' ? '*' : ''}</span>
    </span>
  )
}

// Every column has a width and the groups use table-layout: fixed, so the Long-term and Swing tables stacked on one
// page line up column for column. `hideBelow`: low-priority columns step aside on narrower cards (column chooser).
function columns(): Col<StrategySummary>[] {
  return [
    { id: 'status', header: 'Status', value: (s) => STATUSES.indexOf(s.status), cell: (s) => <StatusBadge status={s.status} short />, width: 116, mobile: 'secondary', label: 'Status' },
    {
      id: 'name', header: 'Strategy', label: 'Strategy', value: (s) => s.name, sticky: true, width: 256, mobile: 'primary',
      cell: (s) => (
        <div className="flex min-w-0 flex-col gap-1 py-0.5">
          <Link to={`/strategies/${s.key}`} onClick={(e) => e.stopPropagation()} title={s.name} className="truncate font-semibold text-fg hover:underline max-md:line-clamp-2 max-md:whitespace-normal">{s.name}</Link>
          <span className="flex flex-wrap items-center gap-1">
            <HorizonChip horizon={s.horizon} letter />
            <EvidenceChip evidence={s.evidence} />
            {s.universe === 'etfs' && <EtfChip />}
            {s.blocked_by_regime && <span className="text-2xs text-muted" title="Regime filter on: no new buys while Nifty is below its 200-DMA">regime-blocked</span>}
          </span>
        </div>
      ),
    },
    {
      id: 'cagr', header: 'CAGR · timing', label: 'CAGR', title: 'Backtest yearly return (CAGR) since 2019, with the timing-luck range: the same rules rebalanced a few days earlier or started later',
      align: 'right', value: (s) => s.headline.cagr_pct, cell: (s) => <CagrCell s={s} />, width: 144, mobile: 'value',
      mobileCell: (s) => <span className="num font-semibold text-fg">{pct(s.headline.cagr_pct, { signed: false })}</span>,
    },
    { id: 'tax', header: 'After tax', title: 'CAGR after Indian capital-gains tax', align: 'right', value: (s) => s.headline.after_tax_cagr_pct, cell: (s) => <Pct v={s.headline.after_tax_cagr_pct} signed={false} />, width: 96, hideBelow: 1300 },
    {
      id: 'edge', header: 'Edge', label: 'Edge vs avg stock', title: 'CAGR minus the average stock in the same list (the fair test while backtests use today’s list). ETF strategies: vs Nifty 50 (*)',
      align: 'right', value: (s) => primaryEdge(s), mobile: 'change', width: 80,
      cell: (s) => <EdgeValue s={s} className="font-semibold" />,
    },
    {
      id: 'factor', header: 'vs ETF alt', label: 'vs factor index', align: 'right', value: (s) => s.edges.vs_factor_cagr_pct, width: 104, hideBelow: 1380,
      title: 'CAGR minus the matching real NSE factor index (investable via an index fund / ETF; no survivorship bias)',
      cell: (s) => (s.factor_benchmark_name ? <span title={`vs ${s.factor_benchmark_name}`}><Pts v={s.edges.vs_factor_cagr_pct} /></span> : <span className="text-faint">—</span>),
    },
    { id: 'dd', header: 'Max DD', title: 'Worst drop from a peak (max drawdown)', align: 'right', value: (s) => s.headline.max_dd_pct, cell: (s) => <Risk v={s.headline.max_dd_pct} />, width: 88, mobile: 'secondary', label: 'Max DD' },
    { id: 'sharpe', header: 'Sharpe', align: 'right', value: (s) => s.headline.sharpe, cell: (s) => <Ratio v={s.headline.sharpe} />, width: 88 },
    { id: 'r12', header: '12m', title: 'Return over the last 12 months (hover for Nifty 500)', align: 'right', value: (s) => s.headline.ret_12m_pct, cell: (s) => <span title={`Nifty 500 12m: ${pct(s.headline.n500_12m_pct)}`}><Pct v={s.headline.ret_12m_pct} /></span>, width: 72, mobile: 'secondary', label: '12m' },
    { id: 'r6', header: '6m', align: 'right', value: (s) => s.headline.ret_6m_pct, cell: (s) => <Pct v={s.headline.ret_6m_pct} />, width: 72, hideBelow: 1460 },
    { id: 'win', header: 'Win %', align: 'right', value: (s) => s.headline.win_rate, cell: (s) => <Pct v={s.headline.win_rate} signed={false} color={false} />, width: 80, hideBelow: 1060 },
    { id: 'trades', header: 'Trades', align: 'right', value: (s) => s.headline.trades, cell: (s) => <span className="num">{s.headline.trades}</span>, width: 88, hideBelow: 1240 },
    { id: 'exp', header: 'Exposure', title: 'Share of time invested', align: 'right', value: (s) => s.headline.exposure_pct, cell: (s) => <Pct v={s.headline.exposure_pct} signed={false} color={false} dp={0} />, width: 100, defaultHidden: true },
    { id: 'spark', header: 'Equity', value: () => null, sortable: false, cell: (s) => <Sparkline values={s.spark} width={88} height={24} />, width: 112 },
    {
      id: 'orders', header: 'Orders', title: 'Orders for the next open (buy / sell)', align: 'right', value: (s) => s.orders_buy + s.orders_sell, width: 88,
      cell: (s) => (s.orders_buy + s.orders_sell ? <span className="num"><span className="text-profit">{s.orders_buy}B</span> <span className="text-loss">{s.orders_sell}S</span></span> : <span className="text-faint">—</span>),
    },
  ]
}

/** Tested & rejected: never traded, so no live status / regime / orders columns; the reason is what matters. */
function rejectedColumns(): Col<StrategySummary>[] {
  const all = columns()
  const pick = (id: string) => all.find((c) => c.id === id)!
  return [
    { id: 'life', header: 'Status', value: (s) => s.lifecycle, cell: (s) => <LifecycleBadge lifecycle={s.lifecycle === 'disabled' ? 'disabled' : 'rejected'} />, width: 110, mobile: 'secondary', label: 'Status' },
    {
      id: 'name', header: 'Strategy', label: 'Strategy', value: (s) => s.name, sticky: true, minWidth: 220, mobile: 'primary',
      cell: (s) => (
        <div className="flex min-w-0 flex-col gap-1 py-0.5">
          <Link to={`/strategies/${s.key}`} onClick={(e) => e.stopPropagation()} className="truncate font-semibold text-fg hover:underline">{s.name}</Link>
          <span className="flex items-center gap-1"><HorizonChip horizon={s.horizon} letter /><EvidenceChip evidence={s.evidence} />{s.universe === 'etfs' && <EtfChip />}</span>
        </div>
      ),
    },
    { id: 'why', header: 'Why rejected', value: (s) => s.rejected_reason ?? '', cell: (s) => <span className="block max-w-[360px] whitespace-normal text-xs leading-4 text-muted">{s.rejected_reason ?? 'Disabled in config.yaml'}</span>, minWidth: 260 },
    pick('cagr'), pick('edge'), pick('dd'), pick('r12'), pick('trades'), pick('spark'),
  ]
}

function StrategyCard({ s }: { s: StrategySummary }) {
  const t = s.timing
  return (
    <Link to={`/strategies/${s.key}`} className={cn('focus-ring card flex min-w-0 flex-col gap-3 p-4 transition-colors hover:border-line-strong', s.status === 'not-working' && 'opacity-75')}>
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="line-clamp-2 text-[14px] font-semibold" title={s.name}>{s.name}</div>
          <div className="mt-1 flex flex-wrap items-center gap-1"><HorizonChip horizon={s.horizon} /><EvidenceChip evidence={s.evidence} />{s.universe === 'etfs' && <EtfChip />}</div>
        </div>
        <StatusBadge status={s.status} short />
      </div>
      {/* mt-auto: cards in a row share one height, so a one-line name leaves its spare line above the numbers and the
          CAGR, timing bar and metric rows line up across the row */}
      <div className="mt-auto flex flex-col gap-3">
        <div className="flex items-end justify-between gap-3">
          <div>
            <div className="text-2xs text-muted">CAGR (backtest)</div>
            <div className="num text-[26px] font-semibold leading-8">{pct(s.headline.cagr_pct, { signed: false })}</div>
          </div>
          <Sparkline values={s.spark} width={130} height={40} />
        </div>
        {t && <div><TimingRangeBar low={t.low} high={t.high} base={t.base_cagr_pct} consistent={t.consistent} /><div className="num mt-1 flex justify-between text-2xs text-faint"><span>{pct(t.low, { signed: false })}</span><span>timing range{!t.consistent && <span className="text-warn"> · out of date</span>}</span><span>{pct(t.high, { signed: false })}</span></div></div>}
        <div className="num grid grid-cols-3 gap-2 border-t border-line pt-3 text-xs">
          <div><div className="text-2xs text-muted">Edge{s.edges.primary === 'nifty' ? ' vs N50' : ' vs avg'}</div><EdgeValue s={s} className="font-semibold" /></div>
          <div><div className="text-2xs text-muted">Max DD</div><Risk v={s.headline.max_dd_pct} /></div>
          <div><div className="text-2xs text-muted">12m</div><Pct v={s.headline.ret_12m_pct} /></div>
        </div>
        <div className="text-2xs text-muted">{s.orders_buy + s.orders_sell ? `${s.orders_buy + s.orders_sell} order${s.orders_buy + s.orders_sell > 1 ? 's' : ''} for the next open` : 'No orders for the next open'} · holding {s.positions}</div>
      </div>
    </Link>
  )
}

function IntradayGroup({ rows }: { rows: IntradayStrategy[] }) {
  const nav = useNavigate()
  const cols: Col<IntradayStrategy>[] = [
    { id: 'status', header: 'Status', value: (s) => s.status, cell: (s) => <StatusBadge status={s.status} short />, width: 110 },
    { id: 'name', header: 'Strategy', value: (s) => s.name, sticky: true, minWidth: 240, mobile: 'primary', cell: (s) => (
      <div className="flex flex-col gap-1 py-0.5"><span className={cn('font-semibold max-md:line-clamp-2 max-md:whitespace-normal', s.status === 'not-working' && 'text-muted')}>{s.name}</span><span className="flex gap-1"><HorizonChip horizon="intraday" letter /><EvidenceChip evidence={s.evidence} /></span></div>
    ) },
    { id: 'ret', header: 'Return', title: 'Total return over the tested sessions, after all costs', align: 'right', value: (s) => s.metrics.return_pct, cell: (s) => <Pct v={s.metrics.return_pct} />, mobile: 'change' },
    { id: 'ann', header: 'Annualised', align: 'right', value: (s) => s.metrics.annualised_pct, cell: (s) => <Pct v={s.metrics.annualised_pct} /> },
    { id: 'dd', header: 'Max DD', align: 'right', value: (s) => s.metrics.max_dd_pct, cell: (s) => <Risk v={s.metrics.max_dd_pct} /> },
    { id: 'sh', header: 'Sharpe', align: 'right', value: (s) => s.metrics.sharpe, cell: (s) => <Ratio v={s.metrics.sharpe} /> },
    { id: 'win', header: 'Win %', align: 'right', value: (s) => s.metrics.win_rate, cell: (s) => <Pct v={s.metrics.win_rate} signed={false} color={false} />, hideBelow: 1300 },
    { id: 'tr', header: 'Trades', align: 'right', value: (s) => s.metrics.trades, cell: (s) => <span className="num">{s.metrics.trades}</span>, hideBelow: 1200 },
    { id: 'tpd', header: 'Per day', align: 'right', value: (s) => s.metrics.trades_per_day, cell: (s) => <span className="num">{num(s.metrics.trades_per_day, 1)}</span>, hideBelow: 1400 },
    { id: 'sig', header: 'Real edge?', title: 'Is the average day a profit beyond luck (95% confidence)? "loses" = a loss beyond luck', value: (s) => edgeVerdict(s), cell: (s) => <EdgeVerdict s={s} /> },
    { id: 'spark', header: 'Equity', value: () => null, sortable: false, cell: (s) => <Sparkline values={s.equity.series[0]?.v ?? []} width={88} height={24} /> },
  ]
  return <DataTable id="strategies.intraday" data={rows} columns={cols} rowKey={(s) => s.key} onRowClick={() => nav('/intraday')} />
}

function GroupHeader({ h, n, extra }: { h: Horizon; n: number; extra?: React.ReactNode }) {
  const Icon = HORIZON[h].icon
  return (
    <div className="flex flex-wrap items-center gap-2 border-b border-line bg-raised/40 px-4 py-2">
      <Icon className="h-4 w-4 text-muted" />
      <span className="text-[13px] font-semibold">{HORIZON[h].label}</span>
      <span className="num text-xs text-muted">{n}</span>
      <span className="text-xs text-faint">{HORIZON[h].help}</span>
      {extra && <span className="ml-auto">{extra}</span>}
    </div>
  )
}

function Rejected({ d, horizon }: { d: StrategyListResponse; horizon: 'all' | Horizon }) {
  const [open, setOpen] = useState(false)
  const cols = useMemo(rejectedColumns, [])
  const nav = useNavigate()
  const rejected = d.rejected.filter((r) => horizon === 'all' || r.horizon === horizon)
  const catalogue = d.rejected_catalogue.filter((r) => horizon === 'all' || r.horizon === horizon)
  const n = rejected.length + catalogue.length
  if (!n) return null
  const names = [...rejected.map((r) => r.name), ...catalogue.map((r) => r.name)]
  return (
    <Card flush>
      <button type="button" onClick={() => setOpen(!open)} className="focus-ring flex w-full items-center gap-2 px-4 py-3 text-left">
        <ChevronDown className={cn('h-4 w-4 text-muted transition-transform', !open && '-rotate-90')} />
        <Ban className="h-4 w-4 shrink-0 text-muted" />
        <span className="shrink-0 whitespace-nowrap text-[13px] font-semibold">Tested &amp; rejected</span>
        <span className="num shrink-0 text-xs text-muted">{n}</span>
        {!open && <span className="ml-2 min-w-0 flex-1 truncate text-xs text-faint max-sm:hidden" title={names.join(' · ')}>{names.join(' · ')}</span>}
      </button>
      {open && (
        <div className="border-t border-line">
          {rejected.length > 0 && <DataTable id="strategies.rejected" data={rejected} columns={cols} rowKey={(s) => s.key} onRowClick={(s) => nav(`/strategies/${s.key}`)} />}
          {catalogue.length > 0 && (
            <ul className="divide-y divide-line">
              {catalogue.map((r: RejectedEntry) => (
                <li key={r.key} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2.5 text-[13px] opacity-70">
                  <LifecycleBadge lifecycle="rejected" />
                  <span className="font-medium">{r.name}</span>
                  <HorizonChip horizon={r.horizon} letter />
                  <EvidenceChip evidence={r.evidence} />
                  <span className="min-w-[200px] flex-1 text-muted">{r.result_text}</span>
                  <span className="text-2xs text-faint">Not re-tested by this version</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </Card>
  )
}

function Filter<T extends string>({ label, all, value, onChange, render }: { label: string; all: T[]; value: T[]; onChange: (v: T[]) => void; render: (v: T) => string }) {
  return (
    <Popover trigger={({ toggle, open }) => <SelectButton label={label} value={value.length ? `${value.length}` : 'All'} open={open} onClick={toggle} />}>
      <div className="py-1">
        {all.map((v) => (
          <MenuCheck key={v} checked={value.includes(v)} onChange={(on) => onChange(on ? [...value, v] : value.filter((x) => x !== v))}>{render(v)}</MenuCheck>
        ))}
        {value.length > 0 && <button type="button" className="w-full px-2.5 py-1.5 text-left text-xs text-accent hover:underline" onClick={() => onChange([])}>Clear</button>}
      </div>
    </Popover>
  )
}

export default function Strategies() {
  const [sp, setSp] = useSearchParams()
  const tab = (sp.get('horizon') as Horizon | null) ?? 'all'
  const view = (sp.get('view') as View | null) ?? 'table'
  const status = (sp.get('status')?.split(',').filter(Boolean) ?? []) as StrategyStatus[]
  const evidence = (sp.get('evidence')?.split(',').filter(Boolean) ?? []) as Evidence[]
  const universe = sp.get('universe') ?? 'all'
  const setParam = (k: string, v: string | null) => setSp((p) => { const n = new URLSearchParams(p); if (v) n.set(k, v); else n.delete(k); return n }, { replace: true })
  const q = useStrategies()
  const intra = useIntraday()
  const [sorting, setSorting] = useState<SortingState>([])
  const nav = useNavigate()
  const d = q.data
  const cols = useMemo(columns, [])
  const [boxRef, boxW] = useWidth<HTMLDivElement>()

  const filtered = useMemo(() => (d ? d.strategies.filter((s) =>
    (!status.length || status.includes(s.status)) && (!evidence.length || evidence.includes(s.evidence)) && (universe === 'all' || s.universe === universe),
  ) : []), [d, status, evidence, universe])

  const intraAll = intra.data?.strategies ?? []
  // the Status / Evidence / Universe filters apply to the intraday group too (intraday strategies trade stocks)
  const intraRows = useMemo(() => intraAll.filter((s) =>
    (!status.length || status.includes(s.status)) && (!evidence.length || evidence.includes(s.evidence)) && universe !== 'etfs',
  ), [intraAll, status, evidence, universe])
  const counts = { longterm: d?.counts.longterm ?? 0, swing: d?.counts.swing ?? 0, intraday: intraAll.length || d?.counts.intraday || 0 }
  const horizons = tab === 'all' ? HORIZONS : [tab]
  const b = d?.benchmarks

  return (
    <div>
      <PageHeader
        title="Strategies"
        subtitle={d ? <>Every strategy re-tested on {d.period.start ? date(d.period.start) : '—'} → {date(d.period.end)} after each scan, with full Indian costs. Backtest numbers.</> : <Skeleton className="h-3 w-80" />}
        right={
          <Segmented<View> ariaLabel="View" value={view} onChange={(v) => setParam('view', v === 'table' ? null : v)} items={[
            { id: 'table', label: <><Rows3 className="h-3.5 w-3.5" />Table</> }, { id: 'cards', label: <><LayoutGrid className="h-3.5 w-3.5" />Cards</> },
          ]} />
        }
      />
      {q.error && !d ? <div className="card"><ErrorState error={q.error} onRetry={() => void q.refetch()} /></div> : !d ? (
        <div className="card"><SkeletonRows rows={10} cols={8} /></div>
      ) : (
        <div ref={boxRef} className="space-y-3">
          <div className="border-b border-line">
            <Tabs<'all' | Horizon>
              value={tab}
              onChange={(h) => setParam('horizon', h === 'all' ? null : h)}
              items={[
                { id: 'all', label: 'All', count: counts.longterm + counts.swing + counts.intraday },
                { id: 'longterm', label: 'Long-term', count: counts.longterm },
                { id: 'swing', label: 'Swing', count: counts.swing },
                { id: 'intraday', label: 'Intraday', count: counts.intraday },
              ]}
            />
          </div>

          <div className="card num flex flex-wrap items-center gap-x-5 gap-y-1.5 px-4 py-3 text-[13px]">
            <span className="text-muted">Same period {date(d.period.start)} → {date(d.period.end)}:</span>
            <span>Nifty 50 <span className="font-semibold">{pct(b?.nifty50?.cagr_pct, { signed: false })}</span>/yr</span>
            <span>Nifty 500 <span className="font-semibold">{pct(b?.nifty500?.cagr_pct, { signed: false })}</span>/yr</span>
            <span>Average stock in this list <span className="font-semibold">{pct(b?.average_stock?.cagr_pct, { signed: false })}</span>/yr
              <Help text="Equal-weight average of every stock in today's Nifty 500 list. It is inflated by survivorship bias, which is exactly why strategies are judged against it." />
            </span>
          </div>
          <BiasNote asOf={d.as_of} gap={b?.survivorship_gap_pct} />

          {tab !== 'intraday' && (
            <div className="flex flex-wrap items-center gap-2">
              <Filter label="Status" all={STATUSES} value={status} onChange={(v) => setParam('status', v.join(',') || null)} render={(v) => STATUS[v].label} />
              <Filter label="Evidence" all={EVIDENCES} value={evidence} onChange={(v) => setParam('evidence', v.join(',') || null)} render={(v) => EVIDENCE[v].label} />
              <Segmented ariaLabel="Universe" value={universe} onChange={(v) => setParam('universe', v === 'all' ? null : v)} items={[{ id: 'all', label: 'All' }, { id: 'stocks', label: 'Stocks' }, { id: 'etfs', label: 'ETFs' }]} />
              <span className="ml-auto flex items-center gap-2 text-xs text-muted">
                <span>
                  Sort: {sorting.length ? 'by column' : 'evidence order (working first, then evidence, then 12m)'}
                  {sorting.length > 0 && <Button size="xs" variant="ghost" className="ml-1" onClick={() => setSorting([])}>Reset</Button>}
                </span>
                {/* one column choice for every group, here instead of a toolbar row on the first group only */}
                {view === 'table' && <ColumnChooser id="strategies" columns={cols} boxWidth={boxW - 2} />}
              </span>
            </div>
          )}

          {horizons.map((h) => {
            if (h === 'intraday') {
              return (
                <Card key={h} flush>
                  <GroupHeader h="intraday" n={intraRows.length} extra={<Link to="/intraday" className="link inline-flex items-center gap-1 text-xs">Intraday research <ArrowRight className="h-3 w-3" /></Link>} />
                  <div className="border-b border-line bg-loss/[0.05] px-4 py-2 text-xs text-muted">
                    {intra.data?.summary ?? 'Research only: intraday strategies produce no orders.'}
                  </div>
                  {intra.error ? <ErrorState error={intra.error} compact /> : !intra.data ? <SkeletonRows rows={4} /> : intraRows.length ? <IntradayGroup rows={intraRows} /> : intraAll.length ? <div className="px-4 py-4 text-[13px] text-muted">No intraday strategies match the filters.</div> : <div className="px-4 py-4 text-[13px] text-muted">{intra.data.reason ?? 'Intraday backtest not run yet.'}</div>}
                </Card>
              )
            }
            const rows = filtered.filter((s) => s.horizon === h)
            if (view === 'cards') {
              return (
                <section key={h} className="space-y-2">
                  <div className="card overflow-hidden"><GroupHeader h={h} n={rows.length} /></div>
                  <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">{rows.map((s) => <StrategyCard key={s.key} s={s} />)}</div>
                </section>
              )
            }
            return (
              <Card key={h} flush>
                <GroupHeader h={h} n={rows.length} />
                <DataTable
                  id="strategies"
                  data={rows}
                  columns={cols}
                  rowKey={(s) => s.key}
                  onRowClick={(s) => nav(`/strategies/${s.key}`)}
                  rowClassName={(s) => (s.status === 'not-working' ? 'opacity-75' : undefined)}
                  sorting={sorting}
                  onSortingChange={setSorting}
                  fixedLayout
                  keyboard={h === horizons[0]}
                  empty={<div className="px-4 py-4 text-[13px] text-muted">No strategies match the filters.</div>}
                />
              </Card>
            )
          })}
          {tab !== 'intraday' && <Rejected d={d} horizon={tab} />}
          <p className="text-2xs text-faint">* ETF strategies are compared with Nifty 50. “!” next to the timing range: the range was computed on older data and does not contain the base CAGR; re-scan.</p>
        </div>
      )}
    </div>
  )
}
