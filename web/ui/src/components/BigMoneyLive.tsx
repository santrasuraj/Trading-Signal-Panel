// Big money live (Smart money > Big money live): today's footprints of large investors - unusual volume for the time
// of day, large trades, one-sided order books, block deals - next to what the disclosures say about the same stock,
// and the measured next-day result of past alerts. Clues, never orders (scanner/footprints.py).

import { Link } from 'react-router-dom'
import { Activity, ShieldCheck } from 'lucide-react'
import { useSmLive, type SmDir, type SmLiveRow } from '@/api/smartMoney'
import { DataTable, SymbolCell, type Col } from '@/components/DataTable'
import { KpiStrip, KpiTile } from '@/components/domain'
import { EmptyState, ErrorState, SkeletonRows } from '@/components/feedback'
import { Pct, Price } from '@/components/num'
import { Card } from '@/components/ui'
import { cn } from '@/lib/csv'
import { date, dateTimeIST, num, pct } from '@/lib/format'

const DIR: Record<SmDir, { label: string; cls: string }> = {
  up: { label: 'Buying', cls: 'tint-profit text-profit' }, down: { label: 'Selling', cls: 'tint-loss text-loss' },
  mixed: { label: 'Unclear', cls: 'tint-muted text-muted' },
}
const KIND: Record<string, string> = { volume: 'Volume', prints: 'Large trades', block: 'Block deal' }

function DirPill({ d }: { d: SmDir }) {
  return <span className={cn('inline-flex h-5 items-center rounded-full px-2 text-2xs font-semibold', DIR[d].cls)}>{DIR[d].label}</span>
}

const COLS: Col<SmLiveRow>[] = [
  { id: 'sym', header: 'Stock', value: (r) => r.symbol, cell: (r) => <SymbolCell symbol={r.symbol} company={r.company} />, sticky: true, minWidth: 150, mobile: 'primary' },
  { id: 'dir', header: 'Live', title: 'Price vs the previous close and VWAP', value: (r) => r.direction, cell: (r) => <DirPill d={r.direction} />, mobile: 'secondary', label: 'Live' },
  { id: 'chg', header: 'Change', align: 'right', value: (r) => r.change_pct, cell: (r) => <Pct v={r.change_pct} />, mobile: 'change' },
  { id: 'last', header: 'Last ₹', align: 'right', value: (r) => r.last, cell: (r) => <Price v={r.last} /> },
  { id: 'rvol', header: 'Volume', title: "Today's volume so far vs normal for this time of day (last 20 sessions)", align: 'right', value: (r) => r.rvol, cell: (r) => <span className={cn('num font-semibold', (r.rvol ?? 0) >= 4 && 'text-accent')}>{r.rvol == null ? '—' : `${num(r.rvol, 1)}×`}</span> },
  { id: 'val', header: 'Traded', align: 'right', value: (r) => r.value_cr, cell: (r) => <span className="num">₹{num(r.value_cr, 0)} cr</span>, mobile: 'value', hideBelow: 1100 },
  { id: 'what', header: 'What happened', value: (r) => r.reasons.join(' · '), cell: (r) => (
    <div className="max-w-[360px] py-0.5 text-xs">
      <div className="flex flex-wrap gap-1">{r.kinds.map((k) => <span key={k} className="rounded bg-raised px-1.5 text-2xs font-medium text-muted">{KIND[k] ?? k}</span>)}</div>
      <div className="mt-0.5 truncate text-muted" title={r.reasons.join('\n')}>{r.reasons[0]}</div>
    </div>
  ) },
  { id: 'disc', header: 'Disclosures (30 days)', title: 'What big investors reported for this stock: bulk/block deals, insider and promoter trades, shareholding changes', value: (r) => r.disclosures?.direction ?? '', cell: (r) => (
    r.disclosures ? (
      <div className="max-w-[300px] py-0.5 text-xs">
        <div className="flex items-center gap-1.5"><DirPill d={r.disclosures.direction} />{r.agree && <span className="inline-flex items-center gap-1 text-2xs font-semibold text-profit"><ShieldCheck className="h-3 w-3" />agrees</span>}</div>
        <div className="mt-0.5 truncate text-muted" title={r.disclosures.reasons.join('\n')}>{r.disclosures.reasons[0] ?? '—'}</div>
      </div>
    ) : <span className="text-xs text-faint">Nothing disclosed</span>
  ) },
]

