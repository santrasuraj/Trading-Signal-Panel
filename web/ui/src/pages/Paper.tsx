// Paper trading `/paper`, `/paper/:key` (spec 3.8): the live proof, journal vs backtest.

import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { ChevronDown, ChevronLeft, NotebookPen } from 'lucide-react'
import { usePaper } from '@/api/hooks'
import type { PaperSummary } from '@/api/types'
import { TonePill } from '@/components/badges'
import { DataTable, type Col } from '@/components/DataTable'
import { PageHeader } from '@/components/domain'
import { EmptyState, ErrorState, SkeletonRows } from '@/components/feedback'
import { PaperDetailView, verdictLabel } from '@/components/PaperDetail'
import { Money, Pct, Pts } from '@/components/num'
import { Card } from '@/components/ui'
import { cn } from '@/lib/csv'
import { date, pct } from '@/lib/format'

function Intro() {
  const [open, setOpen] = useState(true)
  return (
    <button type="button" onClick={() => setOpen(!open)} className="focus-ring mb-3 flex w-full items-start gap-2 rounded-lg border border-line bg-panel px-4 py-2.5 text-left text-[13px] text-muted">
      <ChevronDown className={cn('mt-0.5 h-4 w-4 shrink-0 transition-transform', !open && '-rotate-90')} />
      {open ? (
        <span>Live proof: every completed-day scan journals its orders; they fill at the next official open with full charges and slippage. Nothing here can be fitted to the past. Judge only after a few weeks: short periods are mostly noise.</span>
      ) : <span>What is paper trading?</span>}
    </button>
  )
}

export default function Paper() {
  const { key } = useParams()
  const q = usePaper()
  const nav = useNavigate()
  const d = q.data
  const minDays = d?.min_days_to_judge ?? 21

  if (key) {
    const s = d?.strategies.find((x) => x.key === key)
    return (
      <div>
        <div className="mb-3 text-xs"><Link to="/paper" className="inline-flex items-center gap-1 text-muted hover:text-fg"><ChevronLeft className="h-3.5 w-3.5" />Paper trading</Link></div>
        <PageHeader title={s?.name ?? key} subtitle={s ? <>Paper since {date(s.start)} · {s.days} trading days · <Link className="link" to={`/strategies/${key}`}>backtest</Link></> : null} />
        <PaperDetailView k={key} />
      </div>
    )
  }

  const cols: Col<PaperSummary>[] = [
    { id: 'name', header: 'Strategy', value: (r) => r.name, sticky: true, minWidth: 200, mobile: 'primary', cell: (r) => <span className="font-semibold">{r.name}</span> },
    { id: 'verdict', header: 'Verdict', value: (r) => r.level, cell: (r) => <TonePill tone={r.level}>{verdictLabel(r, minDays)}</TonePill>, mobile: 'secondary', label: 'Verdict' },
    { id: 'ret', header: 'Paper', align: 'right', value: (r) => r.return_pct, cell: (r) => <Pct v={r.return_pct} />, mobile: 'change' },
    { id: 'n500', header: 'Nifty 500', title: 'Same days (hover a value for Nifty 50)', align: 'right', value: (r) => r.n500_pct, cell: (r) => <span title={`Nifty 50 ${pct(r.nifty_pct)}`}><Pct v={r.n500_pct} /></span>, mobile: 'secondary', label: 'N500' },
    { id: 'gap', header: 'Gap vs N500', title: 'Paper return minus Nifty 500 over the same days (percentage points)', align: 'right', value: (r) => r.excess_pct, cell: (r) => <Pts v={r.excess_pct} /> },
    { id: 'exp', header: 'Expected', title: 'What the backtest implies for the same days, given what the index did', align: 'right', value: (r) => r.expected_pct, cell: (r) => <span title={r.expected_range_pct ? `range ${pct(r.expected_range_pct[0])} to ${pct(r.expected_range_pct[1])}` : undefined}><Pct v={r.expected_pct} /></span> },
    { id: 'noise', header: 'Noise ±', title: 'Typical random spread for this many days', align: 'right', value: (r) => r.noise_pct, cell: (r) => <span className="num text-muted">±{pct(r.noise_pct, { signed: false })}</span>, hideBelow: 1200 },
    { id: 'pnl', header: 'P&L ₹', align: 'right', value: (r) => r.pnl, cell: (r) => <Money v={r.pnl} signed color /> },
    { id: 'since', header: 'Since', value: (r) => r.start, cell: (r) => <span className="num text-muted">{date(r.start, { year: false })}</span>, hideBelow: 1240 },
    { id: 'days', header: 'Days', align: 'right', value: (r) => r.days, cell: (r) => <span className="num">{r.days}</span>, mobile: 'secondary', label: 'Days' },
    { id: 'open', header: 'Holding', align: 'right', value: (r) => r.open, cell: (r) => <span className="num">{r.open}{r.pending ? <span className="text-faint"> +{r.pending}</span> : ''}</span> },
    { id: 'closed', header: 'Closed', align: 'right', value: (r) => r.trades, cell: (r) => <span className="num">{r.trades}</span> },
  ]

  return (
    <div>
      <PageHeader title="Paper trading" subtitle={d?.journal ? <>Journal: {d.journal.days} scan day{d.journal.days === 1 ? '' : 's'}, {date(d.journal.first)} → {date(d.journal.last)}</> : 'The journal of completed-day scans'} />
      <Intro />
      <Card flush>
        {q.error && !d ? <ErrorState error={q.error} onRetry={() => void q.refetch()} /> : !d ? <SkeletonRows rows={4} /> : !d.available || d.strategies.length === 0 ? (
          <EmptyState title="No paper journal yet" icon={<NotebookPen className="h-6 w-6" strokeWidth={1.5} />}>
            The journal starts automatically with the next scan of a completed trading day (after ~6 PM or before 9:15 AM). Intraday scans are never journaled.
          </EmptyState>
        ) : (
          <DataTable id="paper" data={d.strategies} columns={cols} rowKey={(r) => r.key} onRowClick={(r) => nav(`/paper/${r.key}`)} keyboard />
        )}
      </Card>
      {d?.available && (
        <p className="mt-2 text-2xs text-faint">
          Expected = the backtest's pace for the same number of days, minus a survivorship haircut of {pct(d.survivorship_haircut_pct, { signed: false, dp: 0 })}/yr. Verdicts stay “Too early” for the first {minDays} trading days.
        </p>
      )}
    </div>
  )
}
