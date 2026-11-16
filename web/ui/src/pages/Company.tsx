// Company `/company/:symbol`: ten-plus years of a company's financials from NSE's filings (web/api/services/company_svc.py)
// - the key ratios, compounded growth, profit & loss, quarters, balance sheet, cash flow, ratios by year, business
// segments, industry peers and the filings timeline (call transcripts, presentations, annual reports). What
// Screener.in, Tijori or Trendlyne show, built from the filings they start from; every year links to its filing.

import { useMemo, useState, type FormEvent } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { Building2, CandlestickChart, ExternalLink, FileText, RefreshCw } from 'lucide-react'
import { fetchJson } from '@/api/client'
import { useCompany, useDocuments, type CompanyView, type LineKind, type PeerRow, type Statement } from '@/api/company'
import { DataTable, type Col } from '@/components/DataTable'
import { IvRankTile } from '@/components/IvRank'
import { KpiStrip, KpiTile, PageHeader } from '@/components/domain'
import { EmptyState, ErrorState, SkeletonRows } from '@/components/feedback'
import { Button, Card, Segmented, Tabs } from '@/components/ui'
import { cn } from '@/lib/csv'

const inr = (v: number) => v.toLocaleString('en-IN', { maximumFractionDigits: Math.abs(v) >= 100 ? 0 : 2 })
const fmt = (v: number | null | undefined, kind: LineKind) =>
  v == null ? '—' : kind === 'pct' ? `${v.toFixed(1)}%` : kind === 'x' ? v.toFixed(2) : inr(v)
const pct = (v: unknown) => (typeof v === 'number' ? `${v.toFixed(1)}%` : '—')
const cr = (v: unknown) => (typeof v === 'number' ? `₹${inr(v)} cr` : '—')
const x = (v: unknown, nd = 1) => (typeof v === 'number' ? v.toFixed(nd) : '—')
const period = (end: string, quarter = false) => {
  const d = new Date(`${end}T00:00:00Z`)
  return `${d.toLocaleString('en-IN', { month: 'short', timeZone: 'UTC' })} ${quarter ? String(d.getUTCFullYear()).slice(2) : d.getUTCFullYear()}`
}

/** A statement as Screener lays it out: line items down, periods across (oldest left), each period linked to its filing. */
function StatementTable({ s, quarter }: { s: Statement; quarter?: boolean }) {
  if (!s.periods.length || !s.rows.length) return <EmptyState compact title="Not in the filings for this basis." />
  return (
    <div className="scroll-x">
      <table className="w-full min-w-max text-[12.5px]">
        <thead>
          <tr className="border-b border-line text-2xs uppercase tracking-[0.04em] text-muted">
            <th className="sticky left-0 z-[1] bg-panel px-3 py-2 text-left font-semibold">₹ crore</th>
            {s.periods.map((p, i) => (
              <th key={p} className="px-2.5 py-2 text-right font-semibold">
                {s.sources[i]?.url ? (
                  <a className="inline-flex items-center gap-0.5 hover:text-fg" href={s.sources[i].url!} target="_blank" rel="noreferrer"
                    title={`Filed ${s.sources[i].filed ?? '?'} · ${s.sources[i].src === 'xbrl' ? 'XBRL filing' : "NSE's line items"} - open the source`}>
                    {period(p, quarter)}<ExternalLink className="h-2.5 w-2.5 opacity-60" />
                  </a>) : period(p, quarter)}
              </th>))}
          </tr>
        </thead>
        <tbody>
          {s.rows.map((r) => (
            <tr key={r.key} className={cn('border-b border-line/60', ['ebitda', 'pbt', 'profit', 'nii', 'fcf', 'equity', 'cfo'].includes(r.key) && 'font-semibold')}>
              <td className="sticky left-0 z-[1] whitespace-nowrap bg-panel px-3 py-1.5 text-fg">{r.label}</td>
              {r.values.map((v, i) => (
                <td key={i} className={cn('num px-2.5 py-1.5 text-right', v != null && v < 0 && 'text-loss', v == null && 'text-faint')}>{fmt(v, r.kind)}</td>))}
            </tr>))}
        </tbody>
      </table>
    </div>
  )
}

