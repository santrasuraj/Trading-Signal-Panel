// The order ticket: fill in, Review (sends nothing: the server returns the exact FYERS order, every check, the charges
// and the risk), then tick "I have checked this order" and Send (one attempt, never retried).

import { useEffect, useState } from 'react'
import { CheckCircle2, ShieldAlert, XCircle } from 'lucide-react'
import { Link } from 'react-router-dom'
import { isFailure } from '@/api/client'
import { useOrderActions, type Preview, type Ticket } from '@/api/orders'
import { Button, Dialog, Segmented } from '@/components/ui'
import { cn } from '@/lib/csv'
import { num } from '@/lib/format'

export function OrderTicket({ open, onClose, initial }: { open: boolean; onClose: () => void; initial: Ticket }) {
  const a = useOrderActions()
  const [t, setT] = useState<Ticket>(initial)
  const [pv, setPv] = useState<Preview | null>(null)
  const [checked, setChecked] = useState(false)
  useEffect(() => { if (open) { setT(initial); setPv(null); setChecked(false); a.place.reset(); a.preview.reset() } }, [open]) // eslint-disable-line react-hooks/exhaustive-deps
  const edit = (k: keyof Ticket, v: unknown) => { setT((x) => ({ ...x, [k]: v })); setPv(null); setChecked(false) }
  const review = () => a.preview.mutate(t, { onSuccess: setPv })
  const res = a.place.data
  const buy = t.side === 'BUY'
  const err = a.preview.error ?? a.place.error
  return (
    <Dialog open={open} onClose={onClose} width={560} title={<span className="flex items-center gap-2"><span className={cn('rounded px-1.5 py-0.5 text-xs font-bold text-white', buy ? 'bg-profit' : 'bg-loss')}>{t.side}</span> {t.symbol} on FYERS</span>}
      footer={res ? <Button variant="primary" onClick={onClose}>Close</Button> : (
        <>
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          {!pv?.ok ? <Button onClick={review} loading={a.preview.isPending}>Review order</Button>
            : <Button variant={buy ? 'buy' : 'sell'} disabled={!checked} loading={a.place.isPending} onClick={() => a.place.mutate(pv.preview_id!)}>Send {t.side} to FYERS</Button>}
        </>
      )}>
      {res ? (
        <div className="space-y-2 text-[13px]">
          {res.ok ? <p className="flex items-center gap-2 text-profit"><CheckCircle2 className="h-4 w-4" />Sent: FYERS order {res.order_id}. {res.message}</p>
            : res.unknown ? <p className="flex items-center gap-2 text-warn"><ShieldAlert className="h-4 w-4" />{res.message}</p>
            : <p className="flex items-center gap-2 text-loss"><XCircle className="h-4 w-4" />FYERS rejected it: {res.message}</p>}
          {res.next && <p className="text-muted">{res.next}</p>}
          <Link to="/orders" className="link text-xs" onClick={onClose}>Open the Orders page</Link>
        </div>
      ) : (
        <div className="space-y-3 text-[13px]">
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            <label className="text-2xs text-muted">Quantity<input aria-label="Quantity" inputMode="numeric" value={t.qty} onChange={(e) => edit('qty', Math.max(0, Math.floor(Number(e.target.value) || 0)))} className="input num mt-0.5 block h-8 w-full px-2 text-right" /></label>
            <label className="text-2xs text-muted">Limit price ₹<input aria-label="Limit price" inputMode="decimal" value={t.limit_price ?? ''} onChange={(e) => edit('limit_price', e.target.value === '' ? null : Number(e.target.value))} className="input num mt-0.5 block h-8 w-full px-2 text-right" /></label>
            <label className="text-2xs text-muted">Stop-loss ₹<input aria-label="Stop-loss" inputMode="decimal" value={t.stop ?? ''} onChange={(e) => edit('stop', e.target.value === '' ? null : Number(e.target.value))} className="input num mt-0.5 block h-8 w-full px-2 text-right" /></label>
            <label className="text-2xs text-muted">Target ₹<input aria-label="Target" inputMode="decimal" value={t.target ?? ''} onChange={(e) => edit('target', e.target.value === '' ? null : Number(e.target.value))} className="input num mt-0.5 block h-8 w-full px-2 text-right" /></label>
          </div>
          <Segmented<'CNC' | 'INTRADAY'> size="xs" ariaLabel="Product" value={t.product} onChange={(v) => edit('product', v)} items={[{ id: 'CNC', label: 'Delivery (CNC)' }, { id: 'INTRADAY', label: 'Intraday' }]} />
          <p className="text-2xs text-faint">A limit order at your price. The stop-loss and target aren't sent with it: once a delivery buy fills, protect it with both from the Orders page (a FYERS GTT order that stays live across days).</p>
          {err && <p className="text-xs text-loss">{isFailure(err) ? err.message : 'Failed.'}</p>}
          {pv && (
            <div className="space-y-2 rounded-md border border-line p-2.5">
              <div className="flex flex-wrap gap-x-4 gap-y-1">
                <span>Value <span className="num font-medium">₹{num(pv.value, 0)}</span></span>
                <span>Charges ≈ <span className="num">₹{num(pv.charges, 0)}</span></span>
                {pv.risk_if_stopped != null && <span>Risk if stopped <span className="num text-loss">₹{num(pv.risk_if_stopped, 0)}</span></span>}
                {pv.last && <span className="text-muted">Last {num(pv.last.price, 2)} ({pv.last.source})</span>}
              </div>
              <ul className="space-y-0.5">{pv.checks.map((c) => (
                <li key={c.key + c.name} className={cn('flex items-start gap-1.5 text-xs', c.ok ? 'text-muted' : c.blocking ? 'text-loss' : 'text-warn')}>
                  {c.ok ? <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-profit" /> : <XCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />}
                  <span><span className="text-fg">{c.name}</span>: {c.detail}</span>
                </li>
              ))}</ul>
              {pv.ok ? (
                <label className="flex items-center gap-2 text-xs font-medium">
                  <input type="checkbox" checked={checked} onChange={(e) => setChecked(e.target.checked)} />
                  I have checked this order: {t.side} {t.qty} {t.symbol} at ₹{num(t.limit_price, 2)} ({t.product}), valid today. Send within {pv.expires_in_s} s.
                </label>
              ) : <p className="text-xs text-loss">Not ready to send: fix the checks in red.</p>}
            </div>
          )}
          <p className="text-2xs text-faint">Your own order on your own account. Nothing is sent until you press Send; one attempt only. The kill switch on the Orders page stops all trading at once.</p>
        </div>
      )}
    </Dialog>
  )
}
