// Company screener `/companies`: every stock's latest quarter from NSE's filings (P/E, revenue and profit growth,
// margin, EPS) next to its price trend, sortable and filterable (web/api/services/fund_svc.py screener).

import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Building2, Download } from 'lucide-react'
import { fetchJson } from '@/api/client'
import { PageHeader } from '@/components/domain'
import { EmptyState, ErrorState, SkeletonRows } from '@/components/feedback'
import { Button, Card, Field } from '@/components/ui'
import { downloadCsv } from '@/lib/exporting'
import { useLocalStorage } from '@/lib/useLocalStorage'
import { cn } from '@/lib/csv'

interface Row {
  symbol: string; company: string | null; industry: string | null; price: number | null; ret_3m: number | null; ret_12m: number | null; rs: number | null
  above_sma200: boolean | null; pct_from_52w_high: number | null; turnover_cr: number | null; qe: string | null; filed: string | null
  revenue_cr: number | null; profit_cr: number | null; sales_growth: number | null; profit_growth: number | null; net_margin: number | null; eps_ttm: number | null; pe: number | null
}
interface Resp { rows: Row[]; stored: number; universe: number; note: string }
interface FStatus { companies: number; universe: number; job: { running: boolean; done: number; total: number } }
type Key = keyof Row
const COLS: { k: Key; label: string; fmt: (r: Row) => string; tone?: (r: Row) => string }[] = [
  { k: 'pe', label: 'P/E', fmt: (r) => (r.pe != null ? r.pe.toFixed(1) : '—') },
  { k: 'sales_growth', label: 'Revenue y/y', fmt: (r) => g(r.sales_growth), tone: (r) => t(r.sales_growth) },
  { k: 'profit_growth', label: 'Profit y/y', fmt: (r) => g(r.profit_growth), tone: (r) => t(r.profit_growth) },
  { k: 'net_margin', label: 'Margin', fmt: (r) => (r.net_margin != null ? `${r.net_margin.toFixed(1)}%` : '—') },
  { k: 'revenue_cr', label: 'Revenue ₹ cr', fmt: (r) => (r.revenue_cr != null ? Math.round(r.revenue_cr).toLocaleString('en-IN') : '—') },
  { k: 'eps_ttm', label: 'EPS (4Q)', fmt: (r) => (r.eps_ttm != null ? r.eps_ttm.toFixed(2) : '—') },
  { k: 'ret_3m', label: '3M', fmt: (r) => g(r.ret_3m), tone: (r) => t(r.ret_3m) },
  { k: 'ret_12m', label: '12M', fmt: (r) => g(r.ret_12m), tone: (r) => t(r.ret_12m) },
  { k: 'rs', label: 'RS', fmt: (r) => (r.rs != null ? String(r.rs) : '—') },
]
const g = (v: number | null) => (v == null ? '—' : `${v >= 0 ? '+' : ''}${v.toFixed(1)}%`)
const t = (v: number | null) => (v == null ? '' : v >= 0 ? 'text-profit' : 'text-loss')
const n = (s: string) => (s.trim() === '' ? null : Number(s))