function Growth({ s }: { s: CompanyView['snapshot'] }) {
  const rows: [string, string][] = [['Sales', 'sales_cagr'], ['Profit', 'profit_cagr'], ['Average ROE', 'roe'], ['Average ROCE', 'roce']]
  return (
    <table className="w-full text-[13px]">
      <thead><tr className="text-2xs uppercase tracking-[0.04em] text-muted"><th className="py-1 text-left font-semibold">Compounded / average</th>{['3 years', '5 years', '10 years'].map((h) => <th key={h} className="py-1 text-right font-semibold">{h}</th>)}</tr></thead>
      <tbody>
        {rows.map(([label, k]) => (
          <tr key={k} className="border-t border-line/60">
            <td className="py-1.5">{label}</td>
            {[3, 5, 10].map((n) => {
              const v = s[`${k}_${n}y`] as number | null | undefined
              return <td key={n} className={cn('num py-1.5 text-right', typeof v === 'number' && v < 0 && 'text-loss')}>{pct(v)}</td>
            })}
          </tr>))}
      </tbody>
    </table>
  )
}

const PEER_COLS: Col<PeerRow>[] = [
  { id: 'sym', header: 'Company', value: (r) => r.symbol, sticky: true, mobile: 'primary', cell: (r) => <Link to={`/company/${r.symbol}`} className="font-semibold hover:underline" title={r.company ?? undefined}>{r.symbol}</Link> },
  { id: 'mcap', header: 'Market cap ₹ cr', align: 'right', value: (r) => r.market_cap_cr, mobile: 'value', cell: (r) => <span className="num">{r.market_cap_cr == null ? '—' : inr(r.market_cap_cr)}</span> },
  { id: 'pe', header: 'P/E', align: 'right', value: (r) => r.pe, cell: (r) => <span className="num">{x(r.pe)}</span> },
  { id: 'pb', header: 'P/B', align: 'right', value: (r) => r.pb, cell: (r) => <span className="num">{x(r.pb)}</span> },
  { id: 'roce', header: 'ROCE', align: 'right', value: (r) => r.roce, cell: (r) => <span className="num">{pct(r.roce)}</span> },
  { id: 'roe', header: 'ROE', align: 'right', value: (r) => r.roe, cell: (r) => <span className="num">{pct(r.roe)}</span> },
  { id: 'de', header: 'Debt/eq', align: 'right', value: (r) => r.de, cell: (r) => <span className="num">{x(r.de, 2)}</span> },
  { id: 'opm', header: 'OPM', align: 'right', value: (r) => r.opm, cell: (r) => <span className="num">{pct(r.opm)}</span> },
  { id: 'sg', header: 'Sales 3y', title: 'Sales growth, 3-year compounded', align: 'right', value: (r) => r.sales_cagr_3y, cell: (r) => <span className="num">{pct(r.sales_cagr_3y)}</span> },
  { id: 'pg', header: 'Profit 3y', title: 'Profit growth, 3-year compounded', align: 'right', value: (r) => r.profit_cagr_3y, cell: (r) => <span className="num">{pct(r.profit_cagr_3y)}</span> },
  { id: 'dy', header: 'Div yield', align: 'right', value: (r) => r.dividend_yield, cell: (r) => <span className="num">{pct(r.dividend_yield)}</span> },
]

