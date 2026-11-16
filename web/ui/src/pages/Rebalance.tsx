// Rebalancing planner `/rebalance`: your holdings brought to equal, equal-risk or your own weights, as trades with
// their charges and the tax they would book; review and send them as one basket (practice or real) through the
// Orders checks (rebalance_svc.py). Nothing is sent from this page by itself.

import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation } from '@tanstack/react-query'
import { Download, Scale } from 'lucide-react'
import { fetchJson, isFailure } from '@/api/client'
import type { Ticket } from '@/api/orders'
import { BasketDialog } from '@/components/BasketDialog'
import { KpiStrip, KpiTile, PageHeader } from '@/components/domain'
import { Button, Card, Field } from '@/components/ui'
import { downloadCsv } from '@/lib/exporting'
import { money, num, pct } from '@/lib/format'
import { useLocalStorage } from '@/lib/useLocalStorage'
import { cn } from '@/lib/csv'

type Mode = 'equal' | 'equal_risk' | 'custom'
interface Row { symbol: string; price: number; qty: number; value: number; weight_pct: number; target_pct: number; target_qty: number; side: 'BUY' | 'SELL' | null; trade_qty: number; trade_value: number; skipped_small: boolean; gain_st: number | null; gain_lt: number | null }
interface Plan { mode: Mode; value: number; budget: number; rows: Row[]; totals: { buys: number; sells: number; charges: number; cash_after: number; gain_st: number; gain_lt: number; tax_if_alone: number }; note: string; price_source?: string }

