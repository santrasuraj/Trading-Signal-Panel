// Data & Settings `/settings/:section` (spec 3.11). Config is read-only in this version (PATCH is P2): values are
// shown with where to change them.

import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { Link, NavLink, useNavigate, useParams } from 'react-router-dom'
import { Download, LogIn, RotateCw, Terminal } from 'lucide-react'
import { isFailure } from '@/api/client'
import { useConfig, useCostPreview, useDataHealth, useFyersLogin, useFyersStatus, useScanHistory, useScanLog, useStatus } from '@/api/hooks'
import type { ConfigView, CostBreakdown, ScanHistoryItem } from '@/api/types'
import { useUi } from '@/app/uiState'
import { DataTable, type Col } from '@/components/DataTable'
import { PageHeader } from '@/components/domain'
import { Banner, ErrorState, SkeletonRows } from '@/components/feedback'
import { ProgressBar, useRunScan } from '@/components/layout/ScanButton'
import { useToast } from '@/components/toast'
import { Button, Card, Chip, KV, Segmented, Switch } from '@/components/ui'
import { cn } from '@/lib/csv'
import { date, dateTimeIST, duration, money, num, pct, relative, timeIST } from '@/lib/format'
import { useTheme, type Density, type ThemePref } from '@/lib/theme'

type Section = 'data' | 'fyers' | 'scan' | 'capital' | 'strategies' | 'costs' | 'filters' | 'appearance' | 'about'
const SECTIONS: { id: Section; label: string }[] = [
  { id: 'data', label: 'Data health' }, { id: 'fyers', label: 'Fyers login' }, { id: 'scan', label: 'Scan' },
  { id: 'capital', label: 'Capital & allocations' }, { id: 'strategies', label: 'Strategies' }, { id: 'costs', label: 'Costs & tax' },
  { id: 'filters', label: 'Filters' }, { id: 'appearance', label: 'Appearance' }, { id: 'about', label: 'About & disclaimer' },
]

function ReadOnlyNote() {
  return <p className="text-2xs text-faint">Read-only here for now: edit <span className="font-mono">config.yaml</span> in the app folder (this checkout), then run a scan. In-app editing is planned.</p>
}

