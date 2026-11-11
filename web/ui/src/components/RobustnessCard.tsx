// Strategy robustness (web/api/services/robustness.py): could the backtest be luck? 10,000-path Monte Carlo,
// deflated Sharpe (corrected for every strategy tried here) and rolling 12-month consistency.

import { useRobustness } from '@/api/scans'
import { ErrorState, Skeleton } from '@/components/feedback'
import { Pct } from '@/components/num'
import { Card } from '@/components/ui'
import { cn } from '@/lib/csv'
import { date, num, pct } from '@/lib/format'

const VERDICT = {
  likely_real: { label: 'Likely real', cls: 'bg-profit text-white', text: 'The edge survives the luck tests: deflated Sharpe 95%+ and most Monte Carlo histories beat the average stock.' },
  maybe_luck: { label: 'Could be luck', cls: 'tint-warn text-warn', text: 'Better than chance, but not clearly better than the best of the many strategies tried here would look by luck alone.' },
  likely_luck: { label: 'Likely luck', cls: 'bg-raised text-muted border border-line-strong', text: 'With this many strategies tried, a result like this is what luck alone tends to produce.' },
}

export function RobustnessCard({ k }: { k: string }) {
  const q = useRobustness(k)
  const d = q.data
  if (q.error) return <Card title="Robustness"><ErrorState error={q.error} compact /></Card>
  if (!d) return <Card title="Robustness"><Skeleton className="h-32 w-full" /></Card>
  const v = VERDICT[d.verdict]
  const mc = d.monte_carlo, ds = d.deflated_sharpe, co = d.consistency
  return (
    <Card title="Robustness: could it be luck?" subtitle={`${date(d.from)} to ${date(d.to)} · ${d.days.toLocaleString('en-IN')} trading days · after costs`}>
      <div className="flex flex-wrap items-start gap-3">
        <span className={cn('rounded-md px-2.5 py-1 text-sm font-bold', v.cls)}>{v.label.toUpperCase()}</span>
        <p className="min-w-0 flex-1 text-xs text-muted">{v.text}</p>
      </div>
      <div className="mt-3 grid gap-3 text-[13px] md:grid-cols-3">
        <div>
          <div className="eyebrow mb-1">Monte Carlo ({(mc.paths ?? 0).toLocaleString('en-IN')} histories)</div>
          {mc.cagr_pct ? (
            <ul className="space-y-0.5">
              <li className="flex justify-between"><span className="text-muted">Yearly return, middle</span><Pct v={mc.cagr_pct.p50} dp={1} /></li>
              <li className="flex justify-between"><span className="text-muted">Bad case (5%)</span><Pct v={mc.cagr_pct.p5} dp={1} /></li>
              <li className="flex justify-between"><span className="text-muted">Good case (95%)</span><Pct v={mc.cagr_pct.p95} dp={1} /></li>
              <li className="flex justify-between"><span className="text-muted">Worst drop, typical / bad</span><span><Pct v={mc.max_dd_pct?.p50} dp={0} /> / <Pct v={mc.max_dd_pct?.p5} dp={0} /></span></li>
              <li className="flex justify-between"><span className="text-muted">Lost money</span><span className="num">{num(mc.prob_loss_pct, 1)}%</span></li>
              {mc.prob_beat_bench_pct != null && <li className="flex justify-between"><span className="text-muted">Beat {d.benchmark?.toLowerCase()}</span><span className="num">{num(mc.prob_beat_bench_pct, 1)}%</span></li>}
            </ul>
          ) : <p className="text-xs text-muted">Too short to resample.</p>}
        </div>
        <div>
          <div className="eyebrow mb-1">Deflated Sharpe</div>
          {ds.deflated_pct != null ? (
            <ul className="space-y-0.5">
              <li className="flex justify-between"><span className="text-muted">Sharpe (yearly)</span><span className="num">{num(ds.sharpe_ann, 2)}</span></li>
              <li className="flex justify-between" title={`What the best of ${ds.trials} strategies with no edge would show by chance`}><span className="text-muted">Best of {ds.trials} by luck</span><span className="num">{num(ds.expected_max_sharpe_ann, 2)}</span></li>
              <li className="flex justify-between"><span className="text-muted">Not luck (deflated)</span><span className={cn('num font-semibold', (ds.deflated_pct ?? 0) >= 95 ? 'text-profit' : (ds.deflated_pct ?? 0) >= 50 ? 'text-warn' : 'text-loss')}>{num(ds.deflated_pct, 1)}%</span></li>
              <li className="flex justify-between" title="Ignoring that many strategies were tried"><span className="text-muted">Not luck (one strategy)</span><span className="num">{num(ds.probabilistic_pct, 1)}%</span></li>
              <li className="flex justify-between"><span className="text-muted">Skew / kurtosis</span><span className="num">{num(ds.skew, 2)} / {num(ds.kurtosis, 1)}</span></li>
            </ul>
          ) : <p className="text-xs text-muted">Not enough data.</p>}
        </div>
        <div>
          <div className="eyebrow mb-1">Consistency</div>
          <ul className="space-y-0.5">
            {co.beat_bench_pct != null && <li className="flex justify-between"><span className="text-muted">12-month windows beating {d.benchmark?.toLowerCase()}</span><span className="num">{num(co.beat_bench_pct, 0)}%</span></li>}
            <li className="flex justify-between"><span className="text-muted">Worst / best 12 months</span><span><Pct v={co.worst_12m_pct} dp={0} /> / <Pct v={co.best_12m_pct} dp={0} /></span></li>
            {co.first_half_cagr_pct != null && <>
              <li className="flex justify-between" title={`Split at ${date(co.split_at)}`}><span className="text-muted">First half /yr (bench)</span><span><Pct v={co.first_half_cagr_pct} dp={1} /> <span className="text-faint">({pct(co.first_half_bench_pct, { dp: 1 })})</span></span></li>
              <li className="flex justify-between"><span className="text-muted">Second half /yr (bench)</span><span><Pct v={co.second_half_cagr_pct} dp={1} /> <span className="text-faint">({pct(co.second_half_bench_pct, { dp: 1 })})</span></span></li>
            </>}
          </ul>
        </div>
      </div>
      <p className="mt-3 text-2xs text-faint">{d.note}</p>
    </Card>
  )
}
