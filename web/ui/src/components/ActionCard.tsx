// The one answer for a stock: BUY · SELL (exit) · HOLD · NO EDGE (web/api/services/action_svc.py), with the strategy
// behind it, its tested record, the live price, and the risk facts that never change the answer.

import { useState } from 'react'
import { Link } from 'react-router-dom'
import { AlertTriangle, ArrowDownRight, ArrowUpRight, CircleSlash, ShieldCheck } from 'lucide-react'
import { useAction, type ActionCardData, type ActionOrder, type ActionState } from '@/api/action'
import { useLiveQuotes } from '@/api/hooks'
import { PriceStamp } from '@/components/LivePrice'
import { OrderTicket } from '@/components/OrderTicket'
import { Button } from '@/components/ui'
import type { Ticket } from '@/api/orders'
import { Money, Pct, Price } from '@/components/num'
import { Skeleton } from '@/components/feedback'
import { cn } from '@/lib/csv'
import { num, pct, qty } from '@/lib/format'

export const ACTION_STYLE: Record<ActionState, { label: string; cls: string; badge: string; icon: typeof ArrowUpRight }> = {
  BUY: { label: 'BUY', cls: 'border-profit/50 bg-profit/[0.06]', badge: 'bg-profit text-white', icon: ArrowUpRight },
  SELL: { label: 'SELL', cls: 'border-loss/50 bg-loss/[0.06]', badge: 'bg-loss text-white', icon: ArrowDownRight },
  HOLD: { label: 'HOLD', cls: 'border-accent/40 bg-accent/[0.05]', badge: 'bg-accent-strong text-white', icon: ShieldCheck },
  NO_EDGE: { label: 'NO EDGE', cls: 'border-line', badge: 'bg-raised text-muted border border-line-strong', icon: CircleSlash },
}

export function ActionBadge({ state, small }: { state: ActionState; small?: boolean }) {
  const s = ACTION_STYLE[state]
  const Icon = s.icon
  return (
    <span className={cn('inline-flex shrink-0 items-center gap-1 rounded-md font-bold tracking-wide', small ? 'h-5 px-1.5 text-[11px]' : 'h-8 px-2.5 text-sm', s.badge)}>
      <Icon className={small ? 'h-3 w-3' : 'h-4 w-4'} strokeWidth={2.5} />{s.label}
    </span>
  )
}

function Evidence({ o }: { o: ActionOrder }) {
  const range = o.timing_low_pct != null && o.timing_high_pct != null ? ` (range ${pct(o.timing_low_pct)} to ${pct(o.timing_high_pct)})` : ''
  return (
    <div className="text-xs text-muted">
      <Link to={`/strategies/${o.strategy_key}`} className="font-medium text-fg hover:underline">{o.strategy_name}</Link>
      {' · '}backtest {o.cagr_pct != null ? <span className="num text-fg">{pct(o.cagr_pct)}/yr</span> : '—'} after costs{range}
      {o.max_dd_pct != null && <> · worst drop <span className="num">{pct(o.max_dd_pct)}</span></>}
      {o.trades ? <> · {o.trades.toLocaleString('en-IN')} trades</> : null}
      {' · '}live record: <span className={o.live_level === 'good' ? 'text-profit' : o.live_level === 'bad' ? 'text-loss' : ''}>{o.live_verdict}</span>
    </div>
  )
}

function OrderLine({ o, live }: { o: ActionOrder; live?: number | null }) {
  return (
    <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-[13px] sm:grid-cols-4">
      <div><div className="text-2xs text-faint">{o.action === 'BUY' ? 'Entry (next open)' : 'Exit (next open)'}</div><span className="num">≈ <Price v={live ?? o.price} /></span></div>
      <div><div className="text-2xs text-faint">Quantity</div><span className="num">{o.qty != null ? qty(o.qty) : '—'}</span>{o.amount != null && <span className="text-2xs text-muted"> · <Money v={o.amount} compact /></span>}</div>
      {o.action === 'BUY' && <div><div className="text-2xs text-faint">Stop-loss</div><span className="num text-loss"><Price v={o.stop} /></span>{o.stop_distance_pct != null && <span className="text-2xs text-muted"> ({pct(o.stop_distance_pct)})</span>}</div>}
      {o.action === 'BUY' && <div><div className="text-2xs text-faint">Risk if stopped</div><Money v={o.risk_amount} /></div>}
    </div>
  )
}