function DataSection() {
  const q = useDataHealth()
  const { data: st } = useStatus()                 // before the early returns: hooks run on every render
  const [level, setLevel] = useState<'all' | 'error'>('all')
  const log = useScanLog(level)
  const logRef = useRef<HTMLPreElement>(null)
  // the log is oldest-first: open it at the newest line
  useEffect(() => { const el = logRef.current; if (el) el.scrollTop = el.scrollHeight }, [log.data, q.data])
  if (q.error) return <Card><ErrorState error={q.error} onRetry={() => void q.refetch()} /></Card>
  if (!q.data) return <Card><SkeletonRows rows={6} /></Card>
  const h = q.data
  const failed = Object.entries(h.failed_symbols)
  return (
    <div className="space-y-3">
      <div className="grid gap-3 lg:grid-cols-2">
        <Card title="Price store" subtitle={<span className="font-mono">{h.store.version}</span>}>
          <KV k="Dates" v={`${date(h.store.first_date)} → ${date(h.store.last_date)}`} />
          <KV k="Trading days · symbols" v={`${num(h.store.trading_days, 0)} · ${h.store.symbols}`} />
          <KV k="Fields" v={h.store.fields.join(', ')} />
          <KV k="Size" v={`${num(h.store.size_mb, 1)} MB`} />
          <KV k="NSE status" v={h.nse.status ?? '—'} />
          <KV k="NSE complete up to" v={date(h.nse.complete_upto)} />
        </Card>
        <Card title="Sources">
          <KV k="Universe" v={`${h.universe.note} · ${h.universe.size}`} />
          <KV k="Index history" v={h.index_history ? `${date(h.index_history.last_date)} · ${h.index_history.columns} indices` : 'missing'} />
          <KV k="Results calendar" v={h.results_calendar.cached_on ? `cached ${date(h.results_calendar.cached_on)}` : 'missing'} title={h.results_calendar.note ?? undefined} />
          <KV k="Point-in-time universe" v={h.pit?.built ? (st?.latest?.backtest_universe === 'point_in_time' ? 'built · in use' : 'built · not used') : 'not built'} title={h.pit?.note} />
          <KV k="Paper journal" v={h.journal.exists ? `${h.journal.days ?? 0} day${(h.journal.days ?? 0) === 1 ? '' : 's'} · ${num(h.journal.size_kb, 0)} KB` : 'not started'} />
          <KV k="Saved scans" v={`${h.scans.count}${h.scans.newest ? ` · newest ${dateTimeIST(h.scans.newest)}` : ''}`} />
          {h.scans.mixed_producers && <p className="mt-2 text-2xs text-warn">Saved scans come from different scanner versions (the data folder is shared with other checkouts); comparisons only use fields present in both.</p>}
        </Card>
      </div>
      {(failed.length > 0 || h.stale_symbols.length > 0 || Object.keys(h.errors).length > 0) && (
        <Card title="Problems">
          {failed.length > 0 && <div className="mb-2 text-[13px]"><span className="text-muted">Failed downloads: </span>{failed.map(([s, f]) => <Chip key={s} className="mr-1 tint-warn text-warn" title={`${f.count} tries, last ${f.last_try}`}>{s}</Chip>)}</div>}
          {h.stale_symbols.length > 0 && <div className="mb-2 text-[13px]"><span className="text-muted">No fresh price: </span>{h.stale_symbols.join(', ')}</div>}
          {Object.entries(h.errors).map(([k, v]) => <div key={k} className="text-xs text-loss"><span className="font-semibold">{k}</span>: {v}</div>)}
        </Card>
      )}
      <Card title="Corporate-action adjustments" subtitle={`Last 20 of ${h.corporate_actions_total}; prices before the ex-date are multiplied by the factor`} flush>
        <div className="scroll-x">
        <table className="w-full text-[13px]">
          <thead><tr className="border-b border-line text-2xs font-semibold uppercase tracking-[0.04em] text-muted"><th className="px-4 py-2 text-left font-semibold">Symbol</th><th className="px-3 py-2 text-left font-semibold">Ex-date</th><th className="px-3 py-2 text-right font-semibold">Factor</th><th className="px-4 py-2 text-left font-semibold">Reason</th></tr></thead>
          <tbody>{h.corporate_actions_recent.map((c) => (
            <tr key={`${c.symbol}${c.date}`} className="border-b border-line/60 last:border-0"><td className="px-4 py-1.5 font-semibold"><Link to={`/chart/${c.symbol}`} className="hover:underline">{c.symbol}</Link></td><td className="num whitespace-nowrap px-3 py-1.5 text-muted">{date(c.date)}</td><td className="num px-3 py-1.5 text-right">{num(c.factor, 4)}</td><td className="whitespace-nowrap px-4 py-1.5 text-muted">{c.reason}</td></tr>
          ))}</tbody>
        </table>
        </div>
      </Card>
      <Card title="Scanner log" subtitle={<span className="break-all font-mono text-2xs">{h.logs.path}</span>} right={<Segmented size="xs" ariaLabel="Log level" value={level} onChange={setLevel} items={[{ id: 'all', label: 'All' }, { id: 'error', label: 'Errors' }]} />} flush>
        {h.logs.last_error && <div className="border-b border-line px-4 py-2 text-xs text-loss">Last error: {h.logs.last_error}</div>}
        <pre ref={logRef} className="max-h-[360px] overflow-auto px-4 py-3 font-mono text-[11.5px] leading-[18px] text-muted">{log.data ? log.data.lines.join('\n') || 'Empty.' : 'Loading…'}</pre>
      </Card>
    </div>
  )
}

