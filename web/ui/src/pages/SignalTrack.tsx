// Signal track record `/signals/track`: every BUY signal the scanner gave (journal), followed on real prices by the
// strategy's own rules (next-open fill, stop, target, trailing stop, sell when the strategy sells), after all charges.
// Live evidence only: nothing here is a backtest, except the backtest column that puts each live record in context.

import { Link, useSearchParams } from 'react-router-dom'
import { ChevronLeft, History } from 'lucide-react'
import { useTrackRecord } from '@/api/hooks'
import type { TrackSignal, TrackState, TrackStrategy } from '@/api/types'
import { StatusBadge, TonePill } from '@/components/badges'
import { DataTable, type Col } from '@/components/DataTable'
import { KpiStrip, KpiTile, PageHeader } from '@/components/domain'
import { EmptyState, ErrorState, RefreshFailed, SkeletonRows } from '@/components/feedback'
import { Money, Pct, Price, Ratio } from '@/components/num'
import { Card, Tabs } from '@/components/ui'
import { cn } from '@/lib/csv'
import { date, num, pct } from '@/lib/format'
import { TONE_TEXT, TONE_TINT } from '@/lib/vocab'

const STATE: Record<TrackState, { label: string; tone: 'profit' | 'muted' | 'info' | 'warn' }> = {
  open: { label: 'Open', tone: 'info' }, closed: { label: 'Closed', tone: 'muted' },
  pending: { label: 'Fills next open', tone: 'warn' }, not_filled: { label: 'Not filled', tone: 'muted' },
}
const LEVEL = { good: 'good', bad: 'bad', unknown: 'neutral' } as const

function StatePill({ state, note }: { state: TrackState; note: string | null }) {
  const m = STATE[state]
  return <span title={note ?? undefined} className={cn('inline-flex h-5 items-center whitespace-nowrap rounded-full px-2 text-2xs font-medium', TONE_TINT[m.tone], TONE_TEXT[m.tone])}>{m.label}</span>
}

const SIGNAL_COLS: Col<TrackSignal>[] = [
  { id: 'date', header: 'Signal', value: (r) => r.signal_date, cell: (r) => <span className="num text-muted">{date(r.signal_date, { year: false })}</span> },
  { id: 'sym', header: 'Symbol', value: (r) => r.symbol, cell: (r) => <Link to={`/chart/${r.symbol}?s=${r.strategy_key}`} className="font-semibold hover:underline">{r.symbol}</Link>, sticky: true, mobile: 'primary' },
  { id: 'st', header: 'Strategy', value: (r) => r.strategy_name, cell: (r) => <Link to={`/strategies/${r.strategy_key}`} className="block max-w-[200px] truncate hover:underline" title={r.strategy_name}>{r.strategy_name}</Link> },
  { id: 'state', header: 'State', value: (r) => r.state, cell: (r) => <StatePill state={r.state} note={r.note} />, mobile: 'secondary', label: 'State' },
  { id: 'entry', header: 'Entry ₹', title: 'Next official open plus slippage', align: 'right', value: (r) => r.entry_price, cell: (r) => <Price v={r.entry_price} /> },
  { id: 'qty', header: 'Qty', align: 'right', value: (r) => r.qty, cell: (r) => <span className="num">{r.qty ?? '—'}</span>, hideBelow: 1100 },
  { id: 'stop', header: 'Stop ₹', align: 'right', value: (r) => r.stop, cell: (r) => <Price v={r.stop} />, hideBelow: 1200 },
  { id: 'last', header: 'Exit / last ₹', title: 'Exit price, or the last close while open', align: 'right', value: (r) => r.last_price, cell: (r) => <Price v={r.last_price} /> },
  { id: 'why', header: 'Exit', value: (r) => r.exit_reason ?? r.note ?? '', cell: (r) => <span className="block max-w-[200px] truncate text-muted" title={r.exit_reason ?? r.note ?? undefined}>{r.state === 'closed' ? `${r.exit_reason} · ${date(r.exit_date, { year: false })}` : r.note ?? (r.state === 'open' ? 'still held' : '—')}</span> },
  { id: 'days', header: 'Days', title: 'Trading days held', align: 'right', value: (r) => r.days, cell: (r) => <span className="num text-muted">{r.state === 'open' || r.state === 'closed' ? r.days : '—'}</span>, hideBelow: 1240 },
  { id: 'pnl', header: 'P&L ₹', title: 'After all charges and slippage (open: if sold at the last close)', align: 'right', value: (r) => r.pnl, cell: (r) => (r.state === 'open' || r.state === 'closed' ? <Money v={r.pnl} signed color /> : <span className="text-faint">—</span>), mobile: 'value' },
  { id: 'ret', header: 'Return', align: 'right', value: (r) => r.ret_pct, cell: (r) => (r.state === 'open' || r.state === 'closed' ? <Pct v={r.ret_pct} dp={2} /> : <span className="text-faint">—</span>), mobile: 'change' },
]

