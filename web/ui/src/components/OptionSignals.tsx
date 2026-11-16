// Signals page > Options: the app's intraday and stock signals as option trades, volatility (IV rank) trades and the
// index verdicts (scanner/option_signals.py, web/api/services/optsig_svc.py). Each row is a concrete trade - contract,
// entry premium, stop and target in premium, lot, capital, maximum loss - labelled with its strategy's backtest and its
// source's own record; the volatility source shows its backtest on NIFTY / BANKNIFTY. Practice only.

import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Info, Layers, RefreshCw } from 'lucide-react'
import { useOptionSignals, useRefreshOptionSignals, useVolTest, type OptPnlParts, type OptRecord, type OptSignal, type OptSignalsView, type OptSource } from '@/api/optionSignals'
import type { SignalProof } from '@/api/types'
import { ProofBadge } from '@/components/badges'
import { DataTable, type Col } from '@/components/DataTable'
import { Banner, EmptyState, ErrorState, SkeletonRows } from '@/components/feedback'
import { IndexOptions } from '@/components/IndexOptions'
import { Money } from '@/components/num'
import { Button, Card, Segmented } from '@/components/ui'
import { cn } from '@/lib/csv'

const SRC: Record<OptSource, string> = { intraday: 'From intraday', stock: 'From stock strategies', volatility: 'Volatility (IV rank)', index: 'Index verdicts' }
const rs = (v: number | null | undefined, nd = 2) => (v == null ? '—' : v.toLocaleString('en-IN', { maximumFractionDigits: nd, minimumFractionDigits: nd }))
const day = (iso: string) => { const d = new Date(`${iso}T00:00:00Z`); return `${d.getUTCDate()} ${d.toLocaleString('en-IN', { month: 'short', timeZone: 'UTC' })}` }
const contract = (r: OptSignal) => r.legs.map((l) => `${r.legs.length > 1 ? (l.action === 'buy' ? '+' : '−') : ''}${l.strike.toLocaleString('en-IN')} ${l.type}`).join(' ') + ` · ${day(r.expiry)}`
const PROOF = new Set(['working', 'mixed', 'unknown', 'not-working', 'untested'])

