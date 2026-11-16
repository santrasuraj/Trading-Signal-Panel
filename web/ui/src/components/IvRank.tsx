// IV rank / IV percentile (GET /api/iv-rank, /api/iv-rank/{symbol}; web/api/services/ivrank_svc.py): every F&O
// underlying's ~30-day at-the-money implied volatility against its own past year, from NSE's daily F&O file - the
// table on the Volatility page and the tile on a Company page.

import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { fetchJson } from '@/api/client'
import { DataTable, type Col } from '@/components/DataTable'
import { KpiTile } from '@/components/domain'
import { EmptyState, ErrorState, SkeletonRows } from '@/components/feedback'
import { Button, Card } from '@/components/ui'
import { cn } from '@/lib/csv'

export interface IvRow { symbol: string; iv: number; low: number; high: number; days: number; rank: number | null; percentile: number | null; median: number; change_5d: number | null; expiry: string; dte: number; spot: number; date: string }
interface IvJob { running: boolean; done: number; total: number; days_stored: number; error: string | null }
interface IvTable { rows: IvRow[]; days: number; date: string | null; job: IvJob; note: string }
interface IvOne { symbol: string; iv?: number; rank?: number | null; percentile?: number | null; low?: number; high?: number; days?: number; date?: string; dte?: number; history: { date: string; iv: number }[] }

const tone = (p: number | null | undefined) => (p == null ? '' : p >= 80 ? 'text-loss' : p <= 20 ? 'text-profit' : '')
const ivWord = (p: number | null | undefined) => (p == null ? '' : p >= 80 ? 'expensive vs its year' : p <= 20 ? 'cheap vs its year' : 'normal for its year')

const COLS: Col<IvRow>[] = [
  { id: 'sym', header: 'Underlying', value: (r) => r.symbol, sticky: true, mobile: 'primary', cell: (r) => <Link to={`/options/${r.symbol}`} className="font-semibold hover:underline">{r.symbol}</Link> },
  { id: 'iv', header: 'IV', align: 'right', value: (r) => r.iv, cell: (r) => <span className="num">{r.iv.toFixed(1)}%</span> },
  { id: 'rank', header: 'IV rank', title: '0 = the year\'s lowest IV, 100 = its highest', align: 'right', value: (r) => r.rank, mobile: 'value', cell: (r) => <span className={cn('num font-semibold', tone(r.rank))}>{r.rank == null ? '—' : r.rank.toFixed(0)}</span> },
  { id: 'pct', header: 'IV percentile', title: 'Share of the year\'s days with a lower IV', align: 'right', value: (r) => r.percentile, cell: (r) => <span className={cn('num', tone(r.percentile))}>{r.percentile == null ? '—' : `${r.percentile.toFixed(0)}%`}</span> },
  { id: 'rng', header: '1-year range', align: 'right', value: (r) => r.high - r.low, cell: (r) => <span className="num text-muted">{r.low.toFixed(1)}–{r.high.toFixed(1)}%</span> },
  { id: 'chg', header: '5-day change', align: 'right', value: (r) => r.change_5d, cell: (r) => <span className={cn('num', (r.change_5d ?? 0) > 0 ? 'text-loss' : 'text-profit')}>{r.change_5d == null ? '—' : `${r.change_5d > 0 ? '+' : ''}${r.change_5d.toFixed(1)}`}</span> },
  { id: 'exp', header: 'Expiry', value: (r) => r.expiry, cell: (r) => <span className="num text-xs text-muted">{r.expiry} ({r.dte}d)</span> },
]

export function IvRankTable() {
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['iv-rank'], queryFn: () => fetchJson<IvTable>('/api/iv-rank'), staleTime: 10 * 60_000, refetchInterval: (x) => (x.state.data?.job.running ? 5000 : false) })
  const fill = useMutation({ mutationFn: () => fetchJson<IvJob>('/api/iv-rank/backfill', { method: 'POST', body: '{}' }), onSuccess: () => { void qc.invalidateQueries({ queryKey: ['iv-rank'] }) } })
  const d = q.data
  const job = d?.job
  return (
    <Card flush title="IV rank of every F&O underlying" subtitle={d ? `${d.note}${d.date ? ` Latest day ${d.date}, ${d.days} days stored.` : ''}` : 'Implied volatility against its own past year'}
      right={job && (job.running ? <span className="text-xs text-muted">Fetching history: {job.done} of {job.total} days</span>
        : d && d.days < 250 ? <Button size="sm" variant="subtle" loading={fill.isPending} onClick={() => fill.mutate()}>Fetch a year of history (~5 min)</Button> : undefined)}>
      {q.error ? <ErrorState compact error={q.error} /> : !d ? <SkeletonRows rows={8} /> : d.rows.length === 0
        ? <EmptyState compact title="No IV history yet">It fills from the nightly F&O download, or fetch a year now.</EmptyState>
        : <DataTable id="volatility.ivrank" data={d.rows} columns={COLS} rowKey={(r) => r.symbol} exportName="iv-rank" maxHeight={520} />}
    </Card>
  )
}

/** The Company page's tile: shown only for F&O stocks with IV history. */
export function IvRankTile({ symbol }: { symbol: string }) {
  const q = useQuery({ queryKey: ['iv-rank', symbol], queryFn: () => fetchJson<IvOne>(`/api/iv-rank/${encodeURIComponent(symbol)}`), staleTime: 10 * 60_000, retry: false })
  const d = q.data
  if (!d || d.iv == null) return null
  return <KpiTile label="Option IV rank" value={<span className={tone(d.rank)}>{d.rank == null ? '—' : d.rank.toFixed(0)}</span>}
    sub={`IV ${d.iv.toFixed(1)}% · ${ivWord(d.percentile)}`} title={`At-the-money implied volatility ${d.iv}% (${d.dte} days to expiry); percentile ${d.percentile ?? '—'}% over ${d.days} days`} />
}
