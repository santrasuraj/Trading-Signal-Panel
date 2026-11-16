// Auto-trader `/autotrade`: the high-speed engine on its own PRACTICE account (web/api/services/autotrade_svc.py).
// Every second while the market is open it takes the app's intraday signals (all, or proven only), live OI build-ups,
// index option BUY verdicts (one lot) and - through the practice bot - the daily strategies; stops and targets act on
// every price update. Each trade records its speed (signal lag, reaction in ms, price age) and slippage, so the page
// shows what the strategies earn when actually traded. Nothing is ever sent to FYERS.
// The Speed card shows the live path: the ZeroMQ tick bus, the live signal engine (Numba-compiled bar loops) and the
// P50 / P95 / P99 of each step (also at /api/metrics for Prometheus / Grafana).

import { Link } from 'react-router-dom'
import { Gauge, OctagonX, RotateCcw, Zap } from 'lucide-react'
import { useAutoTrade, useAutoTradeActions, type AutoPosition, type AutoRecordRow, type AutoSettings, type AutoSpeed, type AutoTrade, type LatencyRow } from '@/api/autotrade'
import { DataTable, type Col } from '@/components/DataTable'
import { ProofBadge } from '@/components/badges'
import { KpiTile, PageHeader } from '@/components/domain'
import { Banner, EmptyState, ErrorState, SkeletonRows } from '@/components/feedback'
import { Money, Price } from '@/components/num'
import { Button, Card, Field, Segmented, Switch } from '@/components/ui'
import { cn } from '@/lib/csv'
import { dateTimeIST, money, num } from '@/lib/format'

const FEED: Record<string, [string, string]> = {
  live: ['FYERS real time (~1 s)', 'text-profit'], fyers: ['FYERS quotes (up to 30 s)', 'text-warn'],
  yahoo: ['Yahoo, ~15 min delayed', 'text-loss'],
}
const bps = (v: number | null) => (v == null ? '—' : `${v > 0 ? '+' : ''}${num(v, 1)} bps`)
const side = (s: 'LONG' | 'SHORT') => <span className={cn('text-2xs font-bold tracking-[0.04em]', s === 'LONG' ? 'text-profit' : 'text-loss')}>{s}</span>

const POS_COLS: Col<AutoPosition>[] = [
  { id: 'sym', header: 'Symbol', value: (r) => r.symbol, sticky: true, mobile: 'primary', cell: (r) => <Link to={`/chart/${r.symbol}`} className="font-semibold hover:underline">{r.symbol}</Link> },
  { id: 'st', header: 'Strategy', value: (r) => r.strategy_name, cell: (r) => <span className="block max-w-[200px] truncate" title={r.detail ?? undefined}>{r.strategy_name}</span> },
  { id: 'proof', header: 'Backtest', value: (r) => r.strategy_status, cell: (r) => <ProofBadge status={r.strategy_status} /> },
  { id: 'side', header: 'Side', value: (r) => r.side, cell: (r) => side(r.side) },
  { id: 'qty', header: 'Qty', align: 'right', value: (r) => r.qty, cell: (r) => <span className="num">{r.qty}</span> },
  { id: 'fill', header: 'Filled ₹', align: 'right', value: (r) => r.fill, cell: (r) => <Price v={r.fill} /> },
  { id: 'slip', header: 'Slippage', title: 'Fill vs the signal\'s price (positive = paid more / sold lower)', align: 'right', value: (r) => r.slippage_bps, cell: (r) => <span className="num">{bps(r.slippage_bps)}</span> },
  { id: 'stop', header: 'Stop ₹', align: 'right', value: (r) => r.stop, cell: (r) => <Price v={r.stop} /> },
  { id: 'tgt', header: 'Target ₹', align: 'right', value: (r) => r.target, cell: (r) => <Price v={r.target} /> },
  { id: 'last', header: 'Last ₹', align: 'right', value: (r) => r.last, cell: (r) => <Price v={r.last} /> },
  { id: 'pnl', header: 'Open P&L', align: 'right', value: (r) => r.unrealized, mobile: 'value', cell: (r) => <Money v={r.unrealized} signed color /> },
]