function strategyCols(minClosed: number): Col<TrackStrategy>[] {
  return [
    { id: 'name', header: 'Strategy', value: (s) => s.name, sticky: true, minWidth: 200, mobile: 'primary', cell: (s) => <Link to={`/strategies/${s.key}`} className="font-semibold hover:underline">{s.name}</Link> },
    { id: 'status', header: 'Now', value: (s) => s.status, cell: (s) => (s.status ? <StatusBadge status={s.status} short /> : <span className="text-faint">not scanned</span>) },
    { id: 'n', header: 'Signals', align: 'right', value: (s) => s.live.signals, cell: (s) => <span className="num">{s.live.signals}</span> },
    { id: 'closed', header: 'Closed', align: 'right', value: (s) => s.live.closed, cell: (s) => <span className={cn('num', s.live.closed < minClosed && 'text-muted')}>{s.live.closed}</span>, mobile: 'secondary', label: 'Closed' },
    { id: 'win', header: 'Win %', title: 'Live closed signals (backtest in grey)', align: 'right', value: (s) => s.live.win_rate, cell: (s) => <span className="num"><Pct v={s.live.win_rate} signed={false} color={false} dp={0} /> <span className="text-faint">{s.backtest?.win_rate != null ? pct(s.backtest.win_rate, { signed: false, dp: 0 }) : ''}</span></span> },
    { id: 'exp', header: 'Avg signal', title: 'Average closed signal after costs, live (backtest in grey)', align: 'right', value: (s) => s.live.expectancy_pct, cell: (s) => <span className="num"><Pct v={s.live.expectancy_pct} dp={2} /> <span className="text-faint">{s.backtest?.expectancy_pct != null ? pct(s.backtest.expectancy_pct, { dp: 1 }) : ''}</span></span>, mobile: 'change' },
    { id: 'pf', header: 'PF', title: 'Profit factor, live (backtest in grey)', align: 'right', value: (s) => s.live.profit_factor, cell: (s) => <span className="num"><Ratio v={s.live.profit_factor} /> <span className="text-faint">{s.backtest?.profit_factor != null ? num(s.backtest.profit_factor, 2) : ''}</span></span>, hideBelow: 1100 },
    { id: 'real', header: 'Realised ₹', align: 'right', value: (s) => s.live.realised_pnl, cell: (s) => <Money v={s.live.realised_pnl} signed color /> },
    { id: 'open', header: 'Open ₹', title: 'Open signals, if sold at the last close', align: 'right', value: (s) => s.live.open_pnl, cell: (s) => <Money v={s.live.open_pnl} signed color />, mobile: 'value' },
    { id: 'verdict', header: 'Verdict', value: (s) => s.live.level, cell: (s) => <span title={s.live.verdict}><TonePill tone={LEVEL[s.live.level]}>{s.live.level === 'unknown' ? 'Too early' : s.live.level === 'good' ? 'Making money' : 'Losing money'}</TonePill></span> },
  ]
}