function Segments({ d }: { d: CompanyView }) {
  const latest = d.segments.find((s) => s.period === 'year') ?? d.segments[0]
  if (!latest) return null
  const total = latest.segments.reduce((a, s) => a + Math.max(s.revenue_cr ?? 0, 0), 0) || 1
  return (
    <Card title="Business segments" subtitle={`Revenue and result by segment, ${latest.period === 'year' ? 'year to' : 'quarter to'} ${period(latest.end)} (as reported in the results)`}>
      <div className="space-y-1.5">
        {latest.segments.map((s) => (
          <div key={s.name} className="grid grid-cols-[minmax(0,14rem)_1fr_auto_auto] items-center gap-2 text-[12.5px]">
            <span className="truncate" title={s.name}>{s.name}</span>
            <div className="h-2.5 overflow-hidden rounded bg-raised"><div className="h-full bg-accent/60" style={{ width: `${(Math.max(s.revenue_cr ?? 0, 0) / total) * 100}%` }} /></div>
            <span className="num w-24 text-right">{cr(s.revenue_cr)}</span>
            <span className={cn('num w-28 text-right text-muted', (s.result_cr ?? 0) < 0 && 'text-loss')} title="Segment result (profit before interest and tax)">{s.result_cr == null ? '' : `result ${inr(s.result_cr)}`}</span>
          </div>))}
      </div>
      {d.segments.filter((s) => s.period === 'year').length > 1 && (
        <p className="mt-2 text-2xs text-muted">Earlier years: {d.segments.filter((s) => s.period === 'year').slice(1).map((s) => `${period(s.end)} ${s.segments.map((g) => `${g.name} ${inr(g.revenue_cr ?? 0)}`).join(', ')}`).join(' · ')}</p>)}
    </Card>
  )
}

function DocumentsCard({ symbol }: { symbol: string }) {
  const q = useDocuments(symbol)
  const [cat, setCat] = useState<string>('transcript')
  const d = q.data
  const items = useMemo(() => (d?.items ?? []).filter((i) => cat === 'all' || i.category === cat).slice(0, 60), [d, cat])
  return (
    <Card title={<span className="flex items-center gap-1.5"><FileText className="h-4 w-4 text-muted" />Filings: transcripts, presentations, reports</span>}
      subtitle={d?.note ?? "Everything the company filed with NSE since 2004 that an investor reads"}>
      {!d ? (q.error ? <ErrorState compact error={q.error} /> : <SkeletonRows rows={4} />) : (
        <>
          <div className="mb-2 flex flex-wrap gap-1.5">
            {[...d.categories.filter((c) => c.count > 0), { id: 'all', label: 'All', count: d.items.length }].map((c) => (
              <button key={c.id} onClick={() => setCat(c.id)} className={cn('rounded-full border px-2.5 py-0.5 text-xs', cat === c.id ? 'border-accent bg-accent/10 text-fg' : 'border-line text-muted hover:text-fg')}>
                {c.label} <span className="num text-faint">{c.count}</span>
              </button>))}
          </div>
          {items.length === 0 ? <p className="text-xs text-muted">None filed.</p> : (
            <ul className="max-h-96 divide-y divide-line/60 overflow-auto text-[12.5px]">
              {items.map((i, k) => (
                <li key={k} className="flex items-start gap-3 py-1.5">
                  <span className="num w-20 shrink-0 text-muted">{i.time ? i.time.slice(0, 10) : '—'}</span>
                  <span className="min-w-0 flex-1">
                    {i.url ? <a href={i.url} target="_blank" rel="noreferrer" className="hover:underline">{i.text || i.subject}</a> : (i.text || i.subject)}
                    {i.category === 'annual_report' && <span className="text-muted"> {i.subject}</span>}
                  </span>
                  {i.size && <span className="shrink-0 text-2xs text-faint">{i.size}</span>}
                </li>))}
            </ul>)}
        </>)}
    </Card>
  )
}

type StatTab = 'pl' | 'quarters' | 'bs' | 'cf' | 'ratios'

