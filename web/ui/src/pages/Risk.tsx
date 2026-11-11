// Portfolio risk `/risk`: money at risk to your stops, concentration, beta, a one-day loss estimate, stress tests and
// correlation between holdings (web/api/services/risk_svc.py).

import { Link } from 'react-router-dom'
import { ShieldAlert } from 'lucide-react'
import { useRisk, type RiskResponse } from '@/api/desk'
import { KpiStrip, KpiTile, PageHeader } from '@/components/domain'
import { Banner, EmptyState, ErrorState, SkeletonKpis } from '@/components/feedback'
import { Card } from '@/components/ui'
import { date as fmtDate, money, moneyCompact, num, pct, qty as fmtQty } from '@/lib/format'
import { cn } from '@/lib/csv'

function corrColour(v: number | null): string {
  if (v == null) return 'rgb(var(--raised))'
  const a = Math.min(1, Math.abs(v)) * 0.75 + 0.05
  return v >= 0 ? `rgb(var(--loss) / ${a})` : `rgb(var(--profit) / ${a})`
}

function Correlation({ c }: { c: NonNullable<RiskResponse['correlation']> }) {
  if (c.symbols.length < 2) return <p className="text-xs text-muted">Needs two or more holdings with a year of prices.</p>
  return (
    <div className="overflow-x-auto">
      <table className="text-2xs">
        <thead><tr><th />{c.symbols.map((s) => <th key={s} className="px-0.5 pb-1 font-medium text-muted [writing-mode:vertical-rl]">{s}</th>)}</tr></thead>
        <tbody>{c.matrix.map((row, i) => (
          <tr key={c.symbols[i]}>
            <th className="pr-2 text-right font-medium text-muted">{c.symbols[i]}</th>
            {row.map((v, j) => <td key={j} title={`${c.symbols[i]} / ${c.symbols[j]}: ${v ?? '—'}`} className="num h-7 w-9 text-center text-fg" style={{ background: i === j ? 'rgb(var(--raised))' : corrColour(v) }}>{i === j ? '' : v?.toFixed(2)}</td>)}
          </tr>))}</tbody>
      </table>
    </div>
  )
}

