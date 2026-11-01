// Price action card (Chart page): pivots, swing support / resistance, trend and candle patterns from daily bars, plus
// today's VWAP, opening range and volume profile when the stock has 5-minute bars (web/api/routers/levels.py).
// Descriptive only - the card says so.

import { useLevels, type LvChartPattern, type LvLevel, type LvPattern } from '@/api/levels'
import { isFailure } from '@/api/client'
import { EmptyState, ErrorState, SkeletonRows } from '@/components/feedback'
import { Card, Tip } from '@/components/ui'
import { cn } from '@/lib/csv'
import { DASH, date, num, ok, pct, timeIST } from '@/lib/format'

const dist = (px: number | null, from: number | null) => (ok(px) && ok(from) && from > 0 ? pct((px / from - 1) * 100, { dp: 1 }) : DASH)

function Row({ k, v, sub, tone, strong }: { k: string; v: number | null; sub?: string; tone?: 'profit' | 'loss'; strong?: boolean }) {
  return (
    <tr className="border-b border-line/50 last:border-0">
      <td className={cn('py-1 text-xs', strong ? 'font-semibold text-fg' : 'text-muted')}>{k}</td>
      <td className={cn('num py-1 text-right text-[13px]', tone === 'profit' ? 'text-profit' : tone === 'loss' ? 'text-loss' : 'text-fg', strong && 'font-semibold')}>{num(v, 2)}</td>
      <td className="num py-1 pl-2 text-right text-2xs text-muted">{sub ?? ''}</td>
    </tr>
  )
}

function Levels({ title, items, tone }: { title: string; items: LvLevel[]; tone: 'profit' | 'loss' }) {
  return (
    <div>
      <div className="eyebrow mb-1">{title}</div>
      {items.length ? items.map((l) => (
        <div key={`${l.price}-${l.last}`} className="flex items-baseline justify-between gap-2 border-b border-line/50 py-1 last:border-0" title={`Formed ${l.touches} time${l.touches > 1 ? 's' : ''}, last on ${date(l.last)}`}>
          <span className={cn('num text-[13px] font-semibold', tone === 'profit' ? 'text-profit' : 'text-loss')}>{num(l.price, 2)}</span>
          <span className="flex items-center gap-1" aria-label={`strength ${l.touches}`}>
            {Array.from({ length: Math.min(l.touches, 5) }).map((_, i) => <span key={i} className={cn('h-1.5 w-1.5 rounded-full', tone === 'profit' ? 'bg-profit' : 'bg-loss')} />)}
          </span>
          <span className="num text-2xs text-muted">{pct(l.dist_pct, { dp: 1 })}</span>
        </div>
      )) : <div className="text-xs text-muted">None within a year</div>}
    </div>
  )
}

function Patterns({ items, intraday }: { items: LvPattern[]; intraday?: boolean }) {
  if (!items.length) return <div className="text-xs text-muted">No pattern on the last bars.</div>
  return (
    <ul className="space-y-1">
      {items.map((p) => (
        <li key={`${p.key}-${p.at}`} className="flex items-center justify-between gap-2 text-[13px]">
          <Tip text={p.what}>
            <span className={cn('rounded border px-1.5 text-2xs font-semibold', p.bias === 'bullish' ? 'border-profit/40 text-profit' : p.bias === 'bearish' ? 'border-loss/40 text-loss' : 'border-line text-muted')}>{p.name}</span>
          </Tip>
          <span className="text-2xs text-muted">{p.bars_ago === 0 ? 'last bar' : `${p.bars_ago} bar${p.bars_ago > 1 ? 's' : ''} ago`} · {intraday ? timeIST(p.at) : date(p.at.slice(0, 10), { year: false })}</span>
        </li>
      ))}
    </ul>
  )
}

/** A small drawing of one chart pattern: the closes, its labelled swing points and its lines. */
function Sketch({ p }: { p: LvChartPattern }) {
  const W = 220, H = 86, P = 6
  const vals = [...p.series, ...p.points.map((x) => x.price), ...p.lines.flatMap((l) => [l.p1, l.p2])].filter(ok)
  if (p.series.length < 2 || !vals.length) return null
  const lo = Math.min(...vals), hi = Math.max(...vals)
  const x = (i: number) => P + ((W - 2 * P) * i) / (p.series.length - 1)
  const y = (v: number) => P + (H - 2 * P) * (1 - (v - lo) / (hi - lo || 1))
  const d = p.series.map((v, i) => (ok(v) ? `${i && ok(p.series[i - 1]) ? 'L' : 'M'}${x(i).toFixed(1)},${y(v).toFixed(1)}` : '')).join('')
  const tone = p.bias === 'bullish' ? 'stroke-profit' : p.bias === 'bearish' ? 'stroke-loss' : 'stroke-warn'
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="h-[86px] w-full max-w-[260px]" role="img" aria-label={`${p.name} sketch`}>
      <path d={d} fill="none" className="stroke-muted" strokeWidth={1.25} vectorEffect="non-scaling-stroke" />
      {p.lines.map((l, k) => ok(l.p1) && ok(l.p2) && (
        <line key={k} x1={x(l.i1)} y1={y(l.p1)} x2={x(l.i2)} y2={y(l.p2)} className={tone} strokeWidth={1.5} strokeDasharray="4 3" vectorEffect="non-scaling-stroke" />
      ))}
      {p.points.map((pt, k) => ok(pt.price) && (
        <g key={k}>
          <circle cx={x(pt.i)} cy={y(pt.price)} r={2.5} className={cn('fill-current', p.bias === 'bullish' ? 'text-profit' : p.bias === 'bearish' ? 'text-loss' : 'text-warn')} />
          {pt.label && <text x={x(pt.i)} y={Math.max(9, y(pt.price) - 5)} textAnchor="middle" className="fill-current text-[8px] text-muted">{pt.label}</text>}
        </g>
      ))}
    </svg>
  )
}

