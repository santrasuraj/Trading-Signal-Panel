// Volatility `/volatility`: how expensive options are now (India VIX rank / percentile, ATM IV per index), against
// how much the index actually moves (realised volatility), the expected moves the VIX prices, and the record of the
// VIX against the volatility that followed (vol_svc.py).

import { useQuery } from '@tanstack/react-query'
import { fetchJson } from '@/api/client'
import { KpiStrip, KpiTile, PageHeader } from '@/components/domain'
import { ErrorState, SkeletonKpis } from '@/components/feedback'
import { LinesChart } from '@/components/charts/LinesChart'
import { Card } from '@/components/ui'
import { date as fmtDate, num } from '@/lib/format'
import { cn } from '@/lib/csv'

interface Rec { days: number; gap_avg: number; below_pct: number; gap_worst: number; by_percentile: { bucket: string; days: number; vix_avg: number; then_avg: number; gap_avg: number; gap_worst: number; below_pct: number }[] }
interface Nifty { vix: number; vix_chg: number | null; rank: number | null; percentile: number | null; low_1y: number; high_1y: number; rv20: number | null; spot: number; moves: Record<'day' | 'week' | 'month', number>; series: { t: string; vix: number; rv: number | null }[]; record: Rec }
interface Atm { iv: number; rank: number | null; percentile: number | null; days: number; first: string; rv20: number | null; series: { t: string; iv: number; rv: number | null }[] }
interface Vol { as_of: string | null; nifty?: Nifty; atm_iv: Record<string, Atm>; note: string }

const level = (p: number | null | undefined) => (p == null ? '' : p >= 80 ? 'options are expensive against the last year' : p <= 20 ? 'options are cheap against the last year' : 'about normal for the last year')

export default function Volatility() {
  const q = useQuery({ queryKey: ['volatility'], queryFn: () => fetchJson<Vol>('/api/volatility'), staleTime: 10 * 60_000 })
  const d = q.data
  const n = d?.nifty
  return (
    <div>
      <PageHeader title="Volatility" subtitle={d?.as_of ? `India VIX and index option volatility · as of ${fmtDate(d.as_of)}` : 'How expensive options are, and how much the index really moves'} />
      {q.error ? <ErrorState error={q.error} onRetry={() => q.refetch()} /> : !d ? <SkeletonKpis n={6} /> : (
        <>
          {n && (
            <>
              <KpiStrip>
                <KpiTile label="India VIX" value={num(n.vix, 2)} sub={n.vix_chg != null ? `${n.vix_chg >= 0 ? '+' : ''}${n.vix_chg.toFixed(2)} today` : undefined} />
                <KpiTile label="VIX percentile (1 year)" value={n.percentile != null ? `${n.percentile.toFixed(0)}%` : '—'} sub={level(n.percentile)} tone={n.percentile != null && n.percentile >= 80 ? 'text-warn' : undefined} />
                <KpiTile label="VIX rank (1 year)" value={n.rank != null ? n.rank.toFixed(0) : '—'} sub={`range ${n.low_1y.toFixed(1)} – ${n.high_1y.toFixed(1)}`} />
                <KpiTile label="Nifty realised (20 days)" value={n.rv20 != null ? `${n.rv20.toFixed(1)}%` : '—'} sub={n.rv20 != null ? `VIX is ${(n.vix - n.rv20).toFixed(1)} pts ${n.vix >= n.rv20 ? 'above' : 'below'}` : undefined} />
                <KpiTile label="Expected move: 1 day" value={`±${num(n.moves.day, 0)}`} sub={`${((n.moves.day / n.spot) * 100).toFixed(2)}% of ${num(n.spot, 0)}`} />
                <KpiTile label="1 week / 1 month" value={<span className="text-base">±{num(n.moves.week, 0)} / ±{num(n.moves.month, 0)}</span>} sub="one standard deviation" />
              </KpiStrip>
              <div className="mt-3 grid gap-3 xl:grid-cols-3">
                <Card flush className="xl:col-span-2" title="India VIX against Nifty's realised volatility" subtitle="Two years: implied (what options charge) above realised (what happened) is the usual state">
                  <LinesChart t={n.series.map((x) => x.t)} height={300} lines={[
                    { id: 'vix', label: 'India VIX', v: n.series.map((x) => x.vix), color: 'warn', width: 2, format: (v) => v.toFixed(1) },
                    { id: 'rv', label: 'Realised 20d', v: n.series.map((x) => x.rv), color: 'accent', format: (v) => v.toFixed(1) },
                  ]} />
                </Card>
                <Card flush title="The record since 2018" subtitle="The VIX against the volatility of the next 21 trading days, by VIX percentile">
                  <table className="w-full text-[13px]">
                    <thead className="text-2xs text-muted"><tr className="text-left"><th className="px-4 py-1.5">VIX pctl</th><th className="px-2 text-right">VIX</th><th className="px-2 text-right">Then</th><th className="px-2 text-right">Lower</th><th className="px-4 text-right">Worst gap</th></tr></thead>
                    <tbody className="divide-y divide-line">{n.record.by_percentile?.map((b) => (
                      <tr key={b.bucket}><td className="px-4 py-1.5">{b.bucket}</td><td className="num px-2 text-right">{b.vix_avg}</td><td className="num px-2 text-right">{b.then_avg}</td>
                        <td className="num px-2 text-right">{b.below_pct.toFixed(0)}%</td><td className="num px-4 text-right text-loss">{b.gap_worst}</td></tr>))}</tbody>
                  </table>
                  <p className="px-4 py-2 text-2xs text-muted">Over {n.record.days} days the next month moved less than the VIX priced {n.record.below_pct}% of the time (on average {n.record.gap_avg} points less): what option sellers earn. The worst month moved {Math.abs(n.record.gap_worst)} points more: what they risk.</p>
                </Card>
              </div>
            </>
          )}
          <div className="mt-3 grid gap-3 xl:grid-cols-2">{Object.entries(d.atm_iv).map(([sym, a]) => (
            <Card flush key={sym} title={`${sym}: at-the-money implied volatility`} subtitle={`${a.days} days stored since ${fmtDate(a.first)} · now ${a.iv.toFixed(1)}% · percentile ${a.percentile?.toFixed(0) ?? '—'}% · realised ${a.rv20?.toFixed(1) ?? '—'}%`}>
              <LinesChart t={a.series.map((x) => x.t)} height={220} lines={[
                { id: 'iv', label: 'ATM IV', v: a.series.map((x) => x.iv), color: 'warn', width: 2, format: (v) => v.toFixed(1) },
                { id: 'rv', label: 'Realised 20d', v: a.series.map((x) => x.rv), color: 'accent', format: (v) => v.toFixed(1) },
              ]} />
              <p className={cn('px-4 py-2 text-2xs', a.days < 250 ? 'text-warn' : 'text-muted')}>{a.days < 250 ? 'Less than a year stored: the percentile covers only these days. Fetch 2 years on the Options backtest page.' : level(a.percentile)}</p>
            </Card>))}</div>
          <p className="mt-3 text-2xs text-faint">{d.note}</p>
        </>
      )}
    </div>
  )
}
