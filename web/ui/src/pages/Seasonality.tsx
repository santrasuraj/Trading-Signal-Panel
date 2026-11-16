// Seasonality `/seasonality`: which stocks and sectors have tended to rise or fall in each calendar month and each Indian
// market season, against the NIFTY 500 (scanner/seasonal.py, web/api/services/seasonal_svc.py). Next to every list: how
// many such "consistent" stocks chance alone gives (month labels shuffled within each year), and a walk-forward test of
// buying the best-record stocks from the point-in-time top 500 after costs. Descriptive base rates, not a forecast.

import { useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { CalendarRange, Info } from 'lucide-react'
import { useSeasonal, type SeasonRow, type SeasonStrength, type SeasonSummary, type SeasonView } from '@/api/seasonal'
import { ProofBadge } from '@/components/badges'
import { DataTable, type Col } from '@/components/DataTable'
import { PageHeader } from '@/components/domain'
import { Banner, ErrorState, SkeletonRows } from '@/components/feedback'
import { Card, Segmented } from '@/components/ui'
import { cn } from '@/lib/csv'
import { num, pct } from '@/lib/format'

const STRENGTH: Record<SeasonStrength, [string, string, string]> = {
  consistent: ['Consistent', 'bg-info/15 text-info', '|t| of 2+ and the same direction in 75%+ of the years'],
  lean: ['Lean', 'bg-raised text-fg', '|t| of 1.5+ or the same direction in 70%+ of the years'],
  noise: ['Noise', 'bg-raised text-faint', 'no steady record: as likely luck as not'],
}

function StrengthBadge({ s }: { s: SeasonStrength }) {
  const [label, tone, title] = STRENGTH[s]
  return <span className={cn('inline-flex h-5 items-center rounded-full px-2 text-2xs font-semibold', tone)} title={title}>{label}</span>
}

/** One square per year: green above the NIFTY 500, red below, stronger for bigger moves. */
function YearStrip({ years, first, last }: { years: Record<string, number | null>; first: number | null; last: number | null }) {
  if (first == null || last == null) return null
  const ys = Array.from({ length: last - first + 1 }, (_, i) => first + i)
  return (
    <span className="inline-flex gap-[3px]" aria-label="Each year against the NIFTY 500">
      {ys.map((y) => {
        const v = years[String(y)]
        const a = v == null ? 0 : Math.min(1, 0.25 + Math.abs(v) / 10)
        return <span key={y} title={`${y}: ${v == null ? 'not listed' : pct(v)} vs NIFTY 500`} className="h-3 w-3 rounded-[2px] border border-line"
          style={{ background: v == null ? 'transparent' : `rgb(var(--${v >= 0 ? 'profit' : 'loss'}) / ${a})` }} />
      })}
    </span>
  )
}

function cols(d: SeasonView): Col<SeasonRow>[] {
  const out: Col<SeasonRow>[] = [
    { id: 'sym', header: 'Stock', sticky: true, mobile: 'primary', value: (r) => r.symbol, search: (r) => `${r.symbol} ${r.company ?? ''}`, cell: (r) => (
      <Link to={`/chart/${r.symbol}`} className="block hover:underline" title={`Open ${r.symbol}'s chart (its own month-by-month card is there)`}>
        <span className="block font-semibold">{r.symbol}</span><span className="block max-w-[180px] truncate text-2xs text-muted">{r.company ?? ''}</span>
      </Link>) },
    { id: 'ind', header: 'Sector', value: (r) => r.industry ?? '', hideBelow: 900, cell: (r) => <span className="block max-w-[160px] truncate text-xs text-muted">{r.industry ?? '—'}</span> },
    { id: 'ex', header: 'vs NIFTY 500', align: 'right', mobile: 'change', title: 'Average return over the NIFTY 500 in this period, over the years shown', value: (r) => r.excess_pct,
      cell: (r) => <span className={cn('num font-semibold', (r.excess_pct ?? 0) >= 0 ? 'text-profit' : 'text-loss')}>{pct(r.excess_pct)}</span> },
    { id: 'beat', header: 'Years', align: 'right', title: 'Years it beat (rising list) or lagged (falling list) the NIFTY 500, of the years it was listed', value: (r) => (r.side === 'bullish' ? r.beat_pct : 100 - (r.beat_pct ?? 0)),
      cell: (r) => { const k = Math.round(((r.side === 'bullish' ? r.beat_pct : 100 - (r.beat_pct ?? 0)) ?? 0) * r.n / 100); return <span className="num">{k}/{r.n}</span> } },
    { id: 't', header: 't', align: 'right', title: 'How far the average is from zero given how much the years vary: about 2 or more is unlikely to be pure luck for ONE stock (but see the chance check above)', value: (r) => r.t, cell: (r) => <span className="num text-muted">{num(r.t, 1)}</span> },
    { id: 'str', header: 'Record', mobile: 'secondary', value: (r) => ['consistent', 'lean', 'noise'].indexOf(r.strength), cell: (r) => <StrengthBadge s={r.strength} /> },
    { id: 'strip', header: 'Each year', sortable: false, hideBelow: 640, value: () => 0, cell: (r) => <YearStrip years={r.years} first={d.first_year} last={d.last_year} /> },
    { id: 'avg', header: 'Avg return', align: 'right', defaultHidden: true, title: 'Average plain return in this period', value: (r) => r.avg_pct, cell: (r) => <span className="num">{pct(r.avg_pct)}</span> },
  ]
  if (d.in_progress) {
    out.push({ id: 'now', header: 'This year so far', align: 'right', title: `Since the period began this year, against the NIFTY 500 (${pct(d.market_so_far_pct)} itself)`, value: (r) => r.so_far_excess_pct,
      cell: (r) => <span className={cn('num', (r.so_far_excess_pct ?? 0) >= 0 ? 'text-profit' : 'text-loss')}>{pct(r.so_far_excess_pct)}</span> })
  }
  return out
}

function chanceVerdict(found: number, chance: number, p95: number): [string, string] {
  if (found > p95) return ['More than chance', 'text-profit']
  if (found > chance) return ['Within what luck gives', 'text-warn']
  return ['No more than chance', 'text-muted']
}

function TestLine({ s, unit }: { s: SeasonSummary; unit: string }) {
  if (!s.n) return <span className="text-faint">not enough history yet</span>
  return (
    <span>
      Top {unit === 'season' ? '10 each season' : '10 each month'}: <b className={cn('num', (s.top_avg_pct ?? 0) >= 0 ? 'text-profit' : 'text-loss')}>{pct(s.top_avg_pct, { dp: 2 })}</b> a {unit} over the NIFTY 500 after costs, beat it in {num(s.top_hit_pct, 0)}% of {s.n} {unit}s (t {num(s.top_t, 1)}).
      {' '}Bottom 10: <b className="num">{pct(s.bottom_avg_pct, { dp: 2 })}</b>.
    </span>
  )
}

function Summary({ d }: { d: SeasonView }) {
  const c = d.counts, m = d.market, unit = d.period.kind
  const [bv, bt] = chanceVerdict(c.bullish.consistent, c.chance.bullish, c.chance.bullish_p95)
  const [sv, st] = chanceVerdict(c.bearish.consistent, c.chance.bearish, c.chance.bearish_p95)
  const up = m.up_pct != null ? Math.round(m.up_pct * m.n / 100) : null
  return (
    <div className="grid gap-3 lg:grid-cols-3">
      <Card title={`NIFTY 500 in ${d.period.name}`} subtitle={d.period.why ?? `${d.first_year}–${d.last_year}`}>
        <div className="flex items-baseline gap-3"><span className={cn('num text-2xl font-semibold', (m.avg_pct ?? 0) >= 0 ? 'text-profit' : 'text-loss')}>{pct(m.avg_pct)}</span>
          <span className="text-xs text-muted">average · up {up ?? '—'} of {m.n} years · t {num(m.t, 1)}</span></div>
        <div className="mt-2"><YearStrip years={m.years} first={d.first_year} last={d.last_year} /></div>
        {d.in_progress && <p className="mt-2 text-xs">This year so far: <b className={cn('num', (d.market_so_far_pct ?? 0) >= 0 ? 'text-profit' : 'text-loss')}>{pct(d.market_so_far_pct)}</b> <span className="text-muted">(to {d.as_of})</span></p>}
      </Card>
      <Card title="More than luck?" subtitle={`${c.chance.permutations} shuffles of the month labels within each year`}>
        <ul className="space-y-1.5 text-xs">
          <li><b className="num">{c.bullish.consistent}</b> stocks consistently <span className="text-profit">rose</span>; chance alone gives about <b className="num">{num(c.chance.bullish, 0)}</b> (up to {c.chance.bullish_p95}). <span className={cn('font-semibold', bt)}>{bv}.</span></li>
          <li><b className="num">{c.bearish.consistent}</b> consistently <span className="text-loss">fell</span>; chance alone gives about <b className="num">{num(c.chance.bearish, 0)}</b> (up to {c.chance.bearish_p95}). <span className={cn('font-semibold', st)}>{sv}.</span></li>
        </ul>
        <p className="mt-2 text-2xs text-muted">With ~500 stocks and {d.last_year && d.first_year ? d.last_year - d.first_year + 1 : 8} years, some look steady by luck. A list only means something when it clearly beats this count.</p>
      </Card>
      <Card title="Did buying them work?" subtitle={`Walk-forward, ${d.test.universe === 'point_in_time' ? 'point-in-time top 500 (delisted stocks included)' : "today's list only (flattered: survivors)"}, ${pct(d.test.cost_pct, { dp: 2, signed: false })} costs`}>
        <div className="mb-1.5 flex items-center gap-2 text-xs"><ProofBadge status={d.test.pooled.status} /><span className="text-muted">every {unit} pooled{d.test.pooled.first ? `, ${d.test.pooled.first} to ${d.test.pooled.last}` : ''}</span></div>
        <p className="text-xs"><TestLine s={d.test.pooled} unit={unit} /></p>
        <p className="mt-2 text-2xs text-muted">
          {d.period.name} alone: {d.test.rows.length ? d.test.rows.map((r) => `${r.label.split(' ').pop()} ${pct(r.top_excess_pct)}`).join(' · ') : 'no year with enough history yet'}
          {d.test.rows.length > 0 && d.test.rows.length < 12 ? ' - too few to judge on their own.' : '.'}
        </p>
        <p className="mt-1 text-2xs text-faint">Each {unit}: the {d.test.top_n} stocks with the best record in it over the earlier years only ({d.test.train_min_years}+ years each), bought at its start, sold at its end.</p>
      </Card>
    </div>
  )
}

function SectorGrid({ d, kind, onPick }: { d: SeasonView; kind: 'month' | 'season'; onPick: (k: string) => void }) {
  const periods = d.periods.filter((p) => p.kind === kind)
  if (!d.sectors.length) return null
  return (
    <Card title="Sectors, period by period" subtitle="Average return over the NIFTY 500 of each sector's stocks (equal weight); bold = |t| of 2+. Click a column to open it." flush>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[720px] border-collapse text-2xs">
          <thead><tr className="border-b border-line text-muted">
            <th className="sticky left-0 bg-panel px-3 py-1.5 text-left font-medium">Sector</th>
            {periods.map((p) => (
              <th key={p.key} className={cn('px-1 py-1.5 text-center font-medium', p.key === d.period.key && 'text-fg')}>
                <button type="button" className={cn('rounded px-1.5 py-0.5 hover:bg-raised', p.key === d.period.key && 'bg-raised font-semibold')} onClick={() => onPick(p.key)} title={p.name}>{p.short}</button>
              </th>))}
          </tr></thead>
          <tbody>
            {d.sectors.map((s) => (
              <tr key={s.industry} className="border-b border-line/60">
                <td className="sticky left-0 max-w-[200px] truncate bg-panel px-3 py-1 text-xs" title={`${s.industry}: ${s.stocks} stocks`}>{s.industry}</td>
                {periods.map((p) => {
                  const c = s.cells.find((x) => x.period === p.key)
                  const v = c?.excess_pct
                  const a = v == null ? 0 : Math.min(0.75, Math.abs(v) / 5)
                  return (
                    <td key={p.key} className={cn('px-1 py-1 text-center num', p.key === d.period.key && 'outline outline-1 -outline-offset-1 outline-line-strong', c?.t != null && Math.abs(c.t) >= 2 && 'font-bold')}
                      style={{ background: v == null ? undefined : `rgb(var(--${v >= 0 ? 'profit' : 'loss'}) / ${a})` }}
                      title={c ? `${s.industry}, ${p.name}: ${pct(v)} vs NIFTY 500, beat it ${num(c.beat_pct, 0)}% of ${c.n} years, t ${num(c.t, 1)}` : undefined}>{v == null ? '—' : pct(v, { dp: 1 })}</td>)
                })}
              </tr>))}
          </tbody>
        </table>
      </div>
    </Card>
  )
}

export default function Seasonality() {
  const [params, setParams] = useSearchParams()
  const period = params.get('period')
  const q = useSeasonal(period)
  const d = q.data
  const [kind, setKind] = useState<'month' | 'season'>(() => (period && !/^\d+$/.test(period) ? 'season' : 'month'))
  const [all, setAll] = useState(false)
  const pick = (k: string) => setParams((p) => { p.set('period', k); return p }, { replace: true })
  const columns = useMemo(() => (d ? cols(d) : []), [d])
  const bull = useMemo(() => (d?.rows ?? []).filter((r) => r.side === 'bullish' && (all || r.strength !== 'noise')).sort((a, b) => (b.t ?? 0) - (a.t ?? 0)), [d, all])
  const bear = useMemo(() => (d?.rows ?? []).filter((r) => r.side === 'bearish' && (all || r.strength !== 'noise')).sort((a, b) => (a.t ?? 0) - (b.t ?? 0)), [d, all])
  const switchKind = (k: 'month' | 'season') => { setKind(k); if (d) pick(k === 'month' ? d.current.month : d.current.season) }
  return (
    <div className="space-y-3">
      <PageHeader title={<span className="flex items-center gap-2"><CalendarRange className="h-5 w-5 text-muted" />Seasonality</span>}
        subtitle={d ? `Which stocks and sectors have tended to rise or fall in each month and season, against the NIFTY 500 (${d.first_year}–${d.last_year}, to ${d.as_of})` : 'Which stocks and sectors have tended to rise or fall in each month and season'} />
      <div className="flex flex-wrap items-center gap-2">
        <Segmented<'month' | 'season'> ariaLabel="Months or seasons" size="sm" value={kind} onChange={switchKind} items={[{ id: 'month', label: 'Months' }, { id: 'season', label: 'Seasons' }]} />
        <div className="flex flex-wrap gap-1" role="radiogroup" aria-label={kind === 'month' ? 'Month' : 'Season'}>
          {(d?.periods ?? []).filter((p) => p.kind === kind).map((p) => {
            const on = (d?.period.key ?? '') === p.key
            const now = d && (p.key === d.current.month || p.key === d.current.season)
            return (
              <button key={p.key} type="button" role="radio" aria-checked={on} onClick={() => pick(p.key)} title={p.name}
                className={cn('relative h-7 rounded-md border px-2.5 text-xs', on ? 'border-accent bg-accent/10 font-semibold text-fg' : 'border-line text-muted hover:text-fg')}>
                {kind === 'month' ? p.short : p.name}
                {now && <span className="absolute -right-1 -top-1 h-2 w-2 rounded-full bg-info" title="Now" />}
              </button>)
          })}
        </div>
      </div>
      {q.error && !d ? <ErrorState error={q.error} onRetry={() => void q.refetch()} />
        : !d ? <div className="card"><SkeletonRows rows={8} /></div>
        : <>
          {d.period.kind === 'season' && <p className="text-xs text-muted"><b className="text-fg">{d.period.name}</b> ({d.period.months.map((m) => d.periods[m - 1]?.short).join(', ')}): {d.period.why}.</p>}
          <Summary d={d} />
          <div className="grid gap-3">
            <Card title={<span className="text-profit">Tended to rise in {d.period.name}</span>} subtitle={`${bull.length} stocks${all ? '' : ' with a consistent or lean record'}, steadiest first`} flush
              right={<label className="flex items-center gap-1.5 text-xs text-muted"><input type="checkbox" checked={all} onChange={(e) => setAll(e.target.checked)} />Show noise too</label>}>
              <DataTable id="seasonal.bull" data={bull} columns={columns} rowKey={(r) => r.symbol} exportName={`seasonal-${d.period.key}-rising`} pageSize={25} filterable filterPlaceholder="Find a stock" />
            </Card>
            <Card title={<span className="text-loss">Tended to fall in {d.period.name}</span>} subtitle={`${bear.length} stocks${all ? '' : ' with a consistent or lean record'}, steadiest first`} flush>
              <DataTable id="seasonal.bear" data={bear} columns={columns} rowKey={(r) => r.symbol} exportName={`seasonal-${d.period.key}-falling`} pageSize={25} filterable filterPlaceholder="Find a stock" />
            </Card>
          </div>
          <SectorGrid d={d} kind={d.period.kind} onPick={pick} />
          <Banner tone="info" icon={<Info className="h-4 w-4 text-info" />}><span className="text-muted">{d.note} Stocks need {d.counts.min_years}+ years of the period to be listed. Research, not advice: you decide.</span></Banner>
        </>}
    </div>
  )
}