function ChartPatterns({ items }: { items: LvChartPattern[] }) {
  if (!items.length) return <p className="text-xs text-muted">No double top or bottom, head and shoulders, triangle, wedge, rectangle or flag on the last months of daily bars.</p>
  return (
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      {items.map((p) => (
        <div key={`${p.key}-${p.start}`} className="rounded-md border border-line p-3">
          <div className="flex flex-wrap items-center gap-1.5">
            <Tip text={p.what}><span className={cn('rounded border px-1.5 text-2xs font-semibold', p.bias === 'bullish' ? 'border-profit/40 text-profit' : p.bias === 'bearish' ? 'border-loss/40 text-loss' : 'border-warn/40 text-warn')}>{p.name}</span></Tip>
            <span className={cn('text-2xs font-medium', p.status === 'confirmed' ? 'text-fg' : 'text-muted')}>
              {p.status === 'confirmed' ? `confirmed${p.direction ? ` ${p.direction}` : ''}${p.confirmed_bars_ago != null ? `, ${p.confirmed_bars_ago === 0 ? 'last bar' : `${p.confirmed_bars_ago} bars ago`}` : ''}` : 'forming'}
            </span>
          </div>
          <Sketch p={p} />
          <table className="w-full text-xs">
            <tbody>
              <tr><td className="py-0.5 text-muted" title="A close beyond this level completes the pattern">Breakout</td><td className="num py-0.5 text-right">{num(p.breakout, 2)}</td></tr>
              <tr><td className="py-0.5 text-muted" title="Beyond this level the pattern is void">Invalid beyond</td><td className="num py-0.5 text-right">{num(p.invalidation, 2)}</td></tr>
              <tr><td className="py-0.5 text-muted" title="The textbook measured move - folklore, never tested here">Textbook target</td><td className="num py-0.5 text-right">{p.target != null ? <>{num(p.target, 2)} <span className="text-muted">({pct(p.target_pct, { dp: 1 })})</span></> : DASH}</td></tr>
            </tbody>
          </table>
          <div className="mt-1 text-2xs text-faint">{date(p.start, { year: false })} – {date(p.end, { year: false })}</div>
        </div>
      ))}
    </div>
  )
}

const yes = (b: boolean | null) => (b == null ? <span className="text-faint">{DASH}</span> : b ? <span className="text-profit">above</span> : <span className="text-loss">below</span>)

