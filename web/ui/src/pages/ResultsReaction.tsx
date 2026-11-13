// Results reaction `/results-reaction`: how stocks moved in the weeks after their quarterly results, by the market's
// first reaction (tested since 2018, survivorship-free), and the stocks that just reported (results_svc.py).

import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Download, FlaskConical } from 'lucide-react'
import { fetchJson } from '@/api/client'
import { PageHeader } from '@/components/domain'
import { Banner, EmptyState, ErrorState, SkeletonRows } from '@/components/feedback'
import { Button, Card } from '@/components/ui'
import { downloadCsv } from '@/lib/exporting'
import { date as fmtDate, pct } from '@/lib/format'
import { useLocalStorage } from '@/lib/useLocalStorage'
import { cn } from '@/lib/csv'

interface H { n: number; months?: number; excess_pct?: number; median_pct?: number; hit_pct?: number; t?: number | null; after_cost_pct?: number }
interface Bucket { bucket: string; side: number; events: number; reaction_avg: number | null; horizons: Record<string, H>; verdict: string }
interface Study { generated_at: string; events: number; first_day: string; last_day: string; buckets: Bucket[] }
interface Recent { symbol: string; company: string | null; date: string; reaction: number; bucket: string; since_pct: number | null; days_since: number }
interface Resp { study: Study | null; job: { running: boolean; error: string | null }; recent: Recent[]; note: string }

const VERDICT: Record<string, { label: string; cls: string }> = {
  drift_edge: { label: 'Keeps going: tested edge', cls: 'text-profit' }, drift_before_costs: { label: 'Keeps going, not after costs', cls: 'text-warn' },
  reversal: { label: 'Gives back', cls: 'text-warn' }, no_edge: { label: 'No edge', cls: 'text-muted' }, no_direction: { label: 'No direction', cls: 'text-muted' },
  too_few: { label: 'Too few events', cls: 'text-muted' },
}

