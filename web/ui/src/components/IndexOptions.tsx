// Index options (Signals page tab): the scan's daily options verdict for every NSE index with options - NIFTY,
// BANKNIFTY, FINNIFTY, MIDCPNIFTY, NIFTYNXT50 - for the nearest two expiries (GET /api/options/indices). BUY CALL /
// BUY PUT only when the index's own tested setup points one way and an option is worth more than it costs on the
// index's history; NO TRADE is the usual answer. The chain's numbers (ATM premiums, IV, expected move) are shown next
// to it; PCR and max pain for reference only. A BUY shows its trade in premiums (entry, stop, target, lot, capital); a
// NO TRADE shows the option nearest to passing and why it fails; "Why each verdict" lists every check and the direction's
// tested sources. Each index links to its full chain on the Options page.

import { Link } from 'react-router-dom'
import { Check, Info, Layers, X } from 'lucide-react'
import { isBuy, useIndexOptions, type IndexOptionRow, type IndexVerdict } from '@/api/indexOptions'
import { DataTable, type Col } from '@/components/DataTable'
import { Banner, EmptyState, ErrorState, SkeletonRows } from '@/components/feedback'
import { Price } from '@/components/num'
import { PlanLine } from '@/components/OptionVerdict'
import { Card } from '@/components/ui'
import { cn } from '@/lib/csv'
import { date, dateTimeIST, num } from '@/lib/format'

const VERDICT: Record<IndexVerdict, [string, string]> = {
  BUY_CALL: ['BUY CALL', 'bg-profit/15 text-profit'],
  BUY_PUT: ['BUY PUT', 'bg-loss/15 text-loss'],
  NO_TRADE: ['NO TRADE', 'bg-raised text-muted'],
  NO_DATA: ['NO DATA', 'bg-raised text-faint'],
}

function VerdictBadge({ r }: { r: IndexOptionRow }) {
  if (!r.verdict) return <span className="text-2xs text-faint" title="The scan gives this expiry its first verdict after the next trading day's close">Not yet</span>
  const [label, tone] = VERDICT[r.verdict]
  return <span className={cn('inline-flex h-5 items-center whitespace-nowrap rounded-full px-2 text-2xs font-semibold', tone)} title={r.verdict_day ? `Verdict of ${r.verdict_day}` : undefined}>{label}</span>
}

function signalText(r: IndexOptionRow): string {
  if (r.pick && r.pick.strike != null) {
    const side = r.pick.side === 'ce' ? 'CE' : 'PE'
    return `${num(r.pick.strike, 0)} ${side} at ${num(r.pick.premium, 2)} · breakeven ${num(r.pick.breakeven, 2)}`
  }
  if (r.headline) return r.headline.replace(/^No options edge: /, '')
  if (r.verdict === 'NO_TRADE') return 'No options edge on the scan\'s checks (verdicts before 14 Nov 2026 kept no reason).'
  if (r.verdict === 'NO_DATA') return 'Not enough price history or option prices to value the options.'
  return r.verdict ? '' : 'First verdict after the next trading day\'s scan.'
}

function closestText(r: IndexOptionRow): string | null {
  const c = r.closest
  if (isBuy(r.verdict) || !c || c.strike == null) return null
  const edge = c.edge_pct != null ? `${c.edge_pct > 0 ? '+' : ''}${num(c.edge_pct, 0)}%` : '—'
  return `Closest: ${num(c.strike, 0)} ${c.side.toUpperCase()} at ${num(c.premium, 2)} · fair ${edge} · ${num(c.prob_profit_pct, 0)}% chance${c.fails.length ? ` · ${c.fails.length} check${c.fails.length === 1 ? '' : 's'} failed` : ' · price checks pass'}`
}