export function PriceAction({ symbol }: { symbol: string }) {
  const q = useLevels(symbol)
  if (q.isLoading) return <Card title="Price action"><SkeletonRows rows={6} cols={4} /></Card>
  if (q.error) {
    if (isFailure(q.error) && q.error.code === 'NOT_FOUND') return null          // no daily bars: nothing to show
    return <Card title="Price action"><ErrorState compact error={q.error} onRetry={() => void q.refetch()} /></Card>
  }
  const d = q.data?.daily
  const i = q.data?.intraday
  if (!d) return <Card title="Price action"><EmptyState compact title="Not enough history">Price action needs at least 30 daily bars.</EmptyState></Card>
  const t = d.trend
  return (
    <Card title="Price action" subtitle={`Daily to ${date(d.date)}${i ? ` · today's 5-minute bars to ${timeIST(i.last_bar)} (${q.data?.intraday_source === 'live' ? 'live feed' : 'stored'})` : ''}`}>
      <div className="grid gap-5 md:grid-cols-2 xl:grid-cols-4">
        <div>
          <div className="eyebrow mb-1" title="Classic floor pivots for the next session, from the last completed day's high, low and close">Pivots · next session</div>
          <table className="w-full">
            <tbody>
              <Row k="R3" v={d.pivots.r3} sub={dist(d.pivots.r3, d.close)} tone="loss" />
              <Row k="R2" v={d.pivots.r2} sub={dist(d.pivots.r2, d.close)} tone="loss" />
              <Row k="R1" v={d.pivots.r1} sub={dist(d.pivots.r1, d.close)} tone="loss" />
              <Row k="CPR top" v={d.pivots.tc} sub={dist(d.pivots.tc, d.close)} />
              <Row k="Pivot" v={d.pivots.p} sub={dist(d.pivots.p, d.close)} strong />
              <Row k="CPR bottom" v={d.pivots.bc} sub={dist(d.pivots.bc, d.close)} />
              <Row k="S1" v={d.pivots.s1} sub={dist(d.pivots.s1, d.close)} tone="profit" />
              <Row k="S2" v={d.pivots.s2} sub={dist(d.pivots.s2, d.close)} tone="profit" />
              <Row k="S3" v={d.pivots.s3} sub={dist(d.pivots.s3, d.close)} tone="profit" />
            </tbody>
          </table>
          <p className="mt-1 text-2xs text-muted">CPR width {num(d.cpr_width_pct, 2)}% of price{ok(d.cpr_width_pct) && d.cpr_width_pct < 0.15 ? ' (narrow)' : ''}</p>
        </div>
        <div className="space-y-3">
          <Levels title="Resistance (swing highs)" items={d.levels.resistance} tone="loss" />
          <Levels title="Support (swing lows)" items={d.levels.support} tone="profit" />
          <p className="text-2xs text-muted">Dots: how many swings formed there in the last year. Day range {num(d.atr, 2)} ({num(d.atr_pct, 1)}%).</p>
        </div>
        <div className="space-y-3">
          <div>
            <div className="eyebrow mb-1">Trend</div>
            <table className="w-full text-[13px]">
              <tbody>
                <tr><td className="py-0.5 text-xs text-muted">20-day average</td><td className="num py-0.5 text-right">{num(t.sma20, 2)}</td><td className="py-0.5 pl-2 text-right text-xs">{yes(t.above_sma20)}</td></tr>
                <tr><td className="py-0.5 text-xs text-muted">50-day average</td><td className="num py-0.5 text-right">{num(t.sma50, 2)}</td><td className="py-0.5 pl-2 text-right text-xs">{yes(t.above_sma50)}</td></tr>
                <tr><td className="py-0.5 text-xs text-muted">200-day average</td><td className="num py-0.5 text-right">{num(t.sma200, 2)}</td><td className="py-0.5 pl-2 text-right text-xs">{yes(t.above_sma200)}</td></tr>
                <tr><td className="py-0.5 text-xs text-muted">Supertrend (10, 3)</td><td className="num py-0.5 text-right">{num(t.supertrend, 2)}</td><td className="py-0.5 pl-2 text-right text-xs">{t.supertrend_dir === 'up' ? <span className="text-profit">up</span> : t.supertrend_dir === 'down' ? <span className="text-loss">down</span> : DASH}</td></tr>
              </tbody>
            </table>
            <p className="mt-1 text-xs">{t.structure === 'up' ? <span className="text-profit">Higher highs and higher lows</span> : t.structure === 'down' ? <span className="text-loss">Lower highs and lower lows</span> : <span className="text-muted">Mixed swings (no clear structure)</span>}</p>
            <p className="mt-1 text-2xs text-muted">52-week range {num(d.low_52w, 2)} – {num(d.high_52w, 2)} · {pct(d.from_high_52w_pct, { dp: 1 })} from the high</p>
          </div>
          <div>
            <div className="eyebrow mb-1">Daily candle patterns</div>
            <Patterns items={d.patterns} />
          </div>
        </div>
        <div className="space-y-3">
          <div className="eyebrow">Today (5-minute bars)</div>
          {i ? (
            <>
              <table className="w-full">
                <tbody>
                  <Row k="VWAP +1 SD" v={i.vwap_upper} sub={dist(i.vwap_upper, i.last)} />
                  <Row k="VWAP" v={i.vwap} sub={i.above_vwap == null ? '' : i.above_vwap ? 'price above' : 'price below'} strong />
                  <Row k="VWAP −1 SD" v={i.vwap_lower} sub={dist(i.vwap_lower, i.last)} />
                  <Row k="Opening range high" v={i.or_high} sub={i.or_state === 'above' ? 'broken up' : ''} tone="loss" />
                  <Row k="Opening range low" v={i.or_low} sub={i.or_state === 'below' ? 'broken down' : ''} tone="profit" />
                  <Row k="Day high / low" v={i.high} sub={num(i.low, 2)} />
                  {i.profile && <Row k="Point of control" v={i.profile.poc} sub={`value ${num(i.profile.val, 1)}–${num(i.profile.vah, 1)}`} />}
                </tbody>
              </table>
              <Patterns items={i.patterns} intraday />
            </>
          ) : <p className="text-xs text-muted">No 5-minute bars for this symbol today (the live feed covers the 100 most liquid F&O stocks; the stored bars the ~150 of the intraday universe).</p>}
        </div>
      </div>
      <div className="mt-5">
        <div className="eyebrow mb-2">Chart patterns (daily)</div>
        <ChartPatterns items={d.chart_patterns} />
        {d.chart_patterns.length > 1 && <p className="mt-2 text-2xs text-muted">Patterns over different stretches can point different ways - one more reason not to trade them blindly.</p>}
      </div>
      <p className="mt-3 text-2xs text-muted">{q.data?.note}</p>
    </Card>
  )
}