export function ActionCardView({ a, compact }: { a: ActionCardData; compact?: boolean }) {
  const lq = useLiveQuotes([a.symbol])
  const q = lq.quotes[a.symbol]
  const s = ACTION_STYLE[a.state]
  const p = a.primary
  const [ticket, setTicket] = useState<Ticket | null>(null)
  const price = q?.price ?? p?.price ?? a.holding?.price ?? null
  const open = (side: 'BUY' | 'SELL') => setTicket({
    symbol: a.symbol, side, type: 'LIMIT', product: 'CNC',
    qty: Math.max(1, side === 'SELL' ? Math.floor(a.holding?.qty ?? p?.qty ?? 1) : (p?.qty ?? 1)),
    limit_price: price != null ? Math.round(price * 100) / 100 : null,
    stop: side === 'BUY' ? (p?.stop ?? null) : null, target: a.holding?.target_price ?? null,
    ref_price: p?.price ?? price, strategy_key: p?.strategy_key ?? null, source: 'action_card',
  })
  return (
    <div className={cn('rounded-lg border p-3', s.cls)} data-testid="action-card" data-state={a.state}>
      <div className="flex flex-wrap items-center gap-2">
        <ActionBadge state={a.state} />
        {compact && <Link to={`/chart/${a.symbol}`} className="text-[15px] font-semibold hover:underline">{a.symbol}</Link>}
        <span className="min-w-0 flex-1 text-[13px] font-medium">{a.headline}</span>
        <span className="flex items-baseline gap-1.5 text-[13px]">
          <span className="num font-semibold">{num(q?.price ?? a.holding?.price ?? p?.price ?? null, 2)}</span>
          {q && <Pct v={q.change_pct} dp={2} />}
          <PriceStamp q={q} session={lq.data?.session} fallbackDate={a.as_of.data_date} />
        </span>
        {a.state === 'BUY' && <Button size="sm" variant="primary" onClick={() => open('BUY')}>Buy on FYERS…</Button>}
        {a.state === 'SELL' && <Button size="sm" onClick={() => open('SELL')} className="border-loss/50 text-loss">Sell on FYERS…</Button>}
        {a.state === 'HOLD' && <Button size="sm" variant="ghost" onClick={() => open('SELL')}>Sell…</Button>}
      </div>
      {ticket && <OrderTicket open onClose={() => setTicket(null)} initial={ticket} />}
      {p && (a.state === 'BUY' || a.state === 'SELL') && (
        <div className="mt-2 space-y-1.5">
          <OrderLine o={p} live={q?.price} />
          {p.late_lag != null && <div className="text-xs text-muted"><span className="font-medium text-fg">Late entry, tested:</span> {p.reason}</div>}
          <Evidence o={p} />
          {p.below_min_position && <div className="text-2xs text-warn">Below the minimum position size in config.yaml: costs eat a larger share.</div>}
        </div>
      )}
      {p && a.state === 'HOLD' && <div className="mt-1.5"><Evidence o={p} /></div>}
      {a.holding && (
        <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted">
          <span>You hold <span className="num text-fg">{qty(a.holding.qty)}</span> @ <Price v={a.holding.buy_price} /></span>
          <span>P&amp;L <Pct v={q && a.holding.buy_price ? (q.price / a.holding.buy_price - 1) * 100 : a.holding.pnl_pct} /></span>
          {a.holding.stop_price != null && <span>stop <span className="num text-loss">{num(a.holding.stop_price)}</span></span>}
          {a.holding.target_price != null && <span>target <span className="num text-profit">{num(a.holding.target_price)}</span></span>}
        </div>
      )}
      {!compact && a.others.length > 0 && (
        <div className="mt-2 space-y-1">{a.others.map((o) => <Evidence key={o.strategy_key} o={o} />)}</div>
      )}
      {!compact && a.near.length > 0 && (
        <ul className="mt-2 list-disc space-y-0.5 pl-4 text-xs text-muted">{a.near.map((n) => <li key={n}>{n}</li>)}</ul>
      )}
      {!compact && a.unproven.length > 0 && (
        <div className="mt-2 text-xs text-faint">
          Unproven buy: {a.unproven.map((u) => `${u.strategy_name} (backtest ${u.status === 'mixed' ? 'mixed' : 'too new'})`).join(', ')}: shown for comparison, never the answer.
        </div>
      )}
      {!compact && a.exits.length > 0 && a.state !== 'SELL' && (
        <div className="mt-1 text-xs text-faint">Model exit (you don't hold it): {a.exits.map((e) => e.strategy_name).join(', ')}.</div>
      )}
      {a.risks.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {a.risks.map((r) => (
            <span key={r.kind} title={r.text} className={cn('inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-2xs', r.kind === 'provisional' ? 'bg-raised text-muted' : 'tint-warn text-warn')}>
              <AlertTriangle className="h-3 w-3" />{r.text}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}

/** The action card for one symbol (Chart page). */
export function ActionPanel({ symbol }: { symbol: string }) {
  const q = useAction(symbol)
  if (q.error) return null                                    // no scan yet: the page shows its own empty state
  if (!q.data || q.data.symbol !== symbol) return <Skeleton className="h-16 w-full" />
  return <ActionCardView a={q.data} />
}
