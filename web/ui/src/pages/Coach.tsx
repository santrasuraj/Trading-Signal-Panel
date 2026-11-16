// Coach `/coach`: what your own trading does well and where it leaks money. The numbers and checks come from your
// records only (practice replays, real FYERS fills, holdings now: web/api/services/coach_svc.py); the written review
// is Claude's reading of those numbers, on request (one call, a few rupees), kept until your numbers change.

import { AlertTriangle, CheckCircle2, Info, Sparkles, XCircle } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { fetchJson, isFailure } from '@/api/client'
import { KpiStrip, KpiTile, PageHeader } from '@/components/domain'
import { EmptyState, ErrorState, Skeleton } from '@/components/feedback'
import { Money } from '@/components/num'
import { Button, Card } from '@/components/ui'
import { holdingChecks, practiceChecks, type Check, type CoachFacts, type Group } from '@/lib/coach'
import { cn } from '@/lib/csv'
import { dateTimeIST, num } from '@/lib/format'

interface Review {
  key: string; at: string; model: string; sample: CoachFacts['sample']
  review: { headline: string; strengths: { title: string; evidence: string }[]; leaks: { title: string; evidence: string; cost: string; fix: string }[]
    rules: string[]; next_focus: string; sample_note: string }
}
interface CoachView { facts: CoachFacts; review: Review | null; stale: boolean; ai: { configured: boolean; model: string; note: string }; note: string }

const ICON = {
  good: <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-profit" />,
  warn: <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-warn" />,
  bad: <XCircle className="mt-0.5 h-4 w-4 shrink-0 text-loss" />,
  info: <Info className="mt-0.5 h-4 w-4 shrink-0 text-info" />,
}

function Checks({ items }: { items: Check[] }) {
  return (
    <ul className="space-y-2">
      {items.map((c) => (
        <li key={c.title} className="flex gap-2 text-[13px]">
          {ICON[c.tone]}
          <span><span className="font-medium text-fg">{c.title}.</span> <span className="text-muted">{c.detail}</span></span>
        </li>
      ))}
    </ul>
  )
}

function GroupRow({ label, g }: { label: string; g: Group }) {
  return (
    <tr className="border-t border-line">
      <td className="py-1.5">{label}</td>
      <td className="num text-right">{g.trades}</td>
      <td className="num text-right">{g.win_rate == null ? '—' : `${num(g.win_rate, 0)}%`}</td>
      <td className="text-right"><Money v={g.per_trade} signed color dp={0} /></td>
      <td className="text-right"><Money v={g.net} signed color dp={0} /></td>
    </tr>
  )
}

function Splits({ f }: { f: NonNullable<CoachFacts['practice']> }) {
  const TF: Record<string, string> = { '5m': '5-min replays', '15m': '15-min replays', '1d': 'Daily replays' }
  const rows: [string, Group][] = [
    ...Object.entries(f.by_bar_size).map(([k, g]) => [TF[k] ?? k, g] as [string, Group]),
    ...Object.entries(f.long_vs_short).map(([k, g]) => [k === 'LONG' ? 'Long trades' : 'Short trades', g] as [string, Group]),
    ...Object.entries(f.blind_vs_named).map(([k, g]) => [k === 'blind' ? 'Blind sessions' : 'Named sessions', g] as [string, Group]),
  ]
  return (
    <table className="mt-3 w-full text-[13px]">
      <thead className="text-left text-2xs text-muted"><tr><th className="py-1">Group</th><th className="text-right">Trades</th><th className="text-right">Won</th><th className="text-right">Per trade</th><th className="text-right">Net</th></tr></thead>
      <tbody>{rows.map(([l, g]) => <GroupRow key={l} label={l} g={g} />)}</tbody>
    </table>
  )
}