function FyersSection() {
  const { data: s } = useStatus()
  const { setFyersLogin } = useUi()
  const toast = useToast()
  const login = useFyersLogin()
  // One profile check (server caches it 5 min and skips it while a scan runs), only when today's token exists.
  const verify = useFyersStatus(!!s?.fyers.logged_in_today)
  const f = s?.fyers
  if (!f) return <Card><SkeletonRows rows={4} /></Card>
  const v = verify.data
  const openWindow = () =>
    login.mutate('window', {
      onSuccess: (r) => toast({ tone: 'info', title: 'Fyers login window opened', detail: r.instructions.join(' ') }),
      onError: (e) => toast({ tone: 'bad', title: isFailure(e) ? e.message : 'Could not open the login window', detail: isFailure(e) ? e.hint ?? undefined : undefined }),
    })
  return (
    <div className="space-y-3">
      <Card title="Fyers" subtitle={v?.note ?? f.note}>
        <KV k="App credentials (.env)" v={f.configured ? 'configured' : <span className="text-warn">missing</span>} />
        <KV k="Client id" v={<span className="font-mono">{f.client_id_masked ?? '—'}</span>} />
        <KV k="Plan" v={<span className="capitalize">{f.plan}</span>} />
        <KV k="Data source" v={f.data_source === 'auto' ? 'Fyers when logged in, else Yahoo (~15 min delayed)' : 'Yahoo only'} />
        <KV k="Token created" v={f.token_created ? `${dateTimeIST(f.token_created)} (${relative(f.token_created)})` : 'never'} />
        <KV k="Logged in today" v={f.logged_in_today ? <span className="text-profit">yes</span> : <span className="text-warn">no</span>} />
        {f.logged_in_today && (
          <KV
            k="Token check"
            title={v?.verified_at ? `Checked ${dateTimeIST(v.verified_at)}` : undefined}
            v={verify.isLoading ? <span className="text-muted">checking…</span>
              : v?.verified === true ? <span className="text-profit">verified{v.user_name ? ` as ${v.user_name}` : ''}</span>
              : v?.verified === false ? <span className="text-loss">rejected: log in again</span>
              : <span className="text-muted" title="Skipped while a scan runs or when the Fyers API budget is low">not checked yet</span>}
          />
        )}
        <div className="mt-4 flex flex-wrap gap-2">
          <Button variant="primary" icon={<LogIn className="h-4 w-4" />} disabled={!f.configured} onClick={() => setFyersLogin(true)}>Log in</Button>
          <Button icon={<Terminal className="h-4 w-4" />} disabled={!f.configured} loading={login.isPending} onClick={openWindow} title="Runs 1_login.bat in a console window on this computer">Open login window (legacy)</Button>
        </div>
      </Card>
      <Card title="How login works">
        <ol className="list-decimal space-y-1.5 pl-5 text-[13px] text-muted">
          <li>Fyers tokens expire daily, so log in once each trading day (before the 15:40 scheduled scan if you want real-time prices).</li>
          <li>The login page redirects to your app's redirect URL (<span className="break-all font-mono text-fg">{f.redirect_uri}</span>). That page may not load; copy the full address from the browser bar and paste it into the dialog.</li>
          <li>The secret and the access token never leave this computer and are never shown in the app.</li>
        </ol>
      </Card>
    </div>
  )
}

