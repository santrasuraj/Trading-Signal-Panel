// Practice `/sim`: a practice account on today's live prices (web/api/services/sim_svc.py). The same order ticket as
// the real one, filled against live quotes; nothing reaches FYERS. Positions are marked live; stops, targets and
// resting limit orders are checked as quotes arrive.

import { useState } from 'react'
import { Link } from 'react-router-dom'
import { RotateCcw, X } from 'lucide-react'
import { isFailure } from '@/api/client'
import { useLiveQuotes } from '@/api/hooks'
import { useSim, useSimActions, type SimAccount } from '@/api/sim'
import { OrderTicket } from '@/components/OrderTicket'
import { KpiStrip, KpiTile, PageHeader } from '@/components/domain'
import { EmptyState, ErrorState, Skeleton } from '@/components/feedback'
import { Money, Pct } from '@/components/num'
import { useToast } from '@/components/toast'
import { Button, Card, IconButton } from '@/components/ui'
import { dateTimeIST, num } from '@/lib/format'
import type { Ticket } from '@/api/orders'

function NewOrder({ capital }: { capital: number }) {
  const [sym, setSym] = useState('')
  const [ticket, setTicket] = useState<Ticket | null>(null)
  const s = sym.trim().toUpperCase()
  const lq = useLiveQuotes(s ? [s] : [])
  const px = lq.quotes[s]?.price ?? null
  const open = (side: 'BUY' | 'SELL') => setTicket({ symbol: s, side, qty: px ? Math.max(1, Math.floor((capital * 0.1) / px)) : 1, type: 'LIMIT', product: 'CNC',
    limit_price: px ? Math.round(px * 20) / 20 : null, stop: null, target: null, source: 'practice' })
  return (
    <div className="flex flex-wrap items-end gap-2">
      <label className="text-2xs text-muted">Stock<input aria-label="Stock" value={sym} onChange={(e) => setSym(e.target.value)} className="input mt-0.5 block h-8 w-36 px-2 uppercase" /></label>
      <span className="pb-2 text-xs text-muted">{px != null ? <>Live <span className="num text-fg">₹{num(px, 2)}</span></> : s ? 'no live price yet' : ''}</span>
      <Button variant="buy" disabled={!s} onClick={() => open('BUY')}>Buy</Button>
      <Button variant="sell" disabled={!s} onClick={() => open('SELL')}>Sell</Button>
      {ticket && <OrderTicket open={!!ticket} onClose={() => setTicket(null)} initial={ticket} mode="sim" />}
    </div>
  )
}

