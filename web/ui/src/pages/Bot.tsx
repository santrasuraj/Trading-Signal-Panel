// Practice bot `/bot`: forward-test strategies in the practice account on live prices (web/api/services/bot_svc.py).
// It mirrors each chosen strategy's model portfolio after each scan; nothing is ever sent to FYERS.

import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Bot as BotIcon, Play } from 'lucide-react'
import { fetchJson, isFailure } from '@/api/client'
import { PageHeader } from '@/components/domain'
import { Banner, ErrorState, SkeletonRows } from '@/components/feedback'
import { Button, Card, Field } from '@/components/ui'
import { money, num, pct } from '@/lib/format'
import { cn } from '@/lib/csv'

interface Lot { symbol: string; qty: number; price: number | null; at: string | null; model_price: number | null; price_now: number | null }
interface Rec { realised: number; unrealised: number; charges: number; net: number; closed: number; win_rate: number | null; avg_entry_vs_model_pct: number | null; open: Lot[] }
interface Row { key: string; name: string; status: string; horizon: string; max_positions: number | null; on: boolean; since: string | null; skipped: number; record: Rec | null }
interface LogRow { at: string; strategy: string; symbol: string; side: 'BUY' | 'SELL'; qty: number; price: number | null; charges: number | null; model_price: number | null; slip_pct: number | null }
interface BotView { capital: number; strategies: Row[]; last_run: { at: string; orders: number; problems: string[] } | null; log: LogRow[]; running: boolean; session: string; note: string }

const STATUS_TONE: Record<string, string> = { working: 'text-profit', mixed: 'text-warn', 'not-working': 'text-loss' }

