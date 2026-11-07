// Claude's option-chain forecast (Options page): the latest answer for this underlying, a button to ask now, and the
// record so far against a coin flip and the options market's own range (web/api/services/forecast_svc.py). Unproven
// until enough forecasts beat a coin flip beyond luck: the card says so in its title, and nothing here is an order.

import type { ReactNode } from 'react'
import { Sparkles } from 'lucide-react'
import { useForecastNow, useForecasts, type FcHorizon, type FcHorizonTrack, type FcTrack, type Forecast } from '@/api/forecast'
import { ErrorState, SkeletonRows } from '@/components/feedback'
import { Button, Card, Tip } from '@/components/ui'
import { cn } from '@/lib/csv'
import { DASH, date, dateTimeIST, num, ok, pct, price } from '@/lib/format'

const VIEW: Record<string, { label: string; cls: string }> = {
  up: { label: 'Leans up', cls: 'border-profit/40 text-profit' },
  down: { label: 'Leans down', cls: 'border-loss/40 text-loss' },
  sideways: { label: 'Sideways', cls: 'border-info/40 text-info' },
  no_view: { label: 'No view', cls: 'border-line text-muted' },
}
const STATUS: Record<FcHorizonTrack['status'], { label: string; cls: string }> = {
  unproven: { label: 'unproven', cls: 'border-line text-muted' },
  beats_coin_flip: { label: 'beats a coin flip', cls: 'border-profit/40 text-profit' },
  no_edge: { label: 'no edge', cls: 'border-warn/40 text-warn' },
}
const HORIZON: Record<FcHorizon, string> = { next_close: 'Next close', expiry: 'Expiry close' }

function Tag({ cls, children, title }: { cls: string; children: ReactNode; title?: string }) {
  return <span title={title} className={cn('whitespace-nowrap rounded border px-1.5 py-px text-2xs font-medium', cls)}>{children}</span>
}

function HorizonTile({ f, h }: { f: Forecast; h: FcHorizon }) {
  const x = f.forecast![h]
  const base = f.baseline[h]
  const o = f.outcome?.[h]
  return (
    <div className="rounded-md border border-line p-3">
      <div className="text-2xs text-muted">{HORIZON[h]}{h === 'expiry' ? ` · ${date(f.expiry, { year: false })}` : ''}</div>
      <div className="mt-0.5 flex items-baseline gap-2">
        <span className={cn('num text-lg font-semibold', x.p_up > 50 ? 'text-profit' : x.p_up < 50 ? 'text-loss' : 'text-fg')}>{num(x.p_up, 0)}%</span>
        <span className="text-2xs text-muted">chance to close above {price(f.spot)}</span>
      </div>
      <div className="mt-1 text-xs"><span className="text-muted">Claude's range </span><span className="num">{price(x.low)} – {price(x.high)}</span></div>
      {base && <div className="text-xs"><span className="text-muted">Options-implied </span><span className="num text-muted">{price(base.low)} – {price(base.high)}</span></div>}
      {o && (
        <div className={cn('mt-1.5 text-xs font-medium', o.hit == null ? 'text-muted' : o.hit ? 'text-profit' : 'text-loss')}>
          Closed {price(o.close)} on {date(o.date, { year: false })} ({pct(o.move_pct, { dp: 2 })}): {o.hit == null ? 'no call' : o.hit ? 'right way' : 'wrong way'}, {o.in_range ? 'inside' : 'outside'} its range
        </div>
      )}
    </div>
  )
}

