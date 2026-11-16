// Orders `/orders`: your own FYERS orders. Switch placement on or off, the kill switch, today's orders (cancel), positions
// and P&L, stop-loss / target protection for delivery holdings (FYERS GTT OCO), slippage against the signals, and the
// audit log of everything the app sent. Limits come from config.yaml `orders:` and are enforced on the server.

import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { OctagonX, Power, ShieldCheck } from 'lucide-react'
import { fetchJson, isFailure } from '@/api/client'
import { useOrderActions, useOrdersView } from '@/api/orders'
import { PageHeader } from '@/components/domain'
import { EmptyState, ErrorState, SkeletonRows } from '@/components/feedback'
import { Money, Pct } from '@/components/num'
import { useToast } from '@/components/toast'
import { Button, Card, Dialog } from '@/components/ui'
import { cn } from '@/lib/csv'
import { dateTimeIST, num } from '@/lib/format'

function ProtectRow({ symbol, qty, avg }: { symbol: string; qty: number; avg: number | null }) {
  const a = useOrderActions()
  const toast = useToast()
  const [stop, setStop] = useState(avg ? String(Math.round(avg * 0.92 * 20) / 20) : '')
  const [target, setTarget] = useState(avg ? String(Math.round(avg * 1.25 * 20) / 20) : '')
  const ok = Number(stop) > 0 && Number(target) > Number(stop)
  const [trailPct, setTrailPct] = useState('8')
  const trail = useQuery({ queryKey: ['trail', symbol, trailPct], queryFn: () => fetchJson<{ stop: number | null; note: string }>(`/api/trail/${encodeURIComponent(symbol)}?pct=${Number(trailPct) || 8}`), staleTime: 60_000, enabled: Number(trailPct) > 0 })
  return (
    <div className="flex flex-wrap items-center gap-2 border-b border-line/60 py-1.5 text-[13px]">
      <span className="w-28 font-semibold">{symbol}</span>
      <span className="text-muted">{qty} @ {num(avg, 2)}</span>
      <label className="text-2xs text-muted">Stop <input aria-label={`${symbol} stop-loss`} value={stop} onChange={(e) => setStop(e.target.value)} className="input num h-7 w-24 px-2 text-right text-[13px]" /></label>
      <label className="text-2xs text-muted">Target <input aria-label={`${symbol} target`} value={target} onChange={(e) => setTarget(e.target.value)} className="input num h-7 w-24 px-2 text-right text-[13px]" /></label>
      <Button size="sm" icon={<ShieldCheck className="h-3.5 w-3.5" />} disabled={!ok} loading={a.protect.isPending}
        onClick={() => {
          if (!window.confirm(`Place a FYERS GTT for ${qty} ${symbol}: sell if it falls to ${stop} or rises to ${target} (whichever comes first)?`)) return
          a.protect.mutate({ symbol, qty, stop: Number(stop), target: Number(target) }, {
            onSuccess: (r) => toast({ tone: r.ok ? 'good' : 'bad', title: r.ok ? `${symbol} protected (GTT ${r.id})` : `FYERS: ${r.message}` }),
            onError: (e) => toast({ tone: 'bad', title: 'Not placed', detail: isFailure(e) ? e.message : undefined }),
          })
        }}>Protect</Button>
      {trail.data?.stop != null && (
        <span className="flex items-center gap-1 text-2xs text-muted" title={trail.data.note}>
          Trailing stop <input aria-label={`${symbol} trailing %`} value={trailPct} onChange={(e) => setTrailPct(e.target.value)} className="input num h-6 w-10 px-1 text-right" />% →
          <button type="button" className="link" onClick={() => setStop(String(trail.data!.stop))}>use ₹{num(trail.data.stop, 2)}</button>
        </span>)}
    </div>
  )
}

