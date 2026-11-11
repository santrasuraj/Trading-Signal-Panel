// Late entry (scanner/late_entry.py): does the strategy's edge survive joining its trades 5, 10 or 21 trading days
// after its own buy? A model-held stock shows BUY (late entry) on the Action card only where this says edge.

import { useQuery } from '@tanstack/react-query'
import { fetchJson } from '@/api/client'
import type { HorizonStats, StudyVerdict } from '@/api/scans'
import { VERDICT_TEXT } from '@/api/scans'
import { ErrorState, Skeleton } from '@/components/feedback'
import { Pct } from '@/components/num'
import { Card } from '@/components/ui'
import { cn } from '@/lib/csv'
import { num } from '@/lib/format'

interface LateEntry { key: string; lags: number[]; trades: number; results: Record<string, HorizonStats & { verdict: StudyVerdict; return_pct: number | null }>; note: string }

export function LateEntryCard({ k }: { k: string }) {
  const q = useQuery({ queryKey: ['late-entry', k], queryFn: () => fetchJson<LateEntry>(`/api/strategies/${k}/late-entry`), staleTime: Infinity, retry: false })
  if (q.error) return <Card title="Late entry"><ErrorState error={q.error} compact /></Card>
  if (!q.data) return <Card title="Late entry"><Skeleton className="h-24 w-full" /><p className="mt-2 text-2xs text-faint">Testing every trade of the backtest: a few seconds the first time.</p></Card>
  const d = q.data
  return (
    <Card title="Late entry: can you still join?" subtitle={`${d.trades.toLocaleString('en-IN')} backtest trades, each joined later than the model did`}>
      <table className="w-full text-[13px]">
        <thead className="text-2xs uppercase tracking-[0.04em] text-faint">
          <tr className="border-b border-line"><th className="py-1.5 text-left font-semibold">Join</th><th className="py-1.5 text-right font-semibold">Trades</th><th className="py-1.5 text-right font-semibold">Return</th><th className="py-1.5 text-right font-semibold">vs avg stock</th><th className="py-1.5 text-right font-semibold">After costs</th><th className="py-1.5 text-right font-semibold">t</th><th className="py-1.5 text-right font-semibold">Verdict</th></tr>
        </thead>
        <tbody>
          {d.lags.map((lag) => {
            const r = d.results[String(lag)]
            if (!r) return <tr key={lag} className="border-b border-line/60 text-muted"><td className="py-1.5">{lag === 0 ? 'With the model' : `${lag} days late`}</td><td colSpan={6} className="py-1.5 text-right">no trade lasted that long</td></tr>
            const v = VERDICT_TEXT[r.verdict]
            return (
              <tr key={lag} className="border-b border-line/60">
                <td className="py-1.5">{lag === 0 ? 'With the model' : `${lag} days late`}</td>
                <td className="num py-1.5 text-right">{r.n.toLocaleString('en-IN')}</td>
                <td className="py-1.5 text-right"><Pct v={r.return_pct} dp={2} /></td>
                <td className="py-1.5 text-right"><Pct v={r.excess_pct} dp={2} /></td>
                <td className="py-1.5 text-right"><Pct v={r.after_cost_pct} dp={2} /></td>
                <td className="num py-1.5 text-right">{num(r.t, 1)}</td>
                <td className={cn('py-1.5 text-right text-xs font-medium', v.tone === 'good' ? 'text-profit' : v.tone === 'bad' ? 'text-loss' : 'text-muted')}>{v.label}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
      <p className="mt-2 text-2xs text-faint">{d.note} Where it says "Edge after costs" (and the strategy is working), a stock the model holds shows as BUY (late entry) on its chart and on Today.</p>
    </Card>
  )
}
