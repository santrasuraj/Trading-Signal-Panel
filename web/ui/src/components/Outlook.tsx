// Outlook card (Chart page): the symbol's setup today, what happened next in similar setups (8 years of the
// survivorship-free top 500), expected ranges, the levels above and below the live price, every signal with its
// tested record, and upcoming events. Base rates - the card says plainly that none of it is a forecast.

import { useState } from 'react'
import { ArrowDown, ArrowUp, Minus } from 'lucide-react'
import type { OlAnalogs, OlBias, OlHorizon, OlLevel, OlSignal, OlVerdict, OutlookResponse } from '@/api/outlook'
import { useOutlook } from '@/api/outlook'
import { EmptyState, ErrorState, SkeletonRows } from '@/components/feedback'
import { Card, Segmented, Tip } from '@/components/ui'
import { cn } from '@/lib/csv'
import { DASH, date, num, ok, pct, qty } from '@/lib/format'

const VERDICT: Record<OlVerdict, { label: string; cls: string; help: string }> = {
  better: { label: 'better than average', cls: 'border-profit/40 text-profit', help: 'Beat the average stock by more than luck explains (t ≥ 2), before costs.' },
  worse: { label: 'worse than average', cls: 'border-loss/40 text-loss', help: 'Lagged the average stock by more than luck explains (t ≤ −2).' },
  same: { label: 'like the average stock', cls: 'border-line text-muted', help: 'No difference from the average stock beyond luck.' },
  unknown: { label: 'not measurable', cls: 'border-line text-faint', help: 'Too few cases.' },
}
const BIAS: Record<OlBias, { cls: string; Icon: typeof ArrowUp; label: string }> = {
  bullish: { cls: 'text-profit', Icon: ArrowUp, label: 'Bullish' },
  bearish: { cls: 'text-loss', Icon: ArrowDown, label: 'Bearish' },
  neutral: { cls: 'text-muted', Icon: Minus, label: 'Neutral' },
}
const SOURCE: Record<OlSignal['source'], string> = {
  strategy: 'Strategy', pattern: 'Candle', chart_pattern: 'Chart pattern', trend: 'Trend', volume: 'Volume',
  options: 'Options', futures: 'Futures', intraday: 'Intraday', event: 'Event',
}

function VerdictBadge({ v }: { v: OlVerdict }) {
  const x = VERDICT[v]
  return <Tip text={x.help}><span className={cn('whitespace-nowrap rounded border px-1.5 text-2xs font-medium', x.cls)}>{x.label}</span></Tip>
}

/** p10-p90 whisker, p25-p75 box, median tick and the zero line, for one horizon. */
function DistBar({ h, base }: { h: OlHorizon; base?: boolean }) {
  const s = base ? h.base : h.setup
  if (!s || !ok(s.p10_pct) || !ok(s.p90_pct) || !ok(s.p25_pct) || !ok(s.p75_pct) || !ok(s.median_pct)) return null
  const lo = Math.min(-25, s.p10_pct), hi = Math.max(25, s.p90_pct)
  const x = (v: number) => ((v - lo) / (hi - lo)) * 100
  const tone = base ? 'bg-faint/40' : s.median_pct >= 0 ? 'bg-profit/50' : 'bg-loss/50'
  return (
    <div className="relative h-4 w-full" aria-label={`10th to 90th percentile ${pct(s.p10_pct)} to ${pct(s.p90_pct)}, median ${pct(s.median_pct)}`}>
      <div className="absolute top-1/2 h-px -translate-y-1/2 bg-line-strong" style={{ left: `${x(s.p10_pct)}%`, width: `${x(s.p90_pct) - x(s.p10_pct)}%` }} />
      <div className={cn('absolute top-0.5 h-3 rounded-sm', tone)} style={{ left: `${x(s.p25_pct)}%`, width: `${Math.max(0.5, x(s.p75_pct) - x(s.p25_pct))}%` }} />
      <div className="absolute top-0 h-4 w-0.5 bg-fg" style={{ left: `${x(s.median_pct)}%` }} />
      <div className="absolute top-0 h-4 w-px bg-muted/60" style={{ left: `${x(0)}%` }} title="0%" />
    </div>
  )
}