function Latest({ f }: { f: Forecast }) {
  if (f.status !== 'ok' || !f.forecast) {
    return (
      <p className="text-xs text-muted">
        {f.status === 'pending' ? `Tonight's forecast was sent ${dateTimeIST(f.created_at)}; the answer is collected by the next scheduled run.`
          : f.status === 'refused' ? 'Claude declined this one.' : `No valid answer: ${f.error ?? 'unknown error'}.`}
      </p>
    )
  }
  const b = f.forecast
  const v = VIEW[b.view]
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <Tag cls={v.cls}>{v.label}</Tag>
        <span className="text-2xs text-muted">{b.confidence} confidence · from the {dateTimeIST(f.chain_time)} chain (spot {price(f.spot)}) · {f.kind === 'evening' ? 'evening run' : 'asked on demand'}{f.cached ? ' · same chain, journalled answer' : ''}</span>
      </div>
      <p className="text-[13px] leading-relaxed">{b.summary}</p>
      <div className="grid gap-3 sm:grid-cols-2">
        <HorizonTile f={f} h="next_close" />
        <HorizonTile f={f} h="expiry" />
      </div>
      {b.invalidation != null && <p className="text-xs"><span className="text-muted">Proved wrong at </span><span className="num font-medium">{price(b.invalidation)}</span></p>}
      {b.reasons.length > 0 && (
        <ul className="space-y-1 text-xs">
          {b.reasons.map((r, i) => (
            <li key={i} className="flex gap-2">
              <Tag cls={r.tested ? 'border-profit/40 text-profit' : 'border-line text-faint'} title={r.evidence.join(', ')}>{r.tested ? 'tested' : 'untested'}</Tag>
              <span>{r.text}</span>
            </li>
          ))}
        </ul>
      )}
      {b.key_levels.length > 0 && (
        <div className="flex flex-wrap gap-1.5 text-2xs">
          {b.key_levels.map((l, i) => (
            <span key={i} title={l.why} className={cn('rounded border px-1.5 py-px', l.kind === 'support' ? 'border-profit/40' : l.kind === 'resistance' ? 'border-loss/40' : 'border-line')}>
              {l.kind} <span className="num">{price(l.price)}</span>
            </span>
          ))}
        </div>
      )}
    </div>
  )
}

