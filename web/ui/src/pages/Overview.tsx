// Overview `/` (spec 3.1): regime, index tiles, breadth, next-open orders by horizon, alerts, strategy pulse,
// since-last-scan, movers, relevant results, paper strip.

import { useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { AlertOctagon, AlertTriangle, ArrowRight, CheckCircle2, ChevronDown, Info, Minus, TrendingDown, TrendingUp } from 'lucide-react'
import { useBreadth, useOverview, usePaper, useStrategies } from '@/api/hooks'
import type { Alert, Change, Horizon, IndexTile, Mover, OverviewResponse, ResultsEvent, StrategySummary } from '@/api/types'
import { EvidenceChip, HorizonChip, StatusDot, TonePill, WarnChip } from '@/components/badges'
import { LinesChart, type LineDef } from '@/components/charts/LinesChart'
import { AdBar, Sparkline } from '@/components/charts/svg'
import { AsOfLine, BiasNote, MoreLink, OrdersTable, PageHeader, ResultsWhy, flatteredNote } from '@/components/domain'
import { Banner, EmptyState, ErrorState, RefreshFailed, Skeleton, SkeletonChart, SkeletonRows } from '@/components/feedback'
import { verdictLabel } from '@/components/PaperDetail'
import { Pct, Price, Pts } from '@/components/num'
import { Card, Chip, Tabs } from '@/components/ui'
import { cn } from '@/lib/csv'
import { date, daysUntil, keepDatesTogether, money, num, pct } from '@/lib/format'
import { groupChanges, groupResultsAlerts } from '@/lib/overview'
import { useIsMobile } from '@/lib/useMedia'
import { lostMoney } from '@/lib/vocab'

function RegimeCard({ o }: { o: OverviewResponse }) {
  const m = o.market
  const Icon = m.label === 'Bullish' ? TrendingUp : m.label === 'Bearish' ? TrendingDown : Minus
  const tone = m.label === 'Bullish' ? 'text-profit' : m.label === 'Bearish' ? 'text-loss' : 'text-warn'
  return (
    // Beside the breadth chart (xl) both cards are about as tall, so the facts follow the advice directly: no spacer
    // pushing them to the bottom (it left an empty block in the middle of the card).
    <Card title="Market regime" subtitle="Nifty 50 vs its 200-day average, and breadth" className="h-full">
      <div className="flex items-center gap-3">
        <span className={cn('grid h-11 w-11 place-items-center rounded-lg', m.label === 'Bullish' ? 'tint-profit' : m.label === 'Bearish' ? 'tint-loss' : 'tint-warn')}>
          <Icon className={cn('h-6 w-6', tone)} strokeWidth={2.25} />
        </span>
        <div>
          <div className={cn('text-[22px] font-bold uppercase leading-7 tracking-[0.04em]', tone)}>{m.label}</div>
          <div className="num text-xs text-muted">
            Nifty {m.nifty_vs_sma200_pct != null ? <span className={m.nifty_vs_sma200_pct < 0 ? 'text-loss' : 'text-profit'}>{pct(Math.abs(m.nifty_vs_sma200_pct), { signed: false })} {m.nifty_vs_sma200_pct < 0 ? 'below' : 'above'}</span> : '—'} its 200-DMA
            {m.nifty_sma200 != null && <span className="text-faint"> ({num(m.nifty_sma200)})</span>}
          </div>
        </div>
        {m.high_vix && <Chip className="tint-warn ml-auto text-warn" icon={<AlertTriangle className="h-3 w-3" />}>High volatility</Chip>}
      </div>
      <p className="mt-3 text-[13px] leading-5 text-muted">{m.advice}</p>
      {/* full-width card (below xl): the three facts sit side by side instead of stretching across the page */}
      <div className="mt-4 grid gap-3 border-t border-line pt-3 sm:grid-cols-3 sm:gap-8 xl:grid-cols-1 xl:gap-3">
        <div className="flex items-baseline justify-between text-xs">
          <span className="text-muted">Stocks above 50-DMA</span>
          <span className="num text-[15px] font-semibold text-fg">{pct(m.breadth_50, { signed: false })}</span>
        </div>
        <div>
          <div className="mb-1.5 flex items-baseline justify-between text-xs">
            <span className="text-muted">Advance / decline today</span>
            <span className="num"><span className="text-profit">{m.advances}</span><span className="text-faint"> : </span><span className="text-loss">{m.declines}</span></span>
          </div>
          <AdBar advances={m.advances} declines={m.declines} />
        </div>
        <div className="flex items-baseline justify-between text-xs">
          <span className="text-muted">India VIX</span>
          <span className="num"><span className="text-fg">{num(m.vix)}</span> <Pct v={m.vix_change_pct} dp={2} /></span>
        </div>
      </div>
    </Card>
  )
}

/** Index tile. Nothing in it has a fixed width it can't give up: the number keeps its size, the sparkline shrinks
 *  (max 72 px) and is hidden when the tile is too narrow (qd-tile container query), the name wraps to two lines. */
function Tile({ t }: { t: IndexTile }) {
  const isVix = t.name === 'India VIX'
  return (
    <Link to={t.href} title={t.name} className="qd-tile focus-ring card group relative flex min-w-0 snap-start flex-col justify-between overflow-hidden p-3 transition-colors hover:border-line-strong max-md:w-[176px] max-md:shrink-0">
      {/* the hover arrow floats over the corner, so the whole width is left for the name (one line at 184 px) */}
      <span className="line-clamp-2 min-w-0 break-words text-2xs font-semibold uppercase tracking-[0.04em] text-muted">{t.name}</span>
      <ArrowRight className="absolute right-2 top-2.5 h-3.5 w-3.5 rounded-sm bg-panel text-faint opacity-0 transition-opacity group-hover:opacity-100" />
      <div className="mt-1.5 flex items-end justify-between gap-2">
        <div className="shrink-0">
          <div className="num text-[17px] font-semibold leading-6 text-fg">{num(t.last)}</div>
          <Pct v={t.chg_1d_pct} dp={2} className={isVix ? 'text-muted' : undefined} color={!isVix} />
        </div>
        <Sparkline values={t.spark} width={72} height={30} fluid tone={isVix ? 'muted' : 'auto'} className="qd-tile-spark mb-0.5 min-w-0 max-w-[72px] flex-1" />
      </div>
      <div className="mt-1 text-2xs text-faint">3 months</div>
    </Link>
  )
}

function BreadthCard() {
  const q = useBreadth('1y')
  const lines: LineDef[] | null = useMemo(() => {
    const b = q.data
    if (!b) return null
    return [
      { id: 'b', label: '% above 50-DMA', v: b.breadth_50, color: 'accent', width: 2, format: (v) => `${num(v, 0)}%`, refLines: [{ price: 50 }] },
      { id: 'n', label: 'Nifty 50', v: b.nifty, color: 'muted', scale: 'left', format: (v) => num(v, 0) },
      { id: 's', label: '200-DMA', v: b.nifty_sma200, color: 'violet', scale: 'left', style: 'dashed', format: (v) => num(v, 0) },
    ]
  }, [q.data])
  return (
    <Card title={<>Breadth · % of stocks above their <span className="whitespace-nowrap">50-DMA</span></>} subtitle="1 year; Nifty 50 and its 200-DMA on the left scale" right={<MoreLink to="/market/breadth">Breadth</MoreLink>} flush className="h-full">
      {q.error ? <ErrorState error={q.error} onRetry={() => void q.refetch()} compact /> : !q.data || !lines ? <SkeletonChart height={220} /> : <LinesChart t={q.data.t} lines={lines} height={220} />}
    </Card>
  )
}

function OrdersCard({ o }: { o: OverviewResponse }) {
  const [h, setH] = useState<'all' | Horizon>('all')
  const [showCmp, setShowCmp] = useState(false)
  const active = o.orders.filter((x) => !x.comparison_only)
  const cmp = o.orders.filter((x) => x.comparison_only)
  const count = (hz: Horizon) => active.filter((x) => x.horizon === hz).length
  const shown = h === 'all' ? active : active.filter((x) => x.horizon === h)
  const cmpShown = h === 'all' ? cmp : cmp.filter((x) => x.horizon === h)
  const emptyLines = (h === 'all' ? (['longterm', 'swing'] as Horizon[]) : [h]).filter((hz) => count(hz) === 0 && o.empty_reasons[hz])
  return (
    <Card
      title="Next-open orders"
      subtitle={<>Model orders for the next market open, sized for {money(o.as_of.capital)} · <AsOfLine a={o.as_of} /></>}
      right={<MoreLink to="/signals">All signals</MoreLink>}
      flush
    >
      <div className="border-b border-line px-3">
        <Tabs<'all' | Horizon>
          size="sm"
          value={h}
          onChange={setH}
          items={[
            { id: 'all', label: 'All', count: active.length },
            { id: 'longterm', label: 'Long-term', count: count('longterm') },
            { id: 'swing', label: 'Swing', count: count('swing') },
            { id: 'intraday', label: 'Intraday', count: '—' },
          ]}
        />
      </div>
      {shown.length > 0 && <OrdersTable id="overview" orders={shown} showStrategy compact />}
      {(shown.length === 0 || emptyLines.length > 0) && (
        <ul className="divide-y divide-line">
          {emptyLines.map((hz) => (
            <li key={hz} className="flex items-start gap-2 px-4 py-2.5 text-[13px]">
              <HorizonChip horizon={hz} />
              <span className="text-muted">No orders. {keepDatesTogether(o.empty_reasons[hz] ?? '')}</span>
            </li>
          ))}
          {shown.length === 0 && emptyLines.length === 0 && <li className="px-4 py-3 text-[13px] text-muted">No orders for the next open.</li>}
        </ul>
      )}
      {cmpShown.length > 0 && (
        <div className="border-t border-line">
          <button type="button" onClick={() => setShowCmp(!showCmp)} className="focus-ring flex w-full items-center gap-2 px-4 py-2 text-left text-xs text-muted hover:text-fg">
            <ChevronDown className={cn('h-3.5 w-3.5 transition-transform', !showCmp && '-rotate-90')} />
            {cmpShown.length} order{cmpShown.length > 1 ? 's' : ''} from strategies that are not working (comparison only)
          </button>
          {showCmp && <OrdersTable id="overview-cmp" orders={cmpShown} showStrategy compact />}
        </div>
      )}
    </Card>
  )
}

const SEV: Record<Alert['severity'], { icon: typeof Info; cls: string; label: string }> = {
  danger: { icon: AlertOctagon, cls: 'text-loss', label: 'Danger' },
  warn: { icon: AlertTriangle, cls: 'text-warn', label: 'Warning' },
  info: { icon: Info, cls: 'text-info', label: 'Info' },
  good: { icon: CheckCircle2, cls: 'text-profit', label: 'Good' },
}

const ALERTS_SHOWN = 5

function AlertsCard({ alerts: raw }: { alerts: Alert[] }) {
  const [all, setAll] = useState(false)
  const alerts = useMemo(() => groupResultsAlerts(raw), [raw])
  const shown = all ? alerts : alerts.slice(0, ALERTS_SHOWN)
  return (
    <Card title={<>Alerts <span className="num ml-1 text-muted">{alerts.length}</span></>} flush>
      {alerts.length === 0 ? (
        <div className="flex items-center gap-2.5 px-4 py-2.5 text-[13px] text-muted">
          <CheckCircle2 className="h-4 w-4 shrink-0 text-profit" />Nothing needs attention: no holding, order, data or login issues.
        </div>
      ) : (
        <ul className="divide-y divide-line">
          {shown.map((a) => {
            const s = SEV[a.severity]
            const Icon = s.icon
            const body = (
              <div className="flex items-start gap-2.5 px-4 py-2.5">
                <Icon className={cn('mt-0.5 h-4 w-4 shrink-0', s.cls)} aria-label={s.label} />
                <div className="min-w-0 flex-1">
                  <div className="text-[13px] text-fg">{a.title}</div>
                  {a.detail && <div className="mt-0.5 line-clamp-3 text-xs text-muted">{a.detail}</div>}
                </div>
                {a.href && <ArrowRight className="mt-1 h-3.5 w-3.5 shrink-0 text-faint" />}
              </div>
            )
            return <li key={a.id}>{a.href ? <Link to={a.href} className="block hover:bg-raised/60">{body}</Link> : body}</li>
          })}
          {alerts.length > ALERTS_SHOWN && (
            <li><button type="button" onClick={() => setAll(!all)} className="w-full px-4 py-2 text-left text-xs font-medium text-accent hover:underline">{all ? 'Show fewer' : `Show all ${alerts.length}`}</button></li>
          )}
        </ul>
      )}
    </Card>
  )
}

function PulseCard({ items, pit }: { items: StrategySummary[]; pit: boolean }) {
  const nav = useNavigate()
  const all = useStrategies()
  const total = all.data?.strategies.length
  const mobile = useIsMobile()
  const edgeOf = (s: StrategySummary) => (s.edges.primary === 'ew' ? s.edges.vs_ew_cagr_pct : s.edges.vs_nifty_cagr_pct)
  return (
    <Card title="Strategy pulse" subtitle="Backtest CAGR · edge vs the average stock · last 12 months vs Nifty 500" right={<MoreLink to="/strategies">All {total ?? ''} strategies</MoreLink>} flush className="h-full">
      {mobile ? (
        // Phones (spec 3.12): list rows, name in full on line 1 and the three numbers on line 2. As a table the name
        // column was left ~90 px ("Momentum l…", "Turtle / Don…") and the last column still scrolled off.
        <ul className="divide-y divide-line/70">
          {items.map((s) => (
            <li key={s.key}>
              <Link to={`/strategies/${s.key}`} className={cn('flex flex-col gap-0.5 px-4 py-2 text-[13px] active:bg-raised', s.status === 'not-working' && 'opacity-60')}>
                <span className="flex min-w-0 items-center gap-2">
                  <StatusDot status={s.status} lost={lostMoney(s.headline)} />
                  <span className="min-w-0 flex-1 truncate font-medium" title={s.name}>{s.name}</span>
                  {flatteredNote(s) && <WarnChip title={flatteredNote(s) ?? undefined}>Flattered</WarnChip>}
                  <HorizonChip horizon={s.horizon} letter />
                </span>
                <span className="num flex flex-wrap gap-x-3 pl-[22px] text-xs text-muted">
                  <span>CAGR <span className="text-fg">{pct(s.headline.cagr_pct, { signed: false })}</span></span>
                  <span>Edge <Pts v={edgeOf(s)} />{s.edges.primary === 'nifty' && <span className="text-faint">*</span>}</span>
                  <span>12m vs N500 <Pts v={s.edges.r12m_vs_n500_pct} /></span>
                </span>
              </Link>
            </li>
          ))}
        </ul>
      ) : (
      <div className="scroll-x">
      <table className="w-full text-[13px]">
        <thead>
          <tr className="whitespace-nowrap text-2xs font-semibold uppercase tracking-[0.04em] text-muted">
            <th className="px-4 py-2 text-left font-semibold">Strategy</th>
            <th className="px-2 py-2 text-right font-semibold">CAGR</th>
            <th className="py-2 pl-2 pr-1 text-right font-semibold" title="CAGR minus the equal-weight average stock of the same backtest universe; ETFs vs Nifty 50">Edge<span className="inline-block w-2" /></th>
            <th className="px-4 py-2 text-right font-semibold" title="12-month return minus Nifty 500's">12m vs N500</th>
          </tr>
        </thead>
        <tbody>
          {items.map((s) => {
            const edge = edgeOf(s)
            return (
              <tr key={s.key} onClick={() => nav(`/strategies/${s.key}`)} className={cn('cursor-pointer border-t border-line/70 hover:bg-raised', s.status === 'not-working' && 'opacity-60')}>
                {/* the name column takes what the number columns leave (min 170 px) and truncates, never them */}
                <td className="w-full min-w-[170px] max-w-0 px-4 py-2">
                  <div className="flex min-w-0 items-center gap-2">
                    <StatusDot status={s.status} lost={lostMoney(s.headline)} />
                    <span className="truncate font-medium" title={s.name}>{s.name}</span>
                    {flatteredNote(s) && <WarnChip title={flatteredNote(s) ?? undefined}>Flattered</WarnChip>}
                    <HorizonChip horizon={s.horizon} letter />
                    {/* the evidence chip steps aside where the card is narrow (below lg, and the half-width card at
                        1280-1399), so the name is not cut ("Volatility contraction (VCP) brea…") */}
                    <EvidenceChip evidence={s.evidence} className="max-lg:hidden xl:max-[1399px]:hidden" />
                  </div>
                </td>
                <td className="num whitespace-nowrap px-2 py-2 text-right">{pct(s.headline.cagr_pct, { signed: false })}</td>
                {/* every row reserves the asterisk slot, so the digits stay right-aligned in one column */}
                <td className="num whitespace-nowrap py-2 pl-2 pr-1 text-right"><Pts v={edge} /><span className="inline-block w-2 text-left text-faint" title={s.edges.primary === 'nifty' ? 'vs Nifty 50 (ETF strategy)' : undefined}>{s.edges.primary === 'nifty' ? '*' : ''}</span></td>
                <td className="num whitespace-nowrap px-4 py-2 text-right"><Pts v={s.edges.r12m_vs_n500_pct} /></td>
              </tr>
            )
          })}
        </tbody>
      </table>
      </div>
      )}
      <div className="border-t border-line px-4 py-2 text-2xs text-faint">* ETF strategies are compared with Nifty 50. Backtest numbers{pit ? ' (point-in-time universe)' : ', before survivorship correction'}.</div>
    </Card>
  )
}

function MoverList({ title, rows, kind }: { title: string; rows: Mover[]; kind: 'up' | 'down' | 'vol' }) {
  return (
    <Card title={title} flush>
      <ul className="divide-y divide-line/70">
        {rows.map((m) => (
          <li key={m.symbol}>
            <Link to={`/chart/${m.symbol}`} className="flex items-center gap-2 px-4 py-1.5 text-[13px] hover:bg-raised">
              <span className="min-w-0 flex-1 truncate font-semibold">{m.symbol}</span>
              <Price v={m.price} className="text-muted" />
              <span className="w-16 text-right">{kind === 'vol' ? <span className="num text-fg">{num(m.vol_ratio, 1)}×</span> : <Pct v={m.change_pct} dp={2} />}</span>
            </Link>
          </li>
        ))}
        {rows.length === 0 && <li className="px-4 py-3 text-xs text-muted">None today.</li>}
      </ul>
    </Card>
  )
}

const RESULTS_SHOWN = 20
/** held 0, order 1, model holding or a strategy's top 5 (what the Alerts card warns about) 2, other ranked 3 */
const relTier = (e: ResultsEvent) =>
  e.relevance === 'held' ? 0 : e.relevance === 'order' ? 1 : e.relevance === 'model' || (e.strategy_rank != null && e.strategy_rank <= 5) ? 2 : 3

function ResultsCard({ events }: { events: ResultsEvent[] }) {
  // the most relevant first (held > order > model > ranked, then date), shown in date order
  const shown = useMemo(() => {
    return [...events].sort((a, b) => relTier(a) - relTier(b) || a.date.localeCompare(b.date)).slice(0, RESULTS_SHOWN)
      .sort((a, b) => a.date.localeCompare(b.date) || relTier(a) - relTier(b))
  }, [events])
  const more = events.length - shown.length
  return (
    <Card title="Results · next 7 days" subtitle="Held, ordered or top-ranked stocks" right={<MoreLink to="/market/results">Calendar</MoreLink>} flush className="h-full">
      {events.length === 0 ? (
        <EmptyState compact title="No relevant results this week" />
      ) : (
        <>
          <ul className="max-h-[260px] divide-y divide-line/70 overflow-auto">
            {shown.map((e) => (
              <li key={`${e.symbol}${e.date}`}>
                <Link to={`/chart/${e.symbol}`} title={e.company ?? undefined} className="flex flex-wrap items-center gap-x-2 gap-y-0.5 px-4 py-1.5 text-[13px] hover:bg-raised">
                  <span className={cn('num w-[52px] shrink-0 text-xs', e.days_until <= 1 ? 'font-semibold text-loss' : 'text-muted')}>{e.days_until <= 1 ? daysUntil(e.days_until) : date(e.date, { year: false })}</span>
                  <span className="min-w-[84px] flex-1 truncate font-semibold">{e.symbol}</span>
                  <span className="flex shrink-0 flex-wrap gap-1"><ResultsWhy e={e} /></span>
                </Link>
              </li>
            ))}
          </ul>
          {more > 0 && (
            <Link to="/market/results" className="flex items-center justify-between border-t border-line px-4 py-2 text-xs text-accent hover:underline">
              <span>+{more} more this week</span><ArrowRight className="h-3.5 w-3.5" />
            </Link>
          )}
        </>
      )}
    </Card>
  )
}

const CHANGES_SHOWN = 5
const SYMBOLS_SHOWN = 4

function ChangesCard({ c }: { c: OverviewResponse['changes'] }) {
  const [all, setAll] = useState(false)
  const lines = useMemo(() => groupChanges(c.items), [c.items])
  const shown = all ? lines : lines.slice(0, CHANGES_SHOWN)
  const dot = (k: Change['kind']) => (k === 'new_order' ? 'bg-warn' : k === 'regime' ? 'bg-info' : k === 'position_opened' ? 'bg-profit' : k === 'position_closed' ? 'bg-loss' : 'bg-muted')
  return (
    <Card title="Since last scan" subtitle={c.since_data_date ? `vs the scan of ${date(c.since_data_date)} prices` : 'vs the previous trading day'} flush className="h-full">
      {lines.length === 0 ? (
        <EmptyState compact title={c.since_data_date ? 'Nothing changed' : 'No earlier scan to compare'}>
          {c.since_data_date ? 'Same statuses, regime, orders and model holdings.' : 'The comparison starts after scans on two different trading days.'}
        </EmptyState>
      ) : (
        <ul className="divide-y divide-line/70">
          {shown.map((it, i) => (
            <li key={i} className="flex items-start gap-2 px-4 py-2 text-[13px]">
              <span className={cn('mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full', dot(it.kind))} />
              {'symbols' in it ? (
                <span className="min-w-0">
                  <Link className="hover:underline" to={`/strategies/${it.strategy_key}`}>{it.name}</Link>
                  {' '}{it.kind === 'position_opened' ? 'bought' : 'sold'}{it.symbols.length > 1 ? ` ${it.symbols.length}` : ''}:{' '}
                  {it.symbols.slice(0, SYMBOLS_SHOWN).map((s, k) => (
                    <span key={s}>{k > 0 && ', '}<Link className="font-medium hover:underline" to={`/chart/${s}`}>{s}</Link></span>
                  ))}
                  {it.symbols.length > SYMBOLS_SHOWN && <span className="text-muted"> +{it.symbols.length - SYMBOLS_SHOWN} more</span>}
                </span>
              ) : it.strategy_key ? (
                <Link className="hover:underline" to={it.symbol ? `/chart/${it.symbol}` : `/strategies/${it.strategy_key}`}>{it.text}</Link>
              ) : <span>{it.text}</span>}
            </li>
          ))}
          {lines.length > CHANGES_SHOWN && (
            <li><button type="button" onClick={() => setAll(!all)} className="w-full px-4 py-2 text-left text-xs font-medium text-accent hover:underline">{all ? 'Show fewer' : `Show all ${lines.length}`}</button></li>
          )}
        </ul>
      )}
    </Card>
  )
}

/** Paper portfolios, best first, two columns on wide screens. A verdict every row shares ("Too early to judge") is
 *  said once in the subtitle instead of 17 times, and a portfolio with nothing bought yet says "all cash" - that is
 *  why several show the same small return (the cash yield). */
function PaperStrip({ o }: { o: OverviewResponse }) {
  const minDays = usePaper().data?.min_days_to_judge ?? 21   // server config, same threshold as the Paper page
  const rows = useMemo(() => [...o.paper].sort((a, b) => (b.return_pct ?? -Infinity) - (a.return_pct ?? -Infinity)), [o.paper])
  if (!rows.length) return null
  const labels = rows.map((p) => verdictLabel(p, minDays))
  const same = labels.every((l) => l === labels[0])
  const days = Math.max(...rows.map((p) => p.days))
  const subtitle = same && labels[0] === 'Too early to judge'
    ? `Orders filled at the next official open with full charges · too early to judge: ${days} of the ${minDays} trading days a verdict needs`
    : 'Orders filled at the next official open with full charges'
  return (
    <Card title="Paper trading (live proof)" subtitle={subtitle} right={<MoreLink to="/paper">Paper</MoreLink>} flush>
      <ul className="grid divide-y divide-line/70 xl:grid-cols-2 xl:gap-x-6 xl:divide-y-0 xl:px-1">
        {rows.map((p, i) => (
          <li key={p.key} className={cn('xl:border-line/70', i >= 2 && 'xl:border-t')}>
            <Link to={`/paper/${p.key}`} className="flex items-center gap-3 px-4 py-2 text-[13px] hover:bg-raised xl:px-3">
              <span className="min-w-0 flex-1 truncate font-medium" title={p.name}>{p.name}</span>
              {p.open === 0 && p.pending === 0 && <span className="shrink-0 rounded border border-line px-1 text-2xs text-faint" title="No position open yet: the money waits in cash">all cash</span>}
              <span className="num w-[68px] shrink-0 text-right"><Pct v={p.return_pct} /></span>
              <span className="num w-[92px] shrink-0 text-right text-xs text-muted max-sm:hidden">N500 <Pct v={p.n500_pct} /></span>
              <span className="num w-[52px] shrink-0 text-right text-xs text-faint">{p.days} d</span>
              {!same && <TonePill tone={p.level}>{labels[i]}</TonePill>}
            </Link>
          </li>
        ))}
      </ul>
    </Card>
  )
}

export default function Overview() {
  const q = useOverview()
  if (q.error && !q.data) return <div className="card"><ErrorState error={q.error} onRetry={() => void q.refetch()} /></div>
  const o = q.data
  return (
    <div>
      <PageHeader title="Overview" subtitle={o ? <AsOfLine a={o.as_of} /> : <Skeleton className="h-3 w-48" />} />
      {q.error && o && <div className="mb-3"><RefreshFailed error={q.error} onRetry={() => void q.refetch()} /></div>}
      {o?.as_of.stale && (
        <div className="mb-3"><Banner tone="warn">Prices are from {date(o.as_of.data_date)}. Run a scan to update orders and alerts.</Banner></div>
      )}
      {!o ? (
        <div className="grid gap-3 xl:grid-cols-12">
          <Skeleton className="h-[300px] xl:col-span-5" />
          <Skeleton className="h-[300px] xl:col-span-7" />
          <div className="card xl:col-span-12"><SkeletonRows rows={4} /></div>
        </div>
      ) : (
        // 12-column split from xl only (spec 4.4); below xl every card is full width. Each row pairs cards of about
        // the same length and the cards of a row stretch to one height, so no row ends in a ragged edge or a card
        // that is mostly empty: index tiles | regime + breadth | alerts (full width: one alert stays one slim line)
        // | orders | strategy pulse + since last scan | results, gainers, losers | paper.
        <div className="grid grid-cols-1 gap-3 xl:grid-cols-12">
          <div className="qd-tiles min-w-0 xl:col-span-12">
            <div className="qd-tiles-grid scroll-x no-scrollbar grid snap-x grid-cols-2 gap-3 max-md:flex">
              {o.index_tiles.map((t) => <Tile key={t.name} t={t} />)}
            </div>
          </div>
          <div className="min-w-0 xl:col-span-4"><RegimeCard o={o} /></div>
          <div className="min-w-0 xl:col-span-8"><BreadthCard /></div>
          <div className="min-w-0 xl:col-span-12"><AlertsCard alerts={o.alerts} /></div>
          <div className="min-w-0 xl:col-span-12"><OrdersCard o={o} /></div>
          <div className="min-w-0 xl:col-span-7"><PulseCard items={o.strategy_pulse} pit={o.as_of.backtest_universe === 'point_in_time'} /></div>
          <div className="min-w-0 xl:col-span-5"><ChangesCard c={o.changes} /></div>
          <div className="grid min-w-0 grid-cols-1 gap-3 sm:grid-cols-2 xl:col-span-12 xl:grid-cols-3">
            <ResultsCard events={o.results_soon} />
            <MoverList title="Top gainers" rows={o.movers.gainers} kind="up" />
            <MoverList title="Top losers" rows={o.movers.losers} kind="down" />
          </div>
          <div className="min-w-0 xl:col-span-12"><PaperStrip o={o} /></div>
          <div className="min-w-0 xl:col-span-12"><BiasNote asOf={o.as_of} /></div>
        </div>
      )}
    </div>
  )
}