export default function Risk() {
  const q = useRisk()
  const d = q.data
  const r = d?.risk ?? {}
  return (
    <div>
      <PageHeader title="Portfolio risk" subtitle={d && !d.empty ? `${d.count} holdings · ${moneyCompact(d.value)} · priced at ${d.price_source === 'close' ? 'the last close' : 'live prices'}` : 'How much your holdings can lose'} />
      {q.error ? <ErrorState error={q.error} onRetry={() => q.refetch()} /> : !d ? <SkeletonKpis n={6} /> : d.empty ? (
        <EmptyState icon={<ShieldAlert />} title="No holdings yet" action={<Link className="text-accent" to="/portfolio">Add holdings on Portfolio</Link>}>{d.notes[0]}</EmptyState>
      ) : (
        <>
          <KpiStrip>
            <KpiTile label="At risk to your stops" value={money(d.at_risk)} sub={`${pct(d.at_risk_pct, { signed: false })} of the portfolio, if every stop fills`} tone="text-loss" />
            <KpiTile label="1-day loss, 1 day in 20" value={money(r.var95)} sub={r.es95 != null ? `average of those days ${money(r.es95)}` : undefined} title="95% value at risk from the last two years of daily returns" />
            <KpiTile label="1-day loss, 1 day in 100" value={money(r.var99)} sub={r.var99_pct != null ? `${r.var99_pct.toFixed(1)}% of the portfolio` : undefined} />
            <KpiTile label="Beta to the Nifty 50" value={d.beta != null ? d.beta.toFixed(2) : '—'} sub={d.beta != null ? `Nifty −10% ≈ ${pct(d.beta * -10)}` : undefined} />
            <KpiTile label="Volatility (yearly)" value={r.vol_pct != null ? `${r.vol_pct.toFixed(1)}%` : '—'} sub={r.nifty_vol_pct != null ? `Nifty 50: ${r.nifty_vol_pct.toFixed(1)}%` : undefined} />
            <KpiTile label="Effective no. of stocks" value={d.concentration?.effective_n != null ? num(d.concentration.effective_n, 1) : '—'} sub={`largest ${d.concentration?.top_symbol} ${pct(d.concentration?.top_pct, { signed: false })}`} />
          </KpiStrip>
          {(d.flags ?? []).length > 0 && <div className="mt-3 flex flex-col gap-2">{d.flags!.map((f) => <Banner key={f} tone="warn">{f}</Banner>)}</div>}
          <div className="mt-3 grid gap-3 xl:grid-cols-2">
            <Card flush title="Holdings" subtitle="Weight, beta and money at risk to the stop">
              <div className="overflow-x-auto"><table className="w-full text-[13px]">
                <thead className="text-2xs text-muted"><tr className="text-left"><th className="px-4 py-1.5">Stock</th><th className="px-2">Industry</th><th className="px-2 text-right">Qty</th><th className="px-2 text-right">Value</th><th className="px-2 text-right">Weight</th><th className="px-2 text-right">Beta</th><th className="px-4 text-right">At risk</th></tr></thead>
                <tbody className="divide-y divide-line">{d.positions.map((p) => (
                  <tr key={p.symbol}>
                    <td className="px-4 py-1.5 font-semibold"><Link to={`/chart/${p.symbol}`} className="hover:text-accent">{p.symbol}</Link></td>
                    <td className="max-w-[120px] truncate px-2 text-muted">{p.industry}</td>
                    <td className="num px-2 text-right">{fmtQty(p.qty)}</td>
                    <td className="num px-2 text-right">{money(p.value)}</td>
                    <td className="px-2 text-right"><div className="flex items-center justify-end gap-2"><div className="h-1.5 w-16 overflow-hidden rounded bg-raised"><div className="h-full bg-accent" style={{ width: `${Math.min(100, p.weight_pct)}%` }} /></div><span className="num w-12">{pct(p.weight_pct, { signed: false })}</span></div></td>
                    <td className={cn('num px-2 text-right', p.beta != null && p.beta > 1.2 && 'text-warn')}>{p.beta != null ? p.beta.toFixed(2) : '—'}</td>
                    <td className="num px-4 text-right text-loss">{money(p.at_risk)}</td>
                  </tr>))}</tbody>
              </table></div>
            </Card>
            <Card title="If the market falls" subtitle="Through beta (a stock can fall more, or less, than its beta says)">
              <div className="flex flex-col gap-2">
                {(d.shocks ?? []).map((s) => (
                  <div key={s.nifty_pct} className="flex items-baseline justify-between text-[13px]"><span>Nifty 50 {pct(s.nifty_pct, { dp: 0 })}</span><span className="num text-loss">{money(s.amount, { signed: true })} ({pct(s.pct)})</span></div>))}
                {d.worst_day && <div className="mt-2 border-t border-line pt-2 text-[13px]">Worst day for today's holdings in the store: <b>{fmtDate(d.worst_day.date)}</b>, {pct(d.worst_day.pct)} ({money(d.worst_day.amount, { signed: true })}){d.worst_day.nifty_pct != null && <span className="text-muted"> · Nifty 50 {pct(d.worst_day.nifty_pct)}</span>}</div>}
                {r.max_drawdown_pct != null && <div className="text-[13px]">Deepest fall in the last two years: <b className="text-loss">{pct(r.max_drawdown_pct)}</b></div>}
              </div>
              <div className="mt-4">
                <div className="mb-1 text-xs font-medium text-muted">By industry</div>
                {(d.concentration?.industries ?? []).map((x) => (
                  <div key={x.industry} className="flex items-center gap-2 py-0.5 text-[13px]"><span className="w-40 truncate">{x.industry}</span><div className="h-2 flex-1 overflow-hidden rounded bg-raised"><div className={cn('h-full', x.weight_pct > 35 ? 'bg-warn' : 'bg-accent')} style={{ width: `${Math.min(100, x.weight_pct)}%` }} /></div><span className="num w-12 text-right">{pct(x.weight_pct, { signed: false })}</span></div>))}
              </div>
            </Card>
            <Card title="Correlation" subtitle={d.correlation?.average != null ? `Average ${d.correlation.average.toFixed(2)} (last year's daily returns). Red = move together, green = opposite.` : 'Last year\'s daily returns'} className="xl:col-span-2">
              {d.correlation && <Correlation c={d.correlation} />}
              {(d.correlation?.high_pairs ?? []).length > 0 && <p className="mt-2 text-xs text-muted">Move together: {d.correlation!.high_pairs.slice(0, 8).map((x) => `${x.a} & ${x.b} (${x.corr.toFixed(2)})`).join(', ')}</p>}
            </Card>
          </div>
          <p className="mt-4 text-2xs text-faint">History-based: today's holdings replayed over the last {r.days ?? 500} trading days{r.covered_pct != null && r.covered_pct < 100 ? ` (${r.covered_pct}% of the value has the history)` : ''}. A crash worse than any in the window isn't in these numbers, and a stop can fill below its price after a gap.</p>
        </>
      )}
    </div>
  )
}