export default function Bot() {
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['bot'], queryFn: () => fetchJson<BotView>('/api/bot'), refetchInterval: 30_000 })
  const [sel, setSel] = useState<string[] | null>(null)
  const [cap, setCap] = useState<string>('')
  const d = q.data
  useEffect(() => { if (d && sel === null) { setSel(d.strategies.filter((s) => s.on).map((s) => s.key)); setCap(String(d.capital)) } }, [d, sel])
  const save = useMutation({ mutationFn: () => fetchJson<BotView>('/api/bot/settings', { method: 'POST', body: JSON.stringify({ enabled: sel ?? [], capital: Number(cap) || 100000 }) }), onSuccess: (v) => qc.setQueryData(['bot'], v) })
  const run = useMutation({ mutationFn: () => fetchJson<{ ran: boolean; why?: string; orders?: number; view: BotView }>('/api/bot/run', { method: 'POST', body: '{}' }), onSuccess: (r) => qc.setQueryData(['bot'], r.view) })
  const changed = d && sel && (JSON.stringify([...sel].sort()) !== JSON.stringify(d.strategies.filter((s) => s.on).map((s) => s.key).sort()) || Number(cap) !== d.capital)
  const on = d?.strategies.filter((s) => s.on) ?? []
  return (
    <div>
      <PageHeader title="Practice bot" subtitle="Forward-test strategies in the practice account on live prices: no real money, nothing sent to FYERS"
        right={<Button icon={<Play className="h-4 w-4" />} loading={run.isPending} disabled={!on.length} onClick={() => run.mutate()} title="Check now instead of waiting for the next minute (market hours)">Check now</Button>} />
      {d && <div className="mb-3"><Banner tone="info">{d.note}</Banner></div>}
      {run.data && !run.data.ran && <div className="mb-3"><Banner tone="warn">{run.data.why}</Banner></div>}
      {d?.last_run?.problems?.length ? <div className="mb-3"><Banner tone="warn">Last check {d.last_run.at.slice(11, 16)}: {d.last_run.problems.slice(0, 3).join('; ')}</Banner></div> : null}
      {q.error ? <ErrorState error={q.error} onRetry={() => q.refetch()} /> : !d ? <Card><SkeletonRows rows={8} cols={5} /></Card> : (
        <>
          <Card className="mb-3" title="Strategies to run" subtitle={`Up to 5. A strategy switched on now skips the stocks its model already holds and trades only its new entries and exits. ${d.running ? 'The bot checks every minute while this dashboard runs.' : ''}`}
            right={<span className="flex items-end gap-2">
              <Field label="Bot capital ₹"><input className="input h-8 w-32 px-2 text-right" inputMode="numeric" value={cap} onChange={(e) => setCap(e.target.value)} /></Field>
              <Button variant="primary" disabled={!changed} loading={save.isPending} onClick={() => save.mutate()}>Save</Button>
            </span>}>
            {save.error && <p className="mb-2 text-xs text-loss">{isFailure(save.error) ? save.error.message : 'Not saved.'}</p>}
            <div className="grid gap-1.5 sm:grid-cols-2 xl:grid-cols-3">{d.strategies.map((s) => (
              <label key={s.key} className={cn('flex items-center gap-2 rounded border px-2 py-1.5 text-[13px]', (sel ?? []).includes(s.key) ? 'border-accent bg-accent/5' : 'border-line')}>
                <input type="checkbox" checked={(sel ?? []).includes(s.key)} onChange={(e) => setSel(e.target.checked ? [...(sel ?? []), s.key] : (sel ?? []).filter((k) => k !== s.key))} />
                <span className="min-w-0 flex-1 truncate">{s.name}</span>
                <span className={cn('text-2xs', STATUS_TONE[s.status] ?? 'text-muted')}>{s.status}</span>
              </label>))}</div>
          </Card>
          {on.length === 0 ? (
            <Card><div className="flex items-center gap-3 text-sm text-muted"><BotIcon className="h-5 w-5" />Switch a strategy on and save: from the next scan its new entries and exits are traded in the <Link className="link" to="/sim">practice account</Link>.</div></Card>
          ) : (
            <div className="grid gap-3 xl:grid-cols-2">{on.map((s) => {
              const r = s.record
              return (
                <Card key={s.key} flush title={s.name} subtitle={`Running since ${s.since?.slice(0, 10) ?? '—'} · ${s.skipped} stock${s.skipped === 1 ? '' : 's'} the model already held skipped`}>
                  <div className="grid grid-cols-4 gap-2 border-b border-line px-4 py-2 text-center text-[13px]">
                    <div><div className="text-2xs text-muted">Net after charges</div><div className={cn('num font-semibold', (r?.net ?? 0) >= 0 ? 'text-profit' : 'text-loss')}>{money(r?.net, { signed: true })}</div></div>
                    <div><div className="text-2xs text-muted">Closed trades</div><div className="num font-semibold">{r?.closed ?? 0}{r?.win_rate != null && <span className="text-2xs text-muted"> · {r.win_rate.toFixed(0)}% won</span>}</div></div>
                    <div><div className="text-2xs text-muted">Open P&L</div><div className={cn('num font-semibold', (r?.unrealised ?? 0) >= 0 ? 'text-profit' : 'text-loss')}>{money(r?.unrealised, { signed: true })}</div></div>
                    <div title="The bot's buy price against the model's entry price (the cost of real timing and slippage)"><div className="text-2xs text-muted">Entry vs model</div><div className="num font-semibold">{r?.avg_entry_vs_model_pct != null ? pct(r.avg_entry_vs_model_pct, { dp: 2 }) : '—'}</div></div>
                  </div>
                  {r && r.open.length > 0 ? (
                    <table className="w-full text-[13px]"><tbody className="divide-y divide-line">{r.open.map((l) => (
                      <tr key={l.symbol}><td className="px-4 py-1.5 font-semibold"><Link to={`/chart/${l.symbol}`} className="hover:text-accent">{l.symbol}</Link></td>
                        <td className="num px-2 text-right">{l.qty} @ {num(l.price, 2)}</td>
                        <td className="num px-2 text-right text-muted">model {num(l.model_price, 2)}</td>
                        <td className={cn('num px-4 text-right', l.price_now != null && l.price != null && l.price_now >= l.price ? 'text-profit' : 'text-loss')}>{l.price_now != null && l.price ? pct((l.price_now / l.price - 1) * 100) : '—'}</td></tr>))}</tbody></table>
                  ) : <p className="px-4 py-3 text-xs text-muted">No open positions yet: waiting for the model's next entry.</p>}
                </Card>)
            })}</div>
          )}
          {d.log.length > 0 && (
            <Card flush className="mt-3" title="Bot orders" subtitle="Practice account fills">
              <table className="w-full text-[13px]"><tbody className="divide-y divide-line">{d.log.map((l, i) => (
                <tr key={i}><td className="num px-4 py-1.5 text-muted">{l.at?.slice(0, 16).replace('T', ' ')}</td><td className="px-2">{l.strategy}</td>
                  <td className={cn('px-2 font-semibold', l.side === 'BUY' ? 'text-profit' : 'text-loss')}>{l.side}</td><td className="px-2">{l.symbol}</td>
                  <td className="num px-2 text-right">{l.qty} @ {num(l.price, 2)}</td><td className="num px-4 text-right text-muted">{l.slip_pct != null ? `${pct(l.slip_pct, { dp: 2 })} vs model` : ''}</td></tr>))}</tbody></table>
            </Card>)}
        </>
      )}
    </div>
  )
}
