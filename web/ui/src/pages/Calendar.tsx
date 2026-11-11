// Market calendar `/calendar`: results dates, ex-dividend / rights / bonus / split / buyback dates, F&O expiries and
// market holidays from NSE, nearest first, your holdings and watchlist stocks first (web/api/services/calendar_svc.py).

import { useMemo } from 'react'
import { Link } from 'react-router-dom'
import { CalendarDays } from 'lucide-react'
import { useCalendar, type CalEvent, type CalKind } from '@/api/desk'
import { PageHeader } from '@/components/domain'
import { Banner, EmptyState, ErrorState, SkeletonRows } from '@/components/feedback'
import { Card, Segmented } from '@/components/ui'
import { date as fmtDate, money, todayIST } from '@/lib/format'
import { useLocalStorage } from '@/lib/useLocalStorage'
import { cn } from '@/lib/csv'

type Scope = 'mine' | 'all'
const KIND: Record<CalKind, { label: string; cls: string; help: string }> = {
  results: { label: 'Results', cls: 'bg-accent/15 text-accent', help: 'Quarterly results: a bigger move than usual, and a stop can gap overnight.' },
  dividend: { label: 'Ex-dividend', cls: 'bg-profit/15 text-profit', help: 'Own the shares at the close of the "buy by" day to get the dividend. The price drops by about the dividend on the ex-date.' },
  rights: { label: 'Rights', cls: 'bg-warn/15 text-warn', help: 'Rights issue: holders on the record date may buy new shares at the issue price.' },
  bonus: { label: 'Bonus', cls: 'bg-warn/15 text-warn', help: 'Bonus shares: more shares, a lower price, the same value.' },
  split: { label: 'Split', cls: 'bg-warn/15 text-warn', help: 'Stock split: more shares, a lower price, the same value.' },
  buyback: { label: 'Buyback', cls: 'bg-warn/15 text-warn', help: 'Buyback record date: holders may tender shares to the company.' },
  expiry: { label: 'F&O expiry', cls: 'bg-raised text-fg', help: 'Options and futures expire at 15:30. Expiry days can be volatile near big open-interest strikes.' },
  holiday: { label: 'Holiday', cls: 'bg-loss/15 text-loss', help: 'NSE closed.' },
  meeting: { label: 'Board meeting', cls: 'bg-raised text-muted', help: 'Board meeting (fund raising, bonus, other business).' },
}
const FILTERS: { id: 'all' | CalKind; label: string }[] = [
  { id: 'all', label: 'All' }, { id: 'results', label: 'Results' }, { id: 'dividend', label: 'Dividends' }, { id: 'expiry', label: 'Expiries' },
]

function dayLabel(d: string, today: string): string {
  const t = new Date(`${today}T00:00:00Z`).getTime()
  const x = new Date(`${d}T00:00:00Z`)
  const n = Math.round((x.getTime() - t) / 86_400_000)
  const wd = x.toLocaleDateString('en-IN', { weekday: 'long', timeZone: 'UTC' })
  return n === 0 ? `Today · ${wd}` : n === 1 ? `Tomorrow · ${wd}` : `${wd} · in ${n} days`
}

function Row({ e }: { e: CalEvent }) {
  const k = KIND[e.kind]
  return (
    <li className={cn('flex flex-wrap items-baseline gap-x-3 gap-y-1 px-4 py-2', (e.mine || e.watch) && 'bg-accent/5')}>
      <span className={cn('w-[104px] shrink-0 rounded px-1.5 py-0.5 text-center text-2xs font-semibold', k.cls)} title={k.help}>{k.label}{e.kind === 'expiry' && e.monthly ? ' · monthly' : ''}</span>
      {e.symbol ? (
        <Link to={`/chart/${e.symbol}`} className="w-[110px] shrink-0 font-semibold text-fg hover:text-accent">{e.symbol}</Link>
      ) : null}
      <span className="min-w-0 flex-1 text-[13px] text-fg">
        {e.company && <span className="text-muted">{e.company} · </span>}{e.detail}
        {e.kind === 'dividend' && e.amount != null && (
          <span className="ml-2 text-profit">{money(e.amount, { dp: 2 })} a share{e.yield_pct != null && ` (${e.yield_pct.toFixed(2)}% of the price)`}</span>
        )}
      </span>
      <span className="flex shrink-0 items-center gap-2 text-2xs">
        {e.buy_by && e.kind !== 'buyback' && <span className="text-muted" title="T+1 settlement: own the shares at this day's close">buy by {fmtDate(e.buy_by)}</span>}
        {e.mine && <span className="rounded bg-accent/20 px-1.5 py-0.5 font-semibold text-accent">You hold</span>}
        {e.watch && <span className="rounded bg-raised px-1.5 py-0.5 text-muted">Watchlist</span>}
      </span>
    </li>
  )
}

