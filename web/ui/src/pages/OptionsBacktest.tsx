// Options backtester `/options-backtest`: a strategy (straddle, strangle, iron condor, spreads ...) tested once per
// expiry cycle on NSE's daily index-option prices, with stops, targets and real charges
// (web/api/services/optbt_svc.py, scanner/options_backtest.py).

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Download, FlaskConical } from 'lucide-react'
import { fetchJson, isFailure } from '@/api/client'
import { KpiStrip, KpiTile, PageHeader } from '@/components/domain'
import { Banner, EmptyState } from '@/components/feedback'
import { Button, Card, Field } from '@/components/ui'
import { date as fmtDate, money, num } from '@/lib/format'
import { useLocalStorage } from '@/lib/useLocalStorage'
import { useWidth } from '@/lib/useWidth'
import { cn } from '@/lib/csv'

interface Status { history: { days: number; first: string | null; last: string | null; symbols: string[]; mb: number }; job: { running: boolean; done: number; total: number; finished: string | null; error: string | null; report: { added: number; missing: string[] } | null }; strategies: string[]; underlyings: string[] }
interface Leg { side: string; type: string; strike: number; entry: number; exit: number }
interface BtTrade { entry: string; exit: string; expiry: string; spot_in: number; spot_out: number; legs: Leg[]; qty: number; credit: number; why: string; gross: number; charges: number; pnl: number; worst_open: number }
interface BtStats { trades: number; win_rate?: number; total?: number; avg?: number; avg_win?: number | null; avg_loss?: number | null; best?: number; worst?: number; max_drawdown?: number; profit_factor?: number | null; charges?: number; exits?: Record<string, number>; by_year?: { year: string; trades: number; total: number }[] }
interface BtResult { trades: BtTrade[]; skipped: { expiry: string; why: string }[]; stats: BtStats; curve: { date: string; equity: number }[]; history: { first: string; last: string }; note: string }
interface Spec { underlying: string; strategy: string; cycle: 'monthly' | 'weekly'; entry_dte: number; short_pct: number; wing_pct: number; stop_pct: number | null; target_pct: number | null; lots: number; slippage_pct: number }

const NAMES: Record<string, string> = {
  short_straddle: 'Short straddle', short_strangle: 'Short strangle', iron_condor: 'Iron condor', iron_fly: 'Iron butterfly', bull_put: 'Bull put spread',
  bear_call: 'Bear call spread', long_straddle: 'Long straddle', long_strangle: 'Long strangle', bull_call: 'Bull call spread', bear_put: 'Bear put spread',
}
const USES_WING = new Set(['iron_condor', 'iron_fly', 'bull_put', 'bear_call'])
const DEFAULT: Spec = { underlying: 'NIFTY', strategy: 'iron_condor', cycle: 'monthly', entry_dte: 30, short_pct: 3, wing_pct: 5, stop_pct: 200, target_pct: 50, lots: 1, slippage_pct: 1 }

function Curve({ pts }: { pts: { date: string; equity: number }[] }) {
  const [ref, w] = useWidth<HTMLDivElement>()
  const H = 200, P = 8
  if (pts.length < 2) return <div ref={ref} />
  const ys = [0, ...pts.map((p) => p.equity)]
  const lo = Math.min(...ys), hi = Math.max(...ys)
  const X = (i: number) => P + (i / (pts.length - 1)) * (Math.max(w, 200) - 2 * P)
  const Y = (v: number) => P + ((hi - v) / (hi - lo || 1)) * (H - 2 * P)
  return (
    <div ref={ref}>
      <svg width={Math.max(w, 200)} height={H} role="img" aria-label="Cumulative profit and loss">
        <line x1={P} x2={Math.max(w, 200) - P} y1={Y(0)} y2={Y(0)} stroke="rgb(var(--line-strong))" />
        <path d={pts.map((p, i) => `${i ? 'L' : 'M'}${X(i)},${Y(p.equity)}`).join('')} fill="none" stroke="rgb(var(--accent))" strokeWidth={2} />
        {pts.map((p, i) => <circle key={p.date} cx={X(i)} cy={Y(p.equity)} r={2.5} fill="rgb(var(--accent))"><title>{`${p.date}: ${money(p.equity, { signed: true })}`}</title></circle>)}
      </svg>
    </div>
  )
}

