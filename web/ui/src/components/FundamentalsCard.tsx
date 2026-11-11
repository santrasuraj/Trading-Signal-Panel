// Company numbers (chart side panel): quarterly revenue and profit from NSE's filings, growth against a year ago,
// margin, EPS over the last four quarters and P/E (web/api/services/fund_svc.py). Also starts the universe-wide
// fetch that feeds the scan fields.

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Building2 } from 'lucide-react'
import { fetchJson } from '@/api/client'
import { Button, Card } from '@/components/ui'
import { cn } from '@/lib/csv'

interface Q { qe: string; filed: string; revenue_cr: number | null; profit_cr: number | null; eps: number | null; sales_growth: number | null; profit_growth: number | null; net_margin: number | null }
interface Fund { symbol: string; price: number | null; basis?: string; latest: (Omit<Q, 'eps'> & { eps_ttm: number | null; pe: number | null }) | null; quarters: Q[]; note: string }
interface FStatus { companies: number; universe: number; job: { running: boolean; done: number; total: number } }

const cr = (v: number | null) => (v == null ? '—' : `₹${Math.round(v).toLocaleString('en-IN')} cr`)
const g = (v: number | null) => (v == null ? '—' : `${v >= 0 ? '+' : ''}${v.toFixed(1)}%`)
const qName = (qe: string) => { const d = new Date(`${qe}T00:00:00Z`); return `${d.toLocaleString('en-IN', { month: 'short', timeZone: 'UTC' })} ${String(d.getUTCFullYear()).slice(2)}` }

export function FundamentalsCard({ symbol }: { symbol: string }) {
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['fundamentals', symbol], queryFn: () => fetchJson<Fund>(`/api/fundamentals/${encodeURIComponent(symbol)}`), staleTime: 60 * 60_000, retry: false })
  const st = useQuery({ queryKey: ['fundamentals-status'], queryFn: () => fetchJson<FStatus>('/api/fundamentals-status'), refetchInterval: (x) => (x.state.data?.job.running ? 5000 : false) })
  const all = useMutation({ mutationFn: () => fetchJson<FStatus>('/api/fundamentals/refresh', { method: 'POST', body: '{}' }), onSuccess: () => { void qc.invalidateQueries({ queryKey: ['fundamentals-status'] }) } })
  const d = q.data?.symbol === symbol ? q.data : undefined
  const l = d?.latest
  const qs = d?.quarters ?? []
  const max = Math.max(1, ...qs.map((x) => Math.abs(x.revenue_cr ?? 0)))
  const s = st.data
  return (
    <Card title={<span className="flex items-center gap-1.5"><Building2 className="h-4 w-4 text-muted" />Company numbers</span>}
      subtitle={l ? `Quarter to ${qName(l.qe)} · ${d?.basis}` : 'From NSE\'s quarterly filings'}>
      {!d ? <p className="text-xs text-muted">{q.error ? 'NSE did not answer.' : 'Loading the filings…'}</p> : !l ? (
        <p className="text-xs text-muted">No quarterly filings found for {symbol} (an ETF or index has none).</p>
      ) : (
        <>
          <div className="grid grid-cols-3 gap-2 text-center">
            <div><div className="text-2xs text-muted">Revenue</div><div className="num text-sm font-semibold">{cr(l.revenue_cr)}</div><div className={cn('num text-2xs', (l.sales_growth ?? 0) >= 0 ? 'text-profit' : 'text-loss')}>{g(l.sales_growth)} y/y</div></div>
            <div><div className="text-2xs text-muted">Profit</div><div className="num text-sm font-semibold">{cr(l.profit_cr)}</div><div className={cn('num text-2xs', (l.profit_growth ?? 0) >= 0 ? 'text-profit' : 'text-loss')}>{g(l.profit_growth)} y/y</div></div>
            <div><div className="text-2xs text-muted">P/E</div><div className="num text-sm font-semibold">{l.pe != null ? l.pe.toFixed(1) : '—'}</div><div className="num text-2xs text-muted">EPS {l.eps_ttm ?? '—'} · margin {l.net_margin != null ? `${l.net_margin.toFixed(0)}%` : '—'}</div></div>
          </div>
          <div className="mt-3 space-y-1">
            {qs.slice(-6).map((x) => (
              <div key={x.qe} className="flex items-center gap-2 text-2xs" title={`Filed ${x.filed}`}>
                <span className="w-12 text-muted">{qName(x.qe)}</span>
                <div className="h-2 flex-1 overflow-hidden rounded bg-raised"><div className="h-full bg-accent/60" style={{ width: `${(Math.abs(x.revenue_cr ?? 0) / max) * 100}%` }} /></div>
                <span className="num w-20 text-right">{cr(x.profit_cr)}</span>
              </div>))}
            <div className="text-right text-2xs text-faint">bar: revenue · right: profit</div>
          </div>
        </>
      )}
      {s && s.companies < s.universe && (
        <div className="mt-3 flex items-center justify-between gap-2 border-t border-line pt-2 text-2xs text-muted">
          <span>{s.job.running ? `Fetching every company: ${s.job.done} of ${s.job.total}` : `${s.companies} of ${s.universe} companies stored: scans on P/E and growth need them all`}</span>
          {!s.job.running && <Button size="xs" variant="subtle" loading={all.isPending} onClick={() => all.mutate()}>Fetch all</Button>}
        </div>)}
    </Card>
  )
}