const COLS: Col<IndexOptionRow>[] = [
  { id: 'sym', header: 'Index', value: (r) => r.symbol, sticky: true, mobile: 'primary', cell: (r) => (
    <Link to={`/options/${r.symbol}`} className="block hover:underline" title={`Open the ${r.symbol} option chain`}>
      <span className="block font-semibold">{r.symbol}</span>
      <span className="block text-2xs text-muted">{r.name}</span>
    </Link>
  ) },
  { id: 'exp', header: 'Expiry', value: (r) => r.expiry, cell: (r) => (
    <span className="whitespace-nowrap"><span className="num">{date(r.expiry, { year: false })}</span>{r.days_to_expiry != null && <span className="ml-1 text-2xs text-muted">{num(r.days_to_expiry, 0)}d</span>}</span>
  ) },
  { id: 'spot', header: 'Spot', align: 'right', value: (r) => r.spot, cell: (r) => <Price v={r.spot} /> },
  { id: 'verdict', header: 'Verdict', value: (r) => r.verdict ?? '', cell: (r) => <VerdictBadge r={r} />, mobile: 'secondary', label: 'Verdict' },
  { id: 'why', header: 'Signal / reason', value: (r) => signalText(r), cell: (r) => (
    <span className={cn('block min-w-[260px] max-w-[340px] whitespace-normal text-xs', isBuy(r.verdict) ? 'font-medium text-fg' : 'text-muted')} title={r.headline ?? undefined}>
      <span className="line-clamp-2">{signalText(r)}</span>
      {r.plan && <span className="num block text-2xs text-muted">stop {num(r.plan.stop, 2)} · target {num(r.plan.target, 2)} · lot {num(r.plan.lot, 0)} · capital ₹{num(r.plan.capital, 0)}</span>}
      {closestText(r) && <span className="block text-2xs text-faint" title={r.closest?.fails.join('; ') || undefined}>{closestText(r)}</span>}
      {r.bias && r.bias !== 'none' && !isBuy(r.verdict) && <span className="text-2xs text-faint">tested lean: {r.bias}</span>}
    </span>
  ) },
  { id: 'ce', header: 'ATM CE ₹', title: 'Last price of the at-the-money call', align: 'right', value: (r) => r.atm_call, cell: (r) => <Price v={r.atm_call} /> },
  { id: 'pe', header: 'ATM PE ₹', title: 'Last price of the at-the-money put', align: 'right', value: (r) => r.atm_put, cell: (r) => <Price v={r.atm_put} /> },
  { id: 'iv', header: 'IV', title: 'Implied volatility at the money', align: 'right', value: (r) => r.atm_iv_pct, cell: (r) => <span className="num">{r.atm_iv_pct != null ? `${num(r.atm_iv_pct, 1)}%` : '—'}</span> },
  { id: 'em', header: 'Priced move', title: 'The move to expiry the options price (ATM straddle / spot), and that range', align: 'right', value: (r) => r.expected_move_pct, cell: (r) => (
    <span className="whitespace-nowrap text-right">
      <span className="num block">{r.expected_move_pct != null ? `±${num(r.expected_move_pct, 2)}%` : '—'}</span>
      {r.range_low != null && r.range_high != null && <span className="num block text-2xs text-muted">{num(r.range_low, 0)}–{num(r.range_high, 0)}</span>}
    </span>
  ) },
  { id: 'pcr', header: 'PCR', title: 'Put-call ratio of open interest - reference only: no test here shows it predicts', align: 'right', value: (r) => r.pcr_oi, cell: (r) => <span className="num text-muted">{num(r.pcr_oi, 2)}</span> },
  { id: 'mp', header: 'Max pain', title: 'Reference only: no test here shows it predicts', align: 'right', value: (r) => r.max_pain, cell: (r) => <span className="num text-muted">{num(r.max_pain, 0)}</span> },
]