function TrackTable({ track, provenMin }: { track: FcTrack[]; provenMin: number }) {
  const rows = track.flatMap((t) => (['next_close', 'expiry'] as FcHorizon[]).map((h) => ({ t, h, x: t.horizons[h] })))
  return (
    <div className="scroll-x">
      <table className="w-full min-w-[640px] text-xs">
        <thead className="text-2xs text-muted">
          <tr className="border-b border-line text-left">
            <th className="py-1 pr-2 font-medium">Forecasts</th><th className="py-1 pr-2 font-medium">Horizon</th>
            <th className="py-1 pr-2 text-right font-medium">Settled</th>
            <th className="py-1 pr-2 text-right font-medium"><Tip text="How often the side Claude leaned to (above or below 50%) was right. A coin flip is right 50% of the time.">Right way</Tip></th>
            <th className="py-1 pr-2 text-right font-medium"><Tip text="Two-sided exact binomial test against a coin flip: below 0.05 means luck alone rarely does this well.">p</Tip></th>
            <th className="py-1 pr-2 text-right font-medium"><Tip text="Brier score of the probabilities: 0 is perfect, always saying 50% scores 0.25, lower is better.">Brier</Tip></th>
            <th className="py-1 pr-2 text-right font-medium"><Tip text="How often the close landed in Claude's range (aimed at 2 in 3), and the range's average width.">Claude range</Tip></th>
            <th className="py-1 pr-2 text-right font-medium"><Tip text="The same for the options market's own 1-SD range: the baseline Claude's range has to beat.">Options range</Tip></th>
            <th className="py-1 font-medium">Verdict</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(({ t, h, x }) => (
            <tr key={`${t.kind}${h}`} className="border-b border-line/60">
              <td className="py-1 pr-2">{t.kind === 'evening' ? 'Evening run' : 'On demand'}</td>
              <td className="py-1 pr-2 text-muted">{HORIZON[h]}</td>
              <td className="num py-1 pr-2 text-right">{x.settled}</td>
              <td className="num py-1 pr-2 text-right">{ok(x.hit_pct) ? `${num(x.hit_pct, 0)}%` : DASH}{ok(x.always_up_hit_pct) ? <span className="text-faint"> · up {num(x.always_up_hit_pct, 0)}%</span> : null}</td>
              <td className="num py-1 pr-2 text-right">{ok(x.p_value) ? num(x.p_value, 3) : DASH}</td>
              <td className="num py-1 pr-2 text-right">{ok(x.brier) ? num(x.brier, 3) : DASH} <span className="text-faint">vs {num(x.coin_brier, 2)}</span></td>
              <td className="num py-1 pr-2 text-right">{ok(x.range_hit_pct) ? `${num(x.range_hit_pct, 0)}% · ±${num((x.range_width_pct ?? 0) / 2, 1)}%` : DASH}</td>
              <td className="num py-1 pr-2 text-right text-muted">{ok(x.base_range_hit_pct) ? `${num(x.base_range_hit_pct, 0)}% · ±${num((x.base_width_pct ?? 0) / 2, 1)}%` : DASH}</td>
              <td className="py-1"><Tag cls={STATUS[x.status].cls} title={x.why}>{STATUS[x.status].label}</Tag></td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-1 text-2xs text-faint">"up" = how often the close simply ended higher (the "always up" baseline). A verdict needs {provenMin}+ settled forecasts; the evening run is the clean record (one per day), on-demand ones are asked when something looks interesting.</p>
    </div>
  )
}

function Recent({ rows }: { rows: Forecast[] }) {
  if (!rows.length) return null
  return (
    <div className="scroll-x">
      <table className="w-full min-w-[560px] text-xs">
        <thead className="text-2xs text-muted">
          <tr className="border-b border-line text-left">
            <th className="py-1 pr-2 font-medium">Chain</th><th className="py-1 pr-2 font-medium">Kind</th>
            <th className="py-1 pr-2 text-right font-medium">Next close</th><th className="py-1 pr-2 text-right font-medium">Expiry</th>
            <th className="py-1 font-medium">Status</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const cell = (h: FcHorizon) => {
              const x = r.forecast?.[h]
              const o = r.outcome?.[h]
              if (!x) return DASH
              return <>{num(x.p_up, 0)}%{o ? <span className={cn('ml-1', o.hit == null ? 'text-muted' : o.hit ? 'text-profit' : 'text-loss')}>{o.hit == null ? '·' : o.hit ? '✓' : '✗'} {pct(o.move_pct, { dp: 1 })}</span> : <span className="ml-1 text-faint">open</span>}</>
            }
            return (
              <tr key={r.id} className="border-b border-line/60">
                <td className="num py-1 pr-2">{dateTimeIST(r.chain_time)}</td>
                <td className="py-1 pr-2 text-muted">{r.kind === 'evening' ? 'evening' : 'on demand'}</td>
                <td className="num py-1 pr-2 text-right">{cell('next_close')}</td>
                <td className="num py-1 pr-2 text-right">{cell('expiry')}</td>
                <td className="py-1 text-muted">{r.status === 'ok' ? 'answered' : r.status}{r.error ? `: ${r.error}` : ''}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

export function AiForecastCard({ symbol }: { symbol: string }) {
  const q = useForecasts(symbol)
  const run = useForecastNow(symbol)
  const d = q.data
  const latest = d?.latest.find((r) => r.symbol === symbol)
  const shown = run.data?.symbol === symbol ? run.data : latest
  const pending = d?.pending_batches.filter((b) => b.symbols.includes(symbol)) ?? []
  return (
    <Card title={<span className="inline-flex items-center gap-1.5"><Sparkles className="h-4 w-4 text-violet" />Claude's forecast · {symbol} <span className="text-2xs font-normal text-muted">(unproven)</span></span>}
      subtitle="Claude reads this chain, the F&O positioning and the app's tested readings; every forecast is scored against NSE's official close">
      {q.error ? <ErrorState compact error={q.error} onRetry={() => void q.refetch()} /> : !d ? <SkeletonRows rows={3} cols={3} /> : !d.configured ? (
        <div className="space-y-1 text-xs text-muted">
          <p>To switch it on, add your Anthropic API key to the <code>.env</code> file next to <code>config.yaml</code> on this PC (<code>ANTHROPIC_API_KEY=sk-ant-api03-…</code>; create it at console.anthropic.com). No restart needed.</p>
          <p>Then run <code>setup_schedule.ps1</code> once more: the 19:30 task sends one forecast per underlying ({d.underlyings.join(', ')}) each evening at half price, and the 09:12 task collects the answers. Asking on demand costs roughly ₹8-13 per forecast.</p>
        </div>
      ) : (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center gap-2">
            <Button size="sm" variant="primary" icon={<Sparkles className="h-3.5 w-3.5" />} loading={run.isPending} onClick={() => run.mutate()}>
              {run.isPending ? 'Claude is reading the chain… (up to a minute)' : `Ask Claude now (≈₹8-13)`}
            </Button>
            {pending.length > 0 && <span className="text-2xs text-muted">Evening forecast sent {dateTimeIST(pending[0].submitted_at)}: answer collected by the next scheduled run.</span>}
            {!d.underlyings.includes(symbol) && <span className="text-2xs text-faint">{symbol} is not in the evening run (config.yaml ai_forecast.underlyings).</span>}
          </div>
          {run.error && <ErrorState compact error={run.error} />}
          {shown ? <Latest f={shown} /> : <p className="text-xs text-muted">No forecast for {symbol} yet. The evening run makes one after each session; or ask now.</p>}
          <div>
            <div className="mb-1 text-xs font-semibold">Record so far</div>
            <TrackTable track={d.track} provenMin={d.proven_min} />
          </div>
          <Recent rows={d.rows.slice(0, 10)} />
          <p className="text-2xs text-muted">{d.note} Model: {d.model} ({d.effort} effort).</p>
        </div>
      )}
    </Card>
  )
}