export default function Calendar() {
  const [days, setDays] = useLocalStorage<'14' | '30' | '60' | '90'>('qd.calendar.days', '30')
  const [scope, setScope] = useLocalStorage<Scope>('qd.calendar.scope', 'all')
  const [kind, setKind] = useLocalStorage<'all' | CalKind>('qd.calendar.kind', 'all')
  const q = useCalendar(Number(days))
  const today = todayIST()
  const groups = useMemo(() => {
    const ev = (q.data?.events ?? []).filter((e) =>
      (scope === 'all' || e.mine || e.watch || e.symbol == null) && (kind === 'all' || e.kind === kind || (kind === 'dividend' && ['rights', 'bonus', 'split', 'buyback'].includes(e.kind))))
    const by = new Map<string, CalEvent[]>()
    for (const e of ev) by.set(e.date, [...(by.get(e.date) ?? []), e])
    return [...by.entries()]
  }, [q.data, scope, kind])
  const d = q.data
  return (
    <div>
      <PageHeader title="Market calendar"
        subtitle={d ? `${fmtDate(d.from)} – ${fmtDate(d.to)} · ${d.counts.results} results · ${d.counts.dividend} ex-dividends · ${d.counts.expiry} expiries · ${d.counts.holiday} holiday${d.counts.holiday === 1 ? '' : 's'}${d.mine ? ` · ${d.mine} for stocks you hold` : ''}` : 'Results, dividends, expiries and holidays from NSE'}
        right={<>
          <Segmented<'all' | CalKind> ariaLabel="Event type" value={kind} onChange={setKind} items={FILTERS} />
          <Segmented<Scope> ariaLabel="Stocks" value={scope} onChange={setScope} items={[{ id: 'all', label: 'All stocks' }, { id: 'mine', label: 'Holdings + watchlist' }]} />
          <Segmented<'14' | '30' | '60' | '90'> ariaLabel="Days ahead" value={days} onChange={setDays} items={[{ id: '14', label: '2W' }, { id: '30', label: '1M' }, { id: '60', label: '2M' }, { id: '90', label: '3M' }]} />
        </>} />
      {d?.notes.map((n) => <div key={n} className="mb-3"><Banner tone="warn">{n}</Banner></div>)}
      {q.error ? <ErrorState error={q.error} onRetry={() => q.refetch()} /> : !d ? <Card><SkeletonRows rows={10} cols={4} /></Card> : groups.length === 0 ? (
        <EmptyState icon={<CalendarDays />} title="Nothing in this window">{scope === 'mine' ? 'None of your holdings or watchlist stocks has an event in this window.' : 'Try a longer window.'}</EmptyState>
      ) : (
        <div className="flex flex-col gap-3">
          {groups.map(([day, ev]) => (
            <Card key={day} flush title={`${fmtDate(day, { year: false })} · ${dayLabel(day, today)}`}
              subtitle={ev.some((e) => e.kind === 'holiday') ? 'Market closed' : `${ev.length} event${ev.length === 1 ? '' : 's'}`}>
              <ul className="divide-y divide-line">{ev.map((e, i) => <Row key={`${e.kind}-${e.symbol}-${i}`} e={e} />)}</ul>
            </Card>
          ))}
        </div>
      )}
      <p className="mt-4 text-2xs text-faint">From NSE's event calendar, corporate actions, F&O contract list and holiday list (cached; refreshed every few hours). Results dates are board-meeting dates the companies announced; they can change. With T+1 settlement the record date is the ex-date: buy by the trading day before it.</p>
    </div>
  )
}