/** Every check of each verdict, the direction's tested sources and a BUY's trade in premiums. */
function WhyList({ rows }: { rows: IndexOptionRow[] }) {
  const withWhy = rows.filter((r) => r.checks.length > 0 || r.reasons.length > 0)
  if (!withWhy.length) return null
  return (
    <details className="border-t border-line px-4 py-2">
      <summary className="cursor-pointer text-xs font-medium">Why each verdict</summary>
      <div className="mt-2 grid gap-2 lg:grid-cols-2">
        {withWhy.map((r) => (
          <div key={`${r.symbol}${r.expiry}`} className="rounded-md border border-line px-3 py-2 text-xs">
            <div className="mb-1 flex items-center gap-2"><span className="font-semibold">{r.symbol}</span><span className="num text-muted">{date(r.expiry, { year: false })}</span><VerdictBadge r={r} /></div>
            <ul className="space-y-0.5">
              {r.checks.map((c) => (
                <li key={c.name} className="flex items-start gap-1.5">
                  {c.ok ? <Check className="mt-0.5 h-3.5 w-3.5 shrink-0 text-profit" /> : <X className="mt-0.5 h-3.5 w-3.5 shrink-0 text-loss" />}
                  <span><span className="font-medium">{c.name}</span> <span className="text-muted">· {c.detail}</span></span>
                </li>))}
            </ul>
            {r.reasons.length > 0 && <p className="mt-1 text-2xs text-muted"><span className="font-medium text-fg">Direction: </span>{r.reasons.join(' ')}</p>}
            {r.closest && !isBuy(r.verdict) && r.closest.fails.length > 0 && <p className="mt-1 text-2xs text-muted"><span className="font-medium text-fg">Closest option fails: </span>{r.closest.fails.join('; ')}</p>}
            {r.plan && <PlanLine p={r.plan} className="mt-1.5" />}
          </div>))}
      </div>
    </details>
  )
}

/** Daily options verdicts for every NSE index (Signals page, Index options tab). */
export function IndexOptions() {
  const q = useIndexOptions()
  const d = q.data
  if (q.error && !d) return <div className="card"><ErrorState error={q.error} onRetry={() => void q.refetch()} /></div>
  if (!d) return <div className="card"><SkeletonRows rows={4} /></div>
  const buys = d.rows.filter((r) => isBuy(r.verdict)).length
  const t = d.track
  const pct = (v: number | null) => (v == null ? '—' : `${v > 0 ? '+' : ''}${num(v, 1)}%`)
  return (
    <Card
      title={<span className="flex items-center gap-2"><Layers className="h-4 w-4 text-muted" />Index options</span>}
      subtitle={<>NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY and NIFTYNXT50, nearest two expiries · {buys} buy signal{buys === 1 ? '' : 's'} · updated <span className="num">{dateTimeIST(d.generated_at)}</span></>}
      flush
    >
      <div className="border-b border-line px-4 py-2">
        <Banner tone="info" icon={<Info className="h-4 w-4 text-info" />}><span className="text-muted">{d.note}</span></Banner>
      </div>
      {d.rows.length === 0 ? (
        <EmptyState compact title="No index option chain stored yet.">
          <Link to="/options" className="link">Fetch the option chains on the Options page</Link>
        </EmptyState>
      ) : (
        <DataTable id="signals.index-options" data={d.rows} columns={COLS} rowKey={(r) => `${r.symbol}${r.expiry}`} exportName="index-options" />
      )}
      <WhyList rows={d.rows} />
      <div className="space-y-1 border-t border-line px-4 py-2 text-2xs text-faint">
        {d.missing.length > 0 && (
          <p className="text-warn">No chain stored yet for {d.missing.join(', ')}: the 09:12 options task stores them, and the evening scan fetches any still missing before it gives the verdicts (or Fetch now on the Options page).</p>
        )}
        <p>
          Index verdicts so far: {t.recorded} recorded{t.first_day ? ` since ${date(t.first_day)}` : ''}, {t.settled} settled at expiry, {t.buys} buy{t.buys === 1 ? '' : 's'}
          {t.buys > 0 && <> ({t.buy_wins} won, average {pct(t.buy_avg_return_pct)})</>}. For comparison, buying the ATM call every time: {pct(t.atm_call_avg_return_pct)}; the ATM put: {pct(t.atm_put_avg_return_pct)}{t.skipped > 0 ? <>; the closest option of each NO TRADE, bought anyway: {pct(t.skipped_avg_return_pct)} ({t.skipped_wins} of {t.skipped} won) - the test of whether skipping them is right</> : null}.
        </p>
        <p>Options can lose 100% of the premium. You decide and place every trade yourself.</p>
      </div>
    </Card>
  )
}
