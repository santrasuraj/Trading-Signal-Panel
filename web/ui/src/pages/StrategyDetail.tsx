// Strategy detail `/strategies/:key/:tab` (spec 3.3): header, 10 KPI tiles, tabs Performance / Trades /
// Holdings & orders / Rules & evidence / Paper.

import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { AlertTriangle, Ban, ChevronLeft, ChevronRight, ExternalLink, FlaskConical, NotebookPen } from 'lucide-react'
import { useCurve, useStrategies, useStrategy, useTrades } from '@/api/hooks'
import type { CurveRange, ModelPosition, PerfStats, RankingRow, StrategyDetail as Detail, TradeRow, WindowMetrics } from '@/api/types'
import { EtfChip, EvidenceChip, HorizonChip, LifecycleBadge, ResultsChip, StatusBadge, WarnChip } from '@/components/badges'
import { EquityChart } from '@/components/charts/EquityChart'
import { MonthlyHeatmap, ReturnHistogram, TimingRangeBar, YearlyHeatmap } from '@/components/charts/svg'
import { DataTable, SymbolCell, type Col } from '@/components/DataTable'
import { BiasNote, Help, KpiStrip, KpiTile, OrdersTable, flatteredNote } from '@/components/domain'
import { EmptyState, ErrorState, FeatureUnavailable, RefreshFailed, Skeleton, SkeletonChart, SkeletonKpis, SkeletonRows } from '@/components/feedback'
import { PaperDetailView } from '@/components/PaperDetail'
import { Pct, Price } from '@/components/num'
import { Card, Chip, IconButton, Segmented, Tabs } from '@/components/ui'
import type { CurveMode } from '@/lib/chartMappers'
import { cn } from '@/lib/csv'
import { date, num, pct, pts, ratio } from '@/lib/format'
import { typingTarget } from '@/lib/useMedia'
import { EVIDENCE, HORIZONS, kindLabel, lostMoney } from '@/lib/vocab'

type Tab = 'performance' | 'trades' | 'holdings' | 'rules' | 'paper'

function Kpis({ d }: { d: Detail }) {
  const s = d.strategy
  const f = d.metrics.full
  const t = s.timing
  const edge = s.edges.primary === 'ew' ? s.edges.vs_ew_cagr_pct : s.edges.vs_nifty_cagr_pct
  const fac = f.factor_benchmark
  return (
    <KpiStrip gridClass="md:grid-cols-5 min-[1600px]:grid-cols-10">
      <KpiTile label="CAGR" title="Backtest yearly return (CAGR), with the timing-luck range" value={pct(f.cagr_pct, { signed: false })} sub={t && t.low != null ? (
        // the bar gives way (down to 24 px) so the range never breaks into "41.9–" / "47.5" on a narrow tile
        <span className="flex items-center gap-1.5"><span className="min-w-[24px] max-w-[64px] flex-1"><TimingRangeBar low={t.low} high={t.high} base={t.base_cagr_pct} consistent={t.consistent} compact /></span><span className={cn('shrink-0 whitespace-nowrap', !t.consistent && 'text-warn')}>{num(t.low, 1)}–{num(t.high, 1)}</span></span>
      ) : 'backtest'} />
      <KpiTile label="After tax" value={pct(f.after_tax_cagr_pct, { signed: false })} sub="STCG/LTCG applied" />
      <KpiTile label={s.edges.primary === 'ew' ? 'Edge vs avg stock' : 'Edge vs Nifty 50'} value={pts(edge)} tone={edge == null ? undefined : edge > 0 ? 'text-profit' : 'text-loss'} sub={s.edges.primary === 'ew' ? `avg stock ${pct(f.ew_benchmark?.cagr_pct, { signed: false })}/yr` : `Nifty 50 ${pct(f.benchmark?.cagr_pct, { signed: false })}/yr`} />
      <KpiTile label="vs factor index" value={fac ? pts(s.edges.vs_factor_cagr_pct) : '—'} tone={!fac || s.edges.vs_factor_cagr_pct == null ? 'text-muted' : s.edges.vs_factor_cagr_pct > 0 ? 'text-profit' : 'text-loss'} sub={fac ? `${pct(fac.cagr_pct, { signed: false })}/yr · ${f.factor_benchmark_name}` : s.universe === 'etfs' ? 'Nifty 50: see Edge' : 'no matching index'} title={fac ? `vs ${f.factor_benchmark_name}: a real NSE index you can buy through an index fund or ETF` : undefined} />
      <KpiTile label="Max drawdown" title="Worst drop from a peak" value={pct(f.max_dd_pct)} sub={`Nifty 500 ${pct(f.n500_benchmark?.max_dd_pct)}`} />
      <KpiTile label="Sharpe" value={ratio(f.sharpe)} sub={`Nifty 500 ${ratio(f.n500_benchmark?.sharpe)}`} />
      <KpiTile label="Volatility" value={pct(f.vol_pct, { signed: false })} sub="annualised" />
      <KpiTile label="Win rate" value={pct(f.win_rate, { signed: false })} sub={<><span className="text-profit">{pct(f.avg_win_pct)}</span> / <span className="text-loss">{pct(f.avg_loss_pct)}</span></>} />
      <KpiTile label="Profit factor" value={ratio(f.profit_factor)} sub={`avg trade ${pct(f.expectancy_pct)}`} title={`Expectancy (average trade) ${pct(f.expectancy_pct)}`} />
      <KpiTile label="Exposure" value={pct(f.exposure_pct, { signed: false, dp: 0 })} sub={`${f.trades} trades · ${num(f.avg_days, 0)} d avg`} title={`${f.trades} trades, average hold ${num(f.avg_days, 0)} days`} />
    </KpiStrip>
  )
}