const TRADE_COLS: Col<AutoTrade>[] = [
  { id: 'sym', header: 'Symbol', value: (r) => r.symbol, sticky: true, mobile: 'primary', cell: (r) => <span className="font-semibold">{r.symbol}</span> },
  { id: 'st', header: 'Strategy', value: (r) => r.strategy_name, cell: (r) => <span className="block max-w-[180px] truncate">{r.strategy_name}</span> },
  { id: 'side', header: 'Side', value: (r) => r.side, cell: (r) => side(r.side) },
  { id: 'in', header: 'In', value: (r) => r.opened_at, cell: (r) => <span className="num text-muted">{r.opened_at.slice(11, 19)}</span> },
  { id: 'fill', header: 'Entry ₹', align: 'right', value: (r) => r.fill, cell: (r) => <Price v={r.fill} /> },
  { id: 'exit', header: 'Exit ₹', align: 'right', value: (r) => r.exit, cell: (r) => <Price v={r.exit} /> },
  { id: 'why', header: 'Exit', value: (r) => r.exit_reason, cell: (r) => <span className="text-xs text-muted">{r.exit_reason}</span> },
  { id: 'slip', header: 'Slippage', align: 'right', value: (r) => r.slippage_bps, cell: (r) => <span className="num">{bps(r.slippage_bps)}</span> },
  { id: 'react', header: 'Reaction', title: 'Signal file written -> filled', align: 'right', value: (r) => r.react_ms, cell: (r) => <span className="num">{r.react_ms == null ? '—' : `${num(r.react_ms, 0)} ms`}</span> },
  { id: 'net', header: 'P&L after charges', align: 'right', value: (r) => r.pnl_net, mobile: 'value', cell: (r) => <Money v={r.pnl_net} signed color /> },
]

const REC_COLS: Col<AutoRecordRow>[] = [
  { id: 'st', header: 'Strategy', value: (r) => r.strategy_name, sticky: true, mobile: 'primary', cell: (r) => <span className="font-medium">{r.strategy_name}</span> },
  { id: 'proof', header: 'Backtest', value: (r) => r.strategy_status ?? '', cell: (r) => (r.strategy_status ? <ProofBadge status={r.strategy_status} /> : null) },
  { id: 'n', header: 'Trades', align: 'right', value: (r) => r.trades, cell: (r) => <span className="num">{r.trades}</span> },
  { id: 'win', header: 'Win rate', align: 'right', value: (r) => r.win_rate, cell: (r) => <span className="num">{r.win_rate == null ? '—' : `${num(r.win_rate, 0)}%`}</span> },
  { id: 'slip', header: 'Slippage', title: 'Median', align: 'right', value: (r) => r.slippage_bps, cell: (r) => <span className="num">{bps(r.slippage_bps)}</span> },
  { id: 'lag', header: 'Signal lag', title: 'Median: signal written vs the strategy\'s own entry bar', align: 'right', value: (r) => r.signal_lag_s, cell: (r) => <span className="num">{r.signal_lag_s == null ? '—' : `${num(r.signal_lag_s, 0)} s`}</span> },
  { id: 'ch', header: 'Charges ₹', align: 'right', value: (r) => r.charges, cell: (r) => <Money v={r.charges} /> },
  { id: 'net', header: 'Net P&L ₹', align: 'right', value: (r) => r.pnl_net, mobile: 'value', cell: (r) => <Money v={r.pnl_net} signed color /> },
]

/** Seconds as µs / ms / s, whichever reads best. */
const dur = (s: number | null) =>
  s == null ? '—' : s < 0.001 ? `${num(s * 1e6, 0)} µs` : s < 1 ? `${num(s * 1000, s < 0.01 ? 2 : 0)} ms` : `${num(s, s < 10 ? 2 : 1)} s`

const LAT_COLS: Col<LatencyRow>[] = [
  { id: 'step', header: 'Step', value: (r) => r.label, sticky: true, mobile: 'primary', cell: (r) => <span className={r.n ? 'font-medium' : 'text-muted'}>{r.label}</span> },
  { id: 'n', header: 'Samples', align: 'right', value: (r) => r.n, cell: (r) => <span className="num text-muted">{r.n}</span> },
  { id: 'p50', header: 'P50', align: 'right', value: (r) => r.p50, mobile: 'value', cell: (r) => <span className="num">{dur(r.p50)}</span> },
  { id: 'p95', header: 'P95', align: 'right', value: (r) => r.p95, cell: (r) => <span className="num">{dur(r.p95)}</span> },
  { id: 'p99', header: 'P99', align: 'right', value: (r) => r.p99, cell: (r) => <span className="num">{dur(r.p99)}</span> },
  { id: 'max', header: 'Max', align: 'right', value: (r) => r.max, cell: (r) => <span className="num text-muted">{dur(r.max)}</span> },
]