function ScanSection() {
  const { data: s } = useStatus()
  const { run, pending } = useRunScan()
  const hist = useScanHistory()
  const nav = useNavigate()
  const scan = s?.scan
  const running = !!scan && (scan.running || scan.state === 'starting')
  const cols: Col<ScanHistoryItem>[] = [
    { id: 'when', header: 'Scan', value: (r) => r.scan_id, cell: (r) => <span className="num">{dateTimeIST(r.scan_id)}</span>, mobile: 'primary' },
    { id: 'data', header: 'Prices', value: (r) => r.data_date, cell: (r) => <span className="num text-muted">{date(r.data_date)}</span>, mobile: 'secondary', label: 'Prices' },
    { id: 'live', header: 'Live', value: (r) => r.live, cell: (r) => (r.live ? <Chip className="tint-warn text-warn">live</Chip> : <span className="text-faint">—</span>) },
    { id: 'el', header: 'Took', align: 'right', value: (r) => r.elapsed_s, cell: (r) => <span className="num">{duration(r.elapsed_s)}</span>, mobile: 'value' },
    { id: 'n', header: 'Strategies', align: 'right', value: (r) => r.strategies, cell: (r) => <span className="num">{r.strategies ?? '—'}</span> },
    { id: 'file', header: 'File', value: (r) => r.file, cell: (r) => <span className="font-mono text-2xs text-faint">{r.file}</span>, defaultHidden: true },
  ]
  return (
    <div className="space-y-3">
      <Card title="Run a scan">
        <div className="flex flex-wrap gap-2">
          <Button variant="primary" icon={<Download className="h-4 w-4" />} disabled={running} loading={pending} onClick={() => run(true)}>Full scan</Button>
          <Button icon={<RotateCw className="h-4 w-4" />} disabled={running || pending} onClick={() => run(false)}>Re-check without download (~2 min)</Button>
        </div>
        {scan && (
          <div className="mt-4 space-y-2">
            <div className="flex items-center justify-between text-xs">
              <span className="font-medium"><span className="capitalize">{scan.state}</span>{(scan.by || scan.started_at) ? ` · started${scan.by ? ` by ${scan.by}` : ''}${scan.started_at ? ` at ${timeIST(scan.started_at)}` : ''}` : ''}</span>
              {scan.progress_pct != null && <span className="num text-muted">{num(scan.progress_pct, 0)}%</span>}
            </div>
            {running && <ProgressBar pct={scan.progress_pct} message={scan.message} />}
            <div className={cn('text-xs', scan.state === 'failed' ? 'text-loss' : 'text-muted')}>{scan.message ?? '—'}</div>
            {scan.state === 'failed' && <Button size="sm" onClick={() => nav('/settings/data')}>Open the log</Button>}
          </div>
        )}
        <p className="mt-4 text-2xs text-faint">Scheduled scans run at 08:30, 15:40 and 19:15 on weekdays (setup_schedule.ps1). Scheduled and manual scans share one lock, so this page follows whichever is running.</p>
      </Card>
      {/* the count that is really listed (the server keeps up to 60; "Last 60" over a "1-20 of 30" pager read wrong) */}
      <Card title={hist.data ? `Recent scans (${hist.data.scans.length})` : 'Recent scans'} subtitle="Up to the last 60 kept" flush>
        {hist.error ? <ErrorState error={hist.error} compact /> : !hist.data ? <SkeletonRows rows={6} /> : (
          <DataTable id="settings.scans" data={hist.data.scans} columns={cols} rowKey={(r) => r.file} pageSize={20} />
        )}
      </Card>
    </div>
  )
}

function ConfigSection({ children }: { children: (c: ConfigView, needsRescan: boolean) => ReactNode }) {
  const q = useConfig()
  if (q.error) return <Card><ErrorState error={q.error} onRetry={() => void q.refetch()} /></Card>
  if (!q.data) return <Card><SkeletonRows rows={5} /></Card>
  return (
    <div className="space-y-3">
      {q.data.needs_rescan && <Banner tone="warn">config.yaml changed after the last scan ({dateTimeIST(q.data.file_mtime)}): results reflect the old settings until the next scan.</Banner>}
      {children(q.data.values, q.data.needs_rescan)}
    </div>
  )
}

function CapitalSection() {
  const { data: s } = useStatus()
  return (
    <ConfigSection>
      {(c) => {
        const alloc = Object.entries(c.allocations)
        const total = alloc.reduce((a, [, v]) => a + v, 0)
        return (
          <>
            <Card title="Capital">
              <KV k="Capital" v={money(c.account.capital)} />
              <KV k="Minimum position" v={money(c.account.min_position)} title="Buys smaller than this are flagged (fixed charges hurt tiny orders)" />
              <KV k="Round-trip costs" v={`≈ ${pct(s?.latest?.costs_round_trip_pct, { signed: false, dp: 2 })}`} />
              <div className="mt-3"><ReadOnlyNote /></div>
            </Card>
            <Card title="Allocations" subtitle="Share of capital per strategy; the rest stays in cash">
              {alloc.length === 0 ? (
                <p className="text-[13px] text-muted">No allocations set: each strategy is sized on your full capital. If you follow more than one strategy, add an <span className="font-mono text-fg">allocations:</span> section to config.yaml (for example <span className="font-mono text-fg">momentum: 60</span>, <span className="font-mono text-fg">earnings_gap: 40</span>). Try splits first with the What-if on the Signals page.</p>
              ) : (
                <>
                  {alloc.map(([k, v]) => <KV key={k} k={k} v={`${num(v, 0)}% · ${money((c.account.capital * v) / 100)}`} />)}
                  <KV k="Cash" v={`${num(Math.max(0, 100 - total), 0)}%`} />
                  {total > 100 && <p className="mt-2 text-xs text-loss">Allocations add up to {num(total, 0)}%: more than your capital.</p>}
                </>
              )}
              <div className="mt-3"><Link to="/signals" className="link text-xs">Open Signals what-if</Link></div>
            </Card>
          </>
        )
      }}
    </ConfigSection>
  )
}

