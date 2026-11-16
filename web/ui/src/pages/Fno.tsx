// F&O positioning `/fno/:tab` (scanner/fno.py): NSE's participant-wise open interest (FII, DII, Pro, Client) and the
// day's futures build-ups with each underlying's put-call ratio and call / put walls: live during the session (NSE OI
// spurts + live prices, POST /api/fno/live/refresh every 3 min) and end of day (the F&O bhavcopy), published by
// NSE after the close; "Fetch" posts /api/fno/refresh. Positioning, never a signal.

import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { RefreshCw, Scale } from 'lucide-react'
import { isFailure } from '@/api/client'
import {
  fnoKeys, useFnoFutures, useFnoLive, useFnoLiveRefresh, useFnoPositions, useFnoRefresh, useFnoStatus,
  type FnoBuildup, type FnoClient, type FnoFuturesParams, type FnoLiveParams, type FnoStatus,
} from '@/api/fno'
import { useStatus } from '@/api/hooks'
import { BUILDUP_LABEL } from '@/api/options'
import { useUi } from '@/app/uiState'
import { useLocalStorage } from '@/lib/useLocalStorage'
import { KpiStrip, KpiTile, PageHeader } from '@/components/domain'
import { EmptyState, ErrorState, SkeletonKpis, SkeletonRows } from '@/components/feedback'
import { useToast } from '@/components/toast'
import { Button, Card, Segmented, Tabs, Tip } from '@/components/ui'
import { cn } from '@/lib/csv'
import { DASH, date, num, ok, pct, qty, timeIST } from '@/lib/format'

type Tab = 'positions' | 'futures'
const CLIENT_LABEL: Record<FnoClient, string> = { fii: 'FII', dii: 'DII', pro: 'Pro', client: 'Client' }
const CLIENT_HELP: Record<FnoClient, string> = {
  fii: 'Foreign portfolio investors', dii: 'Domestic institutions (mutual funds, insurers, banks)',
  pro: "Brokers trading their own money", client: 'Everyone else: retail traders, HNIs, corporates',
}
const signed = (x: number | null | undefined) => (ok(x) ? `${x > 0 ? '+' : ''}${qty(x)}` : DASH)
const FUT_HELP: Record<FnoBuildup, string> = {
  long_buildup: 'Price up, open interest up: new long positions.',
  short_buildup: 'Price down, open interest up: new short positions.',
  short_covering: 'Price up, open interest down: shorts closing.',
  long_unwinding: 'Price down, open interest down: longs closing.',
}
const BUILD_TONE: Record<FnoBuildup, string> = {
  long_buildup: 'text-profit border-profit/40', short_buildup: 'text-loss border-loss/40',
  short_covering: 'text-info border-info/40', long_unwinding: 'text-warn border-warn/40',
}

function useWatcher(st: FnoStatus | undefined) {
  const qc = useQueryClient()
  const toast = useToast()
  const was = useRef(false)
  useEffect(() => {
    if (!st) return
    if (was.current && !st.run.running) {
      toast({ tone: st.run.state === 'failed' ? 'bad' : 'good', title: st.run.state === 'failed' ? 'F&O data not fetched' : 'F&O data updated', detail: st.run.message ?? undefined })
      void qc.invalidateQueries({ queryKey: fnoKeys.all })
    }
    was.current = st.run.running
  }, [st, qc, toast])
}

function FetchButton({ st }: { st: FnoStatus | undefined }) {
  const r = useFnoRefresh()
  const toast = useToast()
  return (
    <Button size="sm" icon={<RefreshCw className="h-3.5 w-3.5" />} loading={r.isPending || !!st?.run.running}
      title="Fetch NSE's participant files and F&O bhavcopy for the last 30 trading days not stored yet (published ~6-8 PM)"
      onClick={() => r.mutate(undefined, { onError: (e) => toast({ tone: 'bad', title: isFailure(e) ? e.message : 'Could not start the refresh' }) })}>
      {st?.run.running ? (st.run.message ?? 'Fetching…') : 'Fetch'}
    </Button>
  )
}