const COLS: Col<OptSignal>[] = [
  { id: 'sym', header: 'Underlying', value: (r) => r.symbol, sticky: true, mobile: 'primary', cell: (r) => <Link to={`/options/${r.symbol}`} className="font-semibold hover:underline">{r.symbol}</Link> },
  { id: 'src', header: 'From', value: (r) => `${SRC[r.source]} ${r.strategy.name ?? ''}`, cell: (r) => (
    <span className="flex flex-col leading-tight"><span className="text-xs">{r.strategy.name ?? SRC[r.source]}</span><span className="text-2xs text-muted">{SRC[r.source]}{r.strategy.entry_time ? ` · ${r.strategy.entry_time}` : ''}</span></span>) },
  { id: 'proof', header: 'Evidence', title: "The strategy's own backtest on the shares. Untested = no history to test it on (past intraday OI and option prices are not stored): its live record below is its test. A strategy that lost money in its backtest never opens an option.", value: (r) => String(r.strategy.status), cell: (r) => <ProofBadge status={(PROOF.has(String(r.strategy.status)) ? r.strategy.status : 'untested') as SignalProof} /> },
  { id: 'trade', header: 'Trade', value: (r) => r.structure, mobile: 'secondary', cell: (r) => (
    <span className="flex flex-col leading-tight"><span className={cn('text-xs font-semibold', r.direction === 'LONG' ? 'text-profit' : r.direction === 'SHORT' ? 'text-loss' : 'text-fg')}>{r.structure}</span><span className="num text-2xs text-muted">{contract(r)}</span></span>) },
  { id: 'entry', header: 'Entry ₹', title: 'Premium per unit: paid (buys, at the ask) or collected (credit, sold at the bid)', align: 'right', value: (r) => r.entry, cell: (r) => <span className="num">{rs(r.entry)}{r.kind === 'credit' ? <span className="text-2xs text-muted"> cr</span> : null}</span> },
  { id: 'stop', header: 'Stop ₹', title: 'Premium at which it is closed at a loss (re-priced at the underlying stop; credit: cost to close)', align: 'right', value: (r) => r.stop, cell: (r) => <span className="num text-loss">{rs(r.stop)}</span> },
  { id: 'target', header: 'Target ₹', title: "Premium at the target (stock signals: the strategy's own exit decides)", align: 'right', value: (r) => r.target, cell: (r) => <span className="num text-profit">{r.target == null && r.source === 'stock' ? <span className="text-2xs text-muted">strategy exit</span> : rs(r.target)}</span> },
  { id: 'lot', header: 'Lot', align: 'right', value: (r) => r.lot, cell: (r) => <span className="num">{r.lot}</span> },
  { id: 'cap', header: 'Capital ₹', title: 'Premium paid plus charges (credit trades: the margin-like maximum risk)', align: 'right', value: (r) => r.capital, cell: (r) => <Money v={r.capital} /> },
  { id: 'loss', header: 'Max loss ₹', title: 'At the stop, after charges (debit with no stop: the whole premium)', align: 'right', value: (r) => r.max_loss, cell: (r) => <Money v={r.max_loss} /> },
  { id: 'now', header: 'Now ₹', title: 'Last mark (mid prices) and the open P&L', align: 'right', value: (r) => r.mark, cell: (r) => (
    <span className="flex flex-col items-end leading-tight"><span className="num">{rs(r.mark)}</span>{r.state === 'open' && r.unrealized != null && <Money v={r.unrealized} signed color className="text-2xs" />}</span>) },
  { id: 'state', header: 'State', value: (r) => (r.state === 'open' ? 'open' : r.exit_reason ?? 'closed'), cell: (r) => r.state === 'open'
    ? <span className="text-xs font-semibold">Open</span>
    : <span className="flex flex-col leading-tight"><span className="text-xs text-muted">{r.exit_reason}</span><Money v={r.pnl} signed color className="text-xs" /></span> },
]

const PARTS: [keyof OptPnlParts, string, string][] = [
  ['move', 'stock move', "What the stock's move from entry to exit was worth: the signal itself"],
  ['decay', 'time decay', 'Premium lost to time over the hold'],
  ['vol', 'volatility', 'The change in implied volatility (and what the pricing model misses)'],
  ['spread', 'spread', 'Paid crossing the bid-ask: bought at the ask, sold at the bid'],
  ['charges', 'charges', 'Brokerage, STT, exchange, SEBI, GST and stamp duty'],
]

/** Where a strategy's closed options made or lost their money. */
function Parts({ p, n, of }: { p: OptPnlParts; n: number; of: number }) {
  return (
    <div className="mt-0.5 flex flex-wrap gap-x-2 pl-1 text-muted" title={n < of ? `Breakdown of ${n} of ${of} closed trades (older ones did not store it)` : 'Where the P&L came from'}>
      {PARTS.map(([k, label, tip]) => <span key={k} title={tip}>{label} <Money v={p[k]} signed color /></span>)}
    </div>
  )
}

