// Options `/options/:symbol` (scanner/options.py): NSE's option chain analysed - spot, PCR, max pain, implied
// volatility, the move the market prices, open interest by strike, OI levels, build-ups and the day so far.
// Positioning, never a signal: the page says so, and nothing on it is a buy or sell instruction.
// "Fetch now" posts /api/options/refresh and the page follows the background run; while the market is open the
// chain polls every minute (the 09:12 scheduled task stores a new one about that often).

import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { Layers, RefreshCw } from 'lucide-react'
import { isFailure } from '@/api/client'
import { useStatus } from '@/api/hooks'
import {
  BUILDUP_HELP, BUILDUP_LABEL, optKeys, useOptBigTrades, useOptChain, useOptHistory, useOptRefresh, useOptResearch, useOptStatus,
  type OptBigInstrument, type OptBuildup, type OptChainResponse, type OptHistoryResponse, type OptLeg, type OptLevel, type OptRow, type OptStatus,
} from '@/api/options'
import { AiForecastCard } from '@/components/AiForecast'
import { KpiStrip, KpiTile, PageHeader } from '@/components/domain'
import { Banner, EmptyState, ErrorState, SkeletonKpis, SkeletonRows } from '@/components/feedback'
import { useToast } from '@/components/toast'
import { Button, Card, Segmented, Spinner, Tip } from '@/components/ui'
import { cn } from '@/lib/csv'
import { DASH, date, dateTimeIST, num, ok, pct, qty, timeIST } from '@/lib/format'

type OiMode = 'oi' | 'chg' | 'win'
type Span = '10' | '20' | 'all'

const WINDOWS = [5, 15, 30, 60]
const lakh = (x: number | null | undefined, sign = false) => (ok(x) ? `${sign && x > 0 ? '+' : ''}${num(x / 1e5, 1)}` : DASH)
const signed = (x: number | null | undefined) => (ok(x) ? `${x > 0 ? '+' : ''}${qty(x)}` : DASH)

/** Toasts when a refresh this page watched finishes, and reloads every option query. */
function useRefreshWatcher(st: OptStatus | undefined) {
  const qc = useQueryClient()
  const toast = useToast()
  const was = useRef(false)
  useEffect(() => {
    if (!st) return
    const run = st.run
    if (was.current && !run.running) {
      if (run.state === 'failed') toast({ tone: 'bad', title: 'Option chains not fetched', detail: run.message ?? undefined })
      else toast({ tone: 'good', title: 'Option chains updated', detail: run.message ?? undefined })
      void qc.invalidateQueries({ queryKey: optKeys.all })
    }
    was.current = run.running
  }, [st, qc, toast])
}

function FetchButton({ symbols, st, label = 'Fetch now' }: { symbols?: string[]; st: OptStatus | undefined; label?: string }) {
  const refresh = useOptRefresh()
  const toast = useToast()
  const running = !!st?.run.running
  return (
    <Button
      size="sm"
      icon={<RefreshCw className="h-3.5 w-3.5" />}
      loading={refresh.isPending || running}
      onClick={() => refresh.mutate(symbols, {
        onError: (e) => toast({ tone: 'bad', title: isFailure(e) ? e.message : 'Could not start the refresh', detail: isFailure(e) ? e.hint ?? undefined : undefined }),
      })}
      title="Fetch the chain from NSE now (the scheduled job does this every minute in market hours)"
    >
      {running ? 'Fetching…' : label}
    </Button>
  )
}

function AddSymbol({ st }: { st: OptStatus | undefined }) {
  const [v, setV] = useState('')
  const refresh = useOptRefresh()
  const toast = useToast()
  const navigate = useNavigate()
  const submit = (e: FormEvent) => {
    e.preventDefault()
    const sym = v.trim().toUpperCase()
    if (!/^[A-Z0-9&-]{1,20}$/.test(sym)) return
    refresh.mutate([sym], {
      onSuccess: () => { setV(''); navigate(`/options/${encodeURIComponent(sym)}`) },
      onError: (e2) => toast({ tone: 'bad', title: isFailure(e2) ? e2.message : 'Could not start the refresh' }),
    })
  }
  return (
    <form onSubmit={submit} className="flex items-center gap-1.5">
      <input
        aria-label="Stock or index symbol"
        placeholder="Add a stock, e.g. RELIANCE"
        className={cn('input h-8 w-[190px]', v && 'uppercase')}
        value={v}
        onChange={(e) => setV(e.target.value.toUpperCase())}
        disabled={!!st?.run.running}
      />
      <Button size="sm" type="submit" disabled={!v.trim() || !!st?.run.running}>Fetch</Button>
    </form>
  )
}