// ------------------------------------------------------------------ positions
/** Long share of index futures per day on a 0-100% scale, with the scale and the 50% line drawn: without them a group
 *  that is mostly short (FII ~12% long) showed tiny bars under a blank box that looked like a broken chart. */
function LongPctBars({ dates, v }: { dates: string[]; v: (number | null)[] }) {
  return (
    <div className="flex h-36 gap-2" role="img" aria-label="Index futures long share by day">
      <div className="num flex flex-col justify-between py-0 text-right text-2xs leading-none text-faint" aria-hidden>
        <span>100%</span><span>50%</span><span>0%</span>
      </div>
      <div className="relative min-w-0 flex-1">
        <div className="absolute inset-x-0 top-0 border-t border-line/70" aria-hidden />
        <div className="absolute inset-x-0 top-1/2 border-t border-dashed border-line-strong" aria-hidden />
        <div className="absolute inset-x-0 bottom-0 border-t border-line" aria-hidden />
        <div className="relative flex h-full items-end gap-[3px]">
          {v.map((x, i) => (
            <Tip key={dates[i]} className="h-full min-w-0 max-w-[14px] flex-1" text={`${date(dates[i])}: ${ok(x) ? `${num(x, 1)}% long` : 'no data'}`}>
              <div className="flex h-full w-full flex-col justify-end">
                <div className={cn('w-full rounded-t-sm', ok(x) && x >= 50 ? 'bg-profit' : 'bg-loss')} style={{ height: `${ok(x) ? Math.max(2, x) : 0}%` }} />
              </div>
            </Tip>
          ))}
        </div>
      </div>
    </div>
  )
}