function StrategiesSection() {
  return (
    <ConfigSection>
      {(c) => (
        <Card title="Strategies in config.yaml" subtitle="Enabled strategies are re-tested on every scan; disabled ones with a reason are listed as Tested & rejected" flush>
          <div className="scroll-x">
          <table className="w-full text-[13px]">
            <thead><tr className="border-b border-line text-2xs font-semibold uppercase tracking-[0.04em] text-muted"><th className="px-4 py-2 text-left font-semibold">Key</th><th className="px-3 py-2 text-left font-semibold">State</th><th className="px-4 py-2 text-left font-semibold">Parameters</th></tr></thead>
            <tbody>{Object.entries(c.strategies).map(([k, v]) => (
              <tr key={k} className="border-b border-line/60 align-top last:border-0">
                <td className="px-4 py-2"><Link to={`/strategies/${k}`} className="font-mono text-xs font-semibold hover:underline">{k}</Link></td>
                <td className="px-3 py-2">{v.enabled ? <Chip className="tint-profit text-profit">on</Chip> : <Chip>off</Chip>}</td>
                <td className="min-w-[220px] px-4 py-2 font-mono text-2xs text-muted [overflow-wrap:anywhere]">{Object.entries(v.params).map(([pk, pv]) => `${pk}: ${Array.isArray(pv) ? `[${pv.join(', ')}]` : String(pv)}`).join(' · ') || 'defaults'}</td>
              </tr>
            ))}</tbody>
          </table>
          </div>
          <div className="border-t border-line px-4 py-2"><ReadOnlyNote /></div>
        </Card>
      )}
    </ConfigSection>
  )
}

function Breakdown({ b }: { b: CostBreakdown }) {
  const rows: [string, number][] = [['Brokerage', b.brokerage], ['STT', b.stt], ['Exchange', b.exchange], ['SEBI', b.sebi], ['Stamp duty', b.stamp], ['GST', b.gst], ['DP charge', b.dp], ['Slippage (est.)', b.slippage]]
  return (
    <div>
      <div className="eyebrow mb-1">{b.side === 'buy' ? 'Buy' : 'Sell'}</div>
      {rows.map(([k, v]) => <KV key={k} k={k} v={money(v, { dp: 2 })} />)}
      <KV k={<span className="font-semibold text-fg">Total</span>} v={<span className="font-semibold">{money(b.total, { dp: 2 })} · {pct(b.total_pct, { signed: false, dp: 3 })}</span>} className="border-t border-line" />
    </div>
  )
}