function LiveState({ st, c }: { st: OptStatus; c: OptChainResponse | undefined }) {
  const lastDay = useStatus().data?.clock.last_completed_day
  const asOf = c ? <>NSE data as of <span className="num text-fg">{dateTimeIST(c.time)}</span></> : null
  if (st.live_running) return <span className="flex items-center gap-1.5"><span className="h-2 w-2 animate-pulse rounded-full bg-profit" />Live: stored every {st.interval_seconds} s{asOf && <> · {asOf}</>}</span>
  if (st.market_open) return <span>Market open, live job not running (scheduled at 09:12; or use Fetch now){asOf && <> · {asOf}</>}</span>
  // closed: say so when the stored chain is older than the last session (e.g. the daily job did not run)
  const day = c?.time.slice(0, 10)
  if (day && lastDay && day < lastDay) {
    return <span>Market closed · <span className="text-warn">this chain is from {date(day)}, not the last session ({date(lastDay)})</span> - Fetch now gets the newer one</span>
  }
  return <span>Market closed: the last session's chain{asOf && <> · {asOf}</>}</span>
}

// ------------------------------------------------------------------ KPIs
function Kpis({ c }: { c: OptChainResponse }) {
  const s = c.summary
  return (
    <KpiStrip min={150}>
      <KpiTile label={`${c.symbol} spot`} value={num(c.spot, 2)} sub={`forward ${num(c.forward, 1)} · ATM ${num(c.atm, 0)}`} title="Forward: the level options are priced off (put-call parity at the strikes nearest the spot)" />
      <KpiTile label="Put-call ratio (OI)" value={num(s.pcr_oi, 2)} sub={`by volume ${num(s.pcr_volume, 2)}`} title="Put open interest / call open interest, whole chain. Read both ways by traders; no tested edge." />
      <KpiTile label="Max pain" value={num(s.max_pain, 0)} sub={ok(s.max_pain_gap_pct) ? `${pct(s.max_pain_gap_pct, { dp: 2 })} vs spot` : undefined} title="The expiry level at which option buyers as a whole would collect least" />
      <KpiTile label="ATM implied volatility" value={ok(s.atm_iv_pct) ? `${num(s.atm_iv_pct, 1)}%` : DASH} sub={ok(s.skew_25d) ? `25Δ skew ${s.skew_25d > 0 ? '+' : ''}${num(s.skew_25d, 1)} pts` : undefined} title="Black-76 on the forward. Skew: the 25-delta put's IV minus the 25-delta call's" />
      <KpiTile label="Expected move" value={ok(s.expected_move_pct) ? `±${num(s.expected_move_pct, 2)}%` : DASH} sub={`straddle ${num(s.straddle, 1)} pts`} title="At-the-money call + put: roughly how far the market prices the underlying to move by expiry" />
      <KpiTile label="1-SD move by expiry" value={ok(s.one_sd_pts) ? `±${num(s.one_sd_pts, 0)}` : DASH} sub={ok(s.range_low) ? `${num(s.range_low, 0)} – ${num(s.range_high, 0)} · ${date(c.expiry, { year: false })}` : undefined} title="Forward × ATM IV × √time, in points: about two chances in three of finishing inside the range" />
      <KpiTile label="Call / put OI (lakh)" value={`${lakh(s.ce_oi)} / ${lakh(s.pe_oi)}`} sub={`since yesterday ${lakh(s.ce_oi_chg, true)} / ${lakh(s.pe_oi_chg, true)}`} title="Open contracts, whole chain, in lakh (1 lakh = 100,000)" />
    </KpiStrip>
  )
}

// ------------------------------------------------------------------ OI by strike (mirrored bars)
function oiValue(leg: OptLeg, mode: OiMode): number | null {
  return mode === 'oi' ? leg.oi : mode === 'chg' ? leg.oi_chg : leg.oi_chg_window
}

function around(rows: OptRow[], atm: number | null, n: number | null): OptRow[] {
  if (n == null || atm == null) return rows
  const i = rows.findIndex((r) => r.strike === atm)
  if (i < 0) return rows
  return rows.slice(Math.max(0, i - n), i + n + 1)
}