function Record({ rows }: { rows: OptRecord[] }) {
  return (
    <div className="grid gap-2 sm:grid-cols-3">
      {rows.map((r) => (
        <div key={r.source} className="rounded-lg border border-line px-3 py-2">
          <div className="text-xs font-semibold">{r.label}</div>
          <div className="mt-0.5 flex items-baseline justify-between gap-2"><Money v={r.pnl} signed color className="text-base font-semibold" /><span className="text-2xs text-muted">{r.trades} closed · {r.open} open</span></div>
          <div className="text-2xs text-muted">{r.trades ? `${r.win_rate?.toFixed(0)}% won · average ${r.avg_ret_pct != null ? `${r.avg_ret_pct > 0 ? '+' : ''}${r.avg_ret_pct.toFixed(1)}%` : '—'} on capital · ` : ''}{r.verdict}</div>
          {(r.by_strategy?.length ?? 0) > 0 && (
            <ul className="mt-1.5 space-y-0.5 border-t border-line pt-1.5">
              {r.by_strategy!.map((s) => (
                <li key={s.key} className="text-2xs">
                  <div className="flex items-center justify-between gap-2">
                    <span className="flex min-w-0 items-center gap-1.5"><ProofBadge status={(PROOF.has(String(s.status)) ? s.status : 'untested') as SignalProof} /><span className="truncate" title={s.name}>{s.name}</span></span>
                    <span className="whitespace-nowrap text-muted">{s.trades ? <>{s.wins}/{s.trades} won · <Money v={s.pnl} signed color /></> : 'no closed trade'}{s.open ? ` · ${s.open} open` : ''}</span>
                  </div>
                  {s.live?.paused && (
                    <div className="mt-0.5 pl-1 text-loss" title={`No new option from it while its options since ${day(s.live.since)} are clearly losing: trades leave this 30-day window as they age, and then it gets a new trial`}>
                      Paused: its last {s.live.trades} options netted <Money v={s.live.pnl} signed />{s.live.t != null ? ` (t ${s.live.t.toFixed(1)})` : ''}
                    </div>)}
                  {s.parts && <Parts p={s.parts} n={s.parts_n ?? 0} of={s.trades} />}
                </li>))}
            </ul>)}
        </div>))}
    </div>
  )
}

/** What the rules kept from becoming an option today, and why. */
function NotTaken({ d }: { d: OptSignalsView }) {
  const sk = Object.entries(d.skipped ?? {}).sort((a, b) => b[1].count - a[1].count)
  const rule = d.evidence?.rule === 'proven' ? 'only from strategies whose backtest beat costs' : d.evidence?.rule === 'all' ? 'from every strategy (research setting)' : "from every strategy except those that lost money in their backtest"
  return (
    <div className="border-b border-line px-4 py-2 text-2xs text-muted">
      <span className="font-medium text-fg">Rules: </span>an option opens {rule}{d.evidence?.rule === 'all' ? '' : `, not from a strategy whose own options keep losing (${d.rules.live_min_trades ?? 10}+ closed in ${d.rules.live_days ?? 30} days)`}, once per strategy, stock and direction a day, not while another option on that stock is open, and not after {d.rules.no_new_intraday ?? '14:30'}.
      {sk.length > 0 && <> <span className="font-medium text-fg">Not taken{d.skipped_day ? ` on ${day(d.skipped_day)}` : ''}: </span>
        {sk.map(([k, v], i) => <span key={k} title={v.examples.join(', ')}>{i ? ' · ' : ''}{v.count} {v.label}{v.examples.length ? ` (${v.examples.slice(0, 3).join(', ')}${v.count > 3 ? ', …' : ''})` : ''}</span>)}.</>}
      {(d.cancelled ?? 0) > 0 && <> {d.cancelled} trade{d.cancelled === 1 ? '' : 's'} opened before these rules {d.cancelled === 1 ? 'was' : 'were'} cancelled and left out of the record.</>}
    </div>
  )
}