export default function SignalTrack() {
  const [sp, setSp] = useSearchParams()
  const strategy = sp.get('strategy') ?? undefined
  const state = (sp.get('state') as TrackState | null) ?? undefined
  const q = useTrackRecord({ strategy, state })
  const d = q.data
  const set = (k: string, v?: string) => setSp((p) => { const n = new URLSearchParams(p); if (v) n.set(k, v); else n.delete(k); return n }, { replace: true })
  const o = d?.overall
  const picked = d?.strategies.find((s) => s.key === strategy)

  return (
    <div>
      <Link to="/signals" className="link mb-2 inline-flex items-center gap-1 text-xs"><ChevronLeft className="h-3.5 w-3.5" />Signals</Link>
      <PageHeader
        title="Signal track record"
        subtitle={<>Every buy signal the scanner gave, followed on real prices by the strategy's own rules, after all charges{d?.as_of ? <> · prices to <span className="num">{date(d.as_of, { year: false })}</span></> : ''}</>}
      />
      {q.error && !d ? <div className="card"><ErrorState error={q.error} onRetry={() => void q.refetch()} /></div> : !d || !o ? <div className="card"><SkeletonRows rows={6} /></div> : (
        <div className="space-y-3">
          {q.error && <RefreshFailed error={q.error} onRetry={() => void q.refetch()} />}
          <div className={cn('rounded-lg border px-4 py-3 text-[13px]', o.level === 'good' ? 'border-profit/35 bg-profit/[0.07]' : o.level === 'bad' ? 'border-loss/35 bg-loss/[0.07]' : 'border-line bg-panel')}>
            <span className="font-semibold text-fg">{o.verdict}</span>{' '}
            <span className="text-muted">Each signal: entry at the next official open plus slippage; exit at the stop, target or trailing stop, or at the next open after the strategy sells it. A record needs at least {d.min_closed} closed signals before it means much.</span>
          </div>
          <KpiStrip min={140}>
            <KpiTile label="Signals" value={o.signals} sub={`${o.open} open · ${o.closed} closed${o.pending ? ` · ${o.pending} pending` : ''}`} />
            <KpiTile label="Win rate" value={o.win_rate == null ? '—' : pct(o.win_rate, { signed: false, dp: 0 })} sub="closed signals" />
            <KpiTile label="Avg closed signal" value={o.expectancy_pct == null ? '—' : pct(o.expectancy_pct, { dp: 2 })} tone={o.expectancy_pct == null ? undefined : o.expectancy_pct > 0 ? 'text-profit' : 'text-loss'} sub="after costs" />
            <KpiTile label="Avg win / loss" value={o.avg_win_pct == null && o.avg_loss_pct == null ? '—' : `${o.avg_win_pct == null ? '—' : pct(o.avg_win_pct, { dp: 1 })} / ${o.avg_loss_pct == null ? '—' : pct(o.avg_loss_pct, { dp: 1 })}`} />
            <KpiTile label="Realised P&L" value={<Money v={o.realised_pnl} signed color />} sub="closed signals" />
            <KpiTile label="Open P&L" value={<Money v={o.open_pnl} signed color />} sub="if sold at the last close" />
          </KpiStrip>

          <Card title="By strategy" subtitle="Live record of each strategy's signals; the same strategy's backtest trades in grey for comparison" flush>
            <DataTable id="track.strategies" data={d.strategies} columns={strategyCols(d.min_closed)} rowKey={(s) => s.key}
              onRowClick={(s) => set('strategy', s.key === strategy ? undefined : s.key)} rowClassName={(s) => cn(s.key === strategy && 'bg-accent/[0.06]')}
              empty={<EmptyState compact title="No signals journaled yet" icon={<History className="h-6 w-6" strokeWidth={1.5} />}>Every completed-day scan records its buy signals; they appear here from the next scan on.</EmptyState>} />
          </Card>

          <Card
            title={picked ? <>Signals · {picked.name} <button type="button" onClick={() => set('strategy')} className="link ml-2 text-xs font-normal">show all</button></> : 'Signals'}
            subtitle={picked ? picked.live.verdict : 'Newest first. Click a strategy above to see only its signals.'}
            flush
          >
            <div className="border-b border-line px-3">
              <Tabs<'all' | TrackState>
                size="sm"
                value={state ?? 'all'}
                onChange={(v) => set('state', v === 'all' ? undefined : v)}
                items={[{ id: 'all', label: 'All' }, { id: 'open', label: 'Open' }, { id: 'closed', label: 'Closed' }, { id: 'pending', label: 'Pending' }, { id: 'not_filled', label: 'Not filled' }]}
              />
            </div>
            <DataTable id="track.signals" data={d.signals} columns={SIGNAL_COLS} rowKey={(r) => `${r.strategy_key}${r.signal_date}${r.symbol}`} pageSize={50} exportName="signal-track-record"
              empty={<EmptyState compact title={d.total ? 'No signals match these filters' : 'No signals journaled yet'} />} />
          </Card>
        </div>
      )}
    </div>
  )
}