function OiBars({ c, mode }: { c: OptChainResponse; mode: OiMode }) {
  const rows = around(c.rows, c.atm, 12)
  const max = Math.max(1, ...rows.flatMap((r) => [Math.abs(oiValue(r.ce, mode) ?? 0), Math.abs(oiValue(r.pe, mode) ?? 0)]))
  const bar = (v: number | null, side: 'ce' | 'pe') => {
    const w = ok(v) ? (Math.abs(v) / max) * 100 : 0
    const neg = ok(v) && v < 0
    return (
      <div className={cn('flex h-4 items-center', side === 'ce' ? 'justify-end' : 'justify-start')} title={`${side === 'ce' ? 'Calls' : 'Puts'}: ${signed(v)}`}>
        <div className={cn('h-3 rounded-sm', side === 'ce' ? 'bg-loss' : 'bg-profit', neg && 'opacity-35')} style={{ width: `${w}%` }} />
      </div>
    )
  }
  return (
    <div>
      <div className="mb-1 grid grid-cols-[1fr_64px_1fr] text-2xs text-muted">
        <span className="text-right">Calls</span><span className="text-center">Strike</span><span>Puts</span>
      </div>
      <div className="space-y-0.5">
        {rows.map((r) => (
          <div key={r.strike} className={cn('grid grid-cols-[1fr_64px_1fr] items-center gap-1', r.atm && 'rounded bg-accent/10')}>
            {bar(oiValue(r.ce, mode), 'ce')}
            <span className={cn('num text-center text-2xs', r.atm ? 'font-semibold text-fg' : 'text-muted')}>{num(r.strike, 0)}</span>
            {bar(oiValue(r.pe, mode), 'pe')}
          </div>
        ))}
      </div>
      {mode !== 'oi' && <p className="mt-2 text-2xs text-faint">Faded bars: open interest fell.</p>}
    </div>
  )
}