function ReviewCard({ v }: { v: CoachView }) {
  const qc = useQueryClient()
  const m = useMutation({ mutationFn: () => fetchJson<Review>('/api/coach/review', { method: 'POST', body: '{}' }), onSuccess: () => void qc.invalidateQueries({ queryKey: ['coach'] }) })
  const r = v.review
  const can = !!(v.facts.practice || v.facts.real_money || v.facts.holdings.count)
  const button = (
    <Button variant={r && !v.stale ? 'secondary' : 'primary'} size="sm" icon={<Sparkles className="h-3.5 w-3.5" />} loading={m.isPending} disabled={!v.ai.configured || !can}
      onClick={() => m.mutate()}>{r ? 'Write a new review' : 'Write my review'}</Button>
  )
  return (
    <Card title="Coach's review" subtitle={r ? `Written ${dateTimeIST(r.at)} by ${r.model}${v.stale ? ' · your numbers have changed since' : ''}` : 'Claude reads the numbers on this page (nothing else) and writes what to keep doing and what to fix. About ₹5-15 a review.'} right={button}>
      {!v.ai.configured && <p className="text-xs text-warn">The written review needs an Anthropic API key: {v.ai.note} The numbers and checks above work without it.</p>}
      {m.error && <p className="text-xs text-loss">{isFailure(m.error) ? `${m.error.message}${m.error.hint ? ` ${m.error.hint}` : ''}` : 'The review failed.'}</p>}
      {m.isPending && <div className="space-y-2"><Skeleton className="h-5 w-2/3" /><Skeleton className="h-16 w-full" /><p className="text-2xs text-faint">Claude is reading your record: up to a minute.</p></div>}
      {r && !m.isPending && (
        <div className="space-y-4 text-[13px]">
          <p className="text-[15px] font-medium text-fg">{r.review.headline}</p>
          {r.review.leaks.length > 0 && (
            <section>
              <h3 className="eyebrow mb-1.5">Where money leaks</h3>
              <ul className="space-y-2.5">{r.review.leaks.map((l) => (
                <li key={l.title} className="rounded-md border border-loss/30 p-2.5">
                  <div className="font-medium text-fg">{l.title}</div>
                  <div className="mt-0.5 text-muted">{l.evidence}</div>
                  {l.cost && <div className="mt-0.5 text-xs text-loss">Cost: {l.cost}</div>}
                  <div className="mt-1 text-xs"><span className="font-medium">Fix:</span> {l.fix}</div>
                </li>
              ))}</ul>
            </section>
          )}
          {r.review.strengths.length > 0 && (
            <section>
              <h3 className="eyebrow mb-1.5">Keep doing</h3>
              <ul className="space-y-1.5">{r.review.strengths.map((s) => <li key={s.title} className="flex gap-2">{ICON.good}<span><span className="font-medium">{s.title}.</span> <span className="text-muted">{s.evidence}</span></span></li>)}</ul>
            </section>
          )}
          {r.review.rules.length > 0 && (
            <section>
              <h3 className="eyebrow mb-1.5">Your rules</h3>
              <ol className="list-decimal space-y-1 pl-5">{r.review.rules.map((x) => <li key={x}>{x}</li>)}</ol>
            </section>
          )}
          {r.review.next_focus && <p className="rounded-md bg-raised px-3 py-2"><span className="font-medium">Next: </span>{r.review.next_focus}</p>}
          {r.review.sample_note && <p className="text-xs text-muted">{r.review.sample_note}</p>}
        </div>
      )}
      {!r && !m.isPending && v.ai.configured && can && <p className="text-xs text-muted">No review yet.</p>}
    </Card>
  )
}