function Speed({ sp }: { sp: AutoSpeed }) {
  const bus = !sp.bus.available ? ['not installed (pyzmq)', 'text-muted'] : sp.bus.connected ? [`connected · ${sp.bus.symbols} symbols`, 'text-profit'] : ['waiting for the live feed', 'text-warn']
  const e = sp.engine
  const eng = e.last_error ? [`error: ${e.last_error}`, 'text-loss'] : e.runs ? [`${e.runs} runs · last ${dur(e.last_compute_s)}`, 'text-profit'] : [e.day_ready ? 'ready, waiting for live bars' : 'waiting for the FYERS live feed', 'text-muted']
  return (
    <>
      <div className="mb-2 grid gap-1 text-[13px] sm:grid-cols-3">
        <div><span className="text-muted">Tick bus (ZeroMQ): </span><span className={bus[1]}>{bus[0]}</span></div>
        <div><span className="text-muted">Live signal engine: </span><span className={eng[1]}>{eng[0]}</span></div>
        <div><span className="text-muted">Compiled bar loops (Numba): </span><span className={e.numba ? 'text-profit' : 'text-muted'}>{e.numba == null ? 'starting' : e.numba ? `on${e.numba_warmup_s != null ? ` (ready in ${num(e.numba_warmup_s, 1)} s)` : ''}` : 'off'}</span></div>
      </div>
      <DataTable id="autotrade.speed" data={sp.latency} columns={LAT_COLS} rowKey={(r) => r.name} exportName="autotrade-speed" />
      <p className="mt-2 text-2xs text-muted">Measured in this server since it started. The same numbers are at <a className="link" href="/api/metrics" target="_blank" rel="noreferrer">/api/metrics</a> for Prometheus / Grafana. Exchange to your PC uses the exchange's whole-second time stamps and your PC clock: read it as ±1 s.</p>
    </>
  )
}

function Settings({ s, busy, onSave }: { s: AutoSettings; busy: boolean; onSave: (p: Partial<AutoSettings>) => void }) {
  const numIn = (k: keyof AutoSettings, label: string, hint: string, step = 1) => (
    <Field label={label} hint={hint}>
      <input type="number" step={step} defaultValue={s[k] as number} disabled={busy}
        className="focus-ring h-8 w-28 rounded-md border border-line bg-panel px-2 text-[13px] num"
        onBlur={(e) => { const v = Number(e.target.value); if (v && v !== s[k]) onSave({ [k]: v }) }} />
    </Field>
  )
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
        <Segmented<'all' | 'proven'> ariaLabel="Which signals" value={s.mode} onChange={(v) => onSave({ mode: v })}
          items={[{ id: 'all', label: 'All signals', title: 'Every strategy, each keeping its backtest label' }, { id: 'proven', label: 'Proven only', title: 'Only strategies whose backtest beat costs' }]} />
        <Switch checked={s.intraday} onChange={(v) => onSave({ intraday: v })} label="Intraday strategies" disabled={busy} />
        <Switch checked={s.oi} onChange={(v) => onSave({ oi: v })} label="Live OI build-ups" disabled={busy} />
        <Switch checked={s.options} onChange={(v) => onSave({ options: v })} label="Index option verdicts (1 lot)" disabled={busy} />
        <Switch checked={s.daily} onChange={(v) => onSave({ daily: v })} label="Daily strategies (practice bot)" disabled={busy} />
        <Switch checked={s.option_signals} onChange={(v) => onSave({ option_signals: v })} label="Options signals (1 lot each)" disabled={busy} />
      </div>
      <div className="flex flex-wrap gap-4">
        {numIn('max_positions', 'Max open positions', 'each trade at most 2x capital / this')}
        {numIn('max_trades_per_day', 'Max trades a day', 'then it stops entering')}
        {numIn('daily_loss_pct', 'Daily loss stop %', 'of capital: no new entries below it', 0.1)}
        {numIn('max_late_min', 'Max lateness (min)', 'after the strategy\'s own entry bar')}
        {numIn('max_option_positions', 'Max option positions', 'options signals open at once')}
      </div>
    </div>
  )
}

