// Intraday `/intraday` (spec 3.10, review A7): honest results from data/results/intraday.json, SEBI facts, rules
// from the server (never hard-coded), and today's simulated setups. The server's summary line (how many strategies
// lost money after costs, whether any edge is significant) comes first. "Re-run backtest" posts /api/intraday/run
// and the page polls while it runs.

import { useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { AlertOctagon, ExternalLink, RefreshCw, Timer } from 'lucide-react'
import { isFailure } from '@/api/client'
import { useIntraday, useIntradayRun, useStatus } from '@/api/hooks'
import type { IntradayRun, IntradayStrategy, IntradayTrade } from '@/api/types'
import { EdgeVerdict, EvidenceChip, StatusBadge, edgeVerdict } from '@/components/badges'
import { LinesChart, type LineDef } from '@/components/charts/LinesChart'
import { DataTable, type Col } from '@/components/DataTable'
import { KpiStrip, KpiTile, PageHeader } from '@/components/domain'
import { EmptyState, ErrorState, SkeletonRows } from '@/components/feedback'
import { Money, Pct, Price, Ratio, Risk } from '@/components/num'
import { useToast } from '@/components/toast'
import { Button, Card, KV, Spinner } from '@/components/ui'
import { cn } from '@/lib/csv'
import { date, dateTimeIST, duration, money, num, pct } from '@/lib/format'

type TodayRow = IntradayTrade & { strategy: string; strategy_key: string }

function tradeCols(withStrategy: boolean): Col<TodayRow>[] {
  return [
    ...(withStrategy ? [{ id: 'st', header: 'Strategy', value: (r: TodayRow) => r.strategy, cell: (r: TodayRow) => <span className="block max-w-[180px] truncate">{r.strategy}</span> } as Col<TodayRow>] : []),
    { id: 'sym', header: 'Symbol', value: (r) => r.symbol, cell: (r) => <Link to={`/chart/${r.symbol}`} onClick={(e) => e.stopPropagation()} className="font-semibold hover:underline">{r.symbol}</Link>, sticky: true, mobile: 'primary' },
    { id: 'date', header: 'Date', value: (r) => r.date, cell: (r) => <span className="num text-muted">{date(r.date, { year: false })}</span> },
    { id: 'side', header: 'Side', value: (r) => r.side, cell: (r) => <span className={cn('text-2xs font-bold tracking-[0.04em]', r.side === 'LONG' ? 'text-profit' : 'text-loss')}>{r.side}</span> },
    { id: 'in', header: 'In', value: (r) => r.entry_time, cell: (r) => <span className="num text-muted">{r.entry_time}</span> },
    { id: 'entry', header: 'Entry ₹', align: 'right', value: (r) => r.entry, cell: (r) => <Price v={r.entry} /> },
    { id: 'stop', header: 'Stop ₹', align: 'right', value: (r) => r.stop, cell: (r) => <Price v={r.stop} /> },
    { id: 'out', header: 'Out', value: (r) => r.exit_time, cell: (r) => <span className="num text-muted">{r.open_now ? 'open' : r.exit_time}</span> },
    { id: 'exit', header: 'Exit ₹', align: 'right', value: (r) => r.exit, cell: (r) => <Price v={r.exit} /> },
    { id: 'qty', header: 'Qty', align: 'right', value: (r) => r.qty, cell: (r) => <span className="num">{r.qty}</span>, defaultHidden: true },
    { id: 'pnl', header: 'P&L ₹', title: 'After intraday charges and slippage', align: 'right', value: (r) => r.pnl, cell: (r) => <Money v={r.pnl} signed color />, mobile: 'value' },
    { id: 'ret', header: 'Return', align: 'right', value: (r) => r.ret_pct, cell: (r) => <Pct v={r.ret_pct} dp={2} />, mobile: 'change' },
    { id: 'why', header: 'Exit', value: (r) => r.reason, cell: (r) => <span className="text-muted">{r.reason}</span> },
  ]
}

function StrategyPanel({ s, sessions }: { s: IntradayStrategy; sessions: number | null }) {
  const lines: LineDef[] = useMemo(() => [{ id: s.key, label: 'Equity ₹', v: s.equity.series[0]?.v ?? [], color: 'accent', width: 2, format: (v) => money(v) }], [s])
  const m = s.metrics
  const rows: TodayRow[] = s.recent_trades.map((t) => ({ ...t, strategy: s.name, strategy_key: s.key }))
  return (
    <div className="space-y-3">
      <Card title={<span className="flex flex-wrap items-center gap-2">{s.name}<StatusBadge status={s.status} /><EvidenceChip evidence={s.evidence} /></span>} subtitle={s.description}>
        <div className="grid gap-4 lg:grid-cols-3">
          <div className="lg:col-span-2">{s.equity.t.length > 1 ? <LinesChart t={s.equity.t} lines={lines} height={240} /> : <EmptyState compact title="No equity curve" />}</div>
          <div>
            <KV k="Sessions tested" v={sessions && m.days !== sessions ? `${m.days} of ${sessions}` : m.days} title={sessions && m.days < sessions ? 'The first session(s) only warm up this strategy (it needs the previous day)' : undefined} />
            <KV k="Trades (per day)" v={<>{m.trades} <span className="text-faint">({num(m.trades_per_day, 1)})</span></>} />
            <KV k="Avg trade after costs" v={<Pct v={m.avg_trade_pct} dp={2} />} />
            <KV k="Avg day" v={<Pct v={m.avg_day_pct} dp={3} />} />
            <KV k="95% range of avg day" v={m.ci95_day_pct ? <>{pct(m.ci95_day_pct[0], { dp: 2 })} to {pct(m.ci95_day_pct[1], { dp: 2 })}</> : '—'} title="If this range includes zero, the result is indistinguishable from luck" />
            <KV k="t-stat" v={<span className={m.significant ? 'text-fg' : 'text-muted'}>{num(m.t_stat, 2)} {m.significant ? '(significant)' : '(not significant)'}</span>} />
            <KV k="Profit factor" v={<Ratio v={m.profit_factor} />} />
            <KV k="Win rate" v={<Pct v={m.win_rate} signed={false} color={false} />} />
            <KV k="After-tax return" v={<Pct v={m.after_tax_return_pct} />} title="Speculative business income at the slab rate" />
          </div>
        </div>
      </Card>
      <Card title="Recent simulated trades" flush>
        <DataTable id="intraday.trades" data={rows} columns={tradeCols(false)} rowKey={(r) => `${r.symbol}${r.date}${r.entry_time}`} pageSize={50} exportName={`intraday-${s.key}`} empty={<EmptyState compact title="No trades" />} />
      </Card>
    </div>
  )
}

/** Re-run button + background run state; toasts when a run this page watched finishes. */
function RerunControl({ run, label = 'Re-run backtest' }: { run: IntradayRun | undefined; label?: string }) {
  const start = useIntradayRun()
  const toast = useToast()
  const qc = useQueryClient()
  const wasRunning = useRef(false)
  useEffect(() => {
    if (!run) return
    if (wasRunning.current && !run.running) {
      if (run.state === 'failed') toast({ tone: 'bad', title: 'Intraday backtest failed', detail: run.message ?? undefined })
      else toast({ tone: 'good', title: 'Intraday backtest finished', detail: run.message ?? 'The results below are refreshed.' })
      void qc.invalidateQueries({ queryKey: ['strategies'] })
    }
    wasRunning.current = run.running
  }, [run, qc, toast])
  const go = () =>
    start.mutate(true, {
      onError: (e) => toast({ tone: 'bad', title: isFailure(e) ? e.message : 'Could not start the intraday backtest', detail: isFailure(e) ? e.hint ?? undefined : undefined }),
    })
  return (
    <>
      {run?.running ? (
        <span className="flex max-w-[320px] items-center gap-1.5 text-xs text-muted" title={run.message ?? undefined}><Spinner className="h-3.5 w-3.5 shrink-0" /><span className="truncate">{run.message ?? 'Running…'}</span></span>
      ) : run?.state === 'failed' ? (
        <span className="max-w-[320px] truncate text-xs text-loss" title={run.message ?? undefined}>Last re-run failed{run.message ? `: ${run.message}` : ''}</span>
      ) : null}
      <Button
        size="sm"
        icon={<RefreshCw className="h-3.5 w-3.5" />}
        loading={start.isPending}
        disabled={!!run?.running}
        onClick={go}
        title="Refresh the 5-minute bars (Yahoo) and re-test every intraday strategy in the background. Takes a few minutes."
      >
        {label}
      </Button>
    </>
  )
}

export default function Intraday() {
  const q = useIntraday()
  const d = q.data
  const [sel, setSel] = useState<string | null>(null)
  const strategies = d?.strategies ?? []
  const losers = strategies.filter((s) => (s.metrics.return_pct ?? 0) < 0).length
  const best = strategies.reduce<IntradayStrategy | null>((b, s) => (b == null || (s.metrics.return_pct ?? -1e9) > (b.metrics.return_pct ?? -1e9) ? s : b), null)
  const today: TodayRow[] = useMemo(() => strategies.flatMap((s) => s.today.map((t) => ({ ...t, strategy: s.name, strategy_key: s.key }))), [strategies])
  const selected = strategies.find((s) => s.key === sel) ?? null
  const clk = useStatus().data?.clock
  const marketClosed = !!clk && !clk.is_trading_day
  const setupDay = today.reduce<string | null>((m, r) => (r.date && (!m || r.date > m) ? r.date : m), null)

  const cols: Col<IntradayStrategy>[] = [
    { id: 'status', header: 'Status', value: (s) => s.status, cell: (s) => <StatusBadge status={s.status} short />, width: 110 },
    // items-start: the evidence chip keeps its own width (stretched, it looked like a long empty input bar)
    { id: 'name', header: 'Strategy', value: (s) => s.name, sticky: true, minWidth: 220, mobile: 'primary', cell: (s) => <div className="flex flex-col items-start gap-0.5 py-0.5"><span className={cn('font-semibold', s.status === 'not-working' && 'text-muted')}>{s.name}</span><EvidenceChip evidence={s.evidence} /></div> },
    { id: 'ret', header: 'Return', title: 'Total over the tested sessions, after costs', align: 'right', value: (s) => s.metrics.return_pct, cell: (s) => <Pct v={s.metrics.return_pct} />, mobile: 'change' },
    { id: 'ann', header: 'Annualised', align: 'right', value: (s) => s.metrics.annualised_pct, cell: (s) => <Pct v={s.metrics.annualised_pct} />, hideBelow: 1420 },
    { id: 'tax', header: 'After tax', align: 'right', value: (s) => s.metrics.after_tax_return_pct, cell: (s) => <Pct v={s.metrics.after_tax_return_pct} /> },
    { id: 'avg', header: 'Avg trade', align: 'right', value: (s) => s.metrics.avg_trade_pct, cell: (s) => <Pct v={s.metrics.avg_trade_pct} dp={2} /> },
    { id: 'dd', header: 'Max DD', align: 'right', value: (s) => s.metrics.max_dd_pct, cell: (s) => <Risk v={s.metrics.max_dd_pct} /> },
    { id: 'sh', header: 'Sharpe', align: 'right', value: (s) => s.metrics.sharpe, cell: (s) => <Ratio v={s.metrics.sharpe} />, hideBelow: 1200 },
    { id: 'win', header: 'Win %', align: 'right', value: (s) => s.metrics.win_rate, cell: (s) => <Pct v={s.metrics.win_rate} signed={false} color={false} />, hideBelow: 1100 },
    { id: 'pf', header: 'PF', title: 'Profit factor', align: 'right', value: (s) => s.metrics.profit_factor, cell: (s) => <Ratio v={s.metrics.profit_factor} /> },
    { id: 'tr', header: 'Trades', align: 'right', value: (s) => s.metrics.trades, cell: (s) => <span className="num">{s.metrics.trades}</span>, mobile: 'secondary', label: 'Trades', hideBelow: 1240 },
    { id: 'sig', header: 'Real edge?', title: 'A profit beyond luck (95% confidence)? "loses" = the average day is a loss beyond luck', value: (s) => edgeVerdict(s), cell: (s) => <EdgeVerdict s={s} /> },
  ]

  return (
    <div>
      <PageHeader
        title="Intraday research"
        subtitle={d?.generated_at ? <>Backtest of {dateTimeIST(d.generated_at)}{d.elapsed_s != null ? ` (${duration(d.elapsed_s)})` : ''} · research only, no orders</> : 'Research only: no intraday orders are produced'}
        right={d ? <RerunControl run={d.run} label={d.available ? 'Re-run backtest' : 'Run backtest'} /> : undefined}
      />
      {q.error && !d ? <div className="card"><ErrorState error={q.error} onRetry={() => void q.refetch()} /></div> : !d ? <div className="card"><SkeletonRows /></div> : (
        <div className="space-y-3">
          {d.available && strategies.length > 0 && (
            <div className={cn('flex items-start gap-3 rounded-lg border px-4 py-3', losers > 0 ? 'border-loss/35 bg-loss/[0.07]' : 'border-warn/35 bg-warn/[0.07]')}>
              <AlertOctagon className={cn('mt-0.5 h-5 w-5 shrink-0', losers > 0 ? 'text-loss' : 'text-warn')} />
              <div className="text-[13px] leading-5">
                <div className="font-semibold text-fg">{d.summary}</div>
                {d.costs && (
                  <div className="mt-0.5 text-muted">
                    Every simulated trade pays brokerage, STT, exchange fees, GST and slippage: about {pct(d.costs.round_trip_pct, { signed: false, dp: 3 })} per round trip on {money(d.costs.value)}.
                  </div>
                )}
              </div>
            </div>
          )}

          <div className="grid items-start gap-3 lg:grid-cols-3">
            <Card title="Read this first" subtitle={d.sebi.source} className="lg:col-span-2">
              <ul className="space-y-2 text-[13px] leading-5">
                {d.sebi.points.map((p, i) => <li key={i} className="flex gap-2.5"><span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-loss" /><span>{p}</span></li>)}
              </ul>
              {d.sebi.url && <a href={d.sebi.url} target="_blank" rel="noopener noreferrer" className="link mt-3 inline-flex items-center gap-1 text-xs">SEBI study (PDF) <ExternalLink className="h-3 w-3" /></a>}
            </Card>
            <Card title="How this was tested">
              {d.data ? (
                <div>
                  <KV k="Bars" v={`${d.data.interval} · ${d.data.source}`} />
                  <KV k="Period" v={`${date(d.data.from, { year: false })} → ${date(d.data.to, { year: false })}`} />
                  <KV k="Sessions · symbols" v={`${d.data.sessions} · ${d.data.symbols}`} />
                  {d.costs && <KV k="Round trip on ₹1 L" v={`${money(d.costs.value)} → ${pct(d.costs.round_trip_pct, { signed: false, dp: 3 })}`} />}
                  <p className="mt-2 text-2xs text-muted">{d.data.note}</p>
                </div>
              ) : <p className="text-[13px] text-muted">{d.reason}</p>}
              {Object.keys(d.rules).length > 0 && (
                <dl className="mt-3 space-y-1.5 border-t border-line pt-3 text-xs">
                  {Object.entries(d.rules).map(([k, v]) => <div key={k}><dt className="font-medium capitalize text-fg">{k.replace(/_/g, ' ')}</dt><dd className="text-muted">{v}</dd></div>)}
                </dl>
              )}
            </Card>
          </div>

          {!d.available ? (
            <div className="card"><EmptyState title={d.reason ?? 'Intraday backtest not run yet'} icon={<Timer className="h-6 w-6" strokeWidth={1.5} />}>{d.run.running ? 'The intraday backtest is running; this page fills in when it finishes.' : 'Press Run backtest (top right) to download the 5-minute bars and test the intraday strategies. It runs in the background.'}</EmptyState></div>
          ) : (
            <>
              {best && (
                <KpiStrip min={150}>
                  <KpiTile label="Strategies tested" value={strategies.length} />
                  <KpiTile label="Losing after costs" value={`${losers} of ${strategies.length}`} tone={losers ? 'text-loss' : undefined} />
                  <KpiTile label="Best total return" value={pct(best.metrics.return_pct)} tone={(best.metrics.return_pct ?? 0) < 0 ? 'text-loss' : 'text-profit'} sub={best.name} />
                  <KpiTile label="Significant edges" value={strategies.filter((s) => s.metrics.significant && (s.metrics.return_pct ?? 0) > 0).length} sub="positive and beyond luck" />
                </KpiStrip>
              )}
              <Card title="Results after all costs" subtitle="Click a strategy for its equity and trades" flush>
                <DataTable id="intraday" data={strategies} columns={cols} rowKey={(s) => s.key} onRowClick={(s) => setSel(s.key === sel ? null : s.key)} rowClassName={(s) => cn(s.key === sel && 'bg-accent/[0.06]')} keyboard />
              </Card>
              {selected && <StrategyPanel s={selected} sessions={d.data?.sessions ?? null} />}
              <Card title="Today's setups (simulated)" subtitle={<>What each strategy would have done {setupDay ? <>on <span className="num">{date(setupDay)}</span></> : 'in the latest session'} on delayed 5-minute data. Not orders: intraday strategies are research only.</>} flush>
                <DataTable id="intraday.today" data={today} columns={tradeCols(true)} rowKey={(r) => `${r.strategy_key}${r.symbol}${r.entry_time}`} empty={<EmptyState compact title={marketClosed ? 'Market closed today' : 'No setups today'}>{marketClosed ? `No session today (${clk?.holiday_name ?? (clk?.session === 'weekend' ? 'weekend' : 'holiday')}): setups appear on the next trading day.` : clk?.session === 'pre_open' ? 'The market has not opened yet.' : 'No strategy has triggered so far today.'}</EmptyState>} />
              </Card>
            </>
          )}
        </div>
      )}
    </div>
  )
}