function Analogs({ a, close, kind }: { a: OlAnalogs; close: number | null; kind: string }) {
  const [days, setDays] = useState('20')
  const h = a.horizons.find((x) => String(x.days) === days) ?? a.horizons[a.horizons.length - 1]
  const s = h.setup
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="eyebrow">What happened next in {qty(a.n)} similar cases</div>
        <Segmented ariaLabel="Horizon" value={days} onChange={setDays} items={a.horizons.map((x) => ({ id: String(x.days), label: `${x.days} days` }))} />
      </div>
      {s && (
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          <Stat label="Median move" v={<span className={cn(ok(s.median_pct) && s.median_pct >= 0 ? 'text-profit' : 'text-loss')}>{pct(s.median_pct, { dp: 1 })}</span>} sub={h.base ? `all stocks ${pct(h.base.median_pct, { dp: 1 })}` : undefined} />
          <Stat label="Ended higher" v={`${num(s.up_pct, 0)}%`} sub={h.base ? `all stocks ${num(h.base.up_pct, 0)}%` : undefined} />
          <Stat label="vs average stock" v={<span className={cn(ok(s.excess_pct) && s.excess_pct >= 0 ? 'text-profit' : 'text-loss')}>{pct(s.excess_pct, { dp: 2 })}</span>} sub={`after costs ${pct(h.after_cost_excess_pct, { dp: 2 })} · t ${num(s.t, 1)}`} />
          <Stat label="Verdict" v={<VerdictBadge v={h.verdict} />} sub={`beat the average ${num(s.beat_pct, 0)}% of the time`} />
        </div>
      )}
      {s && (
        <div className="space-y-1.5">
          <div className="grid grid-cols-[88px_minmax(0,1fr)] items-center gap-2 text-2xs text-muted"><span>This setup</span><DistBar h={h} /></div>
          <div className="grid grid-cols-[88px_minmax(0,1fr)] items-center gap-2 text-2xs text-muted"><span>All stocks</span><DistBar h={h} base /></div>
          <p className="text-2xs text-muted">Box: the middle half of outcomes ({pct(s.p25_pct, { dp: 1 })} to {pct(s.p75_pct, { dp: 1 })}); line: 80% of them ({pct(s.p10_pct, { dp: 1 })} to {pct(s.p90_pct, { dp: 1 })}); tick: the median. Thin line: 0%.</p>
        </div>
      )}
      <div className="overflow-x-auto">
      <table className="w-full min-w-[460px] whitespace-nowrap text-xs">
        <thead><tr className="border-b border-line text-2xs text-muted">
          {['After', 'Median', 'Up', '80% of outcomes (price)', 'vs avg', ''].map((x, i) => <th key={i} className={cn('py-1 font-medium', i ? 'text-right' : 'text-left')}>{x}</th>)}
        </tr></thead>
        <tbody>{a.horizons.map((x) => (
          <tr key={x.days} className={cn('border-b border-line/50 last:border-0', String(x.days) === days && 'bg-raised/60')}>
            <td className="py-1">{x.days} days</td>
            <td className="num py-1 text-right">{pct(x.setup?.median_pct, { dp: 1 })}</td>
            <td className="num py-1 text-right">{num(x.setup?.up_pct, 0)}%</td>
            <td className="num py-1 text-right">{close != null ? `${num(x.price_p10, 2)} – ${num(x.price_p90, 2)}` : DASH}</td>
            <td className="num py-1 text-right">{pct(x.setup?.excess_pct, { dp: 2 })}</td>
            <td className="py-1 pl-2 text-right"><VerdictBadge v={x.verdict} /></td>
          </tr>
        ))}</tbody>
      </table>
      </div>
      <div className="grid gap-2 sm:grid-cols-2">
        <div className="rounded-md border border-line p-2 text-xs">
          <div className="text-2xs text-muted">Touched +{num(a.touch.pct, 0)}% within {a.touch.days} days</div>
          <div className="num text-[15px] font-semibold text-profit">{num(a.touch.up_pct, 0)}%</div>
          <div className="text-2xs text-faint">all stocks {num(a.base_touch.up_pct, 0)}%</div>
        </div>
        <div className="rounded-md border border-line p-2 text-xs">
          <div className="text-2xs text-muted">Touched −{num(a.touch.pct, 0)}% within {a.touch.days} days</div>
          <div className="num text-[15px] font-semibold text-loss">{num(a.touch.down_pct, 0)}%</div>
          <div className="text-2xs text-faint">all stocks {num(a.base_touch.down_pct, 0)}%</div>
        </div>
      </div>
      <p className="text-2xs text-muted">
        {a.universe}, {date(a.first_day)} – {date(a.last_day)}; {qty(a.n)} cases over {a.months} months{a.dropped.length ? ` (matched without ${a.dropped.join(', ')}: too few cases with it)` : ''}.
        {h.own_n != null && h.own_n >= 10 && ` In ${h.own_n} cases in its own past, ${h.days} days later the median move was ${pct(h.own_median_pct, { dp: 1 })} (${num(h.own_up_pct, 0)}% up) - few cases, a footnote only.`}
        {kind !== 'stock' && ' Measured on stocks: an index or ETF usually moves less.'}
      </p>
    </div>
  )
}