export default function AutoTradePage() {
  const q = useAutoTrade()
  const { save, stop, reset } = useAutoTradeActions()
  const d = q.data
  if (q.error && !d) return <div><PageHeader title="Auto-trader" /><div className="card"><ErrorState error={q.error} onRetry={() => void q.refetch()} /></div></div>
  if (!d) return <div><PageHeader title="Auto-trader" /><div className="card"><SkeletonRows rows={6} /></div></div>
  const s = d.settings
  const feed = d.feed ? FEED[d.feed] : null
  const busy = save.isPending || stop.isPending
  return (
    <div className="space-y-3">
      <PageHeader
        title="Auto-trader (practice)"
        subtitle={<>Takes the app's signals automatically within about a second, in its own practice account of {money(d.capital)}. Nothing is sent to FYERS.</>}
        right={
          <div className="flex items-center gap-2">
            <Button variant={s.on ? 'subtle' : 'primary'} icon={<Zap className="h-4 w-4" />} disabled={busy} onClick={() => save.mutate({ on: !s.on })}>{s.on ? 'Pause entries' : 'Start'}</Button>
            <Button variant="subtle" icon={<OctagonX className="h-4 w-4 text-loss" />} disabled={busy} onClick={() => stop.mutate()} title="Engine off and every engine position closed at the live price">Stop and close all</Button>
          </div>
        }
      />
      <Banner tone="info" icon={<Gauge className="h-4 w-4 text-info" />}>
        <span className="text-muted">Practice only. Speed through FYERS from a home PC is about 0.1-0.5 s; exchange-co-located HFT firms react in microseconds. Speed multiplies an edge, it doesn't create one: every intraday strategy so far lost money after costs in its backtest - this page measures what they do when actually traded.</span>
      </Banner>
      {(save.error || stop.error || reset.error) && <ErrorState compact error={(save.error || stop.error || reset.error)!} />}

      <div className="grid grid-cols-2 gap-2 md:grid-cols-4 lg:grid-cols-6">
        <KpiTile label="Engine" value={<span className={s.on ? 'text-profit' : 'text-muted'}>{s.on ? 'On' : 'Off'}</span>} sub={`${d.running ? 'loop running' : 'loop stopped'} · market ${d.session}`} />
        <KpiTile label="Prices" value={<span className={cn('text-[15px]', feed?.[1])}>{feed?.[0] ?? '—'}</span>} sub={d.last_loop ? `checked ${d.last_loop.slice(11, 19)}` : 'not run yet'} title="Run 1_login.bat before 09:15 for FYERS real-time prices" />
        <KpiTile label="Today" value={<Money v={d.today_pnl} signed color />} sub={`${d.today.trades} closed · ${d.positions.length} open`} />
        <KpiTile label="Equity" value={<Money compact v={d.equity} />} sub={`cash ${money(d.cash)}`} />
        <KpiTile label="Median slippage" value={bps(d.all_time.slippage_bps)} sub={`${d.all_time.trades} trades in all`} title="Fill vs the signal's price: the cost of being late" />
        <KpiTile label="Median reaction" value={d.all_time.react_ms == null ? '—' : `${num(d.all_time.react_ms, 0)} ms`} sub={d.all_time.signal_lag_s == null ? 'signal lag —' : `signal lag ${num(d.all_time.signal_lag_s, 0)} s`} title="Reaction: signals ready -> filled. Signal lag: the signals vs the strategy's own entry bar (about a second with the live engine, minutes with the 5-minute job)" />
      </div>

      <Card title="What it trades" subtitle={d.signals_at ? `Signals updated ${dateTimeIST(d.signals_at)} by the ${d.signals_engine === 'live' ? 'live engine (about a second after each bar)' : '5-minute job'}` : 'Signals: none today yet (live engine with the FYERS feed, else the 5-minute job 09:20-15:05)'}>
        <Settings s={s} busy={busy} onSave={(p) => save.mutate(p)} />
        {s.daily && d.daily.strategies.length > 0 && <p className="mt-2 text-2xs text-muted">Practice bot running for: {d.daily.strategies.map((x) => x.name).join(', ')} · <Link to="/bot" className="link">its own page</Link></p>}
      </Card>

      <Card title="Speed" subtitle="How long each step of the live path takes (P50 = typical, P99 = 1 in 100 slower)">
        <Speed sp={d.speed} />
      </Card>

      <Card title="Open positions" subtitle="Stops and targets act on every tick (tick bus), else every second; everything is squared off at 15:00" flush>
        {d.positions.length === 0 ? <EmptyState compact title={s.on ? 'No open position.' : 'The engine is off.'} />
          : <DataTable id="autotrade.positions" data={d.positions} columns={POS_COLS} rowKey={(r) => r.symbol} exportName="autotrade-positions" />}
      </Card>

      <Card title="Today's trades" subtitle={d.today.trades ? `${d.today.wins} of ${d.today.trades} won · charges ${money(d.today.charges)} · net ${money(d.today.pnl_net)}` : undefined} flush>
        {d.trades_today.length === 0 ? <EmptyState compact title="No closed trade today." />
          : <DataTable id="autotrade.today" data={d.trades_today} columns={TRADE_COLS} rowKey={(r) => `${r.symbol}${r.opened_at}`} exportName="autotrade-today" />}
      </Card>

      <Card title="Record by strategy (all days)" subtitle="Traded for real on live prices with slippage and charges - compare with each strategy's backtest" flush>
        {d.record.length === 0 ? <EmptyState compact title="No closed trade yet." />
          : <DataTable id="autotrade.record" data={d.record} columns={REC_COLS} rowKey={(r) => r.strategy_key} exportName="autotrade-record" />}
      </Card>

      {((d.options.signals_open?.length ?? 0) > 0 || (d.options.signals_closed?.length ?? 0) > 0) && (
        <Card title="Options signals (one lot each)" subtitle="Taken from Signals > Options; closed with their signal (stop, target, strategy exit, square-off, expiry)">
          <ul className="space-y-1 text-[13px]">
            {(d.options.signals_open ?? []).map((p) => <li key={p.id}><span className="font-semibold">{p.symbol}</span> {p.structure} {p.legs.map((l) => `${l.strike.toLocaleString('en-IN')} ${l.type}`).join(' / ')} · {p.expiry} · lot {p.lot} at {num(p.entry, 2)}{p.mark != null && <> · now {num(p.mark, 2)} (<Money v={p.unrealized ?? null} signed color />)</>}</li>)}
            {(d.options.signals_closed ?? []).slice(0, 30).map((p) => <li key={p.id} className="text-muted">{p.symbol} {p.structure} · {p.exit_reason} · <Money v={p.pnl ?? null} signed color /></li>)}
          </ul>
        </Card>
      )}

      {(d.options.open.length > 0 || d.options.closed.length > 0) && (
        <Card title="Index options (one lot per BUY verdict)" subtitle="Bought at the stored chain's ask with exact charges; settled at expiry at NSE's official close">
          <ul className="space-y-1 text-[13px]">
            {d.options.open.map((p) => <li key={p.id}><span className="font-semibold">{p.symbol}</span> {num(p.strike, 0)} {p.side.toUpperCase()} {p.expiry} · lot {p.lot} at {num(p.premium, 2)}{p.mark != null && <> · now {num(p.mark, 2)} (<Money v={p.value_net ?? null} signed color />)</>}</li>)}
            {d.options.closed.map((p) => <li key={p.id} className="text-muted">{p.symbol} {num(p.strike, 0)} {p.side.toUpperCase()} {p.expiry} · settled {num(p.settle ?? null, 2)} · <Money v={p.pnl_net ?? null} signed color /></li>)}
          </ul>
        </Card>
      )}

      <Card title="Engine log" subtitle="Entries, exits, skips with the reason, settings" right={<Button size="sm" variant="ghost" icon={<RotateCcw className="h-3.5 w-3.5" />} disabled={busy || d.positions.length > 0} onClick={() => reset.mutate()} title="A new practice account for the engine (its record stays)">Reset account</Button>}>
        {d.log.length === 0 ? <p className="text-xs text-muted">Nothing yet.</p> : (
          <ul className="max-h-72 space-y-0.5 overflow-auto text-xs">
            {d.log.map((e, i) => (
              <li key={i} className={cn(e.kind === 'entry' && 'text-fg', e.kind === 'exit' && 'text-fg', e.kind === 'skip' && 'text-muted', e.kind === 'warn' && 'text-warn', e.kind === 'kill' && 'text-loss')}>
                <span className="num text-faint">{e.at.slice(11, 19)}</span> {e.text}
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  )
}