// ------------------------------------------------------------------ OI levels
function LevelList({ title, items, tone, help }: { title: string; items: OptLevel[]; tone: 'profit' | 'loss'; help: string }) {
  return (
    <div>
      <div className="eyebrow mb-1" title={help}>{title}</div>
      {items.length ? (
        <table className="w-full text-[13px]">
          <tbody>
            {items.map((l) => (
              <tr key={l.strike} className="border-b border-line/60 last:border-0">
                <td className={cn('num py-1 font-semibold', tone === 'profit' ? 'text-profit' : 'text-loss')}>{num(l.strike, 0)}</td>
                <td className="num py-1 text-right">{qty(l.oi)}</td>
                <td className={cn('num py-1 text-right text-xs', ok(l.oi_chg) && l.oi_chg < 0 ? 'text-muted' : 'text-fg')}>{signed(l.oi_chg)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : <div className="text-xs text-muted">{DASH}</div>}
    </div>
  )
}

function Levels({ c }: { c: OptChainResponse }) {
  const lv = c.levels
  return (
    <div className="grid gap-4 sm:grid-cols-2">
      <LevelList title="Resistance by call OI" items={lv.resistance} tone="loss" help="Strikes at or above the spot with the most call open interest (contracts, change since yesterday)" />
      <LevelList title="Support by put OI" items={lv.support} tone="profit" help="Strikes at or below the spot with the most put open interest" />
      <LevelList title="Biggest call additions" items={lv.call_adds} tone="loss" help="Largest increases in call open interest since yesterday, any strike" />
      <LevelList title="Biggest put additions" items={lv.put_adds} tone="profit" help="Largest increases in put open interest since yesterday, any strike" />
    </div>
  )
}

// ------------------------------------------------------------------ chain table
const BUILD_SHORT: Record<OptBuildup, string> = { long_buildup: 'LB', short_buildup: 'SB', short_covering: 'SC', long_unwinding: 'LU' }
const BUILD_TONE: Record<OptBuildup, string> = {
  long_buildup: 'text-profit border-profit/40', short_buildup: 'text-loss border-loss/40',
  short_covering: 'text-info border-info/40', long_unwinding: 'text-warn border-warn/40',
}

function Build({ b }: { b: OptBuildup | null }) {
  if (!b) return <span className="text-faint">{DASH}</span>
  return (
    <Tip text={<><b>{BUILDUP_LABEL[b]}</b>: {BUILDUP_HELP[b]}</>}>
      <span className={cn('inline-block rounded border px-1 text-2xs font-semibold', BUILD_TONE[b])}>{BUILD_SHORT[b]}</span>
    </Tip>
  )
}

function Chg({ v }: { v: number | null }) {
  return <span className={cn(ok(v) && v > 0 ? 'text-fg' : 'text-muted')}>{signed(v)}</span>
}

function ChainTable({ c, mode, span }: { c: OptChainResponse; mode: OiMode; span: Span }) {
  const rows = around(c.rows, c.atm, span === 'all' ? null : Number(span))
  const chgOf = (l: OptLeg) => (mode === 'win' ? l.oi_chg_window : l.oi_chg)
  const chgLabel = mode === 'win' ? `ΔOI ${c.window_minutes}m` : 'ΔOI today'
  const th = 'px-2 py-1.5 text-2xs font-medium text-muted whitespace-nowrap'
  const td = 'num px-2 py-1 text-right whitespace-nowrap'
  // one side's cells, keyed by column; in-the-money cells get a light tint
  const leg = (l: OptLeg, itm: boolean) => {
    const c2 = (...x: (string | false)[]) => cn(td, itm && 'bg-warn/[0.06]', ...x)
    return {
      build: <td key="b" className={c2('text-center')}><Build b={l.buildup} /></td>,
      oi: <td key="o" className={c2()}>{qty(l.oi)}</td>,
      chg: <td key="c" className={c2('text-xs')}><Chg v={chgOf(l)} /></td>,
      vol: <td key="v" className={c2('text-muted')}>{qty(l.volume)}</td>,
      iv: <td key="i" className={c2()} title={ok(l.iv_nse_pct) ? `NSE's own IV (on the spot): ${num(l.iv_nse_pct, 2)}%` : undefined}>{num(l.iv_pct, 1)}</td>,
      delta: <td key="d" className={c2('text-muted')}>{num(l.delta, 2)}</td>,
      ltp: <td key="l" className={c2('font-semibold')} title={ok(l.bid) ? `bid ${num(l.bid)} / ask ${num(l.ask)}` : undefined}>{num(l.ltp, 2)}<div className={cn('text-2xs font-normal', ok(l.chg) && l.chg < 0 ? 'text-loss' : 'text-profit')}>{ok(l.chg) ? `${l.chg > 0 ? '+' : ''}${num(l.chg, 2)}` : ''}</div></td>,
    }
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[920px] border-collapse text-[13px]">
        <thead className="sticky top-0 z-10 bg-panel">
          <tr className="border-b border-line">
            <th colSpan={7} className={cn(th, 'text-center text-loss')}>CALLS</th>
            <th className={th} />
            <th colSpan={7} className={cn(th, 'text-center text-profit')}>PUTS</th>
          </tr>
          <tr className="border-b border-line">
            {['Build', 'OI', chgLabel, 'Volume', 'IV %', 'Delta', 'LTP'].map((h) => <th key={`c${h}`} className={cn(th, 'text-right')}>{h}</th>)}
            <th className={cn(th, 'text-center text-fg')}>Strike</th>
            {['LTP', 'Delta', 'IV %', 'Volume', chgLabel, 'OI', 'Build'].map((h) => <th key={`p${h}`} className={cn(th, 'text-right')}>{h}</th>)}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const ce = leg(r.ce, ok(c.spot) && r.strike < c.spot)
            const pe = leg(r.pe, ok(c.spot) && r.strike > c.spot)
            return (
              <tr key={r.strike} className={cn('border-b border-line/60', r.atm && 'outline outline-1 -outline-offset-1 outline-accent')}>
                {ce.build}{ce.oi}{ce.chg}{ce.vol}{ce.iv}{ce.delta}{ce.ltp}
                <td className={cn('num px-3 py-1 text-center font-semibold text-fg', r.atm ? 'bg-accent/15' : 'bg-raised')}>{num(r.strike, 0)}</td>
                {pe.ltp}{pe.delta}{pe.iv}{pe.vol}{pe.chg}{pe.oi}{pe.build}
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

// ------------------------------------------------------------------ the day so far
function DaySoFar({ h }: { h: OptHistoryResponse }) {
  const W = 600, H = 170, P = 6
  const series = [
    { id: 'spot', label: 'Spot', v: h.spot, cls: 'stroke-accent', dash: undefined, w: 2 },
    { id: 'mp', label: 'Max pain', v: h.max_pain, cls: 'stroke-violet', dash: '5 4', w: 1.5 },
    { id: 'res', label: 'Top call OI', v: h.resistance, cls: 'stroke-loss', dash: '2 3', w: 1.5 },
    { id: 'sup', label: 'Top put OI', v: h.support, cls: 'stroke-profit', dash: '2 3', w: 1.5 },
  ]
  const ts = h.t.map((t) => Date.parse(t))
  const all = series.flatMap((s) => s.v.filter(ok))
  if (h.t.length < 2 || !all.length) {
    return (
      <EmptyState compact title={h.t.length ? 'One chain stored so far' : 'No chains stored for this day'}>
        {h.t.length ? `NSE's ${timeIST(h.t[0])} chain. During the session the scheduled job adds one about every minute and these lines fill in.` : 'Fetch the chain to start the day.'}
      </EmptyState>
    )
  }
  const lo = Math.min(...all), hi = Math.max(...all)
  const pad = (hi - lo) * 0.08 || 1
  const y = (v: number) => P + (H - 2 * P) * (1 - (v - (lo - pad)) / (hi - lo + 2 * pad))
  const x = (t: number) => P + (W - 2 * P) * ((t - ts[0]) / Math.max(1, ts[ts.length - 1] - ts[0]))
  const path = (v: (number | null)[]) => v.map((p, i) => (ok(p) ? `${i && ok(v[i - 1]) ? 'L' : 'M'}${x(ts[i]).toFixed(1)},${y(p).toFixed(1)}` : '')).join('')
  const last = (v: (number | null)[]) => [...v].reverse().find(ok)
  const first = (v: (number | null)[]) => v.find(ok)
  return (
    <div>
      <div className="mb-2 flex flex-wrap gap-x-4 gap-y-1 text-2xs text-muted">
        {series.map((s) => (
          <span key={s.id} className="flex items-center gap-1.5">
            <svg width="18" height="6" aria-hidden><line x1="0" y1="3" x2="18" y2="3" className={s.cls} strokeWidth={2} strokeDasharray={s.dash} /></svg>
            {s.label} <span className="num text-fg">{num(last(s.v), 0)}</span>
          </span>
        ))}
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" className="h-[170px] w-full" role="img" aria-label="Spot, max pain and top OI strikes through the day">
        {series.map((s) => <path key={s.id} d={path(s.v)} fill="none" className={s.cls} strokeWidth={s.w} strokeDasharray={s.dash} vectorEffect="non-scaling-stroke" />)}
      </svg>
      <div className="mt-1 flex justify-between text-2xs text-faint"><span>{timeIST(h.t[0])}</span><span>{timeIST(h.t[h.t.length - 1])}</span></div>
      <div className="mt-2 grid grid-cols-3 gap-2 text-xs">
        <span className="text-muted">PCR <span className="num text-fg">{num(first(h.pcr_oi), 2)} → {num(last(h.pcr_oi), 2)}</span></span>
        <span className="text-muted">ATM IV <span className="num text-fg">{num(first(h.atm_iv_pct), 1)} → {num(last(h.atm_iv_pct), 1)}%</span></span>
        <span className="text-muted">Straddle <span className="num text-fg">{num(first(h.straddle), 0)} → {num(last(h.straddle), 0)}</span></span>
      </div>
    </div>
  )
}

// ------------------------------------------------------------------ unusual activity
function Unusual({ c }: { c: OptChainResponse }) {
  if (!c.unusual.length) {
    return <EmptyState compact title="Nothing unusual">No strike traded more than its open interest or changed its open interest by 10% within {c.window_minutes} minutes.</EmptyState>
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[640px] text-[13px]">
        <thead>
          <tr className="border-b border-line text-2xs text-muted">
            <th className="py-1.5 text-left font-medium">Strike</th>
            <th className="py-1.5 text-right font-medium">LTP</th>
            <th className="py-1.5 text-right font-medium">Volume</th>
            <th className="py-1.5 text-right font-medium">OI</th>
            <th className="py-1.5 text-right font-medium" title="Contracts traded today / contracts open">Vol / OI</th>
            <th className="py-1.5 text-right font-medium">ΔOI {c.window_minutes}m</th>
            <th className="py-1.5 text-right font-medium" title="Premium traded today: contracts × lot × price">₹ cr</th>
            <th className="py-1.5 pl-3 text-left font-medium">Why</th>
          </tr>
        </thead>
        <tbody>
          {c.unusual.map((u) => (
            <tr key={`${u.side}${u.strike}`} className="border-b border-line/60 last:border-0">
              <td className="num py-1 font-semibold">{num(u.strike, 0)} <span className={u.side === 'ce' ? 'text-loss' : 'text-profit'}>{u.side.toUpperCase()}</span></td>
              <td className="num py-1 text-right">{num(u.ltp, 2)}</td>
              <td className="num py-1 text-right">{qty(u.volume)}</td>
              <td className="num py-1 text-right">{qty(u.oi)}</td>
              <td className="num py-1 text-right">{num(u.vol_oi, 1)}×</td>
              <td className="num py-1 text-right">{signed(u.oi_chg_window)}{ok(u.oi_chg_window_pct) ? <span className="text-2xs text-muted"> ({pct(u.oi_chg_window_pct, { dp: 0 })})</span> : null}</td>
              <td className="num py-1 text-right">{num(u.value_cr, 1)}</td>
              <td className="py-1 pl-3 text-xs text-muted">{u.why.join('; ')}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-2 text-2xs text-muted">What traded, not who traded it or which side started it.{c.lot ? ` Lot size ${c.lot}.` : ' Premium in ₹ needs the lot size: fetch F&O data (F&O page) once.'}</p>
    </div>
  )
}

// ------------------------------------------------------------------ big trades live (FYERS feed)
const KIND: Record<OptBigInstrument['kind'], string> = { fut: 'FUT', ce: 'CE', pe: 'PE' }
const instName = (x: { underlying: string; kind: OptBigInstrument['kind']; strike: number | null }) =>
  `${x.underlying} ${x.kind === 'fut' ? 'FUT' : `${num(x.strike, 0)} ${KIND[x.kind]}`}`

function BigTrades({ marketOpen }: { marketOpen: boolean }) {
  const q = useOptBigTrades(marketOpen)
  if (q.error) return <ErrorState compact error={q.error} onRetry={() => void q.refetch()} />
  if (!q.data) return <SkeletonRows rows={4} cols={6} />
  const b = q.data
  const th = `futures ≥ ₹${num(b.thresholds.future_print_cr, 0)} cr, options ≥ ₹${num(b.thresholds.option_print_lakh, 0)} lakh premium`
  if (!b.instruments.length) {
    return (
      <EmptyState compact title="No live F&O feed yet">
        The 09:14 live service streams the index futures and near-the-money options of config.yaml (live_fno) once you are
        logged in to FYERS today (Settings › Fyers), and keeps every trade of {th}.
      </EmptyState>
    )
  }
  const active = b.instruments.filter((i) => i.prints > 0).sort((x, y) => Math.abs(y.net_cr) - Math.abs(x.net_cr))
  return (
    <div className="space-y-3">
      <p className="text-xs text-muted">
        {b.live ? <span className="text-profit">Live</span> : <span>Not live{b.updated_at ? ` - last update ${dateTimeIST(b.updated_at)}` : ''}</span>}
        {' · '}{b.instruments.length} instruments streamed · large = {th}
      </p>
      <div className="grid gap-4 lg:grid-cols-2">
        <div className="overflow-x-auto">
          <div className="eyebrow mb-1">By instrument, today</div>
          {active.length ? (
            <table className="w-full min-w-[420px] text-[13px]">
              <thead><tr className="border-b border-line text-2xs text-muted">
                <th className="py-1.5 text-left font-medium">Instrument</th>
                <th className="py-1.5 text-right font-medium">Trades</th>
                <th className="py-1.5 text-right font-medium" title="Traded at the ask: likely started by a buyer">At ask ₹ cr</th>
                <th className="py-1.5 text-right font-medium" title="Traded at the bid: likely started by a seller">At bid ₹ cr</th>
                <th className="py-1.5 text-right font-medium">Net</th>
              </tr></thead>
              <tbody>
                {active.map((i) => (
                  <tr key={i.ticker} className="border-b border-line/60 last:border-0">
                    <td className="py-1 font-semibold">{instName(i)}</td>
                    <td className="num py-1 text-right">{i.prints}</td>
                    <td className="num py-1 text-right text-profit">{num(i.buy_cr, 2)}</td>
                    <td className="num py-1 text-right text-loss">{num(i.sell_cr, 2)}</td>
                    <td className={cn('num py-1 text-right font-semibold', i.net_cr > 0 ? 'text-profit' : i.net_cr < 0 ? 'text-loss' : 'text-muted')}>{i.net_cr > 0 ? '+' : ''}{num(i.net_cr, 2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : <p className="text-xs text-muted">No trade above the thresholds yet today.</p>}
        </div>
        <div className="overflow-x-auto">
          <div className="eyebrow mb-1">Latest large trades</div>
          {b.recent.length ? (
            <table className="w-full min-w-[420px] text-[13px]">
              <thead><tr className="border-b border-line text-2xs text-muted">
                <th className="py-1.5 text-left font-medium">Time</th>
                <th className="py-1.5 text-left font-medium">Instrument</th>
                <th className="py-1.5 text-right font-medium">Lots</th>
                <th className="py-1.5 text-right font-medium">Price</th>
                <th className="py-1.5 text-right font-medium">₹ cr</th>
                <th className="py-1.5 pl-3 text-left font-medium">Likely side</th>
              </tr></thead>
              <tbody>
                {b.recent.map((t, k) => (
                  <tr key={`${t.ts}-${t.ticker}-${k}`} className="border-b border-line/60 last:border-0">
                    <td className="num py-1 text-muted">{timeIST(t.ts)}</td>
                    <td className="py-1">{instName(t)}</td>
                    <td className="num py-1 text-right">{num(t.lots, 0)}</td>
                    <td className="num py-1 text-right">{num(t.price, 2)}</td>
                    <td className="num py-1 text-right">{num(t.value_cr, 2)}</td>
                    <td className={cn('py-1 pl-3 text-xs font-semibold', t.side === 'BUY' ? 'text-profit' : t.side === 'SELL' ? 'text-loss' : 'text-muted')}>{t.side === 'BUY' ? 'buyer' : t.side === 'SELL' ? 'seller' : 'unknown'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : <p className="text-xs text-muted">None yet.</p>}
        </div>
      </div>
      <p className="text-2xs text-muted">{b.note}</p>
    </div>
  )
}

// ------------------------------------------------------------------ does it work?
function Research({ symbol }: { symbol: string }) {
  const q = useOptResearch()
  const s = q.data?.studies.find((x) => x.symbol === symbol)
  if (q.error) return <ErrorState compact error={q.error} onRetry={() => void q.refetch()} />
  if (!q.data) return <SkeletonRows rows={3} cols={3} />
  if (!s) return <EmptyState compact title="No stored days yet">Each session's closing chain is kept; the checks start once days accumulate.</EmptyState>
  const claim = (label: string, measured: string, fair: string, n: number, verdict: string) => (
    <div className="rounded-md border border-line p-3">
      <div className="text-xs font-semibold text-fg">{label}</div>
      <div className="mt-1 flex items-baseline gap-2"><span className="num text-lg font-semibold">{measured}</span><span className="text-2xs text-muted">vs {fair} by chance · {n} day{n === 1 ? '' : 's'}</span></div>
      <p className="mt-1 text-xs text-muted">{verdict}</p>
    </div>
  )
  return (
    <div>
      <div className="grid gap-3 md:grid-cols-3">
        {claim('Price pulled to max pain by expiry', ok(s.max_pain.hit_pct) ? `${num(s.max_pain.hit_pct, 0)}%` : DASH, `${num(s.max_pain.fair_pct, 0)}%`, s.max_pain.n, s.max_pain.verdict)}
        {claim('Expiry close inside spot ± straddle', ok(s.expected_move.inside_pct) ? `${num(s.expected_move.inside_pct, 0)}%` : DASH, `${num(s.expected_move.fair_pct, 1)}%`, s.expected_move.n, s.expected_move.verdict)}
        {claim('PCR vs the next day', ok(s.pcr.corr) ? `ρ ${num(s.pcr.corr, 2)}` : DASH, 'ρ 0', s.pcr.n, s.pcr.verdict)}
      </div>
      <p className="mt-2 text-2xs text-muted">{s.days} stored day{s.days === 1 ? '' : 's'}{s.first_day ? ` since ${date(s.first_day)}` : ''}. Verdicts need {q.data.min_days} days. {q.data.note}</p>
    </div>
  )
}

// ------------------------------------------------------------------ page
export default function Options() {
  const { symbol: param } = useParams()
  const navigate = useNavigate()
  const [sp, setSp] = useSearchParams()
  const status = useOptStatus()
  const st = status.data
  useRefreshWatcher(st)
  const symbols = useMemo(() => [...new Set(st?.chains.map((c) => c.symbol) ?? [])], [st])
  const symbol = (param ?? symbols[0] ?? '').toUpperCase()
  const expiry = sp.get('expiry') ?? undefined
  const [mode, setMode] = useState<OiMode>('oi')
  const [win, setWin] = useState(15)
  const [span, setSpan] = useState<Span>('10')
  const live = !!st?.market_open
  const chain = useOptChain(symbol, expiry, win, live)
  const hist = useOptHistory(symbol, expiry, live)
  const c = chain.data
  const notFound = isFailure(chain.error) && chain.error.code === 'NOT_FOUND'

  const header = (
    <PageHeader
      title={<span className="flex items-center gap-2"><Layers className="h-5 w-5 text-muted" />Option chain</span>}
      subtitle={st ? <LiveState st={st} c={c} /> : 'NSE option chain: open interest, PCR, max pain, implied volatility'}
      right={<>
        {symbols.length > 0 && (
          <Segmented ariaLabel="Underlying" items={symbols.map((s) => ({ id: s, label: s }))} value={symbols.includes(symbol) ? symbol : ''}
            onChange={(s) => navigate(`/options/${encodeURIComponent(s)}`)} />
        )}
        <AddSymbol st={st} />
        <FetchButton symbols={symbol ? [symbol] : undefined} st={st} />
      </>}
    />
  )

  if (status.isLoading) return <div>{header}<SkeletonKpis n={6} /></div>
  if (status.error) return <div>{header}<ErrorState error={status.error} onRetry={() => void status.refetch()} /></div>
  if (st && !st.chains.length && !param) {
    return (
      <div>
        {header}
        <EmptyState icon={<Layers className="h-6 w-6" />} title="No option chains stored yet"
          action={<FetchButton st={st} label={`Fetch ${st.underlyings.join(', ')}`} />}>
          The 09:12 scheduled task (setup_schedule.ps1) stores {st.underlyings.join(' and ')} every {st.interval_seconds} s in
          market hours. Fetch now to get the last session's chains; add stocks with the box above or in config.yaml (options.underlyings).
        </EmptyState>
      </div>
    )
  }

  const lr = st?.last_refresh
  return (
    <div className="space-y-3">
      {header}
      {c?.stale && <Banner tone="warn">The newest stored chain is from {dateTimeIST(c.time)} although the market is open: the live job may have stopped. Fetch now, or check data\logs\intraday.log.</Banner>}
      {lr?.refused && <Banner tone="warn">NSE refused the last request ({lr.errors[0] ?? 'blocked'}). The app waits 5 minutes before asking again.</Banner>}
      {st?.run.state === 'failed' && !st.run.running && <Banner tone="danger">Last fetch failed: {st.run.message}</Banner>}

      {notFound ? (
        <EmptyState icon={<Layers className="h-6 w-6" />} title={`No stored chain for ${symbol}`}
          action={st?.run.running ? <span className="flex items-center gap-2 text-xs text-muted"><Spinner className="h-3.5 w-3.5" />{st.run.message ?? 'Fetching…'}</span> : <FetchButton symbols={[symbol]} st={st} label={`Fetch ${symbol}`} />}>
          Only index and stock symbols with options at NSE (F&O) have a chain.
        </EmptyState>
      ) : chain.error && !c ? (
        <ErrorState error={chain.error} onRetry={() => void chain.refetch()} />
      ) : !c ? (
        <><SkeletonKpis n={7} /><SkeletonRows rows={10} cols={8} /></>
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs text-muted">Expiry</span>
            <Segmented ariaLabel="Expiry" items={c.expiries.map((e) => ({ id: e, label: date(e, { year: false }) }))} value={c.expiry}
              onChange={(e) => setSp(e === c.expiries[0] ? {} : { expiry: e })} />
            <span className="text-2xs text-faint">{num(c.days_to_expiry, 1)} days to expiry</span>
          </div>

          <Kpis c={c} />

          <Card title="What the chain shows" subtitle="Facts from this chain, not a recommendation">
            <ul className="list-disc space-y-1 pl-5 text-[13px] text-fg">
              {c.readings.map((r) => <li key={r}>{r}</li>)}
            </ul>
            <p className="mt-3 text-2xs text-muted">{c.note}</p>
          </Card>

          <AiForecastCard symbol={c.symbol} />

          <div className="grid gap-3 lg:grid-cols-5">
            <Card className="lg:col-span-3" title="Open interest by strike" subtitle={mode === 'oi' ? 'Contracts open, 12 strikes each side of the money' : mode === 'chg' ? 'Change since yesterday' : c.window_since ? `Change since ${timeIST(c.window_since)} (${c.window_minutes} min)` : `Change over ${c.window_minutes} min: no chain that old today yet`}
              right={<>
                <Segmented size="xs" ariaLabel="Open interest view" value={mode} onChange={setMode}
                  items={[{ id: 'oi', label: 'OI' }, { id: 'chg', label: 'Δ today' }, { id: 'win', label: 'Δ recent' }]} />
                {mode === 'win' && <Segmented size="xs" ariaLabel="Window" value={String(win)} onChange={(v) => setWin(Number(v))}
                  items={WINDOWS.map((w) => ({ id: String(w), label: `${w}m` }))} />}
              </>}>
              <OiBars c={c} mode={mode} />
            </Card>
            <div className="space-y-3 lg:col-span-2">
              <Card title="Open-interest levels" subtitle="Contracts · change since yesterday"><Levels c={c} /></Card>
              <Card title={`The day so far · ${hist.data ? date(hist.data.day, { year: false }) : ''}`} subtitle="Every stored chain of this expiry">
                {hist.data ? <DaySoFar h={hist.data} /> : hist.error ? <ErrorState compact error={hist.error} onRetry={() => void hist.refetch()} /> : <SkeletonRows rows={4} cols={3} />}
              </Card>
            </div>
          </div>

          <Card title="Unusual activity" subtitle={`Strikes that traded more than their open interest, or whose OI moved 10%+ in ${c.window_minutes} minutes - ranked by premium traded`}
            right={<Segmented size="xs" ariaLabel="Window" value={String(win)} onChange={(v) => setWin(Number(v))}
              items={WINDOWS.map((w) => ({ id: String(w), label: `${w}m` }))} />}>
            <Unusual c={c} />
          </Card>

          <Card title="Big trades live · index futures and options" subtitle="Single large trades from the FYERS feed, with the side that most likely started them">
            <BigTrades marketOpen={live} />
          </Card>

          <Card title="Option chain" subtitle="Tinted cells are in the money; the outlined row is at the money. Hover IV for NSE's own figure, LTP for bid/ask, build-up tags for what they mean."
            flush right={<>
              <Segmented size="xs" ariaLabel="Change column" value={mode === 'win' ? 'win' : 'chg'} onChange={(v) => setMode(v as OiMode)}
                items={[{ id: 'chg', label: 'Δ today' }, { id: 'win', label: `Δ ${win}m` }]} />
              <Segmented size="xs" ariaLabel="Strikes shown" value={span} onChange={setSpan}
                items={[{ id: '10', label: '±10' }, { id: '20', label: '±20' }, { id: 'all', label: 'All' }]} />
            </>}>
            <ChainTable c={c} mode={mode} span={span} />
          </Card>

          <Card title="Does it work?" subtitle="Popular option-chain claims, checked against what this app has recorded">
            <Research symbol={c.symbol} />
          </Card>
        </>
      )}
    </div>
  )
}