function VolBacktest() {
  const q = useVolTest(true)
  const d = q.data
  if (!d) return q.error ? <ErrorState compact error={q.error} /> : <SkeletonRows rows={2} />
  const line = (label: string, s?: { trades: number; win_rate?: number; total?: number; max_drawdown?: number }) => (
    <div className="flex items-baseline justify-between gap-2 text-xs"><span className="text-muted">{label}</span>
      {s && s.trades ? <span className="num">{s.trades} trades · {s.win_rate?.toFixed(0)}% won · total <Money v={s.total ?? null} signed color /> · worst run <Money v={s.max_drawdown ?? null} /></span> : <span className="text-faint">no trade</span>}</div>)
  return (
    <div className="space-y-2">
      <div className="grid gap-2 sm:grid-cols-2">
        {d.tests.map((t) => (
          <div key={t.symbol} className="rounded-lg border border-line px-3 py-2">
            <div className="mb-1 text-xs font-semibold">{t.symbol} <span className="font-normal text-muted">{t.first ? `${t.first} to ${t.last}` : ''}</span></div>
            {t.error ? <p className="text-2xs text-loss">{t.error}</p> : <>{line('Only when IV is high', t.when_high)}{line('Every month', t.always)}<div className="text-2xs text-faint">{t.high_days} of {t.days_with_rank} days had a high IV rank</div></>}
          </div>))}
      </div>
      <p className="text-2xs text-muted">{d.note}</p>
    </div>
  )
}

export function OptionSignals() {
  const q = useOptionSignals()
  const refresh = useRefreshOptionSignals()
  const [src, setSrc] = useState<'all' | OptSource>('all')
  const d = q.data
  const rows = (d?.signals ?? []).filter((r) => src === 'all' || r.source === src)
  return (
    <div className="space-y-3">
      <Banner tone="info" icon={<Info className="h-4 w-4 text-info" />}><span className="text-muted">{d?.note ?? 'The app\'s signals as concrete option trades, labelled with their evidence. Practice only.'}</span></Banner>
      <Card title={<span className="flex items-center gap-1.5"><Layers className="h-4 w-4 text-muted" />Options signals</span>}
        subtitle={d ? `${d.market_open ? 'Live: an option opens seconds after its signal, and open ones are re-marked every minute on NSE\'s chains' : 'Market closed (live 09:15-15:30): the last session\'s signals'}${d.loop.last_run ? ` · last check ${d.loop.last_run.slice(11, 19)}` : ''}${d.loop.last_error ? ` · ${d.loop.last_error}` : ''}` : undefined}
        right={<>
          <Segmented<'all' | OptSource> ariaLabel="Source" size="xs" value={src} onChange={setSrc} items={[{ id: 'all', label: 'All' }, { id: 'intraday', label: 'Intraday' }, { id: 'stock', label: 'Stocks' }, { id: 'volatility', label: 'Volatility' }, { id: 'index', label: 'Index verdicts' }]} />
          <Button size="sm" variant="subtle" icon={<RefreshCw className="h-3.5 w-3.5" />} loading={refresh.isPending} disabled={!d?.market_open} title={d?.market_open ? 'Check NSE\'s chains now' : 'Market closed'} onClick={() => refresh.mutate()}>Check now</Button>
        </>} flush>
        {d && src !== 'index' && <NotTaken d={d} />}
        {src === 'index' ? <div className="p-3"><IndexOptions /></div>
          : q.error ? <ErrorState compact error={q.error} /> : !d ? <SkeletonRows rows={6} />
          : rows.length === 0 ? <EmptyState compact title={d.market_open ? 'No options signal yet today.' : 'No options signal in the last session.'}>
              They open from intraday signals on F&amp;O stocks, from the working stock strategies' BUYs, and when an F&amp;O underlying's IV rank is {d.rules.iv_high}+ (or {d.rules.iv_low} and under), during market hours.</EmptyState>
          : <DataTable id={`signals.options.${src}`} data={rows} columns={COLS} rowKey={(r) => r.id} exportName="options-signals" />}
      </Card>
      {d && src !== 'index' && (
        <Card title="Record so far (practice, after charges)" subtitle="Every options signal is journalled and closed on NSE's live chain, or at NSE's official close when the dashboard wasn't running">
          <Record rows={d.record.filter((r) => src === 'all' || r.source === src)} />
        </Card>)}
      {(src === 'all' || src === 'volatility') && (
        <Card title="Volatility source: its backtest" subtitle="Selling a monthly iron condor only when the IV rank is high, against selling one every month (NSE's daily option closes)">
          <VolBacktest />
        </Card>)}
    </div>
  )
}