export default function Coach() {
  const nav = useNavigate()
  const q = useQuery({ queryKey: ['coach'], queryFn: () => fetchJson<CoachView>('/api/coach'), staleTime: 30_000 })
  const v = q.data
  const head = <PageHeader title="Coach" subtitle="What your own trading does well and where it leaks money: your practice replays, your real FYERS fills and what you hold now." />
  if (q.error) return <div>{head}<ErrorState error={q.error} onRetry={() => void q.refetch()} /></div>
  if (!v) return <div>{head}<Skeleton className="h-40 w-full" /></div>
  const f = v.facts
  const p = f.practice
  const empty = !p && !f.real_money && !f.holdings.count
  return (
    <div className="space-y-4">
      {head}
      {empty ? (
        <Card>
          <EmptyState title="Nothing to coach yet" action={<Button variant="primary" onClick={() => nav('/replay')}>Start a replay</Button>}>
            The coach reads your own record. Finish a few replays with trades (blind ones are the honest test), trade through the Orders page, or add your holdings on the Portfolio page.
          </EmptyState>
        </Card>
      ) : (
        <>
          {p && (
            <Card title="Practice" subtitle={`${p.sessions} replay session${p.sessions === 1 ? '' : 's'} · real charges, no real money`}>
              <KpiStrip>
                <KpiTile label="Trades" value={p.summary.trades} sub={`${p.summary.wins} won`} />
                <KpiTile label="Win rate" value={p.summary.win_rate == null ? '—' : `${num(p.summary.win_rate, 0)}%`} />
                <KpiTile label="Net after charges" value={<Money v={p.summary.net} signed color dp={0} />} />
                <KpiTile label="Per trade" value={<Money v={p.summary.expectancy} signed color dp={0} />} sub={p.summary.expectancy_r != null ? `${num(p.summary.expectancy_r, 2)} R` : undefined} />
                <KpiTile label="Avg win / loss" value={<span><Money v={p.summary.avg_win} dp={0} /> / <Money v={p.summary.avg_loss} dp={0} /></span>} />
                <KpiTile label="Profit factor" value={p.summary.profit_factor == null ? '—' : num(p.summary.profit_factor, 2)} sub="wins ÷ losses" />
              </KpiStrip>
              <div className="mt-4 grid gap-4 lg:grid-cols-2">
                <div><h3 className="eyebrow mb-2">Process checks</h3><Checks items={practiceChecks(p)} /></div>
                <div><h3 className="eyebrow">Split</h3><Splits f={p} /></div>
              </div>
            </Card>
          )}
          <div className="grid gap-4 lg:grid-cols-2">
            <Card title="Real money" subtitle="Your FYERS fills, matched buy → sell first-in, first-out">
              {f.real_money ? (
                <div className="text-[13px]">
                  <table className="w-full">
                    <thead className="text-left text-2xs text-muted"><tr><th className="py-1">Round trips</th><th className="text-right">Trades</th><th className="text-right">Won</th><th className="text-right">Per trade</th><th className="text-right">Net</th></tr></thead>
                    <tbody>
                      <GroupRow label="All" g={f.real_money.closed} />
                      <GroupRow label="From a signal" g={f.real_money.from_a_signal} />
                      <GroupRow label="Off-signal" g={f.real_money.off_signal} />
                    </tbody>
                  </table>
                  <p className="mt-2 text-xs text-muted">{f.real_money.fills} fills recorded · {f.real_money.still_open_lots} lot{f.real_money.still_open_lots === 1 ? '' : 's'} still open{f.real_money.avg_slippage_pct != null ? ` · average slippage against the signal ${num(f.real_money.avg_slippage_pct, 2)}%` : ''}. {f.real_money.note}</p>
                </div>
              ) : <p className="text-xs text-muted">No real fills recorded yet. Fills are kept from the day you trade through the Orders page (or with the live service running): FYERS' own order book only covers today.</p>}
            </Card>
            <Card title="What you hold now" subtitle="holdings.csv against its stops and targets, as of the last scan">
              {f.holdings.count ? <Checks items={holdingChecks(f.holdings)} /> : <p className="text-xs text-muted">No holdings entered. Add them on the Portfolio page (or import them from FYERS) to have them checked.</p>}
            </Card>
          </div>
        </>
      )}
      <ReviewCard v={v} />
      <p className={cn('text-2xs text-faint')}>{v.note} {f.sample.enough ? '' : `Rule of thumb: ${f.sample.rule_of_thumb}.`}</p>
    </div>
  )
}