function Stat({ label, v, sub }: { label: string; v: React.ReactNode; sub?: string }) {
  return (
    <div className="rounded-md border border-line p-2">
      <div className="text-2xs text-muted">{label}</div>
      <div className="num text-[15px] font-semibold">{v}</div>
      {sub && <div className="text-2xs text-faint">{sub}</div>}
    </div>
  )
}

function Ladder({ above, below, price, live }: { above: OlLevel[]; below: OlLevel[]; price: number | null; live: boolean }) {
  const d = (x: number) => (ok(price) && price > 0 ? (x / price - 1) * 100 : null)
  const row = (l: OlLevel, side: 'above' | 'below') => (
    <li key={`${side}${l.price}`} className="flex items-baseline justify-between gap-2 border-b border-line/50 py-1 last:border-0">
      <span className={cn('num w-20 shrink-0 text-[13px] font-semibold', side === 'above' ? 'text-loss' : 'text-profit')}>{num(l.price, 2)}</span>
      <span className="min-w-0 flex-1 truncate text-xs text-muted" title={l.label}>{l.label}{l.strength ? ` · ${l.strength}×` : ''}</span>
      <span className="num shrink-0 text-2xs text-muted">{pct(d(l.price), { dp: 1 })}</span>
    </li>
  )
  return (
    <div>
      <ul>{[...above].reverse().map((l) => row(l, 'above'))}</ul>
      <div className="my-1 flex items-center justify-between rounded bg-raised px-2 py-1 text-[13px]">
        <span className="font-semibold">{live ? 'Live price' : 'Last close'}</span>
        <span className="num font-semibold">{num(price, 2)}</span>
      </div>
      <ul>{below.map((l) => row(l, 'below'))}</ul>
      {!above.length && !below.length && <p className="text-xs text-muted">No levels yet.</p>}
    </div>
  )
}

function Signals({ items }: { items: OlSignal[] }) {
  const [filter, setFilter] = useState<'all' | OlBias>('all')
  const n = (b: OlBias) => items.filter((x) => x.bias === b).length
  const shown = filter === 'all' ? items : items.filter((x) => x.bias === filter)
  if (!items.length) return <p className="text-xs text-muted">No signal on this symbol right now: no strategy order or holding, no pattern on the last bars, no trend change.</p>
  return (
    <div>
      <Segmented ariaLabel="Signal side" value={filter} onChange={setFilter} items={[
        { id: 'all', label: `All ${items.length}` }, { id: 'bullish', label: `Bullish ${n('bullish')}` },
        { id: 'bearish', label: `Bearish ${n('bearish')}` }, { id: 'neutral', label: `Neutral ${n('neutral')}` },
      ]} />
      <ul className="mt-2 space-y-1.5">
        {shown.map((s, i) => {
          const b = BIAS[s.bias]
          return (
            <li key={`${s.source}${s.title}${i}`} className="flex items-start gap-2 text-[13px]">
              <b.Icon className={cn('mt-0.5 h-3.5 w-3.5 shrink-0', b.cls)} aria-label={b.label} />
              <span className="min-w-0 flex-1">
                <span className="block"><span className="mr-1.5 rounded border border-line px-1 text-2xs text-muted">{SOURCE[s.source]}</span>{s.title}</span>
                {s.detail && <span className="block text-2xs text-muted">{s.detail}</span>}
              </span>
              <span className="shrink-0 text-right">
                {s.tested && <span className={cn('block whitespace-nowrap text-2xs', s.tone === 'good' ? 'text-profit' : s.tone === 'bad' ? 'text-loss' : 'text-faint')}>{s.tested}</span>}
                {s.when && <span className="block text-2xs text-faint">{date(s.when, { year: false })}</span>}
              </span>
            </li>
          )
        })}
      </ul>
      <p className="mt-2 text-2xs text-muted">Counted, not weighted: several signals pointing one way are not a stronger forecast. Trust a strategy line only when the strategy itself is “working”.</p>
    </div>
  )
}

