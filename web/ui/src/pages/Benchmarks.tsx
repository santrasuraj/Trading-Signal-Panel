// Benchmarks `/benchmarks`: the app checked against itself and the competitors - does following "working" strategies
// pay (walk-forward), and how fast and deep it is, measured now on this PC next to what the competitors publish.

import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { fetchJson } from '@/api/client'
import { quoteStream } from '@/api/liveQuotes'
import { LinesChart, type LineDef } from '@/components/charts/LinesChart'
import { PageHeader } from '@/components/domain'
import { ErrorState, Skeleton, SkeletonChart } from '@/components/feedback'
import { Pct } from '@/components/num'
import { Button, Card } from '@/components/ui'
import { cn } from '@/lib/csv'
import { date, num } from '@/lib/format'

interface WalkForward {
  from: string; to: string; months: number; cagr_pct: Record<'follow' | 'all' | 'ew' | 'nifty', number | null>
  beat_all_pct: number | null; t_vs_all: number | null; avg_working: number | null; cash_months: number
  curve: { t: string[]; follow: number[]; all: number[]; ew: number[]; nifty: number[] }
  recent_picks: { month: string; working: string[] }[]; verdict: 'pays' | 'hurts' | 'no_difference'; note: string
}
interface Bench {
  measured_at: string; rows: { key: string; label: string; value: number | null; unit: string; competitor: string }[]
  coverage: Record<string, number | string | null>; client_note: string; note: string
}

const pctFmt = (v: number) => `${((v - 1) * 100).toFixed(0)}%`

function pctile(xs: number[], p: number): number | null {
  if (!xs.length) return null
  const s = [...xs].sort((a, b) => a - b)
  return s[Math.min(s.length - 1, Math.floor((p / 100) * s.length))]
}

function WalkForwardCard() {
  const q = useQuery({ queryKey: ['research', 'walk-forward'], queryFn: () => fetchJson<WalkForward>('/api/research/walk-forward'), staleTime: Infinity })
  const d = q.data
  if (q.error) return <Card title="Walk-forward"><ErrorState error={q.error} compact /></Card>
  if (!d) return <Card title="Walk-forward"><SkeletonChart height={260} /></Card>
  const lines: LineDef[] = [
    { id: 'follow', label: 'Follow "working"', v: d.curve.follow, color: 'accent', width: 2, format: pctFmt },
    { id: 'all', label: 'Every strategy', v: d.curve.all, color: 'muted', format: pctFmt },
    { id: 'ew', label: 'Average stock', v: d.curve.ew, color: 'warn', style: 'dashed', format: pctFmt },
    { id: 'nifty', label: 'Nifty 50', v: d.curve.nifty, color: 'violet', style: 'dashed', format: pctFmt },
  ]
  const tone = d.verdict === 'pays' ? 'bg-profit text-white' : d.verdict === 'hurts' ? 'bg-loss text-white' : 'border border-line-strong bg-raised text-fg'
  return (
    <Card title={'Walk-forward: does following the "working" strategies pay?'} subtitle={`${date(d.from)} to ${date(d.to)} · ${d.months} months, each decided with only the data up to then`}>
      <div className="flex flex-wrap items-center gap-3">
        <span className={cn('rounded-md px-2.5 py-1 text-sm font-bold', tone)}>{d.verdict === 'pays' ? 'IT PAYS' : d.verdict === 'hurts' ? 'IT HURTS' : 'NO CLEAR DIFFERENCE'}</span>
        <span className="text-[13px]">Follow "working" <Pct v={d.cagr_pct.follow} dp={1} />/yr · every strategy <Pct v={d.cagr_pct.all} dp={1} /> · average stock <Pct v={d.cagr_pct.ew} dp={1} /> · Nifty 50 <Pct v={d.cagr_pct.nifty} dp={1} /></span>
        <span className="text-xs text-muted">beat "every strategy" in {num(d.beat_all_pct, 0)}% of months, t {num(d.t_vs_all, 1)} · {num(d.avg_working, 1)} strategies working on average · {d.cash_months} months in cash</span>
      </div>
      <div className="mt-3"><LinesChart t={d.curve.t} lines={lines} height={260} /></div>
      <p className="mt-2 text-2xs text-faint">{d.note}</p>
    </Card>
  )
}

function LatencyRow() {
  const [, tick] = useState(0)
  useEffect(() => { const t = setInterval(() => tick((n) => n + 1), 2000); return () => clearInterval(t) }, [])
  const xs = quoteStream.latencySamples()
  return (
    <tr className="border-b border-line/60">
      <td className="py-2 pr-3">FYERS tick to this screen (measured in your browser)</td>
      <td className="num py-2 pr-3 text-right">{xs.length ? <>p50 {num(pctile(xs, 50), 2)} s · p95 {num(pctile(xs, 95), 2)} s <span className="text-faint">({xs.length})</span></> : <span className="text-faint">needs the FYERS live feed</span>}</td>
      <td className="py-2 text-xs text-muted">Target p95 under 1 s. None of the four publish this.</td>
    </tr>
  )
}

export default function Benchmarks() {
  const q = useQuery({ queryKey: ['research', 'benchmarks'], queryFn: () => fetchJson<Bench>('/api/research/benchmarks'), staleTime: 60_000 })
  const d = q.data
  return (
    <div>
      <PageHeader title="Benchmarks" subtitle="The app checked against itself and against what Trade Ideas, TrendSpider, NinjaTrader and MetaTrader publish." />
      <div className="space-y-3">
        <WalkForwardCard />
        <Card title="Speed and depth, measured now" subtitle={d ? `On this PC, ${d.measured_at.replace('T', ' ')}` : 'Measuring…'}
          right={<Button size="sm" loading={q.isFetching} onClick={() => void q.refetch()}>Measure again</Button>}>
          {q.error && !d ? <ErrorState error={q.error} compact /> : !d ? <Skeleton className="h-40 w-full" /> : (
            <>
              <div className="scroll-x">
                <table className="w-full text-[13px]">
                  <thead className="text-2xs uppercase tracking-[0.04em] text-faint">
                    <tr className="border-b border-line"><th className="py-1.5 pr-3 text-left font-semibold">What</th><th className="py-1.5 pr-3 text-right font-semibold">Quant Desk</th><th className="py-1.5 text-left font-semibold">Competitors publish</th></tr>
                  </thead>
                  <tbody>
                    {d.rows.map((r) => (
                      <tr key={r.key} className="border-b border-line/60">
                        <td className="py-2 pr-3">{r.label}</td>
                        <td className="num py-2 pr-3 text-right font-medium">{r.value == null ? <span className="font-normal text-faint">not measured yet</span> : `${num(r.value, r.value < 10 ? 2 : 0)} ${r.unit}`}</td>
                        <td className="py-2 text-xs text-muted">{r.competitor}</td>
                      </tr>
                    ))}
                    <LatencyRow />
                  </tbody>
                </table>
              </div>
              <div className="mt-3 flex flex-wrap gap-x-5 gap-y-1 text-xs text-muted">
                <span>Universe today: <span className="num text-fg">{d.coverage.universe}</span> stocks</span>
                <span>Strategies re-tested every scan: <span className="num text-fg">{d.coverage.strategies}</span></span>
                {d.coverage.pit_companies != null && <span>Survivorship-free history: <span className="num text-fg">{d.coverage.pit_companies}</span> companies, <span className="num text-fg">{d.coverage.pit_no_longer_trading}</span> no longer trading</span>}
              </div>
              <p className="mt-2 text-2xs text-faint">{d.note} {d.client_note}</p>
            </>
          )}
        </Card>
      </div>
    </div>
  )
}