export default function Companies() {
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['fundamentals-screener'], queryFn: () => fetchJson<Resp>('/api/fundamentals-screener'), staleTime: 5 * 60_000 })
  const st = useQuery({ queryKey: ['fundamentals-status'], queryFn: () => fetchJson<FStatus>('/api/fundamentals-status'), refetchInterval: (x) => (x.state.data?.job.running ? 5000 : false) })
  const all = useMutation({ mutationFn: () => fetchJson<FStatus>('/api/fundamentals/refresh', { method: 'POST', body: '{}' }), onSuccess: () => { void qc.invalidateQueries({ queryKey: ['fundamentals-status'] }) } })
  const [sort, setSort] = useLocalStorage<{ k: Key; desc: boolean }>('qd.companies.sort', { k: 'profit_growth', desc: true })
  const [f, setF] = useLocalStorage('qd.companies.filter', { maxPe: '', minProfit: '', minSales: '', trend: false, industry: '' })
  const [shown, setShown] = useState(100)
  const d = q.data
  const industries = useMemo(() => [...new Set((d?.rows ?? []).map((r) => r.industry).filter(Boolean) as string[])].sort(), [d])
  const rows = useMemo(() => {
    const maxPe = n(f.maxPe), minP = n(f.minProfit), minS = n(f.minSales)
    const out = (d?.rows ?? []).filter((r) => (maxPe == null || (r.pe != null && r.pe <= maxPe)) && (minP == null || (r.profit_growth != null && r.profit_growth >= minP))
      && (minS == null || (r.sales_growth != null && r.sales_growth >= minS)) && (!f.trend || r.above_sma200) && (!f.industry || r.industry === f.industry))
    return out.sort((a, b) => {
      const x = a[sort.k], y = b[sort.k]
      if (x == null) return 1
      if (y == null) return -1
      return (x < y ? -1 : x > y ? 1 : 0) * (sort.desc ? -1 : 1)
    })
  }, [d, f, sort])
  const s = st.data
  return (
    <div>
      <PageHeader title="Company screener" subtitle={d ? `${d.stored} of ${d.universe} stocks have their filings stored · ${rows.length} match` : 'Valuation and growth from NSE filings'}
        right={<>
          {s && s.companies < s.universe && <Button size="sm" variant="subtle" loading={s.job.running || all.isPending} disabled={s.job.running} onClick={() => all.mutate()}>{s.job.running ? `Fetching ${s.job.done} of ${s.job.total}` : 'Fetch all companies'}</Button>}
          <Button size="sm" variant="subtle" icon={<Download className="h-4 w-4" />} disabled={!rows.length}
            onClick={() => downloadCsv('company-screener.csv', rows.map((r) => ({ ...r })))}>CSV</Button>
        </>} />
      <Card className="mb-3">
        <div className="flex flex-wrap items-end gap-3">
          <Field label="P/E at most"><input className="input h-9 w-24 px-2 text-right" inputMode="decimal" value={f.maxPe} onChange={(e) => setF({ ...f, maxPe: e.target.value })} /></Field>
          <Field label="Profit growth at least %"><input className="input h-9 w-24 px-2 text-right" inputMode="decimal" value={f.minProfit} onChange={(e) => setF({ ...f, minProfit: e.target.value })} /></Field>
          <Field label="Revenue growth at least %"><input className="input h-9 w-24 px-2 text-right" inputMode="decimal" value={f.minSales} onChange={(e) => setF({ ...f, minSales: e.target.value })} /></Field>
          <Field label="Industry"><select className="input h-9 px-2" value={f.industry} onChange={(e) => setF({ ...f, industry: e.target.value })}><option value="">All</option>{industries.map((i) => <option key={i}>{i}</option>)}</select></Field>
          <label className="flex items-center gap-2 pb-2 text-xs text-muted"><input type="checkbox" checked={f.trend} onChange={(e) => setF({ ...f, trend: e.target.checked })} /> Above its 200-day average</label>
          <Button size="sm" variant="ghost" onClick={() => setF({ maxPe: '', minProfit: '', minSales: '', trend: false, industry: '' })}>Clear</Button>
        </div>
      </Card>
      {q.error ? <ErrorState error={q.error} onRetry={() => q.refetch()} /> : !d ? <Card><SkeletonRows rows={12} cols={8} /></Card> : d.stored === 0 ? (
        <EmptyState icon={<Building2 />} title="No company filings stored yet" action={<Button variant="primary" onClick={() => all.mutate()}>Fetch all companies (about an hour, in the background)</Button>}>The screener reads each company's quarterly results from NSE once, then keeps them current.</EmptyState>
      ) : (
        <Card flush>
          <div className="overflow-x-auto"><table className="w-full text-[13px]">
            <thead className="text-2xs text-muted"><tr className="text-left">
              <th className="px-4 py-1.5">Stock</th><th className="px-2">Quarter</th>
              {COLS.map((c) => <th key={c.k} className="px-2 text-right"><button type="button" className={cn('hover:text-fg', sort.k === c.k && 'text-fg')} onClick={() => setSort({ k: c.k, desc: sort.k === c.k ? !sort.desc : true })}>{c.label}{sort.k === c.k ? (sort.desc ? ' ↓' : ' ↑') : ''}</button></th>)}
            </tr></thead>
            <tbody className="divide-y divide-line">{rows.slice(0, shown).map((r) => (
              <tr key={r.symbol}>
                <td className="max-w-[220px] truncate px-4 py-1.5"><Link to={`/chart/${r.symbol}`} className="font-semibold hover:text-accent">{r.symbol}</Link> <span className="text-2xs text-muted">{r.industry}</span></td>
                <td className="px-2 text-2xs text-muted">{r.qe?.slice(0, 7)}</td>
                {COLS.map((c) => <td key={c.k} className={cn('num px-2 text-right', c.tone?.(r))}>{c.fmt(r)}</td>)}
              </tr>))}</tbody>
          </table></div>
          {rows.length > shown && <div className="p-2 text-center"><Button size="sm" variant="ghost" onClick={() => setShown(shown + 200)}>Show more ({rows.length - shown})</Button></div>}
        </Card>
      )}
      {d && <p className="mt-3 text-2xs text-faint">{d.note}</p>}
    </div>
  )
}
