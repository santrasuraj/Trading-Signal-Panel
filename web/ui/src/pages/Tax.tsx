// Capital gains and tax harvesting `/tax`: each lot short or long term, this financial year's tax, and what to sell
// before 31 March (web/api/services/tax_svc.py). Not tax advice: the broker's tax P&L report is the record.

import { Link } from 'react-router-dom'
import { Receipt } from 'lucide-react'
import { useTax, type Harvest, type TaxLot } from '@/api/desk'
import { KpiStrip, KpiTile, PageHeader } from '@/components/domain'
import { Banner, EmptyState, ErrorState, SkeletonKpis } from '@/components/feedback'
import { Card, Field } from '@/components/ui'
import { date as fmtDate, money, moneyCompact, pct, qty as fmtQty, toneClass } from '@/lib/format'
import { useLocalStorage } from '@/lib/useLocalStorage'
import { cn } from '@/lib/csv'

const toNum = (s: string): number | null => { const v = Number(s.replace(/[,₹\s]/g, '')); return s.trim() !== '' && Number.isFinite(v) ? v : null }

function HarvestTable({ h, kind }: { h: Harvest; kind: 'gain' | 'loss' }) {
  if (!h.rows.length) return null
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-[13px]">
        <thead className="text-2xs text-muted"><tr className="text-left">
          <th className="px-4 py-1.5">Stock</th><th className="px-2 text-right">Sell qty</th><th className="px-2 text-right">At</th>
          <th className="px-2 text-right">Value</th><th className="px-2 text-right">{kind === 'gain' ? 'Gain booked' : 'Loss booked'}</th>
          {kind === 'loss' && <th className="px-2 text-right">Tax saved</th>}<th className="px-4 text-right">Charges</th></tr></thead>
        <tbody className="divide-y divide-line">{h.rows.map((r) => (
          <tr key={r.id}>
            <td className="px-4 py-1.5 font-semibold"><Link to={`/chart/${r.symbol}`} className="hover:text-accent">{r.symbol}</Link>{r.term && <span className="ml-1 text-2xs font-normal text-muted">{r.term} term</span>}</td>
            <td className="num px-2 text-right">{fmtQty(r.qty)}{r.qty < r.of_qty && <span className="text-2xs text-muted"> of {fmtQty(r.of_qty)}</span>}</td>
            <td className="num px-2 text-right">{money(r.price, { dp: 2 })}</td>
            <td className="num px-2 text-right">{money(r.value)}</td>
            <td className={cn('num px-2 text-right', kind === 'gain' ? 'text-profit' : 'text-loss')}>{money(kind === 'gain' ? r.gain : -(r.loss ?? 0))}</td>
            {kind === 'loss' && <td className="num px-2 text-right text-profit">{money(r.tax_saved)}</td>}
            <td className="num px-4 text-right text-muted">{money(r.cost)}</td>
          </tr>))}</tbody>
      </table>
    </div>
  )
}