export default function Company() {
  const { symbol = '' } = useParams()
  const sym = symbol.toUpperCase()
  const nav = useNavigate()
  const qc = useQueryClient()
  const [basis, setBasis] = useState<'consolidated' | 'standalone' | undefined>(undefined)
  const [tab, setTab] = useState<StatTab>('pl')
  const [refreshing, setRefreshing] = useState(false)
  const [input, setInput] = useState('')
  const q = useCompany(sym, basis)
  const d = q.data?.symbol === sym ? q.data : undefined
  const go = (e: FormEvent) => { e.preventDefault(); const s = input.trim().toUpperCase(); if (s) { setBasis(undefined); nav(`/company/${encodeURIComponent(s)}`); setInput('') } }
  const refresh = async () => {
    setRefreshing(true)
    try {
      const v = await fetchJson<CompanyView>(`/api/company/${encodeURIComponent(sym)}?refresh=true${basis ? `&basis=${basis}` : ''}`)
      qc.setQueryData(['company', sym, basis ?? 'auto'], v)
    } finally { setRefreshing(false) }
  }
  const search = (
    <form onSubmit={go} className="flex items-center gap-1.5">
      <input className="input h-8 w-36" placeholder="Another symbol" value={input} onChange={(e) => setInput(e.target.value)} aria-label="Open another company" />
    </form>
  )
  if (!sym) return <div><PageHeader title="Company" right={search} /><EmptyState title="Type a symbol to open its financials." /></div>
  if (q.error && !d) return <div><PageHeader title={sym} right={search} /><div className="card"><ErrorState error={q.error} onRetry={() => void q.refetch()} /></div></div>
  if (!d) return <div><PageHeader title={sym} subtitle="Fetching ten years of filings from NSE (a few seconds the first time)…" right={search} /><div className="card"><SkeletonRows rows={10} /></div></div>
  const s = d.snapshot
  const empty = !d.years.periods.length && !d.quarters.periods.length
  return (
    <div className="space-y-3">
      <PageHeader
        title={<span className="flex items-center gap-2"><Building2 className="h-5 w-5 text-muted" />{d.company ?? sym} <span className="text-sm font-normal text-muted">{sym}</span></span>}
        subtitle={<>{d.industry ?? 'Industry not classified'}{d.bank ? ' · bank' : ''} · {d.price != null ? `₹${d.price.toLocaleString('en-IN')}` : 'no price'} · checked {d.checked ?? '—'}</>}
        right={
          <div className="flex flex-wrap items-center gap-2">
            <Segmented ariaLabel="Basis" value={d.basis} onChange={(b) => setBasis(b)} items={[
              { id: 'consolidated', label: 'Consolidated', disabled: !d.bases.consolidated, title: 'The group: the company with its subsidiaries' },
              { id: 'standalone', label: 'Standalone', disabled: !d.bases.standalone, title: 'The listed company on its own' }]} />
            <Button variant="subtle" size="sm" icon={<RefreshCw className="h-3.5 w-3.5" />} loading={refreshing} onClick={() => void refresh()} title="Fetch from NSE now">Refresh</Button>
            <Link to={`/chart/${sym}`} className="focus-ring inline-flex h-8 items-center gap-1.5 rounded-md border border-line px-3 text-[13px] font-medium hover:bg-raised"><CandlestickChart className="h-3.5 w-3.5" />Chart</Link>
            {search}
          </div>}
      />
      {empty ? <EmptyState title={`No results filed by ${sym} were found on NSE.`}>An ETF or index has none; for a new listing the first results are still to come.</EmptyState> : (
        <>
          <KpiStrip min={128}>
            <KpiTile label="Market cap" value={cr(s.market_cap)} sub={s.price ? 'at the live / last price' : 'no price'} />
            <KpiTile label="P/E" value={x(s.pe)} sub={s.ttm_end ? `profit of the 4 quarters to ${period(s.ttm_end, true)}` : 'last full year'} />
            <KpiTile label="P/B" value={x(s.pb)} sub="price to book (equity)" />
            {d.bank ? <KpiTile label="ROA" value={pct(s.roa)} sub="profit / total assets" /> : <KpiTile label="ROCE" value={pct(s.roce)} sub="EBIT / (equity + debt)" />}
            <KpiTile label="ROE" value={pct(s.roe)} sub="profit / average equity" />
            {d.bank ? <KpiTile label="Gross NPA" value={pct(s.gross_npa_pct)} sub={`net ${pct(s.net_npa_pct)}`} /> : <KpiTile label="Debt / equity" value={x(s.de, 2)} sub={`OPM ${pct(s.opm)}`} />}
            <KpiTile label="Sales growth 5y" value={pct(s.sales_cagr_5y)} sub={`3y ${pct(s.sales_cagr_3y)}`} tone={typeof s.sales_cagr_5y === 'number' && s.sales_cagr_5y < 0 ? 'text-loss' : undefined} />
            <KpiTile label="Profit growth 5y" value={pct(s.profit_cagr_5y)} sub={`3y ${pct(s.profit_cagr_3y)}`} />
            <KpiTile label="Dividend yield" value={pct(s.dividend_yield)} sub={`earnings yield ${pct(s.earnings_yield)}`} />
            <KpiTile label="QVM score" value={<span className={cn(typeof d.score?.score === 'number' && d.score.score >= 70 ? 'text-profit' : typeof d.score?.score === 'number' && d.score.score <= 30 ? 'text-loss' : undefined)}>{x(d.score?.score, 0)}</span>}
              sub={d.score?.score == null ? 'needs filings + scan' : `Q ${x(d.score.quality, 0)} · V ${x(d.score.value, 0)} · M ${x(d.score.momentum, 0)}`}
              title={`Our quality / value / momentum score, 0-100 among ${d.score?.ranked ?? 0} stocks with stored financials (scanner/qvm.py). Its backtest: Strategies > Quality-value-momentum score.`} />
            <IvRankTile symbol={sym} />
          </KpiStrip>

          <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(0,22rem)]">
            <Card title="Financial statements" subtitle={`${d.basis === 'consolidated' ? 'Consolidated (the group)' : 'Standalone (the listed company)'} · fiscal years ending ${d.years.periods.length ? period(d.years.periods[d.years.periods.length - 1]).split(' ')[0] : 'March'} · click a year to open its filing`} flush
              right={<Tabs size="sm" value={tab} onChange={setTab} items={[{ id: 'pl', label: 'Profit & loss' }, { id: 'quarters', label: 'Quarters' }, { id: 'bs', label: 'Balance sheet' }, { id: 'cf', label: 'Cash flow' }, { id: 'ratios', label: 'Ratios' }]} />}>
              {tab === 'pl' && <StatementTable s={d.years} />}
              {tab === 'quarters' && <StatementTable s={d.quarters} quarter />}
              {tab === 'bs' && <StatementTable s={d.balance_sheet} />}
              {tab === 'cf' && <StatementTable s={d.cash_flow} />}
              {tab === 'ratios' && <StatementTable s={d.ratios} />}
            </Card>
            <Card title="Growth and returns" subtitle={`To the year ending ${s.year_end ? period(String(s.year_end)) : '—'}; blank where the filings don't reach back`}>
              <Growth s={s} />
            </Card>
          </div>

          <Segments d={d} />

          <Card title={`Peers: ${d.peers.industry ?? 'industry unknown'}${d.bank ? ' (banks)' : ''}`} subtitle={d.peers.missing ? `${d.peers.rows.length} with stored financials, largest first; ${d.peers.missing} not fetched yet (Company screener > Fetch all)` : 'Largest first, from the same filings'} flush>
            {d.peers.rows.length <= 1 ? <EmptyState compact title="No peer's financials are stored yet." >Fetch every company once from the Company screener; peers fill in as they arrive.</EmptyState>
              : <DataTable id="company.peers" data={d.peers.rows} columns={PEER_COLS} rowKey={(r) => r.symbol} exportName={`peers-${sym}`} />}
          </Card>
        </>)}

      <DocumentsCard symbol={sym} />
      <p className="text-2xs text-muted">{d.note}</p>
    </div>
  )
}
