// Basket (Today): every BUY / SELL of the day in one review. Practice: each goes to the practice account. Real: the
// server reviews each order with every check (nothing sent), then, after "I have checked these orders", sends them one
// at a time, spaced by the minimum gap; each once, never retried; one that fails does not stop the others.

import { useEffect, useState } from 'react'
import { CheckCircle2, ShieldAlert, XCircle } from 'lucide-react'
import { Link } from 'react-router-dom'
import { fetchJson, isFailure } from '@/api/client'
import { useOrdersView, type Preview, type Ticket } from '@/api/orders'
import { useSimActions } from '@/api/sim'
import { Button, Dialog, Segmented } from '@/components/ui'
import { cn } from '@/lib/csv'
import { num } from '@/lib/format'

interface BasketPreview { previews: Preview[]; ok: number; total: number; buy_value: number; capital: number; over_capital: boolean; note: string }
interface BasketResult { results: { preview_id: string; ok: boolean; unknown?: boolean; order_id: string | null; message: string | null; ticket?: Ticket }[]; sent: number; total: number }
type Row = { t: Ticket; on: boolean; done?: string; error?: string }
const post = <T,>(p: string, b: unknown) => fetchJson<T>(p, { method: 'POST', body: JSON.stringify(b) })

export function BasketDialog({ open, onClose, tickets }: { open: boolean; onClose: () => void; tickets: Ticket[] }) {
  const ov = useOrdersView(false)
  const sim = useSimActions()
  const [mode, setMode] = useState<'sim' | 'real'>('sim')
  const [rows, setRows] = useState<Row[]>([])
  const [pv, setPv] = useState<BasketPreview | null>(null)
  const [res, setRes] = useState<BasketResult | null>(null)
  const [busy, setBusy] = useState(false)
  const [checked, setChecked] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  useEffect(() => {
    if (!open) return
    setRows(tickets.map((t) => ({ t, on: true }))); setPv(null); setRes(null); setChecked(false); setErr(null)
    setMode(ov.data?.enabled ? 'real' : 'sim')
  }, [open]) // eslint-disable-line react-hooks/exhaustive-deps
  const chosen = rows.filter((r) => r.on)
  const value = chosen.reduce((a, r) => a + r.t.qty * (r.t.limit_price ?? 0), 0)
  const fail = (e: unknown) => setErr(isFailure(e) ? `${e.message}${e.hint ? ` ${e.hint}` : ''}` : 'Failed.')
  const practice = async () => {
    setBusy(true); setErr(null)
    const next = [...rows]
    for (let i = 0; i < next.length; i++) {
      if (!next[i].on) continue
      const t = next[i].t
      try {
        const o = await sim.order.mutateAsync({ symbol: t.symbol, side: t.side, qty: t.qty, type: 'LIMIT', product: t.product, limit_price: t.limit_price, stop: t.stop ?? null, target: t.target ?? null })
        next[i] = { ...next[i], done: o.status === 'filled' ? `filled ${num(o.fill_price, 2)}` : `waiting at ${num(o.limit_price, 2)}` }
      } catch (e) { next[i] = { ...next[i], error: isFailure(e) ? e.message : 'failed' } }
      setRows([...next])
    }
    setBusy(false); setRes({ results: [], sent: next.filter((r) => r.done).length, total: chosen.length })
  }
  const review = async () => {
    setBusy(true); setErr(null)
    try { setPv(await post<BasketPreview>('/api/orders/basket/preview', { tickets: chosen.map((r) => r.t) })) } catch (e) { fail(e) }
    setBusy(false)
  }
  const send = async () => {
    if (!pv) return
    setBusy(true); setErr(null)
    try { setRes(await post<BasketResult>('/api/orders/basket/place', { preview_ids: pv.previews.filter((p) => p.ok).map((p) => p.preview_id), confirm: true })) } catch (e) { fail(e) }
    setBusy(false)
  }
  const okCount = pv ? pv.previews.filter((p) => p.ok).length : 0
  const footer = res ? <Button variant="primary" onClick={onClose}>Close</Button> : (
    <>
      <Button variant="ghost" onClick={onClose}>Cancel</Button>
      {mode === 'sim' ? <Button variant="primary" loading={busy} disabled={!chosen.length} onClick={practice}>Place {chosen.length} practice orders</Button>
        : !pv ? <Button loading={busy} disabled={!chosen.length} onClick={review}>Review {chosen.length} orders</Button>
        : <Button variant="primary" loading={busy} disabled={!checked || !okCount} onClick={send}>Send {okCount} to FYERS</Button>}
    </>
  )
  return (
    <Dialog open={open} onClose={onClose} width={680} title={`Today's orders · ${mode === 'sim' ? 'practice' : 'FYERS'}`} footer={footer}>
      {!res && !pv && (
        <Segmented<'sim' | 'real'> size="xs" ariaLabel="Account" value={mode} onChange={(v) => { setMode(v); setPv(null) }} className="mb-3"
          items={[{ id: 'sim', label: 'Practice (no money)' }, { id: 'real', label: 'Real · FYERS' }]} />
      )}
      <table className="w-full text-[13px]">
        <thead className="text-left text-2xs text-muted"><tr><th className="w-6" /><th>Order</th><th className="text-right">Qty</th><th className="text-right">Limit ₹</th><th className="text-right">Stop ₹</th><th className="text-right">Value</th><th>{pv || res ? 'Result' : ''}</th></tr></thead>
        <tbody>{rows.map((r, i) => {
          const p = pv?.previews.find((x) => x.ticket.symbol === r.t.symbol && x.ticket.side === r.t.side)
          const out = res?.results.find((x) => x.preview_id === p?.preview_id)
          return (
            <tr key={`${r.t.symbol}${r.t.side}`} className={cn('border-t border-line', !r.on && 'opacity-50')}>
              <td><input type="checkbox" aria-label={`Include ${r.t.symbol}`} checked={r.on} disabled={!!pv || !!res || busy} onChange={(e) => setRows(rows.map((x, j) => (j === i ? { ...x, on: e.target.checked } : x)))} /></td>
              <td className="py-1.5"><span className={r.t.side === 'BUY' ? 'font-semibold text-profit' : 'font-semibold text-loss'}>{r.t.side}</span> {r.t.symbol}</td>
              <td className="num text-right">{r.t.qty}</td>
              <td className="num text-right">{num(r.t.limit_price, 2)}</td>
              <td className="num text-right text-muted">{r.t.stop != null ? num(r.t.stop, 2) : '—'}</td>
              <td className="num text-right">₹{num(r.t.qty * (r.t.limit_price ?? 0), 0)}</td>
              <td className="pl-2 text-xs">
                {r.done ? <span className="text-profit">{r.done}</span> : r.error ? <span className="text-loss">{r.error}</span>
                  : out ? (out.ok ? <span className="flex items-center gap-1 text-profit"><CheckCircle2 className="h-3.5 w-3.5" />sent {out.order_id}</span>
                    : <span className={cn('flex items-center gap-1', out.unknown ? 'text-warn' : 'text-loss')}>{out.unknown ? <ShieldAlert className="h-3.5 w-3.5" /> : <XCircle className="h-3.5 w-3.5" />}{out.message}</span>)
                  : p ? (p.ok ? <span className="text-muted">ready</span> : <span className="text-loss">{p.checks.find((c) => c.blocking && !c.ok)?.name ?? 'blocked'}</span>) : null}
              </td>
            </tr>
          )
        })}</tbody>
      </table>
      <p className="mt-2 text-xs text-muted">{chosen.length} orders · ₹{num(value, 0)}{pv?.over_capital && <span className="text-warn"> · more than your capital (₹{num(pv.capital, 0)}): FYERS will reject what your margin can't cover</span>}</p>
      {pv && !res && (
        <label className="mt-2 flex items-center gap-2 text-xs font-medium">
          <input type="checkbox" checked={checked} onChange={(e) => setChecked(e.target.checked)} />
          I have checked these {okCount} orders. Send them within 60 s (each once, about a second apart).
        </label>
      )}
      {pv && <p className="mt-1 text-2xs text-faint">{pv.note}</p>}
      {err && <p className="mt-2 text-xs text-loss">{err}</p>}
      {res && <p className="mt-2 text-xs">{mode === 'sim' ? <Link to="/sim" className="link" onClick={onClose}>Open the practice account</Link> : <Link to="/orders" className="link" onClick={onClose}>Open the Orders page</Link>}</p>}
      {mode === 'sim' && !res && <p className="mt-2 text-2xs text-faint">Practice account on live prices: nothing is sent to FYERS. Limit orders at the live price; a stop or target closes a position by itself.</p>}
    </Dialog>
  )
}
