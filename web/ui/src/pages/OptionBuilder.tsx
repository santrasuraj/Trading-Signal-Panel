// Options strategy builder `/option-builder`: build a multi-leg position on a stored option chain and see its profit
// and loss at expiry and today, breakevens, maximum profit and loss, Greeks and the chance of profit
// (web/api/services/payoff_svc.py). Prices come from the stored chain; type your own to plan an order.

import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { Plus, Trash2, Layers } from 'lucide-react'
import { deskApi, type Payoff, type PayoffLegIn } from '@/api/desk'
import { useOptChain, useOptStatus } from '@/api/options'
import { KpiStrip, KpiTile, PageHeader } from '@/components/domain'
import { EmptyState, ErrorState, Skeleton } from '@/components/feedback'
import { Button, Card, IconButton } from '@/components/ui'
import { date as fmtDate, money, num } from '@/lib/format'
import { nearestIndex, PRESETS, presetLegs, type PresetId } from '@/lib/optionPresets'
import { useLocalStorage } from '@/lib/useLocalStorage'
import { useWidth } from '@/lib/useWidth'
import { cn } from '@/lib/csv'

const H = 340, PAD = { l: 64, r: 12, t: 12, b: 28 }

function PayoffChart({ p }: { p: Payoff }) {
  const [ref, width] = useWidth<HTMLDivElement>()
  const [hover, setHover] = useState<number | null>(null)
  const w = Math.max(width, 300)
  const xs = p.grid, ys = [...p.at_expiry, ...p.today]
  const x0 = xs[0], x1 = xs[xs.length - 1]
  let y0 = Math.min(0, ...ys), y1 = Math.max(0, ...ys)
  const padY = (y1 - y0) * 0.08 || 1
  y0 -= padY; y1 += padY
  const X = (x: number) => PAD.l + ((x - x0) / (x1 - x0)) * (w - PAD.l - PAD.r)
  const Y = (y: number) => PAD.t + ((y1 - y) / (y1 - y0)) * (H - PAD.t - PAD.b)
  const path = (arr: number[]) => arr.map((y, i) => `${i ? 'L' : 'M'}${X(xs[i]).toFixed(1)},${Y(y).toFixed(1)}`).join('')
  const area = (sign: 1 | -1) => `${path(p.at_expiry.map((y) => (sign > 0 ? Math.max(y, 0) : Math.min(y, 0))))}L${X(x1)},${Y(0)}L${X(x0)},${Y(0)}Z`
  const ticks = Array.from({ length: 6 }, (_, i) => y0 + ((y1 - y0) * i) / 5)
  const xticks = Array.from({ length: 6 }, (_, i) => x0 + ((x1 - x0) * i) / 5)
  const hi = hover != null ? hover : null
  return (
    <div ref={ref} className="relative w-full">
      <svg width={w} height={H} role="img" aria-label="Profit and loss by the underlying's price"
        onMouseMove={(e) => { const r = (e.currentTarget as SVGElement).getBoundingClientRect(); const x = x0 + ((e.clientX - r.left - PAD.l) / (w - PAD.l - PAD.r)) * (x1 - x0); setHover(nearestIndex(xs, x)) }}
        onMouseLeave={() => setHover(null)}>
        <rect x={X(p.one_sd[0])} y={PAD.t} width={Math.max(0, X(p.one_sd[1]) - X(p.one_sd[0]))} height={H - PAD.t - PAD.b} fill="rgb(var(--accent) / 0.06)" />
        {ticks.map((t) => <g key={t}><line x1={PAD.l} x2={w - PAD.r} y1={Y(t)} y2={Y(t)} stroke="rgb(var(--line))" /><text x={PAD.l - 6} y={Y(t) + 4} textAnchor="end" className="fill-[rgb(var(--muted))] text-[10px]">{money(t)}</text></g>)}
        {xticks.map((t) => <text key={t} x={X(t)} y={H - 8} textAnchor="middle" className="fill-[rgb(var(--muted))] text-[10px]">{num(t, 0)}</text>)}
        <path d={area(1)} fill="rgb(var(--profit) / 0.18)" />
        <path d={area(-1)} fill="rgb(var(--loss) / 0.18)" />
        <line x1={PAD.l} x2={w - PAD.r} y1={Y(0)} y2={Y(0)} stroke="rgb(var(--line-strong))" />
        <path d={path(p.today)} fill="none" stroke="rgb(var(--accent))" strokeWidth={1.5} strokeDasharray="5 4" />
        <path d={path(p.at_expiry)} fill="none" stroke="rgb(var(--fg))" strokeWidth={2} />
        <line x1={X(p.spot)} x2={X(p.spot)} y1={PAD.t} y2={H - PAD.b} stroke="rgb(var(--accent))" strokeWidth={1} />
        <text x={X(p.spot) + 4} y={PAD.t + 10} className="fill-[rgb(var(--accent))] text-[10px]">spot {num(p.spot, 0)}</text>
        {p.breakevens.map((b) => <g key={b}><circle cx={X(b)} cy={Y(0)} r={3.5} fill="rgb(var(--warn))" /><text x={X(b)} y={Y(0) + 14} textAnchor="middle" className="fill-[rgb(var(--warn))] text-[10px]">{num(b, 0)}</text></g>)}
        {hi != null && hi >= 0 && <line x1={X(xs[hi])} x2={X(xs[hi])} y1={PAD.t} y2={H - PAD.b} stroke="rgb(var(--muted))" strokeDasharray="2 3" />}
      </svg>
      {hi != null && hi >= 0 && (
        <div className="pointer-events-none absolute right-3 top-3 rounded border border-line bg-panel px-2 py-1 text-2xs shadow">
          <div>At {num(xs[hi], 0)} ({((xs[hi] / p.spot - 1) * 100).toFixed(1)}%)</div>
          <div>Expiry: <b className={p.at_expiry[hi] >= 0 ? 'text-profit' : 'text-loss'}>{money(p.at_expiry[hi], { signed: true })}</b></div>
          <div>{p.days ? `In ${p.days} days` : 'Today'}: <b className={p.today[hi] >= 0 ? 'text-profit' : 'text-loss'}>{money(p.today[hi], { signed: true })}</b></div>
        </div>
      )}
      <div className="mt-1 flex flex-wrap gap-4 px-1 text-2xs text-muted">
        <span><span className="mr-1 inline-block h-0.5 w-4 bg-fg align-middle" />At expiry</span>
        <span><span className="mr-1 inline-block h-0.5 w-4 border-t border-dashed border-accent align-middle" />{p.days ? `In ${p.days} days` : 'Today'}{p.iv_shift ? `, volatility ${p.iv_shift > 0 ? '+' : ''}${p.iv_shift} pts` : ''}</span>
        <span><span className="mr-1 inline-block h-2 w-4 bg-accent/10 align-middle" />±1 standard deviation by expiry</span>
      </div>
    </div>
  )
}