export default function Orders() {
  const q = useOrdersView()
  const a = useOrderActions()
  const toast = useToast()
  const [enableOpen, setEnableOpen] = useState(false)
  const [phrase, setPhrase] = useState('')
  const d = q.data
  const fail = (title: string) => (e: unknown) => toast({ tone: 'bad', title, detail: isFailure(e) ? e.message : undefined })
  const deliveries = (d?.positions ?? []).filter((p) => p.product === 'CNC' && p.qty > 0)
  return (
    <div>
      <PageHeader title="Orders" subtitle="Your own orders on your own FYERS account: every order previewed and confirmed by you, with server-side limits and a kill switch." />
      {q.error && !d ? <div className="card"><ErrorState error={q.error} onRetry={() => void q.refetch()} /></div> : !d ? <div className="card"><SkeletonRows /></div> : (
        <div className="space-y-3">
          <Card>
            <div className="flex flex-wrap items-center gap-3">
              <span className={cn('rounded-md px-2.5 py-1 text-sm font-bold', d.kill ? 'bg-loss text-white' : d.enabled ? 'bg-profit text-white' : 'border border-line-strong bg-raised text-muted')}>
                {d.kill ? 'KILL SWITCH ON' : d.enabled ? 'ORDERS ON' : 'ORDERS OFF'}
              </span>
              <span className="text-xs text-muted">
                {d.logged_in ? 'Logged in to FYERS today' : 'Not logged in to FYERS today'} · {d.today_count} order{d.today_count === 1 ? '' : 's'} today
                {' · '}<span title="FYERS' order socket, run by the live service (4_intraday_live.bat) during market hours">{d.feed?.connected ? 'order updates pushed live by FYERS' : 'order updates checked every 5 s'}</span>
                {d.pnl_today != null && <> · today's P&L <Money v={d.pnl_today} signed color /></>}
              </span>
              <div className="flex-1" />
              {d.enabled ? <Button size="sm" variant="ghost" icon={<Power className="h-3.5 w-3.5" />} onClick={() => a.enable.mutate({ on: false }, { onError: fail('Not changed') })}>Switch orders off</Button>
                : <Button size="sm" icon={<Power className="h-3.5 w-3.5" />} onClick={() => { setPhrase(''); setEnableOpen(true) }}>Switch orders on…</Button>}
              {d.kill ? <Button size="sm" onClick={() => a.kill.mutate({ on: false }, { onError: fail('Not changed') })}>Release kill switch</Button>
                : <Button size="sm" variant="danger" icon={<OctagonX className="h-3.5 w-3.5" />} loading={a.kill.isPending}
                    onClick={() => { if (window.confirm('Stop all trading now? This blocks every new order and cancels every pending order on FYERS.')) a.kill.mutate({ on: true, reason: 'kill switch pressed' }, { onSuccess: (r) => toast({ tone: 'info', title: `Kill switch on: ${r.cancelled.length} pending order(s) cancelled` }), onError: fail('Kill switch failed') }) }}>
                    Kill switch</Button>}
            </div>
            {d.kill_at && <p className="mt-2 text-xs text-loss">On since {dateTimeIST(d.kill_at)}{d.kill_reason ? `: ${d.kill_reason}` : ''}.</p>}
            {d.errors.map((e) => <p key={e} className="mt-2 text-xs text-warn">{e}</p>)}
            <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-2xs text-muted">
              <span>Max per order {String(d.limits.max_order_value_pct)}% of capital</span>
              <span>Max {String(d.limits.max_orders_per_day)} orders a day</span>
              <span>Buys stop for the day at -{String(d.limits.daily_loss_limit_pct)}% of capital</span>
              <span>Limit within {String(d.limits.price_band_pct)}% of the last price</span>
              <span>{d.limits.allow_market ? 'Market orders allowed' : 'Limit orders only'}</span>
              <span className="text-faint">(config.yaml → orders:)</span>
            </div>
          </Card>

          <Card title="Today's orders" flush>
            {d.orders.length === 0 ? <EmptyState compact title="No orders today">Place one from a BUY or SELL card on <Link to="/today" className="link">Today</Link> or any chart.</EmptyState> : (
              <div className="scroll-x"><table className="w-full text-[13px]">
                <thead className="text-2xs uppercase tracking-[0.04em] text-faint"><tr className="border-b border-line">
                  <th className="px-3 py-2 text-left font-semibold">Time</th><th className="px-3 py-2 text-left font-semibold">Order</th><th className="px-3 py-2 text-right font-semibold">Qty</th>
                  <th className="px-3 py-2 text-right font-semibold">Limit</th><th className="px-3 py-2 text-right font-semibold">Filled at</th><th className="px-3 py-2 text-left font-semibold">Status</th><th />
                </tr></thead>
                <tbody>{d.orders.map((o) => (
                  <tr key={o.id} className="border-b border-line/60">
                    <td className="px-3 py-1.5 text-muted">{String(o.time ?? '').slice(-8)}</td>
                    <td className="px-3 py-1.5"><span className={o.side === 'BUY' ? 'text-profit' : 'text-loss'}>{o.side}</span> <span className="font-semibold">{o.symbol}</span> <span className="text-2xs text-muted">{o.type} {o.product}</span></td>
                    <td className="num px-3 py-1.5 text-right">{o.filled}/{o.qty}</td>
                    <td className="num px-3 py-1.5 text-right">{num(o.limit_price, 2)}</td>
                    <td className="num px-3 py-1.5 text-right">{num(o.avg_price, 2)}</td>
                    <td className="px-3 py-1.5" title={o.message ?? ''}>{o.status}</td>
                    <td className="px-3 py-1.5 text-right">{o.pending && <Button size="sm" variant="ghost" onClick={() => a.cancel.mutate(o.id, { onError: fail('Cancel failed') })}>Cancel</Button>}</td>
                  </tr>
                ))}</tbody>
              </table></div>
            )}
          </Card>

          <div className="grid gap-3 xl:grid-cols-2">
            <Card title="Positions today" flush>
              {d.positions.length === 0 ? <EmptyState compact title="No positions today" /> : (
                <ul className="divide-y divide-line/60">{d.positions.map((p) => (
                  <li key={p.symbol + p.product} className="flex items-center gap-3 px-3 py-1.5 text-[13px]">
                    <span className="w-28 font-semibold">{p.symbol}</span><span className="text-muted">{p.qty} @ {num(p.avg, 2)} · {p.product}</span>
                    <span className="ml-auto">LTP {num(p.ltp, 2)} · <Money v={p.pl} signed color /></span>
                  </li>
                ))}</ul>
              )}
            </Card>
            <Card title="Protect with a stop-loss and target" subtitle="A FYERS GTT OCO sell: whichever level is hit first; it stays live across days">
              {deliveries.length === 0 ? <p className="text-xs text-muted">Delivery (CNC) buys from today show here; for older holdings use the FYERS app's GTT, or buy through here first.</p>
                : deliveries.map((p) => <ProtectRow key={p.symbol} symbol={p.symbol} qty={p.qty} avg={p.avg} />)}
              {d.gtt.length > 0 && <p className="mt-2 text-2xs text-muted">Active GTT orders: {d.gtt.map((g) => `${g.symbol} (${String(g.status)})`).join(', ')}</p>}
            </Card>
          </div>

          {d.reconciliation.length > 0 && (
            <Card title="Fills vs the signal" subtitle="What each signal's order actually cost against its reference price">
              <ul className="space-y-0.5 text-[13px]">{d.reconciliation.map((r) => (
                <li key={r.id} className="flex flex-wrap gap-x-3"><span className="font-semibold">{r.symbol}</span><span className="text-muted">{r.side} signal {num(r.ref_price, 2)} → filled {num(r.fill, 2)}</span><span>slippage <Pct v={-r.slippage_pct} dp={2} /></span>{r.strategy_key && <span className="text-faint">{r.strategy_key}</span>}</li>
              ))}</ul>
            </Card>
          )}

          <Card title="Audit log" subtitle="Everything the app sent or blocked, newest first (data/orders_audit.jsonl)">
            {d.audit.length === 0 ? <p className="text-xs text-muted">Nothing yet.</p> : (
              <ul className="max-h-72 space-y-0.5 overflow-auto font-mono text-2xs">{d.audit.map((e, i) => (
                <li key={i} className="text-muted"><span className="text-faint">{e.ts}</span> <span className={cn('font-semibold', e.event === 'placed' ? 'text-profit' : ['rejected', 'blocked', 'unknown', 'kill_on'].includes(e.event) ? 'text-loss' : 'text-fg')}>{e.event}</span> {summarize(e)}</li>
              ))}</ul>
            )}
          </Card>
          <p className="text-2xs text-faint">{d.note}</p>
        </div>
      )}

      <Dialog open={enableOpen} onClose={() => setEnableOpen(false)} title="Switch order placement on"
        footer={<><Button variant="ghost" onClick={() => setEnableOpen(false)}>Cancel</Button>
          <Button variant="primary" disabled={phrase.trim().toUpperCase() !== 'ENABLE'} loading={a.enable.isPending}
            onClick={() => a.enable.mutate({ on: true, phrase }, { onSuccess: () => { setEnableOpen(false); toast({ tone: 'good', title: 'Order placement is on' }) }, onError: fail('Not switched on') })}>Switch on</Button></>}>
        <div className="space-y-2 text-[13px]">
          <p>Orders will go to your FYERS account, only when you confirm each one. Before you start:</p>
          <ul className="list-disc space-y-1 pl-5 text-xs text-muted">
            <li>Register this PC's static IP in the FYERS API dashboard (SEBI rule since 1 Apr 2026): orders from any other IP are rejected.</li>
            <li>Log in to FYERS every trading day (also a SEBI rule).</li>
            <li>Check the limits in config.yaml → orders: (order size, orders a day, daily loss lockout, price band).</li>
            <li>The signals are tested on history, not guarantees: every trade can lose money. You decide each one.</li>
          </ul>
          <label className="block text-xs">Type <span className="font-mono font-semibold">ENABLE</span> to switch on
            <input aria-label="Type ENABLE" value={phrase} onChange={(e) => setPhrase(e.target.value)} className="input mt-1 block h-8 w-40 px-2 font-mono" /></label>
        </div>
      </Dialog>
    </div>
  )
}

function summarize(e: Record<string, unknown>): string {
  const t = e.ticket as { side?: string; qty?: number; symbol?: string; limit_price?: number } | undefined
  const parts = []
  if (t) parts.push(`${t.side} ${t.qty} ${t.symbol} @ ${t.limit_price ?? 'mkt'}`)
  if (e.order_id) parts.push(`id ${String(e.order_id)}`)
  if (e.symbol && !t) parts.push(String(e.symbol))
  if (Array.isArray(e.failed) && e.failed.length) parts.push(`failed: ${(e.failed as string[]).join(', ')}`)
  if (e.message) parts.push(String(e.message))
  return parts.join(' · ')
}