export default function OptionsBacktest() {
  const qc = useQueryClient()
  const st = useQuery({ queryKey: ['optbt-status'], queryFn: () => fetchJson<Status>('/api/options-backtest/status'), refetchInterval: (q) => (q.state.data?.job.running ? 3000 : false) })
  const [spec, setSpec] = useLocalStorage<Spec>('qd.optbt.spec', DEFAULT)
  const set = <K extends keyof Spec>(k: K, v: Spec[K]) => setSpec({ ...spec, [k]: v })
  const run = useMutation({ mutationFn: () => fetchJson<BtResult>('/api/options-backtest/run', { method: 'POST', body: JSON.stringify(spec) }) })
  const fetchHist = useMutation({ mutationFn: (days: number) => fetchJson<Status>('/api/options-backtest/history', { method: 'POST', body: JSON.stringify({ days }) }), onSuccess: () => { void qc.invalidateQueries({ queryKey: ['optbt-status'] }) } })
  const h = st.data?.history
  const job = st.data?.job
  const r = run.data
  const s = r?.stats
  const numIn = (k: keyof Spec, label: string, hint?: string, opt = false) => (
    <Field label={label} hint={hint}><input className="input h-9 w-28 px-2 text-right" inputMode="decimal" value={(spec[k] as number | null) ?? ''} placeholder={opt ? 'off' : ''}
      onChange={(e) => set(k, (e.target.value === '' ? (opt ? null : 0) : Number(e.target.value)) as Spec[typeof k])} /></Field>
  )
  return (
    <div>
      <PageHeader title="Options backtester" subtitle={h ? (h.days ? `${h.days} days of NSE option prices stored (${fmtDate(h.first)} – ${fmtDate(h.last)}, ${h.mb} MB)` : 'No option history stored yet') : 'Option strategies tested on NSE\'s daily prices'}
        right={<Button size="sm" variant="subtle" icon={<Download className="h-4 w-4" />} loading={job?.running} disabled={job?.running}
          title="About 1.2 MB a trading day from NSE, one a second; the nightly F&O refresh keeps it current afterwards"
          onClick={() => fetchHist.mutate(500)}>{job?.running ? `Fetching ${job.done} of ${job.total} days` : 'Fetch 2 years of history'}</Button>} />
      {job?.error && <div className="mb-3"><Banner tone="danger">{job.error}</Banner></div>}
      <Card className="mb-3" title="Strategy" subtitle="One position per expiry, entered at the close; strikes as % away from the index; stop and target checked at each day's close">
        <div className="flex flex-wrap items-end gap-3">
          <Field label="Index"><select className="input h-9 px-2" value={spec.underlying} onChange={(e) => set('underlying', e.target.value)}>{(st.data?.underlyings ?? ['NIFTY', 'BANKNIFTY']).map((u) => <option key={u}>{u}</option>)}</select></Field>
          <Field label="Strategy"><select className="input h-9 px-2" value={spec.strategy} onChange={(e) => set('strategy', e.target.value)}>{Object.entries(NAMES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></Field>
          <Field label="Cycle"><select className="input h-9 px-2" value={spec.cycle} onChange={(e) => set('cycle', e.target.value as Spec['cycle'])}><option value="monthly">Monthly expiry</option><option value="weekly">Every expiry (weekly)</option></select></Field>
          {numIn('entry_dte', 'Enter with days left', 'calendar days')}
          {!['short_straddle', 'long_straddle'].includes(spec.strategy) && numIn('short_pct', spec.strategy.startsWith('long') || spec.strategy.startsWith('bull_call') || spec.strategy.startsWith('bear_put') ? 'Second strike, % away' : 'Short strikes, % away')}
          {USES_WING.has(spec.strategy) && numIn('wing_pct', 'Wings, % away', 'the bought protection')}
          {numIn('stop_pct', 'Stop at loss of (%)', '% of the premium', true)}
          {numIn('target_pct', 'Take profit at (%)', '% of the maximum', true)}
          {numIn('lots', 'Lots')}
          {numIn('slippage_pct', 'Slippage (%)', 'of each price')}
          <Button variant="primary" icon={<FlaskConical className="h-4 w-4" />} loading={run.isPending} disabled={!h?.days} onClick={() => run.mutate()}>Run backtest</Button>
        </div>
        {run.error && <p className="mt-2 text-xs text-loss">{isFailure(run.error) ? `${run.error.message}${run.error.hint ? ` ${run.error.hint}` : ''}` : 'Failed.'}</p>}
      </Card>
      {!h?.days && !job?.running ? (
        <EmptyState icon={<Download />} title="Fetch the option history first">NSE publishes every option's daily close. Quant Desk keeps NIFTY and BANKNIFTY options within 20% of the index and 70 days of expiry: a few MB a year on disk.</EmptyState>
      ) : r && s ? (
        <>
          <KpiStrip>
            <KpiTile label="Cycles traded" value={s.trades} sub={`win rate ${s.win_rate?.toFixed(0) ?? '—'}%`} />
            <KpiTile label="Total after charges" value={money(s.total, { signed: true })} tone={(s.total ?? 0) >= 0 ? 'text-profit' : 'text-loss'} sub={`charges ${money(s.charges)}`} />
            <KpiTile label="Average cycle" value={money(s.avg, { signed: true })} sub={`win ${money(s.avg_win)} · loss ${money(s.avg_loss)}`} />
            <KpiTile label="Worst cycle" value={money(s.worst, { signed: true })} tone="text-loss" />
            <KpiTile label="Deepest fall" value={money(s.max_drawdown, { signed: true })} tone="text-loss" sub="from a running high" />
            <KpiTile label="Exits" value={<span className="text-base">{s.exits?.target ?? 0} target · {s.exits?.stop ?? 0} stop · {s.exits?.expiry ?? 0} expiry</span>} />
          </KpiStrip>
          {s.trades > 0 && s.trades < 20 && <div className="mt-3"><Banner tone="warn">Only {s.trades} cycles: far too few to trust. Fetch more history, or use weekly cycles.</Banner></div>}
          <div className="mt-3 grid gap-3 xl:grid-cols-3">
            <Card className="xl:col-span-2" title="Cumulative P&L" subtitle={`${NAMES[spec.strategy]} on ${spec.underlying}, ${spec.lots} lot${spec.lots > 1 ? 's' : ''}`}><Curve pts={r.curve} /></Card>
            <Card flush title="By year">
              <table className="w-full text-[13px]"><tbody className="divide-y divide-line">{(s.by_year ?? []).map((y) => (
                <tr key={y.year}><td className="px-4 py-1.5">{y.year}</td><td className="num px-2 text-right text-muted">{y.trades} cycles</td><td className={cn('num px-4 text-right', y.total >= 0 ? 'text-profit' : 'text-loss')}>{money(y.total, { signed: true })}</td></tr>))}</tbody></table>
            </Card>
          </div>
          <Card flush className="mt-3" title="Every cycle">
            <div className="overflow-x-auto"><table className="w-full text-[13px]">
              <thead className="text-2xs text-muted"><tr className="text-left"><th className="px-4 py-1.5">Entry → exit</th><th className="px-2">Expiry</th><th className="px-2">Legs (strike: in → out)</th><th className="px-2 text-right">Index</th><th className="px-2">Exit</th><th className="px-2 text-right">Worst open</th><th className="px-4 text-right">P&L</th></tr></thead>
              <tbody className="divide-y divide-line">{r.trades.slice().reverse().map((t) => (
                <tr key={t.entry}>
                  <td className="num px-4 py-1.5">{fmtDate(t.entry, { year: false })} → {fmtDate(t.exit, { year: false })}</td>
                  <td className="num px-2 text-muted">{fmtDate(t.expiry)}</td>
                  <td className="px-2 text-2xs">{t.legs.map((l) => <span key={`${l.type}${l.strike}${l.side}`} className={cn('mr-2 whitespace-nowrap', l.side === 'sell' ? 'text-loss' : 'text-profit')}>{l.side === 'sell' ? 'S' : 'B'} {num(l.strike, 0)}{l.type} {num(l.entry, 1)}→{num(l.exit, 1)}</span>)}</td>
                  <td className="num px-2 text-right text-2xs">{num(t.spot_in, 0)} → {num(t.spot_out, 0)}</td>
                  <td className="px-2 text-muted">{t.why}</td>
                  <td className="num px-2 text-right text-loss">{money(t.worst_open)}</td>
                  <td className={cn('num px-4 text-right', t.pnl >= 0 ? 'text-profit' : 'text-loss')}>{money(t.pnl, { signed: true })}</td>
                </tr>))}</tbody>
            </table></div>
          </Card>
          {r.skipped.length > 0 && <p className="mt-2 text-2xs text-muted">Skipped: {r.skipped.map((x) => `${x.expiry} (${x.why})`).join('; ')}</p>}
          <p className="mt-3 text-2xs text-faint">{r.note}</p>
        </>
      ) : null}
    </div>
  )
}