function Ranges({ o }: { o: OutlookResponse }) {
  const e = o.expected
  const byDays = [...e.ranges].sort((a, b) => a.days - b.days || a.source.localeCompare(b.source))
  return (
    <div>
      <table className="w-full text-xs">
        <thead><tr className="border-b border-line text-2xs text-muted"><th className="py-1 text-left font-medium">Range</th><th className="py-1 text-right font-medium">Low</th><th className="py-1 text-right font-medium">High</th><th className="py-1 text-right font-medium">±</th></tr></thead>
        <tbody>{byDays.map((r) => (
          <tr key={`${r.source}${r.days}`} className="border-b border-line/50 last:border-0">
            <td className="py-1 pr-2 text-muted"><Tip text={`About ${num(r.prob_pct, 0)}% of outcomes fall inside`}><span>{r.label}</span></Tip></td>
            <td className="num py-1 text-right text-profit">{num(r.low, 2)}</td>
            <td className="num py-1 text-right text-loss">{num(r.high, 2)}</td>
            <td className="num py-1 text-right text-muted">{num(r.pct, 1)}%</td>
          </tr>
        ))}</tbody>
      </table>
      <p className="mt-1 text-2xs text-muted">
        Day range (ATR 14) {num(e.atr, 2)} ({num(e.atr_pct, 1)}%) · recent volatility {num(e.realized_vol_pct, 0)}%/yr
        {ok(e.iv_pct) ? ` · option-implied ${num(e.iv_pct, 1)}%/yr (expiry ${date(e.iv_expiry, { year: false })})` : ''}.
      </p>
    </div>
  )
}

export function OutlookPanel({ symbol, livePrice }: { symbol: string; livePrice: number | null }) {
  const q = useOutlook(symbol, livePrice != null)
  if (q.isLoading) return <Card title="Outlook: what usually happens next"><SkeletonRows rows={6} cols={4} /></Card>
  if (q.error) return <Card title="Outlook: what usually happens next"><ErrorState compact error={q.error} onRetry={() => void q.refetch()} /></Card>
  const o = q.data
  if (!o) return null
  const price = livePrice ?? o.close
  return (
    <Card
      title="Outlook: what usually happens next"
      subtitle={`Setup on ${date(o.date)}${o.provisional ? ' (today\'s live candle, provisional)' : ''} · base rates from history, not a forecast`}
    >
      <div className="space-y-4">
        <div>
          <div className="flex flex-wrap gap-1.5">
            {o.setup.map((f) => <Tip key={f.feature} text={f.label}><span className="rounded-full border border-line bg-raised px-2 py-0.5 text-2xs font-medium">{f.short}</span></Tip>)}
          </div>
          <p className="mt-2 text-[13px] leading-relaxed">{o.headline}</p>
        </div>
        <div className="grid gap-5 lg:grid-cols-2 2xl:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)_minmax(0,1fr)]">
          <div className="min-w-0">
            {o.analogs ? <Analogs a={o.analogs} close={o.close} kind={o.kind} /> : <EmptyState compact title="No base rates yet">{o.study_hint}</EmptyState>}
          </div>
          <div className="min-w-0 space-y-4">
            <div>
              <div className="eyebrow mb-1">Levels above and below</div>
              <Ladder above={o.scenarios.above} below={o.scenarios.below} price={price} live={livePrice != null} />
            </div>
            {o.scenarios.flips.length > 0 && (
              <div>
                <div className="eyebrow mb-1">What would change the trend</div>
                <ul className="list-disc space-y-1 pl-4 text-xs text-muted">{o.scenarios.flips.map((f) => <li key={f}>{f}</li>)}</ul>
              </div>
            )}
          </div>
          <div className="min-w-0 space-y-4 lg:col-span-2 2xl:col-span-1">
            <div>
              <div className="eyebrow mb-1">Expected range</div>
              <Ranges o={o} />
            </div>
            {o.events.length > 0 && (
              <div>
                <div className="eyebrow mb-1">Coming up</div>
                <ul className="space-y-1 text-xs">{o.events.map((e) => (
                  <li key={`${e.kind}${e.date}`} className="flex justify-between gap-2"><span className="num text-muted">{date(e.date)}</span><span className={cn(e.kind === 'results' && 'text-warn')}>{e.label}</span></li>
                ))}</ul>
              </div>
            )}
          </div>
        </div>
        <div>
          <div className="eyebrow mb-2">Signals now</div>
          <Signals items={o.signals} />
        </div>
        <p className="text-2xs text-muted">{o.note}</p>
      </div>
    </Card>
  )
}
