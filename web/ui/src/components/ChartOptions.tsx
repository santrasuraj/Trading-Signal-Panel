// Options & F&O card (Chart page): the stored NSE option chain of the chart's underlying - spot / forward, PCR, max
// pain, ATM IV and the expected move, an open-interest profile by strike (calls right, puts left, today's change),
// the OI levels and unusual activity - plus the futures build-up from the F&O bhavcopy. Positioning, not a signal.

import { useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { ExternalLink, RefreshCw } from 'lucide-react'
import { useQueryClient } from '@tanstack/react-query'
import { isFailure } from '@/api/client'
import type { OlDerivatives } from '@/api/outlook'
import { BUILDUP_LABEL, optKeys, useOptChain, useOptRefresh, useOptStatus, type OptChainResponse, type OptRow } from '@/api/options'
import { EmptyState, ErrorState, SkeletonRows } from '@/components/feedback'
import { OptionVerdictPanel } from '@/components/OptionVerdict'
import { useToast } from '@/components/toast'
import { Button, Card, Segmented, Tip } from '@/components/ui'
import { cn } from '@/lib/csv'
import { DASH, date, num, ok, pct, qty, timeIST } from '@/lib/format'

const STRIKES_EACH_SIDE = 10
const lakhs = (x: number | null | undefined) => (ok(x) ? `${num(x / 1e5, 1)} L` : DASH)

function Kpi({ label, v, sub, title }: { label: string; v: React.ReactNode; sub?: React.ReactNode; title?: string }) {
  return (
    <div className="rounded-md border border-line p-2" title={title}>
      <div className="text-2xs text-muted">{label}</div>
      <div className="num text-[15px] font-semibold">{v}</div>
      {sub != null && <div className="text-2xs text-faint">{sub}</div>}
    </div>
  )
}

/** Open interest by strike around the money: puts to the left (support), calls to the right (resistance). */
function OiProfile({ c }: { c: OptChainResponse }) {
  const rows = useMemo(() => {
    const i = Math.max(0, c.rows.findIndex((r) => r.atm))
    return c.rows.slice(Math.max(0, i - STRIKES_EACH_SIDE), i + STRIKES_EACH_SIDE + 1).slice().reverse()
  }, [c.rows])
  const max = Math.max(1, ...rows.flatMap((r) => [r.ce.oi ?? 0, r.pe.oi ?? 0]))
  const w = (v: number | null) => `${(Math.max(0, v ?? 0) / max) * 100}%`
  const spot = c.spot ?? 0
  const mp = c.summary.max_pain
  const rowSpot = (r: OptRow, k: number) => k > 0 && rows[k - 1].strike > spot && r.strike <= spot
  return (
    <div>
      <div className="mb-1 grid grid-cols-[minmax(0,1fr)_64px_minmax(0,1fr)] gap-1 text-2xs text-muted">
        <span className="text-right">Put OI (support) ◀</span><span className="text-center">Strike</span><span>▶ Call OI (resistance)</span>
      </div>
      <ul className="space-y-px">
        {rows.map((r, k) => (
          <li key={r.strike}>
            {rowSpot(r, k) && <div className="my-0.5 flex items-center gap-1 text-2xs text-accent"><span className="h-px flex-1 bg-accent" /> spot {num(spot, 2)} <span className="h-px flex-1 bg-accent" /></div>}
            <div className={cn('grid grid-cols-[minmax(0,1fr)_64px_minmax(0,1fr)] items-center gap-1', r.atm && 'bg-raised/70')}>
              <Tip text={<>Put OI {qty(r.pe.oi)} ({r.pe.oi_chg != null && r.pe.oi_chg >= 0 ? '+' : ''}{qty(r.pe.oi_chg)} today) · IV {num(r.pe.iv_pct, 1)}% · {r.pe.buildup ? BUILDUP_LABEL[r.pe.buildup] : 'no build-up'}</>}>
                <div className="relative flex h-3.5 justify-end">
                  <div className="h-full rounded-l-sm bg-profit/60" style={{ width: w(r.pe.oi) }} />
                  {ok(r.pe.oi_chg) && r.pe.oi_chg > 0 && <div className="absolute right-0 top-0 h-1 rounded-l-sm bg-profit" style={{ width: w(r.pe.oi_chg) }} />}
                </div>
              </Tip>
              <span className={cn('num text-center text-2xs', r.atm ? 'font-semibold text-fg' : 'text-muted', mp != null && r.strike === mp && 'text-warn')}>
                {num(r.strike, 0)}{mp != null && r.strike === mp ? ' ◆' : ''}
              </span>
              <Tip text={<>Call OI {qty(r.ce.oi)} ({r.ce.oi_chg != null && r.ce.oi_chg >= 0 ? '+' : ''}{qty(r.ce.oi_chg)} today) · IV {num(r.ce.iv_pct, 1)}% · {r.ce.buildup ? BUILDUP_LABEL[r.ce.buildup] : 'no build-up'}</>}>
                <div className="relative h-3.5">
                  <div className="h-full rounded-r-sm bg-loss/60" style={{ width: w(r.ce.oi) }} />
                  {ok(r.ce.oi_chg) && r.ce.oi_chg > 0 && <div className="absolute left-0 top-0 h-1 rounded-r-sm bg-loss" style={{ width: w(r.ce.oi_chg) }} />}
                </div>
              </Tip>
            </div>
          </li>
        ))}
      </ul>
      <p className="mt-1 text-2xs text-muted">Bars: open interest in contracts; the thin bar on top: added today. ◆ max pain. Hover a bar for IV and build-up.</p>
    </div>
  )
}

function FetchChain({ osym, label }: { osym: string; label: string }) {
  const st = useOptStatus()
  const refresh = useOptRefresh()
  const toast = useToast()
  const qc = useQueryClient()
  const running = !!st.data?.run.running
  const was = useRef(false)
  useEffect(() => {
    const run = st.data?.run
    if (!run) return
    if (was.current && !run.running) {
      if (run.state === 'failed') toast({ tone: 'bad', title: `${osym} option chain not fetched`, detail: run.message ?? undefined })
      void qc.invalidateQueries({ queryKey: optKeys.all })
      void qc.invalidateQueries({ queryKey: ['outlook'] })
    }
    was.current = run.running
  }, [st.data, qc, toast, osym])
  return (
    <Button size="sm" icon={<RefreshCw className="h-3.5 w-3.5" />} loading={refresh.isPending || running}
      title="Fetch this underlying's chain from NSE now (about 10 seconds)"
      onClick={() => refresh.mutate([osym], { onError: (e) => toast({ tone: 'bad', title: isFailure(e) ? e.message : 'Could not start the refresh', detail: isFailure(e) ? e.hint ?? undefined : undefined }) })}>
      {running ? 'Fetching…' : label}
    </Button>
  )
}

export function ChartOptions({ d, live, lastDay }: { d: OlDerivatives; live: boolean; lastDay: string }) {
  const osym = d.options_symbol ?? ''
  const [expiry, setExpiry] = useState<string | undefined>(undefined)
  useEffect(() => setExpiry(undefined), [osym])
  const q = useOptChain(osym, expiry, 15, live)
  if (!d.fno || !osym) {
    return (
      <Card title="Options & F&O">
        <p className="text-xs text-muted">No options or futures: this symbol is not in NSE's F&O segment (about 220 stocks and the main indices are). Its levels come from price alone.</p>
      </Card>
    )
  }
  const c = q.data
  const missing = q.error && isFailure(q.error) && q.error.code === 'NOT_FOUND'
  const old = c ? c.time.slice(0, 10) < lastDay : false
  const f = d.futures
  return (
    <Card
      id="chart-options"
      title={`Options & F&O · ${osym}`}
      subtitle={c ? `NSE option chain, expiry ${date(c.expiry)} · stored ${date(c.time.slice(0, 10), { year: false })} ${timeIST(c.time)}` : "NSE's option chain for this underlying"}
      right={<>
        {c && c.expiries.length > 1 && <Segmented ariaLabel="Expiry" value={c.expiry} onChange={setExpiry} items={c.expiries.map((e) => ({ id: e, label: date(e, { year: false }) }))} />}
        <FetchChain osym={osym} label={c ? 'Refresh' : 'Fetch chain'} />
        <Link to={`/options/${encodeURIComponent(osym)}`} className="link inline-flex items-center gap-1 text-xs">Full chain <ExternalLink className="h-3 w-3" /></Link>
      </>}
    >
      {q.isLoading ? <SkeletonRows rows={6} cols={4} /> : missing ? (
        <EmptyState compact title="No option chain stored for this underlying">Fetch it from NSE (about 10 seconds). The 09:12 scheduled task keeps the chains in <code>options.underlyings</code> current during market hours.</EmptyState>
      ) : q.error ? <ErrorState compact error={q.error} onRetry={() => void q.refetch()} /> : c ? (
        <div className="space-y-4">
          {d.verdict && <OptionVerdictPanel v={d.verdict} />}
          {(old || c.stale) && (
            <p className="rounded-md border border-warn/40 bg-warn/10 px-2 py-1 text-xs text-warn">
              {old ? `This chain was stored on ${date(c.time.slice(0, 10))}, before the chart's last bar: its walls and IV describe that day, so they are left off the chart and the outlook. Refresh it.` : 'The market is open and this chain is more than 10 minutes old.'}
            </p>
          )}
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 xl:grid-cols-8">
            <Kpi label="Spot" v={num(c.spot, 2)} sub={`forward ${num(c.forward, 1)}`} title="Forward: the level options are priced off (put-call parity)" />
            <Kpi label="PCR (OI)" v={num(c.summary.pcr_oi, 2)} sub={`volume ${num(c.summary.pcr_volume, 2)}`} title="Put open interest / call open interest" />
            <Kpi label="Max pain" v={num(c.summary.max_pain, 0)} sub={`${pct(c.summary.max_pain_gap_pct, { dp: 1 })} from spot`} title="The expiry price at which option buyers together would lose most - folklore, tested on the Options page" />
            <Kpi label="ATM IV" v={`${num(c.summary.atm_iv_pct, 1)}%`} sub={`skew 25Δ ${num(c.summary.skew_25d, 1)}`} title="Implied volatility at the money (Black-76 on the forward)" />
            <Kpi label="Expected move" v={`±${num(c.summary.expected_move_pct, 1)}%`} sub={`to expiry · ${num(c.days_to_expiry, 1)} d`} title="The at-the-money straddle's price as % of spot" />
            <Kpi label="1-SD range" v={<span className="text-[13px]">{num(c.summary.range_low, 0)} – {num(c.summary.range_high, 0)}</span>} sub="≈68% by expiry" />
            <Kpi label="Call OI" v={lakhs(c.summary.ce_oi)} sub={`${c.summary.ce_oi_chg != null && c.summary.ce_oi_chg >= 0 ? '+' : ''}${lakhs(c.summary.ce_oi_chg)} today`} />
            <Kpi label="Put OI" v={lakhs(c.summary.pe_oi)} sub={`${c.summary.pe_oi_chg != null && c.summary.pe_oi_chg >= 0 ? '+' : ''}${lakhs(c.summary.pe_oi_chg)} today`} />
          </div>
          <div className="grid gap-5 lg:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]">
            <OiProfile c={c} />
            <div className="space-y-4">
              <div className="grid grid-cols-2 gap-3 text-xs">
                <div>
                  <div className="eyebrow mb-1">Resistance (call OI)</div>
                  {c.levels.resistance.map((l) => <div key={l.strike} className="flex justify-between border-b border-line/50 py-0.5"><span className="num font-semibold text-loss">{num(l.strike, 0)}</span><span className="num text-muted">{qty(l.oi)}</span></div>)}
                </div>
                <div>
                  <div className="eyebrow mb-1">Support (put OI)</div>
                  {c.levels.support.map((l) => <div key={l.strike} className="flex justify-between border-b border-line/50 py-0.5"><span className="num font-semibold text-profit">{num(l.strike, 0)}</span><span className="num text-muted">{qty(l.oi)}</span></div>)}
                </div>
              </div>
              {c.unusual.length > 0 && (
                <div>
                  <div className="eyebrow mb-1">Unusual activity</div>
                  <table className="w-full text-xs"><tbody>{c.unusual.slice(0, 5).map((u) => (
                    <tr key={`${u.side}${u.strike}`} className="border-b border-line/50 last:border-0">
                      <td className={cn('py-0.5 font-semibold', u.side === 'ce' ? 'text-loss' : 'text-profit')}>{num(u.strike, 0)} {u.side.toUpperCase()}</td>
                      <td className="num py-0.5 text-right text-muted">vol/OI {num(u.vol_oi, 1)}</td>
                      <td className="num py-0.5 text-right">{ok(u.value_cr) ? `₹${num(u.value_cr, 1)} cr` : `${qty(u.volume)} traded`}</td>
                    </tr>
                  ))}</tbody></table>
                </div>
              )}
              {c.readings.length > 0 && (
                <div>
                  <div className="eyebrow mb-1">Reading the chain</div>
                  <ul className="list-disc space-y-0.5 pl-4 text-xs text-muted">{c.readings.map((r) => <li key={r}>{r}</li>)}</ul>
                </div>
              )}
              {f && (
                <div>
                  <div className="eyebrow mb-1">Futures ({date(f.date, { year: false })})</div>
                  <div className="grid grid-cols-3 gap-2 text-xs">
                    <div><div className="text-2xs text-muted">Build-up</div><div className="font-medium">{f.buildup ? f.buildup.replace('_', ' ') : 'none'}</div></div>
                    <div><div className="text-2xs text-muted">Open interest</div><div className="num">{pct(f.oi_chg_pct, { dp: 1 })}</div></div>
                    <div><div className="text-2xs text-muted">Basis</div><div className="num">{pct(f.basis_pct, { dp: 2 })}</div></div>
                  </div>
                </div>
              )}
            </div>
          </div>
          <p className="text-2xs text-muted">Positioning, not a signal: no test in this app shows that PCR, max pain or OI walls predict the price (see the Options page's “Does it work?”). Walls, max pain and the 1-SD range are drawn on the chart when the chain is current.</p>
        </div>
      ) : null}
    </Card>
  )
}