function CostsSection() {
  // the box keeps what is typed (clearing it must not turn it into "0" and then "0500"); only a value >= 1 queries
  const [raw, setRaw] = useState('33333')
  const value = Number(raw)
  const valid = raw.trim() !== '' && Number.isFinite(value) && value >= 1
  const [debounced, setDebounced] = useState(33333)
  useEffect(() => { if (!valid) return; const t = setTimeout(() => setDebounced(value), 300); return () => clearTimeout(t) }, [value, valid])
  const prev = useCostPreview(debounced)
  return (
    <ConfigSection>
      {(c) => (
        <>
          <Card title="Cost of one order" subtitle={`Delivery (CNC) charges; slippage shown for liquid stocks (the backtest uses ${num(c.costs.slippage_illiquid_pct, 2)}% per side under ₹${num(c.costs.illiquid_below_cr, 0)} cr/day)`}>
            <label className="mb-4 flex items-center gap-3 text-[13px]">
              <span className="text-muted">Order value ₹</span>
              <input type="number" min={1} step={1000} value={raw} onChange={(e) => setRaw(e.target.value)} aria-invalid={!valid} className={cn('input num w-36 text-right', !valid && 'border-loss/70')} />
              {!valid && <span className="text-xs text-loss">Enter an order value of ₹1 or more</span>}
              {valid && prev.data && <span className="num ml-auto">Round trip <span className="font-semibold">{pct(prev.data.round_trip_pct, { signed: false, dp: 3 })}</span></span>}
            </label>
            {prev.error ? <ErrorState error={prev.error} compact /> : prev.data ? <div className="grid gap-6 sm:grid-cols-2"><Breakdown b={prev.data.buy} /><Breakdown b={prev.data.sell} /></div> : <SkeletonRows rows={4} cols={2} />}
          </Card>
          <div className="grid gap-3 lg:grid-cols-2">
            <Card title="Cost settings">
              {Object.entries(c.costs).map(([k, v]) => <KV key={k} k={<span className="font-mono text-2xs">{k}</span>} v={num(v, k.endsWith('_cr') || k.startsWith('dp') || k.endsWith('max') ? 2 : 5).replace(/\.?0+$/, '')} />)}
            </Card>
            <Card title="Tax">
              <KV k="Short-term (≤ 12 months)" v={`${num(c.tax.stcg_pct, 1)}%`} />
              <KV k="Long-term" v={`${num(c.tax.ltcg_pct, 1)}%`} />
              <KV k="LTCG exemption per year" v={money(c.tax.ltcg_exempt)} />
              <p className="mt-3 text-2xs text-faint">Intraday profit is speculative business income taxed at your slab rate; the intraday page uses its own cost and tax profile.</p>
            </Card>
          </div>
          <ReadOnlyNote />
        </>
      )}
    </ConfigSection>
  )
}

function FiltersSection() {
  return (
    <ConfigSection>
      {(c) => (
        <Card title="Universe and filters">
          <KV k="Universe" v={c.universe.toUpperCase()} />
          <KV k="History" v={`${num(c.lookback_days, 0)} days`} />
          <KV k="Minimum price" v={money(c.filters.min_price)} />
          <KV k="Minimum turnover" v={`₹${num(c.filters.min_turnover_cr, 0)} cr/day`} />
          <KV k="Results warning" v={`${c.results.warn_days} days`} />
          <KV k="Movers shown" v={c.movers_count} />
          <KV k="Holdings default stop / target" v={`${c.holdings_defaults.stop_loss_pct}% / ${c.holdings_defaults.target_pct}%`} />
          <KV k="ETFs" v={c.etfs.join(', ')} />
          <KV k="Data source · Fyers plan" v={`${c.data_source} · ${c.fyers_plan}`} />
          <KV k="Telegram" v={c.telegram.configured ? `on (top ${c.telegram.top_n})` : 'not configured'} />
          <div className="mt-3"><ReadOnlyNote /></div>
        </Card>
      )}
    </ConfigSection>
  )
}

function AppearanceSection() {
  const t = useTheme()
  return (
    <Card title="Appearance" subtitle="Stored in this browser only">
      <div className="space-y-5">
        <div className="flex flex-wrap items-center justify-between gap-3"><div><div className="text-[13px] font-medium">Theme</div><div className="text-xs text-muted">Dark is easier on long sessions</div></div>
          <Segmented<ThemePref> ariaLabel="Theme" value={t.pref} onChange={t.setPref} items={[{ id: 'system', label: 'System' }, { id: 'dark', label: 'Dark' }, { id: 'light', label: 'Light' }]} /></div>
        <div className="flex flex-wrap items-center justify-between gap-3"><div><div className="text-[13px] font-medium">Density</div><div className="text-xs text-muted">Compact fits more rows on a screen</div></div>
          <Segmented<Density> ariaLabel="Density" value={t.density} onChange={t.setDensity} items={[{ id: 'comfortable', label: 'Comfortable' }, { id: 'compact', label: 'Compact' }]} /></div>
        <div className="flex flex-wrap items-center justify-between gap-3"><div><div className="text-[13px] font-medium">Colour-blind safe</div><div className="text-xs text-muted">Gains in blue, losses in orange</div></div><Switch checked={t.cvd} onChange={t.setCvd} ariaLabel="Colour-blind safe colours" /></div>
        <div className="flex flex-wrap items-center justify-between gap-3"><div><div className="text-[13px] font-medium">Compact rupees on tiles</div><div className="text-xs text-muted">₹5.00 L instead of ₹5,00,000 in KPI tiles</div></div><Switch checked={t.compactMoney} onChange={t.setCompactMoney} ariaLabel="Compact rupees on tiles" /></div>
      </div>
    </Card>
  )
}

