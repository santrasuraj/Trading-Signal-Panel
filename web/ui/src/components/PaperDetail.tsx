// Paper-trading detail for one strategy (used by /paper/:key and the strategy detail Paper tab).

import { useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { usePaper, usePaperDetail } from '@/api/hooks'
import type { PaperPosition, PaperSummary, PaperTrade } from '@/api/types'
import { TonePill } from './badges'
import { LinesChart, type LineDef } from './charts/LinesChart'
import { EvidenceMeter } from './charts/svg'
import { DataTable, SymbolCell, type Col } from './DataTable'
import { KpiStrip, KpiTile } from './domain'
import { EmptyState, ErrorState, SkeletonChart, SkeletonKpis } from './feedback'
import { Money, Pct, Price, Qty, Risk } from './num'
import { Card } from './ui'
import { date, money, pct, pts } from '@/lib/format'

export function verdictLabel(p: Pick<PaperSummary, 'days' | 'level'>, minDays = 21): string {
  if (p.days < minDays) return 'Too early to judge'
  return p.level === 'good' ? 'Ahead (probably luck)' : p.level === 'bad' ? 'Behind backtest' : 'In line with backtest'
}

export function PaperDetailView({ k }: { k: string }) {
  const q = usePaperDetail(k)
  const minDays = usePaper().data?.min_days_to_judge ?? 21   // server config, same threshold as the Paper list
  const nav = useNavigate()
  const lines: LineDef[] = useMemo(() => {
    const e = q.data?.equity
    if (!e) return []
    const color = (id: string) => (id === 'paper' ? 'accent' : id === 'nifty500' ? 'muted' : 'faint') as LineDef['color']
    return e.series.map((s) => ({ id: s.id, label: s.label, v: s.v, color: color(s.id), width: s.id === 'paper' ? 2 : 1, style: s.id === 'paper' ? 'solid' : s.id === 'nifty500' ? 'dashed' : 'dotted', format: (v: number) => money(v) }))
  }, [q.data])

  if (q.error) return <div className="card"><ErrorState error={q.error} onRetry={() => void q.refetch()} /></div>
  const d = q.data
  if (!d) return <div className="space-y-3"><SkeletonKpis n={5} /><div className="card"><SkeletonChart /></div></div>
  const s = d.summary

  const openCols: Col<PaperPosition>[] = [
    { id: 'sym', header: 'Symbol', value: (r) => r.symbol, cell: (r) => <SymbolCell symbol={r.symbol} />, sticky: true, mobile: 'primary' },
    { id: 'fill', header: 'Filled', value: (r) => r.entry_date, cell: (r) => <span className="num text-muted">{date(r.entry_date, { year: false })}</span> },
    { id: 'buy', header: 'Fill ₹', align: 'right', value: (r) => r.entry_price, cell: (r) => <Price v={r.entry_price} /> },
    { id: 'qty', header: 'Qty', align: 'right', value: (r) => r.qty, cell: (r) => <Qty v={r.qty} /> },
    { id: 'now', header: 'Now ₹', align: 'right', value: (r) => r.last_price, cell: (r) => <Price v={r.last_price} />, mobile: 'value' },
    { id: 'val', header: 'Value ₹', align: 'right', value: (r) => r.value, cell: (r) => <Money v={r.value} /> },
    { id: 'pnl', header: 'P&L ₹', align: 'right', value: (r) => r.pnl, cell: (r) => <Money v={r.pnl} signed color /> },
    { id: 'ret', header: 'Return', align: 'right', value: (r) => r.ret_pct, cell: (r) => <Pct v={r.ret_pct} />, mobile: 'change' },
    { id: 'stop', header: 'Stop ₹', align: 'right', value: (r) => r.stop, cell: (r) => <Price v={r.stop} /> },
    { id: 'days', header: 'Days', align: 'right', value: (r) => r.days, cell: (r) => <span className="num">{r.days}</span> },
    { id: 'via', header: 'Via', value: (r) => r.via, cell: (r) => <span className="text-muted">{r.via}</span> },
  ]
  const tradeCols: Col<PaperTrade>[] = [
    { id: 'sym', header: 'Symbol', value: (r) => r.symbol, cell: (r) => <SymbolCell symbol={r.symbol} />, sticky: true, mobile: 'primary' },
    { id: 'in', header: 'Bought', value: (r) => r.entry_date, cell: (r) => <span className="num text-muted">{date(r.entry_date, { year: false })}</span> },
    { id: 'buy', header: 'Buy ₹', align: 'right', value: (r) => r.entry_price, cell: (r) => <Price v={r.entry_price} /> },
    { id: 'out', header: 'Sold', value: (r) => r.exit_date, cell: (r) => <span className="num text-muted">{date(r.exit_date, { year: false })}</span> },
    { id: 'sell', header: 'Sell ₹', align: 'right', value: (r) => r.exit_price, cell: (r) => <Price v={r.exit_price} /> },
    { id: 'qty', header: 'Qty', align: 'right', value: (r) => r.qty, cell: (r) => <Qty v={r.qty} /> },
    { id: 'pnl', header: 'P&L ₹', align: 'right', value: (r) => r.pnl, cell: (r) => <Money v={r.pnl} signed color />, mobile: 'value' },
    { id: 'ret', header: 'Return', align: 'right', value: (r) => r.ret_pct, cell: (r) => <Pct v={r.ret_pct} />, mobile: 'change' },
    { id: 'days', header: 'Days', align: 'right', value: (r) => r.days, cell: (r) => <span className="num">{r.days}</span> },
    { id: 'why', header: 'Reason', value: (r) => r.reason, cell: (r) => <span className="text-muted">{r.reason}</span> },
  ]

  return (
    <div className="space-y-3">
      {/* five fixed columns from md: auto-fit wrapped it 4 + 1 at 800 px */}
      <KpiStrip gridClass="md:grid-cols-5">
        <KpiTile label="Paper value" value={<Money compact v={s.equity} />} sub={<Pct v={s.return_pct} />} />
        <KpiTile label="Nifty 500" value={pct(s.n500_pct)} sub={`same days · Nifty 50 ${pct(s.nifty_pct)}`} />
        <KpiTile label="Backtest expected" value={pct(s.expected_pct)} sub={s.expected_range_pct ? <>range <span className="whitespace-nowrap">{pct(s.expected_range_pct[0])} to {pct(s.expected_range_pct[1])}</span></> : null} />
        <KpiTile label="Worst drop" value={<Risk v={s.max_dd_pct} />} />
        <KpiTile label="Charges + slippage" value={<Money compact v={s.fees + s.slippage} />} sub={`${s.trades} closed · ${s.open} open · ${s.pending} pending`} />
      </KpiStrip>
      <Card title="Verdict" right={<TonePill tone={s.level}>{verdictLabel(s, minDays)}</TonePill>}>
        <p className="text-[13px] leading-6 text-fg">{s.verdict}</p>
        {s.comparison && <p className="mt-1 text-xs text-muted">{s.comparison}</p>}
        <div className="mt-4">
          <div className="mb-2 flex flex-wrap justify-between gap-2 text-xs text-muted">
            <span>Gap vs Nifty 500: <span className="num font-medium text-fg">{pts(s.excess_pct)} pts</span></span>
            {/* point-in-time expectations get no haircut (it equals 'expected'): no second marker then */}
            <span>Expected {pts(s.expected_excess_pct)}{s.haircut_excess_pct !== s.expected_excess_pct && <> · after bias haircut {pts(s.haircut_excess_pct)}</>} · noise ±{pct(s.noise_pct, { signed: false })}</span>
          </div>
          <EvidenceMeter excess={s.excess_pct} expected={s.expected_excess_pct} haircut={s.haircut_excess_pct !== s.expected_excess_pct ? s.haircut_excess_pct : null} noise={s.noise_pct} />
        </div>
      </Card>
      <Card title="Paper equity (₹)" subtitle="Paper portfolio vs Nifty 50 and Nifty 500 scaled to the same capital" flush>
        {d.equity.t.length > 1 ? <LinesChart t={d.equity.t} lines={lines} height={260} /> : <EmptyState compact title="Not enough paper days for a chart yet">The first paper orders fill at the next market open.</EmptyState>}
      </Card>
      {d.pending.length > 0 && (
        <Card title={`Pending orders (${d.pending.length})`} subtitle="Fill at the next official open" flush>
          <ul className="divide-y divide-line">{d.pending.map((p) => (
            <li key={`${p.action}${p.symbol}`} className="flex items-center gap-3 px-4 py-2 text-[13px]"><span className={p.action === 'BUY' ? 'font-semibold text-profit' : 'font-semibold text-loss'}>{p.action}</span><span className="font-semibold">{p.symbol}</span><span className="text-muted">{p.reason}</span></li>
          ))}</ul>
        </Card>
      )}
      <Card title={`Open positions (${d.open.length})`} flush>
        <DataTable id="paper.open" data={d.open} columns={openCols} rowKey={(r) => r.symbol} onRowClick={(r) => nav(`/chart/${r.symbol}`)} empty={<EmptyState compact title="No open paper positions" />} />
      </Card>
      <Card title={`Closed trades (${d.trades.length})`} flush>
        <DataTable id="paper.trades" data={d.trades} columns={tradeCols} rowKey={(r) => `${r.symbol}${r.entry_date}${r.exit_date}`} pageSize={50} exportName={`paper-${k}-trades`} empty={<EmptyState compact title="No closed paper trades yet" />} />
      </Card>
      <p className="text-2xs text-faint">Journal: {d.journal_days} scan day{d.journal_days === 1 ? '' : 's'}, last {date(d.last_journal)}; cash {money(d.cash)} of {money(d.capital)}. Recomputed from the journal and stored prices on every view.</p>
    </div>
  )
}
