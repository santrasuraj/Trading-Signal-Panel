// Smart money > Investors (GET /api/investors, /api/investors/{key}; web/api/services/investors_svc.py): each big
// investor's holdings across companies and what they added, cut or left since the previous quarter - from the
// quarterly shareholding filings, which name every public holder with 1% or more of a company.

import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { fetchJson } from '@/api/client'
import { DataTable, type Col } from '@/components/DataTable'
import { EmptyState, ErrorState, SkeletonRows } from '@/components/feedback'
import { Card, Segmented } from '@/components/ui'
import { cn } from '@/lib/csv'

type Cat = 'famous' | 'mf' | 'fii' | 'insurance' | 'pension' | 'all'
interface InvRow { key: string; investor: string; category: string; label: string; stocks: number; value_cr: number | null; new: number; added: number; cut: number; left: number; top: string[] }
interface InvList { rows: InvRow[]; periods: string[]; note: string }
type Change = 'new' | 'added' | 'cut' | 'left' | 'same' | 'held'
interface Holding { symbol: string; company: string | null; period: string; prev_period: string | null; pct: number | null; prev_pct: number | null; change: Change; shares: number | null; price: number | null; value_cr: number | null; accounts: string[] }
interface InvDetail { key: string; investor: string; label: string; rows: Holding[]; value_cr: number; note: string }

const CATS: { id: Cat; label: string }[] = [
  { id: 'famous', label: 'Well-known' }, { id: 'mf', label: 'Mutual funds' }, { id: 'fii', label: 'FII/FPI' },
  { id: 'insurance', label: 'Insurance' }, { id: 'pension', label: 'Pension' }, { id: 'all', label: 'All' },
]
const crs = (v: number | null) => (v == null ? '—' : `₹${Math.round(v).toLocaleString('en-IN')} cr`)
const CHANGE: Record<Change, [string, string]> = {
  new: ['New', 'text-profit'], added: ['Added', 'text-profit'], cut: ['Cut', 'text-loss'], left: ['Left / under 1%', 'text-loss'],
  same: ['Same', 'text-muted'], held: ['Held', 'text-muted'],
}

const LIST_COLS: Col<InvRow>[] = [
  { id: 'inv', header: 'Investor', value: (r) => r.investor, sticky: true, mobile: 'primary', cell: (r) => <span className="font-semibold">{r.investor}</span>, minWidth: 220 },
  { id: 'type', header: 'Type', value: (r) => r.label, cell: (r) => <span className="text-xs text-muted">{r.label}</span> },
  { id: 'n', header: 'Stocks', align: 'right', value: (r) => r.stocks, cell: (r) => <span className="num">{r.stocks}</span> },
  { id: 'v', header: 'Value', align: 'right', value: (r) => r.value_cr, mobile: 'value', cell: (r) => <span className="num">{crs(r.value_cr)}</span> },
  { id: 'chg', header: 'Last quarter', title: 'New / added / cut / left since the previous quarter', value: (r) => r.new + r.added - r.cut - r.left,
    cell: (r) => <span className="num text-xs"><span className="text-profit">+{r.new} new · {r.added} added</span> <span className="text-loss">· {r.cut} cut · {r.left} left</span></span> },
  { id: 'top', header: 'Largest holdings', value: (r) => r.top.join(' '), cell: (r) => <span className="text-xs text-muted">{r.top.join(', ')}</span> },
]

const HOLD_COLS: Col<Holding>[] = [
  { id: 'sym', header: 'Stock', value: (r) => r.symbol, sticky: true, mobile: 'primary', cell: (r) => <Link to={`/company/${r.symbol}`} className="font-semibold hover:underline" title={r.company ?? undefined}>{r.symbol}</Link> },
  { id: 'pct', header: 'Holding', align: 'right', value: (r) => r.pct, cell: (r) => <span className="num">{r.pct == null ? '—' : `${r.pct.toFixed(2)}%`}</span> },
  { id: 'prev', header: 'Quarter before', align: 'right', value: (r) => r.prev_pct, cell: (r) => <span className="num text-muted">{r.prev_pct == null ? '—' : `${r.prev_pct.toFixed(2)}%`}</span> },
  { id: 'chg', header: 'Change', value: (r) => r.change, mobile: 'secondary', cell: (r) => <span className={cn('text-xs font-medium', CHANGE[r.change][1])}>{CHANGE[r.change][0]}</span> },
  { id: 'v', header: 'Value', align: 'right', value: (r) => r.value_cr, mobile: 'value', cell: (r) => <span className="num">{crs(r.value_cr)}</span> },
  { id: 'q', header: 'Quarter', value: (r) => r.period, cell: (r) => <span className="num text-xs text-muted">{r.period}</span> },
  { id: 'acc', header: 'Filed as', value: (r) => r.accounts.join('; '), cell: (r) => <span className="block max-w-[260px] truncate text-xs text-muted" title={r.accounts.join('\n')}>{r.accounts.length > 1 ? `${r.accounts.length} accounts` : r.accounts[0]}</span> },
]

export function InvestorPortfolios() {
  const [cat, setCat] = useState<Cat>('famous')
  const [q, setQ] = useState('')
  const [sel, setSel] = useState<string | null>(null)
  const list = useQuery({ queryKey: ['investors', cat, q], queryFn: () => fetchJson<InvList>(`/api/investors?category=${cat}&q=${encodeURIComponent(q)}`), staleTime: 10 * 60_000 })
  const det = useQuery({ queryKey: ['investor', sel], queryFn: () => fetchJson<InvDetail>(`/api/investors/${encodeURIComponent(sel!)}`), enabled: !!sel, staleTime: 10 * 60_000 })
  const d = list.data
  return (
    <div className="space-y-3">
      <Card title="Investor portfolios" subtitle={d ? `${d.note}${d.periods.length ? ` Latest quarter: ${d.periods[0]}.` : ''}` : 'Each big investor\'s holdings across companies'}
        right={<>
          <input className="input h-8 w-44" placeholder="Search a name" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search investors" />
          <Segmented<Cat> ariaLabel="Investor type" value={cat} onChange={(c) => { setCat(c); setSel(null) }} items={CATS} />
        </>} flush>
        {list.error ? <ErrorState compact error={list.error} /> : !d ? <SkeletonRows rows={8} /> : d.rows.length === 0 ? <EmptyState compact title={d.note} />
          : <DataTable id={`investors.${cat}`} data={d.rows} columns={LIST_COLS} rowKey={(r) => r.key} onRowClick={(r) => setSel(r.key)}
              rowClassName={(r) => (r.key === sel ? 'bg-accent/10' : undefined)} exportName={`investors-${cat}`} maxHeight={420} />}
      </Card>
      {sel && (
        <Card title={det.data ? `${det.data.investor} · ${crs(det.data.value_cr)}` : 'Loading…'} subtitle={det.data?.note} flush>
          {det.error ? <ErrorState compact error={det.error} /> : !det.data ? <SkeletonRows rows={6} />
            : <DataTable id="investors.holdings" data={det.data.rows} columns={HOLD_COLS} rowKey={(r) => r.symbol} exportName={`holdings-${sel}`} />}
        </Card>)}
    </div>
  )
}