function Positions() {
  const [client, setClient] = useState<FnoClient>('fii')
  const q = useFnoPositions(20)
  if (q.error) return <ErrorState error={q.error} onRetry={() => void q.refetch()} />
  if (!q.data) return <><SkeletonKpis n={5} /><SkeletonRows rows={8} cols={7} /></>
  const { dates, clients } = q.data
  if (!dates.length) return null
  const s = clients[client]
  const last = dates.length - 1
  const rows = dates.map((d, i) => ({ d, i })).reverse()
  return (
    <div className="space-y-3">
      <Segmented ariaLabel="Participant" value={client} onChange={setClient}
        items={(Object.keys(CLIENT_LABEL) as FnoClient[]).map((c) => ({ id: c, label: CLIENT_LABEL[c], title: CLIENT_HELP[c] }))} />
      <KpiStrip min={160}>
        <KpiTile label={`${CLIENT_LABEL[client]} index futures long`} value={ok(s.fut_long_pct[last]) ? `${num(s.fut_long_pct[last], 1)}%` : DASH}
          sub={ok(s.fut_long_pct[last]) && ok(s.fut_long_pct[last - 1]) ? `${pct((s.fut_long_pct[last] as number) - (s.fut_long_pct[last - 1] as number), { dp: 1 })} pts vs the day before` : undefined}
          title="Long contracts / (long + short) in index futures" />
        <KpiTile label="Index futures net" value={signed(s.fut_net[last])} sub={`change ${signed(s.fut_net_chg[last])}`} title="Long minus short contracts" />
        <KpiTile label="Index calls net" value={signed(s.call_net[last])} title="Calls bought minus calls written (contracts)" />
        <KpiTile label="Index puts net" value={signed(s.put_net[last])} title="Puts bought minus puts written (contracts)" />
        <KpiTile label="Stock futures net" value={signed(s.stk_fut_net[last])} />
      </KpiStrip>
      <div className="grid gap-3 lg:grid-cols-3">
        <Card title="Index futures: long share by day" subtitle={`${CLIENT_LABEL[client]} · green = more long than short`}>
          <LongPctBars dates={dates} v={s.fut_long_pct} />
          <div className="mt-1 flex justify-between pl-9 text-2xs text-faint"><span>{date(dates[0], { year: false })}</span><span>{date(dates[last], { year: false })}</span></div>
        </Card>
        <Card className="lg:col-span-2" title="All groups on the last day" subtitle={date(dates[last])}>
          <table className="w-full text-[13px]">
            <thead><tr className="border-b border-line text-2xs text-muted">
              <th className="py-1.5 text-left font-medium">Group</th>
              <th className="py-1.5 text-right font-medium">Index fut. long %</th>
              <th className="py-1.5 text-right font-medium">Index fut. net</th>
              <th className="py-1.5 text-right font-medium">Δ net</th>
              <th className="py-1.5 text-right font-medium">Calls net</th>
              <th className="py-1.5 text-right font-medium">Puts net</th>
            </tr></thead>
            <tbody>
              {(Object.keys(CLIENT_LABEL) as FnoClient[]).map((c) => {
                const x = clients[c]
                return (
                  <tr key={c} className={cn('border-b border-line/60 last:border-0', c === client && 'bg-accent/5')}>
                    <td className="py-1 font-semibold" title={CLIENT_HELP[c]}>{CLIENT_LABEL[c]}</td>
                    <td className="num py-1 text-right">{num(x.fut_long_pct[last], 1)}%</td>
                    <td className="num py-1 text-right">{signed(x.fut_net[last])}</td>
                    <td className={cn('num py-1 text-right', ok(x.fut_net_chg[last]) && (x.fut_net_chg[last] as number) < 0 ? 'text-loss' : 'text-profit')}>{signed(x.fut_net_chg[last])}</td>
                    <td className="num py-1 text-right">{signed(x.call_net[last])}</td>
                    <td className="num py-1 text-right">{signed(x.put_net[last])}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
          <p className="mt-2 text-2xs text-muted">Every contract has a buyer and a seller, so the four groups' nets add up to zero.</p>
        </Card>
      </div>
      <Card title={`${CLIENT_LABEL[client]} day by day`} subtitle="Contracts open at each close" flush>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[720px] text-[13px]">
            <thead><tr className="border-b border-line text-2xs text-muted">
              {['Date', 'Fut. long', 'Fut. short', 'Net', 'Δ net', 'Long %', 'Calls net', 'Puts net'].map((h, i) => <th key={h} className={cn('px-3 py-1.5 font-medium', i ? 'text-right' : 'text-left')}>{h}</th>)}
            </tr></thead>
            <tbody>
              {rows.map(({ d, i }) => (
                <tr key={d} className="border-b border-line/60 last:border-0">
                  <td className="num px-3 py-1">{date(d)}</td>
                  <td className="num px-3 py-1 text-right">{qty(s.fut_long[i])}</td>
                  <td className="num px-3 py-1 text-right">{qty(s.fut_short[i])}</td>
                  <td className="num px-3 py-1 text-right">{signed(s.fut_net[i])}</td>
                  <td className={cn('num px-3 py-1 text-right', ok(s.fut_net_chg[i]) && (s.fut_net_chg[i] as number) < 0 ? 'text-loss' : 'text-profit')}>{signed(s.fut_net_chg[i])}</td>
                  <td className="num px-3 py-1 text-right">{num(s.fut_long_pct[i], 1)}%</td>
                  <td className="num px-3 py-1 text-right">{signed(s.call_net[i])}</td>
                  <td className="num px-3 py-1 text-right">{signed(s.put_net[i])}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
      <p className="text-2xs text-muted">{q.data.note}</p>
    </div>
  )
}

// ------------------------------------------------------------------ live build-ups (during the session)
const LIVE_EVERY_MS = 180_000
const SOURCE_LABEL: Record<string, string> = {
  fyers: 'FYERS real-time prices', yahoo: 'Yahoo prices (~15 min delayed)', close: 'closing prices (market closed)',
}

function BuildBadge({ b }: { b: FnoBuildup | null }) {
  return b ? <Tip text={FUT_HELP[b]}><span className={cn('rounded border px-1.5 text-2xs font-semibold', BUILD_TONE[b])}>{BUILDUP_LABEL[b]}</span></Tip> : <span className="text-faint">{DASH}</span>
}

function LiveFutures() {
  const [p, setP] = useState<FnoLiveParams>({ kind: 'all', buildup: 'all', sort: 'oi_chg' })
  const session = useStatus().data?.clock.session
  const open = session === 'open'
  const q = useFnoLive(p, open)
  const refresh = useFnoLiveRefresh()
  const { setFyersLogin } = useUi()
  const fire = refresh.mutate
  useEffect(() => {                                   // fetch on arrival, then every 3 minutes while the market is open
    fire()
    if (!open) return
    const t = window.setInterval(() => fire(), LIVE_EVERY_MS)
    return () => window.clearInterval(t)
  }, [open, fire])
  if (q.error) return <ErrorState error={q.error} onRetry={() => void q.refetch()} />
  if (!q.data) return <SkeletonRows rows={12} cols={8} />
  const f = q.data
  const builds = Object.keys(BUILDUP_LABEL) as FnoBuildup[]
  const delayed = f.price_source === 'yahoo'
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2 rounded-md border border-line bg-panel px-3 py-2 text-xs">
        <span className={cn('inline-flex items-center gap-1.5 font-semibold', open ? 'text-profit' : 'text-muted')}>
          <span className={cn('h-2 w-2 rounded-full', open ? 'animate-pulse bg-profit' : 'bg-faint')} />{open ? 'LIVE' : 'Market closed'}
        </span>
        <span className="text-muted">NSE open interest at {f.nse_time ? `${date(f.nse_time.slice(0, 10), { year: false })} ${timeIST(f.nse_time)}` : DASH}</span>
        <span className="text-muted">· {f.price_source ? SOURCE_LABEL[f.price_source] ?? f.price_source : 'no prices yet'}</span>
        {open && <span className="text-faint">· refreshes every 3 minutes</span>}
        <span className="ml-auto flex items-center gap-2">
          {delayed && <Button size="xs" variant="subtle" onClick={() => setFyersLogin(true)}>Log in to FYERS for real time</Button>}
          <Button size="xs" icon={<RefreshCw className="h-3 w-3" />} loading={refresh.isPending || f.running} onClick={() => fire()}>Refresh now</Button>
        </span>
      </div>
      {f.error && <p className="rounded-md border border-warn/40 bg-warn/10 px-2 py-1 text-xs text-warn">{f.error} - showing the last good snapshot.</p>}
      <div className="flex flex-wrap items-center gap-2">
        <Segmented ariaLabel="Build-up" value={p.buildup ?? 'all'} onChange={(b) => setP({ ...p, buildup: b })}
          items={[{ id: 'all' as const, label: 'All' }, ...builds.map((b) => ({ id: b, label: `${BUILDUP_LABEL[b]} ${f.counts[b] ?? 0}`, title: FUT_HELP[b] }))]} />
        <Segmented ariaLabel="Kind" value={p.kind ?? 'all'} onChange={(k) => setP({ ...p, kind: k })}
          items={[{ id: 'all', label: 'All' }, { id: 'stock', label: 'Stocks' }, { id: 'index', label: 'Indices' }]} />
        <Segmented ariaLabel="Sort" value={p.sort ?? 'oi_chg'} onChange={(s) => setP({ ...p, sort: s })}
          items={[{ id: 'oi_chg', label: 'ΔOI %' }, { id: 'chg', label: 'Price %' }, { id: 'oi', label: 'OI' }, { id: 'volume', label: 'Volume' }]} />
      </div>
      <Card flush title={`Live today${f.trade_date ? ` · ${date(f.trade_date)}` : ''}`} subtitle={`${f.rows.length} underlyings · open interest of all futures + options vs ${f.prev_date ? date(f.prev_date, { year: false }) : 'yesterday'}`}>
        {f.rows.length === 0 ? <EmptyState compact title="No live snapshot yet">Press Refresh now: one NSE call plus the prices.</EmptyState> : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[900px] text-[13px]">
              <thead className="sticky top-0 bg-panel"><tr className="border-b border-line text-2xs text-muted">
                {['Symbol', 'Price', 'Chg %', 'OI (F&O contracts)', 'ΔOI %', 'Live build-up', `Futures (EOD${f.eod_date ? ` ${date(f.eod_date, { year: false })}` : ''})`, 'Volume'].map((h, i) => (
                  <th key={h} className={cn('px-3 py-1.5 font-medium', i === 0 || h.includes('build-up') || h.startsWith('Futures') ? 'text-left' : 'text-right')}>{h}</th>
                ))}
              </tr></thead>
              <tbody>
                {f.rows.map((r) => (
                  <tr key={r.symbol} className="border-b border-line/60 last:border-0 hover:bg-raised">
                    <td className="px-3 py-1 font-semibold"><Link className="hover:underline" to={r.kind === 'stock' ? `/chart/${encodeURIComponent(r.symbol)}` : `/options/${encodeURIComponent(r.symbol)}`}>{r.symbol}</Link></td>
                    <td className="num px-3 py-1 text-right" title={r.price_source === 'nse_rounded' ? "NSE's feed rounds the spot to whole rupees" : undefined}>{num(r.price, 2)}{r.price_source === 'nse_rounded' ? '*' : ''}</td>
                    <td className={cn('num px-3 py-1 text-right', ok(r.chg_pct) && r.chg_pct < 0 ? 'text-loss' : 'text-profit')}>{pct(r.chg_pct, { dp: 2 })}</td>
                    <td className="num px-3 py-1 text-right">{qty(r.oi)}</td>
                    <td className={cn('num px-3 py-1 text-right', ok(r.oi_chg_pct) && r.oi_chg_pct < 0 ? 'text-loss' : '')}>{pct(r.oi_chg_pct, { dp: 1 })}</td>
                    <td className="px-3 py-1"><BuildBadge b={r.buildup} /></td>
                    <td className="px-3 py-1"><BuildBadge b={r.eod_buildup} /></td>
                    <td className="num px-3 py-1 text-right text-muted">{qty(r.volume)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      <p className="text-2xs text-muted">{f.note} * index spot from NSE's feed, rounded to whole rupees.</p>
    </div>
  )
}

// ------------------------------------------------------------------ futures build-ups
function Futures() {
  const [mode, setMode] = useLocalStorage<'live' | 'eod'>('qd.fno.futures.mode', 'live')
  return (
    <div className="space-y-3">
      <Segmented ariaLabel="Data" value={mode} onChange={setMode}
        items={[{ id: 'live', label: 'Live today', title: "NSE's live open interest (futures + options) with live prices" },
          { id: 'eod', label: 'End of day (futures)', title: "NSE's futures-only F&O bhavcopy, published after the close" }]} />
      {mode === 'live' ? <LiveFutures /> : <EodFutures />}
    </div>
  )
}

function EodFutures() {
  const [p, setP] = useState<FnoFuturesParams>({ kind: 'all', buildup: 'all', sort: 'oi_chg' })
  const q = useFnoFutures(p)
  if (q.error) return <ErrorState error={q.error} onRetry={() => void q.refetch()} />
  if (!q.data) return <SkeletonRows rows={12} cols={10} />
  const f = q.data
  const builds = Object.keys(BUILDUP_LABEL) as FnoBuildup[]
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        {f.dates.length > 1 && (
          <select aria-label="Day" className="input h-8 w-[140px]" value={p.date ?? f.date ?? ''} onChange={(e) => setP({ ...p, date: e.target.value === f.dates[0] ? undefined : e.target.value })}>
            {f.dates.map((d) => <option key={d} value={d}>{date(d)}</option>)}
          </select>
        )}
        <Segmented ariaLabel="Build-up" value={p.buildup ?? 'all'} onChange={(b) => setP({ ...p, buildup: b })}
          items={[{ id: 'all' as const, label: 'All' }, ...builds.map((b) => ({ id: b, label: `${BUILDUP_LABEL[b]} ${f.counts[b] ?? 0}`, title: FUT_HELP[b] }))]} />
        <Segmented ariaLabel="Kind" value={p.kind ?? 'all'} onChange={(k) => setP({ ...p, kind: k })}
          items={[{ id: 'all', label: 'All' }, { id: 'stock', label: 'Stocks' }, { id: 'index', label: 'Indices' }]} />
        <Segmented ariaLabel="Sort" value={p.sort ?? 'oi_chg'} onChange={(s) => setP({ ...p, sort: s })}
          items={[{ id: 'oi_chg', label: 'ΔOI %' }, { id: 'chg', label: 'Price %' }, { id: 'value', label: 'Value' }, { id: 'pcr', label: 'PCR' }]} />
      </div>
      <Card flush title={`Futures on ${f.date ? date(f.date) : DASH}`} subtitle={`${f.rows.length} underlyings`}>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[980px] text-[13px]">
            <thead className="sticky top-0 bg-panel"><tr className="border-b border-line text-2xs text-muted">
              {['Symbol', 'Future', 'Chg %', 'OI (contracts)', 'ΔOI %', 'Build-up', 'Basis %', 'PCR', 'Call wall', 'Put wall', 'Value ₹ cr'].map((h, i) => (
                <th key={h} className={cn('px-3 py-1.5 font-medium', i === 0 || h === 'Build-up' ? 'text-left' : 'text-right')}>{h}</th>
              ))}
            </tr></thead>
            <tbody>
              {f.rows.map((r) => (
                <tr key={r.symbol} className="border-b border-line/60 last:border-0 hover:bg-raised">
                  <td className="px-3 py-1 font-semibold"><Link className="hover:underline" to={r.kind === 'stock' ? `/chart/${encodeURIComponent(r.symbol)}` : `/options/${encodeURIComponent(r.symbol)}`}>{r.symbol}</Link></td>
                  <td className="num px-3 py-1 text-right">{num(r.close, 2)}</td>
                  <td className={cn('num px-3 py-1 text-right', ok(r.chg_pct) && r.chg_pct < 0 ? 'text-loss' : 'text-profit')}>{pct(r.chg_pct, { dp: 2 })}</td>
                  <td className="num px-3 py-1 text-right">{qty(r.oi_contracts)}</td>
                  <td className="num px-3 py-1 text-right">{pct(r.oi_chg_pct, { dp: 1 })}</td>
                  <td className="px-3 py-1">{r.buildup ? <Tip text={FUT_HELP[r.buildup]}><span className={cn('rounded border px-1.5 text-2xs font-semibold', BUILD_TONE[r.buildup])}>{BUILDUP_LABEL[r.buildup]}</span></Tip> : <span className="text-faint">{DASH}</span>}</td>
                  <td className="num px-3 py-1 text-right">{num(r.basis_pct, 2)}</td>
                  <td className="num px-3 py-1 text-right">{num(r.pcr, 2)}</td>
                  <td className="num px-3 py-1 text-right text-loss">{num(r.call_wall, 0)}</td>
                  <td className="num px-3 py-1 text-right text-profit">{num(r.put_wall, 0)}</td>
                  <td className="num px-3 py-1 text-right text-muted">{num(r.value_cr, 0)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
      <p className="text-2xs text-muted">{f.note}</p>
    </div>
  )
}

export default function Fno() {
  const { tab: raw } = useParams()
  const tab: Tab = raw === 'futures' ? 'futures' : 'positions'
  const navigate = useNavigate()
  const st = useFnoStatus()
  useWatcher(st.data)
  const empty = st.data && st.data.days === 0
  const header = (
    <PageHeader
      title={<span className="flex items-center gap-2"><Scale className="h-5 w-5 text-muted" />F&O positioning</span>}
      subtitle={st.data?.last_day ? `NSE end-of-day files · ${st.data.days} days stored, to ${date(st.data.last_day)}${st.data.pending.length ? ' · today not published yet' : ''}` : 'NSE end-of-day derivatives files'}
      right={<FetchButton st={st.data} />}
    >
      <Tabs<Tab> value={tab} onChange={(t) => navigate(`/fno/${t}`)} items={[{ id: 'positions', label: 'FII / DII positions' }, { id: 'futures', label: 'Futures build-up' }]} />
    </PageHeader>
  )
  if (st.error) return <div>{header}<ErrorState error={st.error} onRetry={() => void st.refetch()} /></div>
  if (empty) {
    return (
      <div>
        {header}
        <EmptyState icon={<Scale className="h-6 w-6" />} title="No F&O data stored yet" action={<FetchButton st={st.data} />}>
          Fetch downloads NSE's participant-wise open interest and the F&O bhavcopy for the last 30 trading days (about
          30 MB, a minute or two). The 19:30 scheduled task (setup_schedule.ps1) then adds each new day.
        </EmptyState>
      </div>
    )
  }
  return <div>{header}{tab === 'futures' ? <Futures /> : <Positions />}</div>
}