export default function Rebalance() {
  const [mode, setMode] = useLocalStorage<Mode>('qd.rebal.mode', 'equal')
  const [cash, setCash] = useLocalStorage('qd.rebal.cash', '0')
  const [minTrade, setMinTrade] = useLocalStorage('qd.rebal.min', '2000')
  const [custom, setCustom] = useLocalStorage<Record<string, string>>('qd.rebal.custom', {})
  const [basket, setBasket] = useState(false)
  const run = useMutation({ mutationFn: () => fetchJson<Plan>('/api/rebalance', { method: 'POST', body: JSON.stringify({ mode, add_cash: Number(cash) || 0, min_trade: Number(minTrade) || 0, custom: mode === 'custom' ? Object.fromEntries(Object.entries(custom).map(([k, v]) => [k, Number(v) || 0])) : null }) }) })
  const p = run.data
  const trades = (p?.rows ?? []).filter((r) => r.side && r.trade_qty > 0)
  const tickets: Ticket[] = [...trades].sort((a, b) => (a.side === 'SELL' ? -1 : 1) - (b.side === 'SELL' ? -1 : 1)).map((r) => ({
    symbol: r.symbol, side: r.side!, qty: r.trade_qty, type: 'LIMIT', product: 'CNC', limit_price: Math.round(r.price * 20) / 20, ref_price: r.price, source: 'rebalance' }))
  const customSum = Object.values(custom).reduce((s, v) => s + (Number(v) || 0), 0)
  return (
    <div>
      <PageHeader title="Rebalancing planner" subtitle="Bring your holdings to target weights; review the trades, charges and tax, then send them as one basket" />
      <Card className="mb-3" title="Targets">
        <div className="flex flex-wrap items-end gap-3">
          <Field label="Weights"><select className="input h-9 px-2" value={mode} onChange={(e) => setMode(e.target.value as Mode)}>
            <option value="equal">Equal weight</option><option value="equal_risk">Equal risk (calmer stocks get more)</option><option value="custom">My own %</option></select></Field>
          <Field label="Add (or withdraw −) ₹"><input className="input h-9 w-32 px-2 text-right" inputMode="decimal" value={cash} onChange={(e) => setCash(e.target.value)} /></Field>
          <Field label="Skip trades under ₹" hint="charges eat small trades"><input className="input h-9 w-24 px-2 text-right" inputMode="decimal" value={minTrade} onChange={(e) => setMinTrade(e.target.value)} /></Field>
          <Button variant="primary" icon={<Scale className="h-4 w-4" />} loading={run.isPending} onClick={() => run.mutate()}>Plan</Button>
        </div>
        {mode === 'custom' && p && (
          <div className="mt-3 flex flex-wrap gap-2">{p.rows.map((r) => (
            <label key={r.symbol} className="flex items-center gap-1 text-xs">{r.symbol}<input className="input h-8 w-16 px-1 text-right" inputMode="decimal" value={custom[r.symbol] ?? ''} placeholder={r.weight_pct.toFixed(0)} onChange={(e) => setCustom({ ...custom, [r.symbol]: e.target.value })} />%</label>))}
            <span className={cn('self-center text-2xs', customSum > 100 ? 'text-loss' : 'text-muted')}>total {customSum.toFixed(0)}% (the rest stays cash) · press Plan again</span>
          </div>)}
        {run.error && <p className="mt-2 text-xs text-loss">{isFailure(run.error) ? `${run.error.message} ${run.error.hint ?? ''}` : 'Failed.'}{isFailure(run.error) && run.error.message.includes('holdings') && <> <Link className="link" to="/portfolio">Portfolio</Link></>}</p>}
      </Card>
      {p && (
        <>
          <KpiStrip>
            <KpiTile label="Holdings now" value={money(p.value)} sub={`to invest ${money(p.budget)}`} />
            <KpiTile label="Buys / sells" value={<span className="text-base">{money(p.totals.buys)} / {money(p.totals.sells)}</span>} sub={`${trades.length} trades`} />
            <KpiTile label="Charges" value={money(p.totals.charges)} />
            <KpiTile label="Gains the sales book" value={money(p.totals.gain_st + p.totals.gain_lt, { signed: true })} sub={`short ${money(p.totals.gain_st)} · long ${money(p.totals.gain_lt)}`} />
            <KpiTile label="Tax if alone" value={money(p.totals.tax_if_alone)} sub="see Tax harvesting" />
            <KpiTile label="Cash left" value={money(p.totals.cash_after)} />
          </KpiStrip>
          <Card flush className="mt-3" title="The plan" right={<span className="flex gap-2">
            <Button size="sm" variant="ghost" icon={<Download className="h-3.5 w-3.5" />} onClick={() => downloadCsv('rebalance-plan.csv', p.rows.map((r) => ({ ...r })))}>CSV</Button>
            <Button size="sm" variant="primary" disabled={!tickets.length} onClick={() => setBasket(true)}>Review as a basket</Button></span>}>
            <div className="overflow-x-auto"><table className="w-full text-[13px]">
              <thead className="text-2xs text-muted"><tr className="text-left"><th className="px-4 py-1.5">Stock</th><th className="px-2 text-right">Now</th><th className="px-2 text-right">Weight → target</th><th className="px-2 text-right">Qty → target</th><th className="px-2">Trade</th><th className="px-2 text-right">Value</th><th className="px-4 text-right">Gain booked</th></tr></thead>
              <tbody className="divide-y divide-line">{p.rows.map((r) => (
                <tr key={r.symbol}>
                  <td className="px-4 py-1.5 font-semibold"><Link to={`/chart/${r.symbol}`} className="hover:text-accent">{r.symbol}</Link></td>
                  <td className="num px-2 text-right">{num(r.price, 2)}</td>
                  <td className="num px-2 text-right">{pct(r.weight_pct, { signed: false })} → {pct(r.target_pct, { signed: false })}</td>
                  <td className="num px-2 text-right">{r.qty} → {r.target_qty}</td>
                  <td className={cn('px-2 font-semibold', r.side === 'BUY' ? 'text-profit' : r.side === 'SELL' ? 'text-loss' : 'text-muted')}>{r.side ? `${r.side} ${r.trade_qty}` : r.skipped_small ? 'too small' : '—'}</td>
                  <td className="num px-2 text-right">{r.trade_value ? money(r.trade_value) : '—'}</td>
                  <td className="num px-4 text-right">{r.gain_st != null ? <span className={(r.gain_st + (r.gain_lt ?? 0)) >= 0 ? 'text-profit' : 'text-loss'}>{money(r.gain_st + (r.gain_lt ?? 0), { signed: true })}</span> : '—'}</td>
                </tr>))}</tbody>
            </table></div>
          </Card>
          <p className="mt-3 text-2xs text-faint">{p.note}</p>
          <BasketDialog open={basket} onClose={() => setBasket(false)} tickets={tickets} />
        </>
      )}
    </div>
  )
}