function WindowsTable({ d }: { d: Detail }) {
  const m = d.metrics
  const wins: { id: string; label: string; w: WindowMetrics | null; full?: boolean }[] = [
    { id: 'm3', label: '3M', w: m.m3 }, { id: 'm6', label: '6M', w: m.m6 }, { id: 'm12', label: '12M', w: m.m12 }, { id: 'full', label: 'Full /yr', w: m.full, full: true },
  ]
  const rows: { label: string; pick: (w: WindowMetrics) => PerfStats | null; strong?: boolean }[] = [
    { label: 'Strategy', pick: (w) => w, strong: true },
    { label: 'Nifty 50', pick: (w) => w.benchmark },
    { label: 'Nifty 500', pick: (w) => w.n500_benchmark },
    { label: 'Average stock', pick: (w) => w.ew_benchmark },
    ...(m.full.factor_benchmark_name ? [{ label: m.full.factor_benchmark_name, pick: (w: WindowMetrics) => w.factor_benchmark }] : []),
  ]
  return (
    <Card title="Windows" subtitle="Return (and worst drop) over each window; full period as CAGR" flush>
      <div className="scroll-x">
        <table className="w-full whitespace-nowrap text-[13px]">
          <thead>
            <tr className="border-b border-line text-2xs font-semibold uppercase tracking-[0.04em] text-muted">
              <th className="px-4 py-2 text-left font-semibold" />
              {wins.map((w) => <th key={w.id} className="px-2 py-2 text-right font-semibold last:pr-4">{w.label}</th>)}
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.label} className="border-b border-line/60 last:border-0">
                <th scope="row" className={cn('whitespace-nowrap px-4 py-1.5 text-left font-medium', r.strong ? 'text-fg' : 'text-muted')}>{r.label}</th>
                {wins.map((w) => {
                  const p = w.w ? r.pick(w.w) : null
                  const v = w.full ? p?.cagr_pct : p?.return_pct
                  return (
                    <td key={w.id} className="px-2 py-1.5 text-right last:pr-4">
                      <div className={cn(r.strong && 'font-semibold')}><Pct v={v} /></div>
                      <div className="num text-2xs text-faint">{p?.max_dd_pct != null ? `DD ${pct(p.max_dd_pct)}` : ''}</div>
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  )
}

function TimingCard({ d }: { d: Detail }) {
  const t = d.strategy.timing
  return (
    <Card title="Timing luck" subtitle="How much the result depends on the calendar">
      {!t || t.low == null || t.high == null ? (
        <p className="text-[13px] text-muted">No timing range for this strategy yet.</p>
      ) : (
        <div className="space-y-3">
          <div className="num flex items-center gap-3 text-[13px]">
            <span className="w-14 text-right text-muted">{pct(t.low, { signed: false })}</span>
            <div className="flex-1"><TimingRangeBar low={t.low} high={t.high} base={t.base_cagr_pct} consistent={t.consistent} /></div>
            <span className="w-14 text-muted">{pct(t.high, { signed: false })}</span>
          </div>
          <p className="text-[13px] leading-5 text-muted">
            Base {pct(t.base_cagr_pct, { signed: false })}/yr.{' '}
            {t.method === 'rebalance_offsets' ? 'The same rules rebalanced 5, 10 or 15 days earlier' : 'The same rules started a few weeks later'} gave {pct(t.low, { signed: false })} to {pct(t.high, { signed: false })}/yr. Expect anything in this range.
          </p>
          {!t.consistent && (
            <p className="flex items-start gap-1.5 text-xs text-warn"><AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />Range computed on older data (it does not contain the base value); a re-scan recomputes it.</p>
          )}
        </div>
      )}
    </Card>
  )
}

function Performance({ d }: { d: Detail }) {
  const [range, setRange] = useState<CurveRange>('all')
  const [mode, setMode] = useState<CurveMode>('log')
  const q = useCurve(d.strategy.key, range)
  return (
    <div className="space-y-3">
      <Card
        title="Growth of ₹1"
        subtitle={<>Backtest, rebased at the start of the range{d.strategy.factor_benchmark_name ? `; violet = ${d.strategy.factor_benchmark_name} (real NSE index)` : ''}</>}
        right={
          <>
            <Segmented<CurveRange> size="xs" ariaLabel="Range" value={range} onChange={setRange} items={[{ id: '1y', label: '1Y' }, { id: '3y', label: '3Y' }, { id: 'all', label: 'All' }]} />
            <Segmented<CurveMode> size="xs" ariaLabel="Scale" value={mode} onChange={setMode} items={[{ id: 'log', label: 'Log' }, { id: 'pct', label: '%' }, { id: 'inr', label: '₹' }]} />
          </>
        }
        flush
      >
        {q.error ? <ErrorState error={q.error} onRetry={() => void q.refetch()} /> : !q.data ? <SkeletonChart height={420} /> : (
          <EquityChart curve={q.data.curve} drawdown={q.data.drawdown} mode={mode} capital={q.data.capital} height={420} />
        )}
      </Card>
      {/* side by side only from 2xl: at 1280-1440 the 2/5 column cut the Windows table's 'Full /yr' (CAGR) column */}
      <div className="grid gap-3 2xl:grid-cols-5">
        <div className="min-w-0 space-y-3 2xl:col-span-3">
          <Card title="Yearly returns" subtitle="* partial year · cells tinted by size, value always printed">
            <YearlyHeatmap rows={d.yearly} />
          </Card>
          <Card title="Monthly returns (strategy)"><MonthlyHeatmap rows={d.monthly} /></Card>
        </div>
        <div className="min-w-0 space-y-3 2xl:col-span-2">
          <TimingCard d={d} />
          <WindowsTable d={d} />
          <Card title="Walk-forward validation">
            <div className="flex items-start gap-2 text-[13px] text-muted"><FlaskConical className="mt-0.5 h-4 w-4 shrink-0" />Walk-forward check not run yet (in-sample vs holdout, variants tried, expectancy confidence interval). It arrives with a later backend update.</div>
          </Card>
        </div>
      </div>
      <BiasNote asOf={d.as_of} />
    </div>
  )
}

function Trades({ d }: { d: Detail }) {
  const [outcome, setOutcome] = useState<'all' | 'win' | 'loss'>('all')
  const [reason, setReason] = useState('')
  const [symbol, setSymbol] = useState('')
  const [debounced, setDebounced] = useState('')
  const [page, setPage] = useState(1)                // server page of 500 (the API caps page_size at 500)
  useEffect(() => { const t = setTimeout(() => { setDebounced(symbol); setPage(1) }, 250); return () => clearTimeout(t) }, [symbol])
  const pickOutcome = (v: 'all' | 'win' | 'loss') => { setOutcome(v); setPage(1) }
  const pickReason = (v: string) => { setReason(v); setPage(1) }
  // more trades than one server page: the server sorts (a client sort would only reorder the 500 loaded)
  const [sort, setSort] = useState('-exit_date')
  const pickSort = (v: string) => { setSort(v); setPage(1) }
  const q = useTrades(d.strategy.key, { outcome, reason: reason || undefined, symbol: debounced || undefined, sort, page, page_size: 500 })
  const nav = useNavigate()
  const t = q.data
  const paged = !!t && t.total > t.page_size
  const cols: Col<TradeRow>[] = [
    { id: 'sym', header: 'Symbol', value: (r) => r.symbol, cell: (r) => <SymbolCell symbol={r.symbol} />, sticky: true, mobile: 'primary' },
    { id: 'in', header: 'Bought', value: (r) => r.entry_date, cell: (r) => <span className="num text-muted">{date(r.entry_date)}</span> },
    { id: 'buy', header: 'Buy ₹', align: 'right', value: (r) => r.entry_price, cell: (r) => <Price v={r.entry_price} /> },
    { id: 'out', header: 'Sold', value: (r) => r.exit_date, cell: (r) => <span className="num text-muted">{date(r.exit_date)}</span>, mobile: 'secondary', label: 'Sold' },
    { id: 'sell', header: 'Sell ₹', align: 'right', value: (r) => r.exit_price, cell: (r) => <Price v={r.exit_price} /> },
    { id: 'ret', header: 'Return', align: 'right', value: (r) => r.ret_pct, cell: (r) => <Pct v={r.ret_pct} />, mobile: 'change' },
    { id: 'days', header: 'Days', align: 'right', value: (r) => r.days, cell: (r) => <span className="num">{r.days}</span>, mobile: 'secondary', label: 'Days' },
    { id: 'why', header: 'Exit reason', value: (r) => r.reason, cell: (r) => <span className="text-muted">{r.reason}</span> },
  ]
  return (
    <div className="space-y-3">
      {t?.source === 'recent_only' && (
        <FeatureUnavailable title="Showing the last 25 trades." hint="The full trade history (with prices) appears after the next scan writes trades.parquet. Rupee P&L is not shown: the backtest compounds, so its share counts mean nothing at your capital." />
      )}
      <div className="flex flex-wrap items-center gap-2">
        <Segmented size="sm" ariaLabel="Outcome" value={outcome} onChange={pickOutcome} items={[{ id: 'all', label: 'All' }, { id: 'win', label: 'Winners' }, { id: 'loss', label: 'Losers' }]} />
        <select value={reason} onChange={(e) => pickReason(e.target.value)} className="input h-8" aria-label="Exit reason">
          <option value="">All exit reasons</option>
          {t?.reasons.map((r) => <option key={r.reason} value={r.reason}>{r.reason} ({r.count})</option>)}
        </select>
        <input value={symbol} onChange={(e) => setSymbol(e.target.value.toUpperCase())} placeholder="Symbol…" className="input w-36" aria-label="Filter by symbol" />
      </div>
      {q.error ? <div className="card"><ErrorState error={q.error} onRetry={() => void q.refetch()} /></div> : !t ? <div className="card"><SkeletonRows /></div> : (
        <>
          <div className="grid items-start gap-3 lg:grid-cols-3">
            <Card title="Trade returns" subtitle={`${t.total} trades · 2% bins`} className="lg:col-span-2">
              {t.total ? <ReturnHistogram bins={t.histogram} /> : <EmptyState compact title="No trades match" />}
              <div className="num mt-3 grid grid-cols-2 gap-x-6 gap-y-1 border-t border-line pt-3 text-xs sm:grid-cols-4">
                <span className="text-muted">Win rate <span className="text-fg">{pct(t.stats.win_rate, { signed: false })}</span></span>
                <span className="text-muted">Avg win <span className="text-profit">{pct(t.stats.avg_win_pct)}</span></span>
                <span className="text-muted">Avg loss <span className="text-loss">{pct(t.stats.avg_loss_pct)}</span></span>
                <span className="text-muted">Profit factor <span className="text-fg">{ratio(t.stats.profit_factor)}</span></span>
              </div>
            </Card>
            <Card title="Exit reasons" flush>
              <table className="w-full text-[13px]">
                <thead><tr className="border-b border-line text-2xs font-semibold uppercase tracking-[0.04em] text-muted"><th className="px-4 py-2 text-left font-semibold">Reason</th><th className="px-2 py-2 text-right font-semibold">Count</th><th className="px-4 py-2 text-right font-semibold">Avg</th></tr></thead>
                <tbody>{t.reasons.map((r) => (
                  <tr key={r.reason} className="cursor-pointer border-b border-line/60 last:border-0 hover:bg-raised" onClick={() => pickReason(r.reason === reason ? '' : r.reason)}>
                    <td className={cn('px-4 py-1.5', r.reason === reason ? 'font-semibold text-fg' : 'text-muted')}>{r.reason}</td>
                    <td className="num px-2 py-1.5 text-right">{r.count}</td>
                    <td className="px-4 py-1.5 text-right"><Pct v={r.avg_ret_pct} /></td>
                  </tr>
                ))}</tbody>
              </table>
            </Card>
          </div>
          <Card
            title="Trades"
            flush
            right={paged ? (
              <span className="num flex flex-wrap items-center gap-1 text-xs text-muted">
                <Segmented size="sm" ariaLabel="Sort all trades" value={sort} onChange={pickSort} items={[
                  { id: '-exit_date', label: 'Newest' }, { id: '-ret_pct', label: 'Best' }, { id: 'ret_pct', label: 'Worst' }, { id: '-days', label: 'Longest' },
                ]} />
                {(t.page - 1) * t.page_size + 1}–{Math.min(t.total, t.page * t.page_size)} of {t.total}
                <IconButton size="sm" label="Previous 500 trades" disabled={t.page <= 1} onClick={() => setPage((p) => Math.max(1, p - 1))}><ChevronLeft className="h-4 w-4" /></IconButton>
                <IconButton size="sm" label="Next 500 trades" disabled={t.page * t.page_size >= t.total} onClick={() => setPage((p) => p + 1)}><ChevronRight className="h-4 w-4" /></IconButton>
              </span>
            ) : undefined}
          >
            <DataTable id="strategy.trades" data={t.rows} columns={cols} rowKey={(r) => `${r.symbol}:${r.entry_date}:${r.exit_date}`} pageSize={50} exportName={`${d.strategy.key}-trades`} onRowClick={(r) => nav(`/chart/${r.symbol}?s=${d.strategy.key}`)} initialSort={[{ id: 'out', desc: true }]} sortable={!paged} keyboard
              footer={paged ? <div className="border-t border-line px-4 py-2 text-2xs text-faint">Sorting (the buttons above) covers all {t.total} trades; the CSV export covers the {t.rows.length} trades of this page.</div> : undefined} />
          </Card>
        </>
      )}
    </div>
  )
}

function Holdings({ d }: { d: Detail }) {
  const nav = useNavigate()
  const posCols: Col<ModelPosition>[] = [
    { id: 'sym', header: 'Symbol', value: (r) => r.symbol, cell: (r) => <SymbolCell symbol={r.symbol} company={r.company} />, sticky: true, mobile: 'primary' },
    { id: 'ind', header: 'Sector', value: (r) => r.industry, cell: (r) => <span className="block max-w-[160px] truncate text-muted 2xl:max-w-[240px]" title={r.industry ?? undefined}>{r.industry ?? '—'}</span>, hideBelow: 960 },
    { id: 'in', header: 'Bought', value: (r) => r.entry_date, cell: (r) => <span className="num text-muted">{date(r.entry_date)}</span> },
    { id: 'buy', header: 'Buy ₹', align: 'right', value: (r) => r.entry_price, cell: (r) => <Price v={r.entry_price} /> },
    { id: 'now', header: 'Now ₹', align: 'right', value: (r) => r.last_price, cell: (r) => <Price v={r.last_price} />, mobile: 'value' },
    { id: 'ret', header: 'Return', align: 'right', value: (r) => r.ret_pct, cell: (r) => <Pct v={r.ret_pct} />, mobile: 'change' },
    { id: 'stop', header: 'Stop ₹', align: 'right', value: (r) => r.stop, cell: (r) => <Price v={r.stop} /> },
    { id: 'days', header: 'Days', align: 'right', value: (r) => r.days, cell: (r) => <span className="num">{r.days}</span> },
    { id: 'w', header: 'Weight', title: 'Share of the model portfolio (the backtest compounds, so its share counts are not shown)', align: 'right', value: (r) => r.weight_pct, cell: (r) => <Pct v={r.weight_pct} signed={false} color={false} />, mobile: 'secondary', label: 'Weight' },
    { id: 'res', header: 'Results', value: (r) => r.results_on, cell: (r) => <ResultsChip on={r.results_on} inDays={r.results_in_days} compact /> },
  ]
  const rankCols: Col<RankingRow>[] = [
    { id: 'rank', header: '#', align: 'right', value: (r) => r.rank, cell: (r) => <span className="num text-muted">{r.rank}</span>, width: 44 },
    { id: 'sym', header: 'Symbol', value: (r) => r.symbol, cell: (r) => <SymbolCell symbol={r.symbol} company={r.company} extra={r.in_portfolio ? <span className="h-1.5 w-1.5 rounded-full bg-accent" title="Held by the model" /> : null} />, sticky: true, mobile: 'primary' },
    { id: 'ind', header: 'Sector', value: (r) => r.industry, cell: (r) => <span className="block max-w-[160px] truncate text-muted 2xl:max-w-[240px]" title={r.industry ?? undefined}>{r.industry ?? '—'}</span>, hideBelow: 960 },
    { id: 'score', header: 'Score', align: 'right', value: (r) => r.score, cell: (r) => <span className="num">{num(r.score, 2)}</span> },
    { id: 'price', header: 'Price ₹', align: 'right', value: (r) => r.price, cell: (r) => <Price v={r.price} />, mobile: 'value' },
    { id: 'r6', header: '6M', align: 'right', value: (r) => r.ret_6m_pct, cell: (r) => <Pct v={r.ret_6m_pct} /> },
    { id: 'r12', header: '12M', align: 'right', value: (r) => r.ret_12m_pct, cell: (r) => <Pct v={r.ret_12m_pct} />, mobile: 'change' },
    { id: 'rs', header: 'RS', align: 'right', value: (r) => r.rs, cell: (r) => <span className="num">{num(r.rs, 0)}</span> },
    { id: 'res', header: 'Results', value: (r) => r.results_on, cell: (r) => <ResultsChip on={r.results_on} inDays={r.results_in_days} compact /> },
    { id: 'held', header: 'Held', value: (r) => r.in_portfolio, cell: (r) => (r.in_portfolio ? <Chip className="tint-accent text-accent">held</Chip> : null) },
  ]
  return (
    <div className="space-y-3">
      <Card title="Orders for the next open" subtitle="Same rows as Signals for the same allocations" flush>
        {d.orders.length ? <OrdersTable id={`detail.${d.strategy.key}`} orders={d.orders} /> : <div className="px-4 py-3 text-[13px] text-muted">No orders. {d.regime_note ?? (d.strategy.next_rebalance ? `Next review ${date(d.strategy.next_rebalance)}.` : 'No entry signals today.')}</div>}
      </Card>
      <Card title={`Model holdings (${d.positions.length} of ${d.strategy.max_positions})`} subtitle={d.positions.length > 0 && d.positions.every((p) => p.weight_pct == null)
        ? 'Weights unknown for this scan: it did not record the equity of the model on today’s list (the point-in-time backtest is a different simulation)'
        : 'Weights in the model on today’s list (the one the orders come from), not share counts'} flush>
        <DataTable id="strategy.positions" data={d.positions} columns={posCols} rowKey={(r) => r.symbol} onRowClick={(r) => nav(`/chart/${r.symbol}?s=${d.strategy.key}`)} exportName={`${d.strategy.key}-holdings`} empty={<EmptyState compact title="The model holds nothing right now" />} keyboard
          footer={d.positions.length > 1 ? <div className="border-t border-line px-4 py-2 text-2xs text-faint">Weights drift by design: held positions are never trimmed back, so winners grow, and a new entry gets at most an equal slot (equity / {d.strategy.max_positions}), less when the cash freed by the sale is smaller.</div> : undefined} />
      </Card>
      {d.strategy.kind === 'rank' && (d.ranking.length > 0 ? (
        <Card title="Current ranking" subtitle={`Top ${d.ranking.length} by the strategy score`} flush>
          <DataTable id="strategy.ranking" data={d.ranking} columns={rankCols} rowKey={(r) => r.symbol} onRowClick={(r) => nav(`/chart/${r.symbol}?s=${d.strategy.key}`)} exportName={`${d.strategy.key}-ranking`} filterable filterPlaceholder="Filter symbol or sector…" />
        </Card>
      ) : (
        <Card title="Current ranking">
          <p className="text-[13px] text-muted">{d.strategy.universe === 'etfs'
            ? 'No ranking: this strategy times a single ETF, so there is nothing to rank. It is either in the ETF or in cash (see Model holdings and Orders above).'
            : 'No stock passes the strategy’s entry filters today, so the ranking is empty.'}</p>
        </Card>
      ))}
    </div>
  )
}

function Rules({ d }: { d: Detail }) {
  const r = d.rules
  const e = d.evidence
  const params = Object.entries(r.params).filter(([k]) => k !== 'enabled')
  return (
    <div className="grid gap-3 xl:grid-cols-2">
      <div className="space-y-3">
        <Card title="Rules in plain language">
          <ol className="list-decimal space-y-1.5 pl-5 text-[13px] leading-5 text-fg">{r.plain_rules.map((x, i) => <li key={i}>{x}</li>)}</ol>
        </Card>
        <Card title="Parameters" subtitle={r.source === 'config' ? 'From the current config.yaml (the scan did not record them; may differ if config changed since)' : 'As used by the last scan'} right={<Link to="/settings/strategies" className="link text-xs">Settings › Strategies</Link>} flush>
          <table className="w-full text-[13px]">
            <tbody>
              {[
                ['Kind', kindLabel(r.kind, r.rebalance)], ['Max positions', r.max_positions], ['Top N / keep while ranked', r.top_n != null ? `${r.top_n} / ${r.keep_rank ?? '—'}` : null],
                ['Stop', r.stop_pct != null ? `${num(r.stop_pct, 1)}%` : r.stop_atr != null ? `${num(r.stop_atr, 1)} × ATR` : 'none'], ['Target', r.target_pct != null ? `${num(r.target_pct, 1)}%` : 'none'],
                ['Trailing stop', r.trail_pct ? `${num(r.trail_pct, 1)}%` : 'none'], ['Max hold', r.max_hold ? `${r.max_hold} days` : '—'],
                ['Sizing', r.sizing === 'risk' ? `risk ${num(r.risk_pct, 1)}% per trade` : 'equal weight'], ['Regime filter', r.use_regime ? `on (${r.regime_action ?? 'hold'})` : 'off'],
                ['Costs', `≈ ${num(d.as_of.costs_round_trip_pct, 2)}% round trip incl. slippage (liquid stocks; more for illiquid)`],
              ].filter(([, v]) => v != null).map(([k, v]) => (
                <tr key={String(k)} className="border-b border-line/60 last:border-0"><td className="px-4 py-1.5 text-muted">{k}</td><td className="num px-4 py-1.5 text-right">{String(v)}</td></tr>
              ))}
              {params.map(([k, v]) => (
                <tr key={k} className="border-b border-line/60 last:border-0"><td className="px-4 py-1.5 font-mono text-xs text-muted">{k}</td><td className="num px-4 py-1.5 text-right font-mono text-xs">{Array.isArray(v) ? v.join(', ') : String(v)}</td></tr>
              ))}
            </tbody>
          </table>
        </Card>
      </div>
      <Card title={<span className="flex items-center gap-2">Evidence <EvidenceChip evidence={e.grade} long />{e.catalogue_id && <span className="font-mono text-2xs text-faint">catalogue {e.catalogue_id}</span>}</span>}>
        <div className="space-y-4 text-[13px] leading-5">
          <p className="text-fg">{e.summary}</p>
          <p className="text-muted">{EVIDENCE[e.grade].help}</p>
          <div className="rounded-md border border-warn/25 bg-warn/[0.06] p-3">
            <div className="eyebrow mb-1 text-warn">What to expect</div>
            <p className="text-fg">{e.what_to_expect}</p>
          </div>
          {e.failure_modes.length > 0 && (
            <div><div className="eyebrow mb-1.5">How it fails</div><ul className="list-disc space-y-1 pl-5 text-muted">{e.failure_modes.map((f, i) => <li key={i}>{f}</li>)}</ul></div>
          )}
          {e.sources.length > 0 && (
            <div>
              <div className="eyebrow mb-1.5">Sources</div>
              <ul className="space-y-1">{e.sources.map((s, i) => (
                <li key={i}>{s.url ? <a href={s.url} target="_blank" rel="noopener noreferrer" className="link inline-flex items-center gap-1">{s.title}<ExternalLink className="h-3 w-3" /></a> : <span className="text-muted">{s.title}</span>}</li>
              ))}</ul>
            </div>
          )}
          <div className="text-2xs text-faint">Validation (walk-forward, variants tried, confidence intervals): not run yet.</div>
        </div>
      </Card>
    </div>
  )
}

export default function StrategyDetail() {
  const { key = '', tab: tabParam } = useParams()
  const tab = (['performance', 'trades', 'holdings', 'rules', 'paper'].includes(tabParam ?? '') ? tabParam : 'performance') as Tab
  const q = useStrategy(key)
  const list = useStrategies()
  const nav = useNavigate()
  // the same order as the Strategies leaderboard: Long-term, then Swing (server order inside), then rejected
  const keys = useMemo(() => {
    const d = list.data
    if (!d) return []
    return [...HORIZONS.flatMap((h) => d.strategies.filter((s) => s.horizon === h)), ...d.rejected].map((s) => s.key)
  }, [list.data])
  const i = keys.indexOf(key)
  const prev = i > 0 ? keys[i - 1] : null
  const next = i >= 0 && i < keys.length - 1 ? keys[i + 1] : null
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (typingTarget(e) || e.ctrlKey || e.metaKey) return
      if (e.key === '[' && prev) nav(`/strategies/${prev}/${tab}`)
      if (e.key === ']' && next) nav(`/strategies/${next}/${tab}`)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [prev, next, tab, nav])

  const d = q.data
  if (q.error && !d) return <div className="card"><ErrorState error={q.error} onRetry={() => void q.refetch()} /></div>
  const s = d?.strategy
  return (
    <div>
      <div className="mb-3 flex items-center gap-2 text-xs text-muted">
        <Link to="/strategies" className="inline-flex items-center gap-1 hover:text-fg"><ChevronLeft className="h-3.5 w-3.5" />Strategies</Link>
        <span className="text-faint">/</span>
        <span className="truncate text-fg">{s?.name ?? key}</span>
        <span className="ml-auto flex items-center gap-1">
          <IconButton size="sm" label="Previous strategy ([)" disabled={!prev} onClick={() => prev && nav(`/strategies/${prev}/${tab}`)}><ChevronLeft className="h-4 w-4" /></IconButton>
          <IconButton size="sm" label="Next strategy (])" disabled={!next} onClick={() => next && nav(`/strategies/${next}/${tab}`)}><ChevronRight className="h-4 w-4" /></IconButton>
        </span>
      </div>
      {!d || !s ? (
        <div className="space-y-3"><Skeleton className="h-14 w-full" /><SkeletonKpis n={10} /><div className="card"><SkeletonChart height={420} /></div></div>
      ) : (
        <div className="space-y-3">
          {q.error && <RefreshFailed error={q.error} onRetry={() => void q.refetch()} />}
          <div className={cn(s.comparison_only && 'opacity-90')}>
            <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
              <h1 className="text-xl font-semibold tracking-[-0.01em]">{s.name}</h1>
              {s.lifecycle === 'active' ? <StatusBadge status={s.status} lost={lostMoney(s.headline)} /> : <LifecycleBadge lifecycle={s.lifecycle} />}
              {flatteredNote(s) && <WarnChip title={flatteredNote(s) ?? undefined}>Flattered backtest</WarnChip>}
              {d.paper && <Link to={`/strategies/${s.key}/paper`} className="link ml-auto inline-flex items-center gap-1 text-xs"><NotebookPen className="h-3.5 w-3.5" />Paper <Pct v={d.paper.return_pct} /> · {d.paper.days} d</Link>}
            </div>
            {s.lifecycle === 'active' ? <p className="mt-1 text-[13px] text-muted">{s.status_reason}</p> : (
              <div className="mt-2 flex items-start gap-2 rounded-md border border-line bg-raised/50 px-3 py-2 text-[13px]">
                <Ban className="mt-0.5 h-4 w-4 shrink-0 text-muted" />
                <span><span className="font-medium text-fg">{s.lifecycle === 'disabled' ? 'Disabled' : 'Tested & rejected'}:</span> <span className="text-muted">{s.rejected_reason ?? 'Disabled in config.yaml.'} It is re-tested after every scan for comparison but never produces orders.</span></span>
              </div>
            )}
            <div className="mt-2 flex flex-wrap items-center gap-1.5">
              <HorizonChip horizon={s.horizon} />
              <EvidenceChip evidence={s.evidence} long />
              <Chip>{kindLabel(s.kind, s.rebalance)}</Chip>
              {s.universe === 'etfs' ? <EtfChip /> : <Chip>Stocks</Chip>}
              {s.lifecycle === 'active' && s.next_rebalance && <Chip>Next review {date(s.next_rebalance)}</Chip>}
              {s.lifecycle === 'active' && s.blocked_by_regime && <Chip className="tint-warn text-warn">Regime filter: no new buys</Chip>}
              <Help text={s.description} />
            </div>
          </div>
          <Kpis d={d} />
          <div className="border-b border-line">
            <Tabs<Tab>
              value={tab}
              items={[
                { id: 'performance', label: 'Performance', to: `/strategies/${key}/performance` },
                { id: 'trades', label: 'Trades', to: `/strategies/${key}/trades` },
                { id: 'holdings', label: 'Holdings & orders', count: d.orders.length || null, to: `/strategies/${key}/holdings` },
                { id: 'rules', label: 'Rules & evidence', to: `/strategies/${key}/rules` },
                { id: 'paper', label: 'Paper', to: `/strategies/${key}/paper` },
              ]}
            />
          </div>
          {tab === 'performance' && <Performance d={d} />}
          {tab === 'trades' && <Trades key={s.key} d={d} />}
          {tab === 'holdings' && <Holdings d={d} />}
          {tab === 'rules' && <Rules d={d} />}
          {tab === 'paper' && (d.paper ? <PaperDetailView k={s.key} /> : (
            <div className="card"><EmptyState title="Not paper-traded yet" icon={<NotebookPen className="h-6 w-6" strokeWidth={1.5} />}>The journal records this strategy's orders on every completed-day scan and fills them at the next official open with full charges. Results appear here once it has started.</EmptyState></div>
          ))}
        </div>
      )}
    </div>
  )
}