export function BigMoneyLive() {
  const q = useSmLive()
  const d = q.data
  if (q.error && !d) return <div className="card"><ErrorState error={q.error} onRetry={() => void q.refetch()} /></div>
  if (!d) return <div className="card"><SkeletonRows rows={6} /></div>
  const t = d.track
  const agreeing = d.rows.filter((r) => r.agree).length
  return (
    <div className="space-y-3">
      <div className="rounded-lg border border-line bg-panel px-4 py-3 text-[13px]">
        <div className="flex items-start gap-2.5">
          <Activity className={cn('mt-0.5 h-4 w-4 shrink-0', d.market_open && d.fresh ? 'text-profit' : 'text-muted')} />
          <div>
            <span className="font-semibold text-fg">{d.note}</span>{' '}
            <span className="text-muted">
              {d.generated_at && <>Checked <span className="num">{dateTimeIST(d.generated_at)}</span>{d.source ? <> · bars {d.source}{d.delayed ? ' (~15 min delayed: log in to FYERS for real time)' : ''}</> : null}. </>}
              Nobody can see who is buying live: this shows their footprints (volume {d.thresholds.rvol ?? 2.5}× normal for the time of day, single trades of ₹{d.thresholds.large_print_cr ?? 2} cr+, one-sided order books, block deals). <b className="font-semibold text-fg">Agrees</b> = the disclosures of the last 30 days point the same way. Clues for your own analysis, not orders.
            </span>
          </div>
        </div>
      </div>

      <KpiStrip min={150}>
        <KpiTile label="Unusual stocks now" value={d.rows.length} sub={d.universe ? `of ${d.universe} liquid F&O stocks` : undefined} />
        <KpiTile label="Agree with disclosures" value={agreeing} sub="live move = what big investors reported" tone={agreeing ? 'text-profit' : undefined} />
        <KpiTile label="Past alerts kept going" value={t.all.hit_rate == null ? '—' : pct(t.all.hit_rate, { signed: false, dp: 0 })} sub={`by the next close · ${t.all.alerts} judged`} title={t.verdict} />
        <KpiTile label="…when disclosures agreed" value={t.with_agreement.hit_rate == null ? '—' : pct(t.with_agreement.hit_rate, { signed: false, dp: 0 })} sub={`${t.with_agreement.alerts} judged`} />
      </KpiStrip>

      <Card title="Footprints right now" subtitle="Disclosure agreement first, then the most unusual" flush>
        <DataTable id="sm.live" data={d.rows} columns={COLS} rowKey={(r) => r.symbol} pageSize={50} exportName="big-money-live"
          empty={<EmptyState compact title={d.market_open ? 'Nothing unusual right now' : 'Market closed'}>{d.market_open ? 'Volume, large trades and block deals all look normal at the moment.' : 'Footprints appear from 09:20 on trading days and refresh every 5 minutes.'}</EmptyState>} />
      </Card>

      <Card title="Did past alerts work?" subtitle={t.verdict} flush>
        <DataTable id="sm.live.track" data={t.recent} rowKey={(r) => `${r.date}${r.symbol}`} pageSize={20}
          columns={[
            { id: 'date', header: 'Alert', value: (r) => `${r.date} ${r.time}`, cell: (r) => <span className="num text-muted">{date(r.date, { year: false })} {r.time}</span> },
            { id: 'sym', header: 'Stock', value: (r) => r.symbol, cell: (r) => <Link to={`/chart/${r.symbol}`} className="font-semibold hover:underline">{r.symbol}</Link>, mobile: 'primary' },
            { id: 'dir', header: 'Live', value: (r) => r.direction, cell: (r) => <DirPill d={r.direction} /> },
            { id: 'kinds', header: 'Why', value: (r) => r.kinds.join(', '), cell: (r) => <span className="text-xs text-muted">{r.kinds.map((k) => KIND[k] ?? k).join(', ')}</span> },
            { id: 'px', header: 'Price ₹', align: 'right', value: (r) => r.price, cell: (r) => <Price v={r.price} /> },
            { id: 'move', header: 'Next close', title: 'Move by the next close, in the alert direction (positive = it kept going)', align: 'right', value: (r) => r.move_pct, cell: (r) => (r.move_pct == null ? <span className="text-faint">waiting</span> : <Pct v={r.move_pct} dp={2} />), mobile: 'change' },
          ]}
          empty={<EmptyState compact title="No alerts recorded yet">Every alert is recorded once per stock and day; its result appears after the next close.</EmptyState>} />
        <p className="border-t border-line px-4 py-2 text-2xs text-faint">A record means something from {t.min_to_judge} alerts with a next-day result. If alerts don't keep moving their way more often than not, treat them as noise.</p>
      </Card>
    </div>
  )
}