function LotsTable({ lots }: { lots: TaxLot[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-[13px]">
        <thead className="text-2xs text-muted"><tr className="text-left">
          <th className="px-4 py-1.5">Stock</th><th className="px-2 text-right">Qty</th><th className="px-2">Bought</th><th className="px-2 text-right">Buy</th>
          <th className="px-2 text-right">Now</th><th className="px-2 text-right">Gain</th><th className="px-4">Term</th></tr></thead>
        <tbody className="divide-y divide-line">{lots.map((x) => (
          <tr key={x.id}>
            <td className="px-4 py-1.5 font-semibold">{x.symbol}</td>
            <td className="num px-2 text-right">{fmtQty(x.qty)}</td>
            <td className="px-2">{x.buy_date ? fmtDate(x.buy_date) : <span className="text-warn">no date</span>}</td>
            <td className="num px-2 text-right">{money(x.buy_price, { dp: 2 })}</td>
            <td className="num px-2 text-right">{money(x.price, { dp: 2 })}</td>
            <td className={cn('num px-2 text-right', toneClass(x.gain))}>{money(x.gain, { signed: true })} <span className="text-2xs">{pct(x.gain_pct)}</span></td>
            <td className="px-4">{x.grandfathered ? <span className="text-warn" title="Bought before 1 Feb 2018: grandfathered cost">pre-2018</span>
              : x.term === 'long' ? <span className="text-profit">Long term</span>
                : x.term === 'short' ? <span>Short term <span className="text-2xs text-muted">· long from {fmtDate(x.lt_from)}</span></span>
                  : <span className="text-muted">unknown</span>}</td>
          </tr>))}</tbody>
      </table>
    </div>
  )
}

export default function Tax() {
  const [stIn, setStIn] = useLocalStorage<string>('qd.tax.st', '')
  const [ltIn, setLtIn] = useLocalStorage<string>('qd.tax.lt', '')
  const st = toNum(stIn), lt = toNum(ltIn)
  const q = useTax(st, lt)
  const d = q.data
  const p = d?.position
  return (
    <div>
      <PageHeader title="Tax harvesting"
        subtitle={d ? `Financial year ${d.fy} · sell by ${fmtDate(d.trade_by)} (${d.days_left} days) so it settles by 31 March · STCG ${d.rates.stcg_pct}% · LTCG ${d.rates.ltcg_pct}% above ${moneyCompact(d.rates.exempt)} (incl. 4% cess)` : 'Capital gains on your holdings'} />
      <Card className="mb-3" title="Gains already booked this year" subtitle={d ? (d.booked.source === 'fills'
        ? `From Quant Desk's recorded real orders (${d.booked.fills.trades} closed this year). Type your broker's tax P&L totals for the full picture.`
        : 'Your figures. Clear both boxes to use Quant Desk\'s recorded orders.') : undefined}>
        <div className="flex flex-wrap gap-4">
          <Field label="Short-term gain (loss: negative)" hint="Net STCG this year, ₹"><input className="input h-9 w-48" inputMode="decimal" value={stIn} placeholder={d ? String(d.booked.fills.st) : '0'} onChange={(e) => setStIn(e.target.value)} /></Field>
          <Field label="Long-term gain (loss: negative)" hint="Net LTCG this year, ₹"><input className="input h-9 w-48" inputMode="decimal" value={ltIn} placeholder={d ? String(d.booked.fills.lt) : '0'} onChange={(e) => setLtIn(e.target.value)} /></Field>
        </div>
      </Card>
      {q.error ? <ErrorState error={q.error} onRetry={() => q.refetch()} /> : !d || !p ? <SkeletonKpis n={5} /> : (
        <>
          <KpiStrip>
            <KpiTile label="Tax on booked gains" value={money(p.tax)} sub={`STCG ${money(p.st_net)} · taxable LTCG ${money(p.taxable_lt)}`} tone={p.tax > 0 ? 'text-loss' : undefined} />
            <KpiTile label="LTCG exemption left" value={money(p.exempt_left)} sub={`of ${money(p.exempt)} · used ${money(p.exempt_used)}`} tone={p.exempt_left > 0 ? 'text-profit' : undefined} />
            <KpiTile label="Unrealised short term" value={money(d.unrealised.st, { signed: true })} tone={toneClass(d.unrealised.st)} />
            <KpiTile label="Unrealised long term" value={money(d.unrealised.lt, { signed: true })} tone={toneClass(d.unrealised.lt)} />
            <KpiTile label="Losses carried forward" value={money(p.carry_forward)} sub="8 years, if you file on time" />
          </KpiStrip>
          {d.notes.map((n) => <div key={n} className="mt-3"><Banner tone="info">{n}</Banner></div>)}
          {d.lots.length === 0 ? (
            <div className="mt-3"><EmptyState icon={<Receipt />} title="No holdings yet" action={<Link className="text-accent" to="/portfolio">Add holdings on Portfolio</Link>}>Add your holdings with their buy dates to see each lot's tax and what to harvest.</EmptyState></div>
          ) : (
            <div className="mt-3 grid gap-3 xl:grid-cols-2">
              <Card flush title="Use the ₹1.25 lakh exemption (gain harvesting)"
                subtitle={d.harvest_gains.rows.length ? `Sell, then buy back on a LATER day: ${money(d.harvest_gains.gain)} of gains tax-free saves ${money(d.harvest_gains.tax_saved)} of future tax for ${money(d.harvest_gains.cost)} in charges.` : p.exempt_left <= 0 ? 'This year\'s exemption is used up.' : 'No long-term winners to harvest.'}>
                <HarvestTable h={d.harvest_gains} kind="gain" />
                {d.harvest_gains.rows.length > 0 && <p className="px-4 py-2 text-2xs text-muted">A same-day sell and buy-back nets off as an intraday trade and your cost stays the same. The bought-back shares start a new 12-month clock.</p>}
              </Card>
              <Card flush title="Offset booked gains (loss harvesting)"
                subtitle={d.harvest_losses.rows.length ? `Selling these cuts this year's tax by ${money(d.harvest_losses.tax_saved)} for ${money(d.harvest_losses.cost)} in charges.` : p.tax <= 0 ? 'No tax due on booked gains: nothing to offset.' : 'No losing lots that lower the tax.'}>
                <HarvestTable h={d.harvest_losses} kind="loss" />
                {d.harvest_losses.rows.length > 0 && <p className="px-4 py-2 text-2xs text-muted">India has no wash-sale rule, but buy back on a later day, not the same day.</p>}
              </Card>
              {d.wait.length > 0 && (
                <Card flush title="Wait before selling" subtitle="Short-term winners that turn long term soon: selling after the date is taxed at the lower rate.">
                  <ul className="divide-y divide-line">{d.wait.map((w) => (
                    <li key={w.id} className="flex flex-wrap items-baseline justify-between gap-2 px-4 py-2 text-[13px]">
                      <span><b>{w.symbol}</b> · gain {money(w.gain)} · long term from {fmtDate(w.lt_from)} ({w.days} days)</span>
                      <span className="text-profit">saves ~{money(w.tax_saved)}</span>
                    </li>))}</ul>
                </Card>
              )}
              <Card flush title="Your lots" subtitle={`Priced at ${d.price_source === 'close' ? 'the last close' : 'the live price'}`} className="xl:col-span-2">
                <LotsTable lots={d.lots} />
              </Card>
            </div>
          )}
          <p className="mt-4 text-2xs text-faint">Listed shares with STT paid. Long term = held more than 12 months. A short-term loss offsets short then long-term gains; a long-term loss only long-term gains. Surcharge, the 87A rebate and grandfathering are not computed. Not tax advice: your broker's tax P&L report and your adviser have the final word.</p>
        </>
      )}
    </div>
  )
}
