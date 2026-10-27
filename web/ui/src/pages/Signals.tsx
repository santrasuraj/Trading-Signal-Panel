// Signals `/signals` (spec 3.4): orders for the next open by horizon, sized to capital/allocations, stops, risk,
// results warnings; allocation bar with a session-only what-if; comparison-only groups collapsed. The Intraday tab
// shows today's live signals, only from intraday strategies whose backtest shows a real edge after costs. BUY signals
// carry a strength score (strongest first in their own card); the track record of past signals is /signals/track.

import { useEffect, useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { ChevronDown, History, Info, ShieldCheck, SlidersHorizontal, Undo2 } from 'lucide-react'
import { useIntradaySignals, useLiveQuotes, useSignals } from '@/api/hooks'
import { isFailure } from '@/api/client'
import type { Horizon, IntradaySignal, Quote, SignalGroup, SignalsResponse } from '@/api/types'
import { DataTable, type Col } from '@/components/DataTable'
import { EvidenceChip, EtfChip, HorizonChip, StatusBadge, WarnChip } from '@/components/badges'
import { BiasNote, OrdersTable, PageHeader, flatteredNote } from '@/components/domain'
import { Banner, EmptyState, ErrorState, RefreshFailed, Skeleton, SkeletonRows } from '@/components/feedback'
import { Money, Pct, Price } from '@/components/num'
import { Button, Card, Popover, Tabs } from '@/components/ui'
import { cn } from '@/lib/csv'
import { date, dateTimeIST, keepDatesTogether, money, num, pct, qty } from '@/lib/format'
import { allocationTotal, formatAllocations, parseAllocations } from '@/lib/sizing'
import { HORIZON, lostMoney } from '@/lib/vocab'

const SEG_COLORS = ['bg-accent', 'bg-violet', 'bg-info', 'bg-warn', 'bg-profit', 'bg-muted']

function AllocationBar({ d, onWhatIf }: { d: SignalsResponse; onWhatIf: React.ReactNode }) {
  const total = d.allocations.reduce((s, a) => s + a.pct, 0)
  const scale = Math.max(total, 100)               // over 100% the bar shows the parts of the total, nothing clipped
  const names = Object.fromEntries(d.groups.map((g) => [g.strategy.key, g.strategy.name] as const))
  return (
    <Card flush>
      <div className="flex flex-wrap items-center gap-3 px-4 py-3">
        <span className="eyebrow w-[86px] shrink-0">Allocation</span>
        <div className="min-w-[240px] flex-1">
          {d.allocations.length === 0 ? (
            <div className="flex min-h-6 items-center rounded-md border border-dashed border-line-strong px-2.5 py-0.5 text-xs text-muted">
              No allocations: every strategy is sized on the full {money(d.capital)}
            </div>
          ) : (
            <div className="flex h-6 overflow-hidden rounded-md bg-raised">
              {d.allocations.map((a, i) => (
                <div key={a.strategy_key} className={cn('flex min-w-0 items-center px-2 text-2xs font-medium text-white', SEG_COLORS[i % SEG_COLORS.length], i > 0 && 'border-l border-panel/60')} style={{ width: `${(a.pct / scale) * 100}%` }} title={`${names[a.strategy_key] ?? a.strategy_key}: ${pct(a.pct, { signed: false, dp: 0 })} = ${money(a.capital)}`}>
                  <span className="truncate">{names[a.strategy_key] ?? a.strategy_key} {num(a.pct, 0)}%</span>
                </div>
              ))}
              {total < 100 && <div className="flex flex-1 items-center px-2 text-2xs text-muted">cash {num(100 - total, 0)}%</div>}
            </div>
          )}
        </div>
        <div className="flex items-center gap-2">
          {onWhatIf}
          <Link to="/settings/capital" className="link text-xs">Edit</Link>
        </div>
      </div>
      {(d.allocation_warning || d.allocation_source === 'query') && (
        <div className="border-t border-line px-4 py-2 text-xs">
          {d.allocation_source === 'query' && <span className="mr-2 font-medium text-accent">What-if (this session only).</span>}
          {d.allocation_warning && <span className="text-warn">{d.allocation_warning}</span>}
        </div>
      )}
    </Card>
  )
}

/** `base` = the allocations the server sized with (config.yaml when there is no what-if), so sliders start there. */
function WhatIf({ groups, base, value, onChange }: { groups: SignalGroup[]; base: Record<string, number>; value: Record<string, number>; onChange: (v: Record<string, number>) => void }) {
  const keys = groups.filter((g) => !g.strategy.comparison_only).map((g) => g.strategy)
  const shown = { ...base, ...value }
  const total = allocationTotal(shown)
  return (
    <Popover
      align="right"
      width={360}
      trigger={({ toggle, open }) => (
        <Button size="sm" variant={Object.keys(value).length ? 'primary' : 'secondary'} icon={<SlidersHorizontal className="h-3.5 w-3.5" />} onClick={toggle} aria-expanded={open}>
          What-if
        </Button>
      )}
    >
      <div className="p-3">
        <div className="mb-2 flex items-center justify-between">
          <span className="text-[13px] font-semibold">What-if allocation</span>
          <span className={cn('num text-xs', total > 100 ? 'text-loss' : 'text-muted')}>{num(total, 0)}% of capital</span>
        </div>
        <p className="mb-3 text-2xs text-muted">Split your capital between strategies for this session only. Saved allocations live in Settings › Capital.</p>
        <div className="max-h-[300px] space-y-2.5 overflow-auto pr-1">
          {keys.map((s) => (
            <label key={s.key} className="block">
              <div className="mb-1 flex justify-between text-xs"><span className="truncate">{s.name}</span><span className="num text-muted">{num(shown[s.key] ?? 0, 0)}%</span></div>
              <input type="range" min={0} max={100} step={5} value={shown[s.key] ?? 0} onChange={(e) => onChange({ ...shown, [s.key]: Number(e.target.value) })} className="w-full accent-[rgb(var(--accent))]" />
            </label>
          ))}
        </div>
        <div className="mt-3 flex justify-end">
          <Button size="sm" variant="ghost" icon={<Undo2 className="h-3.5 w-3.5" />} onClick={() => onChange({})}>Reset to saved</Button>
        </div>
      </div>
    </Popover>
  )
}

function Group({ g, cmp, live }: { g: SignalGroup; cmp?: boolean; live?: Record<string, Quote> }) {
  const s = g.strategy
  return (
    <Card
      className={cn(cmp && 'opacity-70')}
      flush
      title={
        <span className="flex flex-wrap items-center gap-2">
          <Link to={`/strategies/${s.key}`} className="hover:underline">{s.name}</Link>
          <StatusBadge status={s.status} lost={lostMoney(s.headline)} />
          <HorizonChip horizon={s.horizon} />
          <EvidenceChip evidence={s.evidence} />
          {flatteredNote(s) && <WarnChip title={flatteredNote(s) ?? undefined}>Flattered</WarnChip>}
          {s.universe === 'etfs' && <EtfChip />}
        </span>
      }
      subtitle={
        <span className="num">
          up to {g.sizing.max_positions} × {money(g.sizing.per_position)} on {money(g.sizing.capital)}
          {g.sizing.sizing === 'risk' && g.sizing.risk_pct != null && ` · risk ${pct(g.sizing.risk_pct, { signed: false })} per trade`}
          {s.next_rebalance && <> · next review <span className="whitespace-nowrap">{date(s.next_rebalance, { year: false })}</span></>}
          {` · holding ${s.positions}`}
        </span>
      }
    >
      {g.orders.length ? <OrdersTable id={`sig.${s.key}`} orders={g.orders} live={live} /> : <div className="px-4 py-3 text-[13px] text-muted">No orders. {g.empty_reason ? keepDatesTogether(g.empty_reason) : null}</div>}
    </Card>
  )
}

const INTRA_COLS: Col<IntradaySignal>[] = [
  { id: 'sym', header: 'Symbol', value: (r) => r.symbol, cell: (r) => <Link to={`/chart/${r.symbol}`} className="font-semibold hover:underline">{r.symbol}</Link>, sticky: true, mobile: 'primary' },
  { id: 'st', header: 'Strategy', value: (r) => r.strategy_name, cell: (r) => <span className="block max-w-[180px] truncate">{r.strategy_name}</span> },
  { id: 'side', header: 'Side', value: (r) => r.side, cell: (r) => <span className={cn('text-2xs font-bold tracking-[0.04em]', r.side === 'LONG' ? 'text-profit' : 'text-loss')}>{r.side}</span> },
  { id: 'state', header: 'State', value: (r) => r.state, cell: (r) => <span className={cn('text-xs', r.state === 'open' ? 'font-semibold text-fg' : 'text-muted')}>{r.state === 'open' ? 'Open' : `Closed ${r.exit_time ?? ''} (${r.reason})`}</span>, mobile: 'secondary', label: 'State' },
  { id: 'in', header: 'In', value: (r) => r.entry_time, cell: (r) => <span className="num text-muted">{r.entry_time}</span> },
  { id: 'entry', header: 'Entry ₹', align: 'right', value: (r) => r.entry, cell: (r) => <Price v={r.entry} /> },
  { id: 'stop', header: 'Stop ₹', align: 'right', value: (r) => r.stop, cell: (r) => <Price v={r.stop} /> },
  { id: 'qty', header: 'Qty', align: 'right', value: (r) => r.qty, cell: (r) => <span className="num">{r.qty}</span> },
  { id: 'last', header: 'Last ₹', title: 'Exit price, or the latest bar while open', align: 'right', value: (r) => r.last, cell: (r) => <Price v={r.last} /> },
  { id: 'pnl', header: 'P&L ₹', title: 'After intraday charges and slippage (open: if closed at the last price)', align: 'right', value: (r) => r.pnl, cell: (r) => <Money v={r.pnl} signed color />, mobile: 'value' },
  { id: 'ret', header: 'Return', align: 'right', value: (r) => r.ret_pct, cell: (r) => <Pct v={r.ret_pct} dp={2} />, mobile: 'change' },
]

/** Today's live intraday signals (MIS, squared off the same day), only from strategies whose backtest passed. */
function IntradaySignals() {
  const q = useIntradaySignals()
  const d = q.data
  if (q.error && !d) return <div className="card"><ErrorState error={q.error} onRetry={() => void q.refetch()} /></div>
  if (!d) return <div className="card"><SkeletonRows rows={3} /></div>
  const bars = d.source ? `${d.source}${d.delayed ? ', ~15 min delayed' : ''}` : null
  return (
    <Card
      title={<span className="flex items-center gap-2"><ShieldCheck className="h-4 w-4 text-muted" />Intraday signals today</span>}
      subtitle={<>Only strategies whose backtest shows a real edge after costs: <span className="num">{d.proven.length} of {d.tested}</span>{d.proven.length > 0 && <> ({d.proven.map((p) => p.name).join(', ')})</>}{bars && <> · bars {bars}</>}{d.generated_at && <> · updated <span className="num">{dateTimeIST(d.generated_at)}</span></>}</>}
      flush
    >
      {d.signals.length === 0 ? (
        <EmptyState compact title={d.note}>
          <Link to="/intraday" className="link">See each intraday strategy's backtest</Link>
        </EmptyState>
      ) : (
        <>
          <DataTable id="signals.intraday" data={d.signals} columns={INTRA_COLS} rowKey={(r) => `${r.strategy_key}${r.symbol}${r.entry_time}`} exportName="intraday-signals" />
          <p className="border-t border-line px-4 py-2 text-2xs text-faint">{d.note} Intraday positions are squared off the same day (15:00 for F&O stocks). You decide and place every trade yourself.</p>
        </>
      )}
    </Card>
  )
}

export default function Signals() {
  const [sp, setSp] = useSearchParams()
  const horizon = (sp.get('horizon') as Horizon | null) ?? 'all'
  const allocParam = sp.get('allocations') ?? ''
  const [draft, setDraft] = useState<Record<string, number>>(() => parseAllocations(allocParam))
  useEffect(() => {
    const t = setTimeout(() => {
      const s = formatAllocations(draft)
      if (s !== allocParam) setSp((p) => { const n = new URLSearchParams(p); if (s) n.set('allocations', s); else n.delete('allocations'); return n }, { replace: true })
    }, 250)
    return () => clearTimeout(t)
  }, [draft, allocParam, setSp])

  const q = useSignals({ allocations: allocParam || undefined })
  const intra = useIntradaySignals().data
  const intraday = horizon === 'intraday'
  // a stale or mistyped ?allocations= (e.g. a strategy key that no longer exists) must not lock the page
  const resetWhatIf = () => { setDraft({}); setSp((p) => { const n = new URLSearchParams(p); n.delete('allocations'); return n }, { replace: true }) }
  const d = q.data
  const groups = useMemo(() => (d ? d.groups.filter((g) => horizon === 'all' || g.strategy.horizon === horizon) : []), [d, horizon])
  const main = groups.filter((g) => !g.strategy.comparison_only)
  const cmp = groups.filter((g) => g.strategy.comparison_only)
  const lq = useLiveQuotes(main.flatMap((g) => g.orders.map((o) => o.symbol)))
  const live = lq.live ? lq.quotes : undefined
  const ranked = main.flatMap((g) => g.orders).filter((o) => o.action === 'BUY' && o.strength)
    .sort((a, b) => (b.strength?.score ?? 0) - (a.strength?.score ?? 0))
  const [showCmp, setShowCmp] = useState(false)
  const count = (h: Horizon) => (d ? d.groups.filter((g) => g.strategy.horizon === h && !g.strategy.comparison_only).reduce((n, g) => n + g.orders.length, 0) : 0)
  const totals = useMemo(() => {
    let buy = 0, buyAmt = 0, sell = 0, sellAmt = 0, risk = 0, warn = 0, noStop = 0
    let sellUnknown = false                          // a SELL with no size (no holding, no model weight): total is a floor
    const soldHolding = new Set<string>()            // two strategies selling a stock you hold: your holding counts once
    for (const g of main) for (const o of g.orders) {
      if (o.action === 'BUY') {
        buy++; buyAmt += o.amount ?? 0; risk += o.risk_amount ?? 0
        if (o.risk_amount == null) noStop++
      } else {
        sell++
        const dup = o.qty_basis === 'your_holding' && soldHolding.has(o.symbol)
        if (o.qty_basis === 'your_holding') soldHolding.add(o.symbol)
        if (!dup) { if (o.amount == null) sellUnknown = true; else sellAmt += o.amount }
      }
      if (o.results_warning) warn++
    }
    return { buy, buyAmt, sell, sellAmt, sellUnknown, risk, noStop, warn }
  }, [main])
  const savedAlloc = useMemo<Record<string, number>>(() => Object.fromEntries((d?.allocations ?? []).map((a) => [a.strategy_key, a.pct] as const)), [d])

  return (
    <div>
      <PageHeader
        title="Signals"
        right={<Link to="/signals/track" className="focus-ring inline-flex h-8 items-center gap-1.5 rounded-md border border-line px-3 text-[13px] font-medium hover:bg-raised"><History className="h-4 w-4" />Track record</Link>}
        subtitle={d ? <>Orders for the next market open · sized for {money(d.capital)} · based on prices of <span className="whitespace-nowrap">{date(d.as_of.data_date, { year: false })}</span> ({d.as_of.stale ? <span className="text-warn">stale</span> : d.as_of.live ? <span className="text-warn">live candle, provisional</span> : 'official close'})</> : <Skeleton className="h-3 w-72" />}
      />
      {q.error && !d && allocParam && isFailure(q.error) && q.error.code === 'VALIDATION' ? (
        <div className="card p-4">
          <Banner tone="warn" action={<Button size="sm" icon={<Undo2 className="h-3.5 w-3.5" />} onClick={resetWhatIf}>Reset what-if</Button>}>
            <span className="font-medium">This what-if allocation can't be used:</span> <span className="text-muted">{q.error.message}</span>
          </Banner>
        </div>
      ) : q.error && !d ? (
        <div className="card"><ErrorState error={q.error} onRetry={() => void q.refetch()} /></div>
      ) : !d ? (
        <div className="space-y-3"><Skeleton className="h-14" /><div className="card"><SkeletonRows rows={5} /></div></div>
      ) : (
        <div className="space-y-3">
          {q.error && <RefreshFailed error={q.error} onRetry={() => void q.refetch()} />}
          <AllocationBar d={d} onWhatIf={<WhatIf groups={d.groups} base={savedAlloc} value={draft} onChange={setDraft} />} />
          {!d.regime.regime_up && d.regime.note && (
            <Banner tone="info" icon={<Info className="h-4 w-4 text-info" />}>{d.regime.note}</Banner>
          )}
          <div className="border-b border-line">
            <Tabs<'all' | Horizon>
              value={horizon}
              onChange={(h) => setSp((p) => { const n = new URLSearchParams(p); if (h === 'all') n.delete('horizon'); else n.set('horizon', h); return n })}
              items={[
                { id: 'all', label: 'All', count: count('longterm') + count('swing') },
                { id: 'longterm', label: HORIZON.longterm.label, count: count('longterm') },
                { id: 'swing', label: HORIZON.swing.label, count: count('swing') },
                { id: 'intraday', label: <span title="Same-day signals, only from intraday strategies whose backtest shows a real edge after costs">Intraday</span>, count: intra?.signals.length ?? 0 },
              ]}
            />
          </div>
          {intraday && <IntradaySignals />}
          {!intraday && ranked.length > 1 && (
            <Card title="Strongest buy signals" subtitle="Every buy signal today, strongest first. Hover a score for its parts: evidence, backtest, agreement between strategies, live record, results day." flush>
              <OrdersTable id="signals.ranked" orders={ranked} showStrategy live={live} />
            </Card>
          )}
          {!intraday && main.length === 0 && <div className="card px-4 py-6 text-center text-[13px] text-muted">No active strategies in this horizon.</div>}
          {!intraday && lq.data && main.some((g) => g.orders.length) && (
            <p className="px-1 text-2xs text-muted">
              <span className={cn('mr-1.5 inline-block h-1.5 w-1.5 rounded-full align-middle', lq.data.delayed ? 'bg-warn' : 'bg-profit')} />
              {lq.data.note} Updated <span className="num">{dateTimeIST(lq.data.as_of)}</span>.
              {d.as_of.live ? ' Signals are from the latest live scan (provisional until the close).' : ' Signals are from the last close; the live scan in market hours re-checks them every 30 minutes.'}
            </p>
          )}
          {main.map((g) => <Group key={g.strategy.key} g={g} live={live} />)}

          {!intraday && <div className="card num flex flex-wrap items-center gap-x-6 gap-y-1 px-4 py-3 text-[13px]">
            <span className="eyebrow">Totals</span>
            <span><span className="text-muted">Buys </span>{totals.buy} · <Money v={totals.buyAmt} /></span>
            <span><span className="text-muted">Sells </span>{totals.sell}{totals.sell > 0 && <> · {totals.sellUnknown ? <span className="text-faint" title="Some sells cannot be sized (you don't hold them and the model weight is unknown)">≥ <Money v={totals.sellAmt} /></span> : <Money v={totals.sellAmt} />}</>}</span>
            <span><span className="text-muted">Risk at stops </span><Money v={totals.risk} />{totals.noStop > 0 && <span className="text-faint" title="BUY orders without a stop are not in this total"> (+{totals.noStop} with no stop)</span>}</span>
            <span className={cn(totals.warn > 0 && 'text-warn')}><span className="text-muted">Results warnings </span>{qty(totals.warn)}</span>
            {d.sized_like_scan && <span className="ml-auto text-2xs text-faint">Same sizes as the scan (and Telegram)</span>}
          </div>}

          {cmp.length > 0 && (
            <div>
              <button type="button" onClick={() => setShowCmp(!showCmp)} className="focus-ring flex items-center gap-2 rounded px-1 py-1.5 text-[13px] text-muted hover:text-fg">
                <ChevronDown className={cn('h-4 w-4 transition-transform', !showCmp && '-rotate-90')} />
                {(() => {
                  const n = cmp.reduce((a, g) => a + g.orders.length, 0)
                  const who = `${cmp.length} strateg${cmp.length > 1 ? 'ies' : 'y'} that ${cmp.length > 1 ? 'are' : 'is'} not working`
                  return n ? `${n} order${n > 1 ? 's' : ''} from ${who} (comparison only, not in totals)` : `${who}: no orders (comparison only)`
                })()}
              </button>
              {showCmp && <div className="mt-2 space-y-3">{cmp.map((g) => <Group key={g.strategy.key} g={g} cmp />)}</div>}
            </div>
          )}
          <BiasNote asOf={d.as_of} />
          <p className="text-2xs text-faint">Orders are what each model portfolio would do at the next open. You decide and place every trade yourself; "Copy" puts a ready-to-type order on the clipboard and the link opens Fyers web.</p>
        </div>
      )}
    </div>
  )
}