export default function OptionBuilder() {
  const st = useOptStatus()
  const chains = st.data?.chains ?? []
  const symbols = [...new Set(chains.map((c) => c.symbol))]
  const [symbol, setSymbol] = useLocalStorage<string>('qd.optb.symbol', 'NIFTY')
  const sym = symbols.includes(symbol) ? symbol : (symbols[0] ?? '')
  const expiries = chains.filter((c) => c.symbol === sym).map((c) => c.expiry)
  const [expiry, setExpiry] = useState<string | undefined>(undefined)
  const exp = expiry && expiries.includes(expiry) ? expiry : expiries[0]
  const chain = useOptChain(sym, exp, 15, false)
  const strikes = useMemo(() => (chain.data?.rows ?? []).map((r) => r.strike), [chain.data])
  const atm = chain.data?.atm ?? null
  const [legs, setLegs] = useState<PayoffLegIn[]>([])
  const [preset, setPreset] = useState<PresetId>('bull_call')
  const [days, setDays] = useState(0)
  const [ivShift, setIvShift] = useState(0)
  const dte = Math.floor(chain.data?.days_to_expiry ?? 0)

  // a new chain (symbol / expiry): start from the chosen preset at the money
  const chainKey = `${chain.data?.symbol}-${chain.data?.expiry}`
  useEffect(() => {
    if (atm != null && strikes.length) { setLegs(presetLegs(preset, strikes, atm)); setDays(0) }
  }, [chainKey]) // eslint-disable-line react-hooks/exhaustive-deps

  const body = { symbol: sym, expiry: exp, legs, days: Math.min(days, dte), iv_shift: ivShift }
  const pay = useQuery({ queryKey: ['payoff', body], queryFn: () => deskApi.payoff(body), enabled: !!sym && legs.length > 0 && legs.every((l) => l.kind === 'FUT' || l.strike != null), placeholderData: keepPreviousData, staleTime: 30_000 })
  const row = (k: number | null) => chain.data?.rows.find((r) => r.strike === k)
  const upd = (i: number, patch: Partial<PayoffLegIn>) => setLegs((ls) => ls.map((l, j) => (j === i ? { ...l, ...patch } : l)))
  const p = pay.data

  if (st.data && !chains.length) {
    return (<div><PageHeader title="Option strategy builder" />
      <EmptyState icon={<Layers />} title="No stored option chains yet" action={<Link className="text-accent" to="/options">Open Options and fetch a chain</Link>}>The builder prices your legs on a stored option chain (NIFTY, BANKNIFTY or a stock).</EmptyState></div>)
  }
  return (
    <div>
      <PageHeader title="Option strategy builder"
        subtitle={chain.data ? `${chain.data.symbol} · expiry ${fmtDate(chain.data.expiry)} (${num(chain.data.days_to_expiry, 1)} days) · spot ${num(chain.data.spot, 2)} · lot ${chain.data.lot ?? '?'} · chain at ${chain.data.time.slice(11, 16)}` : 'Payoff of a multi-leg options position'}
        right={<>
          <select aria-label="Underlying" className="input h-8 px-2 text-[13px]" value={sym} onChange={(e) => { setSymbol(e.target.value); setExpiry(undefined) }}>
            {symbols.map((s) => <option key={s}>{s}</option>)}</select>
          <select aria-label="Expiry" className="input h-8 px-2 text-[13px]" value={exp ?? ''} onChange={(e) => setExpiry(e.target.value)}>
            {expiries.map((e) => <option key={e} value={e}>{fmtDate(e)}</option>)}</select>
        </>} />
      <Card className="mb-3" title="Strategy" subtitle="Pick a ready-made strategy at the money, then change any leg. Prices default to the chain's last trade; type the price you expect to get.">
        <div className="mb-3 flex flex-wrap gap-1.5">
          {PRESETS.map((x) => (
            <button key={x.id} type="button" title={x.view} onClick={() => { setPreset(x.id); if (atm != null) setLegs(presetLegs(x.id, strikes, atm)) }}
              className={cn('rounded border px-2 py-1 text-xs', preset === x.id ? 'border-accent bg-accent/10 text-accent' : 'border-line text-muted hover:text-fg')}>{x.label}</button>))}
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-[13px]">
            <thead className="text-2xs text-muted"><tr className="text-left"><th className="py-1">Side</th><th>Type</th><th>Strike</th><th>Lots</th><th>Price</th><th>IV %</th><th>Bid / ask</th><th /></tr></thead>
            <tbody>{legs.map((l, i) => {
              const r = row(l.strike); const side = l.kind === 'FUT' ? null : r?.[l.kind === 'CE' ? 'ce' : 'pe']
              return (
                <tr key={i} className="border-t border-line">
                  <td className="py-1.5 pr-2"><button type="button" onClick={() => upd(i, { side: l.side === 'buy' ? 'sell' : 'buy' })}
                    className={cn('w-14 rounded px-2 py-1 text-xs font-semibold text-white', l.side === 'buy' ? 'bg-profit' : 'bg-loss')}>{l.side === 'buy' ? 'BUY' : 'SELL'}</button></td>
                  <td className="pr-2"><select aria-label="Type" className="input h-8 px-1" value={l.kind} onChange={(e) => upd(i, { kind: e.target.value as PayoffLegIn['kind'], price: null, iv_pct: null })}>
                    <option value="CE">Call</option><option value="PE">Put</option><option value="FUT">Future</option></select></td>
                  <td className="pr-2">{l.kind === 'FUT' ? <span className="text-muted">—</span> : (
                    <select aria-label="Strike" className="input h-8 px-1" value={l.strike ?? ''} onChange={(e) => upd(i, { strike: Number(e.target.value), price: null, iv_pct: null })}>
                      {strikes.map((k) => <option key={k} value={k}>{num(k, 0)}{k === atm ? ' (ATM)' : ''}</option>)}</select>)}</td>
                  <td className="pr-2"><input aria-label="Lots" className="input h-8 w-16 px-1" type="number" min={1} max={500} value={l.lots} onChange={(e) => upd(i, { lots: Math.max(1, Math.min(500, Number(e.target.value) || 1)) })} /></td>
                  <td className="pr-2"><input aria-label="Price" className="input h-8 w-24 px-1" type="number" min={0} step="0.05" placeholder={side?.ltp != null ? String(side.ltp) : l.kind === 'FUT' ? 'forward' : ''}
                    value={l.price ?? ''} onChange={(e) => upd(i, { price: e.target.value === '' ? null : Number(e.target.value) })} /></td>
                  <td className="pr-2">{l.kind === 'FUT' ? <span className="text-muted">—</span> : <input aria-label="Implied volatility" className="input h-8 w-20 px-1" type="number" min={1} max={300} step="0.5" placeholder={side?.iv_pct != null ? String(side.iv_pct) : ''}
                    value={l.iv_pct ?? ''} onChange={(e) => upd(i, { iv_pct: e.target.value === '' ? null : Number(e.target.value) })} />}</td>
                  <td className="num pr-2 text-2xs text-muted">{side ? `${side.bid ?? '—'} / ${side.ask ?? '—'}` : ''}</td>
                  <td><IconButton label="Remove leg" size="sm" onClick={() => setLegs((ls) => ls.filter((_, j) => j !== i))}><Trash2 className="h-4 w-4" /></IconButton></td>
                </tr>)
            })}</tbody>
          </table>
        </div>
        <div className="mt-2 flex flex-wrap items-center gap-4">
          <Button variant="subtle" size="sm" disabled={legs.length >= 8 || atm == null} onClick={() => setLegs((ls) => [...ls, { side: 'buy', kind: 'CE', strike: atm, lots: 1 }])}><Plus className="h-4 w-4" /> Add leg</Button>
          <label className="flex items-center gap-2 text-xs text-muted">Days from now <input type="range" min={0} max={Math.max(dte, 0)} value={Math.min(days, dte)} onChange={(e) => setDays(Number(e.target.value))} /> <span className="num w-8 text-fg">{Math.min(days, dte)}</span></label>
          <label className="flex items-center gap-2 text-xs text-muted">Volatility change <input type="range" min={-15} max={15} value={ivShift} onChange={(e) => setIvShift(Number(e.target.value))} /> <span className="num w-10 text-fg">{ivShift > 0 ? '+' : ''}{ivShift} pts</span></label>
        </div>
      </Card>
      {pay.error ? <ErrorState error={pay.error} /> : !p ? (legs.length ? <Skeleton className="h-[420px] w-full" /> : <EmptyState title="Add a leg">Pick a strategy or add a leg.</EmptyState>) : (
        <>
          <KpiStrip>
            <KpiTile label={p.kind === 'credit' ? 'Net credit (you receive)' : 'Net debit (you pay)'} value={money(Math.abs(p.premium))} tone={p.kind === 'credit' ? 'text-profit' : undefined} />
            <KpiTile label="Max profit" value={p.max_profit == null ? 'Unlimited' : money(p.max_profit)} tone="text-profit" />
            <KpiTile label="Max loss" value={p.max_loss == null ? 'Unlimited' : money(p.max_loss)} tone="text-loss" sub={p.max_loss == null ? 'a big move against you has no floor' : undefined} />
            <KpiTile label="Breakeven" value={p.breakevens.length ? <span className={p.breakevens.length > 1 ? 'text-base' : undefined}>{p.breakevens.map((b) => num(b, 0)).join(' / ')}</span> : '—'} sub={p.breakevens.length ? p.breakevens.map((b) => `${((b / p.spot - 1) * 100).toFixed(1)}%`).join(' / ') : undefined} />
            <KpiTile label="Chance of profit" value={p.pop_pct != null ? `${p.pop_pct.toFixed(0)}%` : '—'} sub={`at ${p.atm_iv_pct.toFixed(1)}% volatility (a model)`} />
            <KpiTile label="Reward : risk" value={p.reward_risk != null ? `${p.reward_risk.toFixed(2)} : 1` : '—'} />
          </KpiStrip>
          <Card className="mt-3" title="Profit and loss" subtitle={`Delta ${num(p.greeks.delta, 1)} (like holding ${num(p.greeks.delta, 0)} units) · theta ${money(p.greeks.theta, { signed: true })} a day · vega ${money(p.greeks.vega, { signed: true })} per volatility point · gamma ${num(p.greeks.gamma, 4)}`}>
            <PayoffChart p={p} />
          </Card>
          <p className="mt-3 text-2xs text-faint">{p.note} Black-76 on the chain's forward; each leg at its implied volatility. Charges, slippage and early exercise are ignored (NSE options are European). Planning only: orders go through Orders or your broker.</p>
        </>
      )}
    </div>
  )
}