function AboutSection() {
  const { data: s } = useStatus()
  return (
    <div className="space-y-3">
      <Card title="Disclaimer">
        <div className="max-w-[72ch] space-y-3 text-[14px] leading-6 text-muted">
          <p className="text-fg">Quant Desk is a personal research tool. It is not investment advice, and nothing in it is a recommendation to buy or sell.</p>
          <p>Strategy numbers are backtests on past NSE data with realistic Indian costs. While backtests use today's index list they include survivorship bias: stocks that fell out of the index are missing, so results look better than reality. Live and paper results are usually worse than backtests.</p>
          <p>Orders shown are what a model portfolio would do at the next open. You decide and place every trade yourself in your broker's app; the app never places orders.</p>
          <p>Sharing these signals with others as recommendations requires SEBI Research Analyst registration.</p>
          <p>Intraday trading: SEBI found that 71% of individual intraday traders lost money in FY23. Intraday strategies here are research only and produce no orders; the Intraday page shows how each one did after costs.</p>
        </div>
      </Card>
      <Card title="Data and software">
        <KV k="Prices" v="NSE bhavcopy and index files; Yahoo / Fyers for gaps and live candles" />
        <KV k="Corporate actions" v="NSE (splits, bonuses, demergers)" />
        <KV k="Results dates" v="NSE board-meeting calendar" />
        <KV k="Server" v={s?.server_version ?? '—'} />
        {/* non-breaking inside each name, so a narrow card wraps between names ("charts 5" was left alone on line 2) */}
        <KV k="UI" v={'Quant Desk 3.0 · React 18 · TanStack Query/Table · lightweight‑charts 5'} />
        <p className="mt-3 text-2xs text-faint">Charts by TradingView lightweight-charts (Apache-2.0); the TradingView attribution is kept on every chart. Fonts: Inter and JetBrains Mono (SIL OFL), self-hosted.</p>
      </Card>
    </div>
  )
}

export default function Settings() {
  const { section = 'data' } = useParams()
  const s = (SECTIONS.some((x) => x.id === section) ? section : 'data') as Section
  const nav = useNavigate()
  const content = useMemo(() => ({
    data: <DataSection />, fyers: <FyersSection />, scan: <ScanSection />, capital: <CapitalSection />, strategies: <StrategiesSection />,
    costs: <CostsSection />, filters: <FiltersSection />, appearance: <AppearanceSection />, about: <AboutSection />,
  }), [])
  return (
    <div>
      <PageHeader title="Data & Settings" />
      <div className="grid gap-4 md:grid-cols-[200px_minmax(0,1fr)]">
        <nav aria-label="Settings sections" className="md:sticky md:top-16 md:self-start">
          <select value={s} onChange={(e) => nav(`/settings/${e.target.value}`)} className="input w-full md:hidden" aria-label="Section">
            {SECTIONS.map((x) => <option key={x.id} value={x.id}>{x.label}</option>)}
          </select>
          <ul className="hidden space-y-0.5 md:block">
            {SECTIONS.map((x) => (
              <li key={x.id}>
                <NavLink to={`/settings/${x.id}`} className={({ isActive }) => cn('focus-ring block rounded-md px-3 py-1.5 text-[13px]', isActive ? 'bg-raised font-medium text-fg' : 'text-muted hover:bg-raised/60 hover:text-fg')}>{x.label}</NavLink>
              </li>
            ))}
          </ul>
        </nav>
        <div className="min-w-0 max-w-[1100px]">{content[s]}</div>
      </div>
    </div>
  )
}