export default function ResultsReaction() {
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['results-study'], queryFn: () => fetchJson<Resp>('/api/results-study'), refetchInterval: (x) => (x.state.data?.job.running ? 5000 : false), staleTime: 5 * 60_000 })
  const run = useMutation({ mutationFn: () => fetchJson<Resp>('/api/results-study/run', { method: 'POST', body: '{}' }), onSuccess: (d) => qc.setQueryData(['results-study'], d) })
  const [only, setOnly] = useLocalStorage<string>('qd.results.bucket', '')
  const d = q.data
  const s = d?.study
  const byBucket = Object.fromEntries((s?.buckets ?? []).map((b) => [b.bucket, b]))
  const recent = (d?.recent ?? []).filter((r) => !only || r.bucket === only)
  return (
    <div>
      <PageHeader title="Results reaction" subtitle={s ? `${s.events.toLocaleString('en-IN')} results events, ${fmtDate(s.first_day)} – ${fmtDate(s.last_day)}, survivorship-free` : 'What stocks did after their quarterly results'}
        right={<Button size="sm" variant="subtle" icon={<FlaskConical className="h-4 w-4" />} loading={d?.job.running || run.isPending} onClick={() => run.mutate()}>{s ? 'Re-run the study' : 'Run the study'}</Button>} />
      {d?.job.error && <div className="mb-3"><Banner tone="danger">{d.job.error}</Banner></div>}
      {q.error ? <ErrorState error={q.error} onRetry={() => q.refetch()} /> : !d ? <Card><SkeletonRows rows={6} cols={6} /></Card> : (
        <>
          {!s ? <EmptyState icon={<FlaskConical />} title="Not tested yet" action={<Button variant="primary" onClick={() => run.mutate()}>Run the study (about a minute)</Button>}>Every results day since 2018, bucketed by the first reaction, then the next 5, 20 and 60 trading days.</EmptyState> : (
            <Card flush title="After the results: the tested record" subtitle="Excess return against the average stock after the day-after close; t on monthly averages; after a 0.45% round trip, traded in the reaction's direction">
              <div className="overflow-x-auto"><table className="w-full text-[13px]">
                <thead className="text-2xs text-muted"><tr className="text-left"><th className="px-4 py-1.5">First reaction</th><th className="px-2 text-right">Events</th><th className="px-2 text-right">Next 5 days</th><th className="px-2 text-right">Next 20 days</th><th className="px-2 text-right">Next 60 days</th><th className="px-2 text-right">20d after costs</th><th className="px-2 text-right">t (20d)</th><th className="px-4">Verdict</th></tr></thead>
                <tbody className="divide-y divide-line">{s.buckets.map((b) => {
                  const v = VERDICT[b.verdict] ?? VERDICT.no_edge
                  const h = b.horizons
                  return (
                    <tr key={b.bucket}>
                      <td className="px-4 py-1.5 font-medium">{b.bucket}</td><td className="num px-2 text-right">{b.events.toLocaleString('en-IN')}</td>
                      {['5', '20', '60'].map((k) => <td key={k} className={cn('num px-2 text-right', (h[k]?.excess_pct ?? 0) >= 0 ? 'text-profit' : 'text-loss')}>{pct(h[k]?.excess_pct, { dp: 2 })}</td>)}
                      <td className="num px-2 text-right">{b.bucket === 'Within 2%' ? '—' : pct(h['20']?.after_cost_pct, { dp: 2 })}</td>
                      <td className="num px-2 text-right">{h['20']?.t != null ? h['20'].t.toFixed(1) : '—'}</td>
                      <td className={cn('px-4', v.cls)}>{v.label}{b.side < 0 && b.verdict === 'drift_edge' ? ' (short: F&O only)' : ''}</td>
                    </tr>)
                })}</tbody>
              </table></div>
            </Card>
          )}
          <Card flush className="mt-3" title="Who just reported (last 30 days)" subtitle="The first reaction, the move since, and what that bucket did historically"
            right={<span className="flex items-center gap-2">
              <select aria-label="Reaction bucket" className="input h-8 px-2 text-[13px]" value={only} onChange={(e) => setOnly(e.target.value)}>
                <option value="">All reactions</option>{(s?.buckets ?? []).map((b) => <option key={b.bucket}>{b.bucket}</option>)}</select>
              <Button size="sm" variant="ghost" icon={<Download className="h-3.5 w-3.5" />} disabled={!recent.length} onClick={() => downloadCsv('results-reaction.csv', recent.map((r) => ({ ...r })))}>CSV</Button>
            </span>}>
            {recent.length === 0 ? <p className="px-4 py-3 text-xs text-muted">No results in this window.</p> : (
              <div className="max-h-[560px] overflow-auto"><table className="w-full text-[13px]">
                <thead className="sticky top-0 bg-panel text-2xs text-muted"><tr className="text-left"><th className="px-4 py-1.5">Results</th><th className="px-2">Stock</th><th className="px-2 text-right">Reaction</th><th className="px-2 text-right">Since</th><th className="px-4">History for this bucket (20 days)</th></tr></thead>
                <tbody className="divide-y divide-line">{recent.map((r) => {
                  const b = byBucket[r.bucket]
                  const h = b?.horizons['20']
                  return (
                    <tr key={`${r.symbol}${r.date}`}>
                      <td className="num px-4 py-1.5 text-muted">{fmtDate(r.date, { year: false })}</td>
                      <td className="px-2"><Link to={`/chart/${r.symbol}`} className="font-semibold hover:text-accent">{r.symbol}</Link> <span className="text-2xs text-muted">{r.company}</span></td>
                      <td className={cn('num px-2 text-right', r.reaction >= 0 ? 'text-profit' : 'text-loss')}>{pct(r.reaction)}</td>
                      <td className={cn('num px-2 text-right', (r.since_pct ?? 0) >= 0 ? 'text-profit' : 'text-loss')}>{pct(r.since_pct)} <span className="text-2xs text-muted">{r.days_since}d</span></td>
                      <td className="px-4 text-2xs">{b && h ? <span className={(VERDICT[b.verdict] ?? VERDICT.no_edge).cls}>{pct(h.excess_pct, { dp: 2 })} vs the average stock · {(VERDICT[b.verdict] ?? VERDICT.no_edge).label.toLowerCase()}</span> : '—'}</td>
                    </tr>)
                })}</tbody>
              </table></div>)}
          </Card>
          <p className="mt-3 text-2xs text-faint">{d.note}</p>
        </>
      )}
    </div>
  )
}