function Body({ d }: { d: SimAccount }) {
  const a = useSimActions()
  const toast = useToast()
  const fail = (title: string) => (e: unknown) => toast({ tone: 'bad', title, detail: isFailure(e) ? e.message : undefined })
  useLiveQuotes([...d.positions.map((p) => p.symbol), ...d.orders.filter((o) => o.status === 'open').map((o) => o.symbol)])
  const open = d.orders.filter((o) => o.status === 'open')
  const done = d.orders.filter((o) => o.status !== 'open').slice(0, 25)
  return (
    <div className="space-y-4">
      <KpiStrip>
        <KpiTile label="Account value" value={<Money v={d.equity} dp={0} />} sub={`started with ₹${num(d.start_cash, 0)}`} />
        <KpiTile label="P&L" value={<Money v={d.pnl} signed color dp={0} />} sub={<Pct v={(d.pnl / d.start_cash) * 100} dp={2} />} />
        <KpiTile label="Cash" value={<Money v={d.cash} dp={0} />} />
        <KpiTile label="Closed trades" value={d.stats.trades} sub={d.stats.win_rate != null ? `${num(d.stats.win_rate, 0)}% won` : undefined} />
        <KpiTile label="Realised" value={<Money v={d.stats.realised} signed color dp={0} />} sub="before charges" />
        <KpiTile label="Charges paid" value={<Money v={d.charges} dp={0} />} />
      </KpiStrip>
      <Card title="New practice order" subtitle="Type a stock, then Buy or Sell: the ticket opens in practice mode (limit or market).">
        <NewOrder capital={d.start_cash} />
      </Card>
      <Card title={`Positions (${d.positions.length})`} flush>
        {d.positions.length === 0 ? <EmptyState compact title="No practice positions" /> : (
          <table className="w-full text-[13px]">
            <thead className="text-left text-2xs text-muted"><tr><th className="px-4 py-1.5">Stock</th><th className="text-right">Qty</th><th className="text-right">Avg ₹</th><th className="text-right">Now ₹</th><th className="text-right">P&L</th><th className="text-right">Stop / target</th><th className="px-4" /></tr></thead>
            <tbody>{d.positions.map((p) => (
              <tr key={p.symbol} className="border-t border-line">
                <td className="px-4 py-1.5"><Link to={`/chart/${p.symbol}`} className="font-medium hover:underline">{p.symbol}</Link> <span className="text-2xs text-faint">{p.product === 'INTRADAY' ? 'intraday' : 'delivery'}</span></td>
                <td className="num text-right">{p.qty}</td>
                <td className="num text-right">{num(p.avg, 2)}</td>
                <td className="num text-right">{num(p.price, 2)}</td>
                <td className="text-right"><Money v={p.pnl} signed color dp={0} /></td>
                <td className="num text-right text-muted">{p.stop != null ? num(p.stop, 2) : '—'} / {p.target != null ? num(p.target, 2) : '—'}</td>
                <td className="px-4 text-right"><Button size="xs" variant="subtle" loading={a.close.isPending} onClick={() => a.close.mutate(p.symbol, { onError: fail('Not closed') })}>Close</Button></td>
              </tr>
            ))}</tbody>
          </table>
        )}
      </Card>
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title={`Orders (${open.length} waiting)`} flush>
          {open.length + done.length === 0 ? <EmptyState compact title="No practice orders yet" /> : (
            <ul className="divide-y divide-line text-[13px]">
              {[...open, ...done].map((o) => (
                <li key={o.id} className="flex items-center gap-2 px-4 py-1.5">
                  <span className={o.side === 'BUY' ? 'font-semibold text-profit' : 'font-semibold text-loss'}>{o.side}</span>
                  <span>{o.qty} {o.symbol}</span>
                  <span className="text-muted">{o.type === 'LIMIT' ? `limit ${num(o.limit_price, 2)}` : o.auto ? o.auto.replace('_', ' ') : 'market'}</span>
                  <span className="ml-auto text-xs text-muted">{o.status === 'filled' ? `filled ${num(o.fill_price, 2)}` : o.status}</span>
                  {o.status === 'open' && <IconButton label="Cancel order" onClick={() => a.cancel.mutate(o.id, { onError: fail('Not cancelled') })}><X className="h-3.5 w-3.5" /></IconButton>}
                </li>
              ))}
            </ul>
          )}
        </Card>
        <Card title="Closed trades" flush>
          {d.trades.length === 0 ? <EmptyState compact title="No closed practice trades" /> : (
            <ul className="divide-y divide-line text-[13px]">
              {d.trades.slice(0, 30).map((t, i) => (
                <li key={i} className="flex items-center gap-2 px-4 py-1.5">
                  <span className="font-medium">{t.symbol}</span>
                  <span className="text-muted">{t.side === 'LONG' ? 'long' : 'short'} {t.qty} · {num(t.entry, 2)} → {num(t.exit, 2)} ({t.reason.replace('_', ' ')})</span>
                  <span className="ml-auto"><Money v={t.pnl} signed color dp={0} /></span>
                  <span className="text-2xs text-faint">{dateTimeIST(t.closed)}</span>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
      <div className="flex items-center justify-between gap-3">
        <p className="text-2xs text-faint">{d.note}</p>
        <Button size="sm" variant="ghost" icon={<RotateCcw className="h-3.5 w-3.5" />}
          onClick={() => { if (window.confirm('Start the practice account again? Positions, orders and trades are cleared.')) a.reset.mutate(null, { onError: fail('Not reset') }) }}>Reset account</Button>
      </div>
    </div>
  )
}

export default function Sim() {
  const q = useSim()
  return (
    <div>
      <PageHeader title="Practice" subtitle="Trade today's live prices with no money: the same order ticket as the real one, nothing sent to FYERS. Tip: on any chart, Trade on chart opens a practice order at the price you click." />
      {q.error ? <ErrorState error={q.error} onRetry={() => void q.refetch()} /> : !q.data ? <Skeleton className="h-40 w-full" /> : <Body d={q.data} />}
    </div>
  )
}
