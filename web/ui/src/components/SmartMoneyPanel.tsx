// Smart-money pieces shared by the Smart money page and the Chart side panel (docs/smart_money_spec.md 7.2): the
// investor-type badge, the exit chip and the per-stock "Big investors" panel. Disclosed NSE data only: every row keeps
// the name as filed next to our label, and nothing here is a buy or sell signal.

import { Link } from 'react-router-dom'
import { AlertTriangle } from 'lucide-react'
import {
  CATEGORY_LABEL, LIKELY_PROMOTER, ODI_LABEL, fmtInr, useSmStock, type SmCategory, type SmExitKind, type SmHoldingPeriod, type SmStockResponse,
} from '@/api/smartMoney'
import { SidePill, WarnChip } from '@/components/badges'
import { Help, MoreLink } from '@/components/domain'
import { ErrorState, Skeleton } from '@/components/feedback'
import { Pts } from '@/components/num'
import { cn } from '@/lib/csv'
import { date, monthYear, num, ok } from '@/lib/format'
import { TONE_TEXT, TONE_TINT, type ToneName } from '@/lib/vocab'

// same shape as badges.tsx's pill
const pill = 'inline-flex h-5 shrink-0 items-center gap-1 whitespace-nowrap rounded-full px-2 text-2xs font-medium leading-none'

const CATEGORY_TONE: Record<SmCategory, ToneName> = {
  fii: 'info', mf: 'info', insurance: 'info', bank: 'info', pension: 'info', promoter: 'warn', famous: 'accent', broker: 'faint', other: 'muted',
}

/** Investor type: "Mutual fund", "FII/FPI", ...; for 'other' the sub-label ("Individual", "Company insider ...") when
 *  there is one. A label from name rules only - the filed name is always shown beside it. */
export function CategoryBadge({ category, subLabel, className }: { category: SmCategory; subLabel?: string | null; className?: string }) {
  const label = CATEGORY_LABEL[category] ?? 'Other'
  const tone = CATEGORY_TONE[category] ?? 'muted'
  const text = category === 'other' && subLabel ? subLabel : subLabel === LIKELY_PROMOTER ? 'Likely promoter' : label
  return (
    <span title={subLabel ? `${label}: ${subLabel}` : label} className={cn(pill, TONE_TINT[tone], TONE_TEXT[tone], className)}>
      {subLabel === ODI_LABEL && <AlertTriangle className="h-3 w-3" aria-label="Weak signal" />}
      {text}
    </span>
  )
}

const EXIT: Record<SmExitKind, { label: string; tone: ToneName; title: string }> = {
  full_exit: { label: 'Fully exited', tone: 'loss', title: 'Holding after the sale is zero: a certain full exit' },
  below_1pct: { label: 'Now below 1%', tone: 'warn', title: 'No longer in the list of 1%+ holders: sold some or all - the filing cannot tell which' },
  sold_part: { label: 'Sold part', tone: 'muted', title: 'Sold some shares; the disclosure does not show a full exit' },
  category_exit: { label: 'Category sold out', tone: 'loss', title: 'This whole group (e.g. all FIIs together) held shares last quarter and holds none now' },
}

/** What a selling event can prove: a certain full exit, "no longer a 1%+ holder", or a part sale. */
export function ExitChip({ kind }: { kind: SmExitKind | null }) {
  if (!kind) return null
  const m = EXIT[kind]
  if (!m) return null
  return <span title={m.title} className={cn(pill, TONE_TINT[m.tone], TONE_TEXT[m.tone])}>{m.label}</span>
}

const HOLDING_FIELDS: { key: 'promoter_pct' | 'fii_pct' | 'dii_pct' | 'mf_pct'; label: string }[] = [
  { key: 'promoter_pct', label: 'Promoter' },
  { key: 'fii_pct', label: 'FII/FPI' },
  { key: 'dii_pct', label: 'DII' },
  { key: 'mf_pct', label: 'Mutual funds' },
]

const windowText = (days: number) => (days === 365 ? 'the last 12 months' : `the last ${days} days`)

function Heading({ children }: { children: string }) {
  return <div className="mb-1.5 text-xs font-medium text-fg">{children}</div>
}

function Shareholding({ h0, h1 }: { h0: SmHoldingPeriod; h1: SmHoldingPeriod | null }) {
  return (
    <section>
      <Heading>Shareholding</Heading>
      <div className="grid grid-cols-4 gap-2">
        {HOLDING_FIELDS.map((f) => {
          const now = h0[f.key]
          const before = h1 ? h1[f.key] : null
          return (
            <div key={f.key} className="min-w-0">
              <div className="truncate text-2xs text-muted" title={f.label}>{f.label}</div>
              <div className="num text-[13px] font-medium text-fg">{ok(now) ? `${num(now, 2)}%` : '—'}</div>
              <div className="text-2xs" title={h1 ? `Change vs the quarter to ${monthYear(h1.period)}, percentage points` : 'No earlier quarter to compare'}>
                <Pts v={ok(now) && ok(before) ? now - before : null} suffix=" pts" />
              </div>
            </div>
          )
        })}
      </div>
      <div className="mt-1 text-2xs text-faint">
        Quarter to {monthYear(h0.period)}{h1 ? ` vs ${monthYear(h1.period)}` : ''}
        {h0.source === 'master' && ' · only the promoter/public split is filed so far'}
      </div>
    </section>
  )
}

function PanelBody({ d, days }: { d: SmStockResponse; days: number }) {
  const h0 = d.holdings.length > 0 ? d.holdings[0] : null
  const h1 = d.holdings.length > 1 ? d.holdings[1] : null
  const deals = d.deals.filter((x) => !x.round_trip)
  const intraday = d.deals.length - deals.length
  const insider = d.insider.filter((x) => x.is_market || x.mode_kind === 'pledge_invoked')
  const exits = d.events.filter((e) => e.direction === 'down' && e.exit_kind !== null)
  return (
    <>
      {h0 && <Shareholding h0={h0} h1={h1} />}

      <section>
        <Heading>Recent big deals</Heading>
        {deals.length === 0 ? <div className="text-xs text-muted">No bulk or block deals in {windowText(days)}.</div> : (
          <ul className="space-y-2">
            {deals.slice(0, 5).map((x) => (
              <li key={x.id} className="flex items-start gap-2 text-[13px]">
                <span className="num w-12 shrink-0 pt-0.5 text-xs text-muted">{date(x.date, { year: false })}</span>
                {x.side === 'FLAT' ? <span className="tint-muted inline-flex h-5 w-11 shrink-0 items-center justify-center rounded text-2xs font-bold tracking-[0.04em] text-muted">FLAT</span> : <SidePill side={x.side} />}
                <span className="min-w-0 flex-1">
                  <span className="block truncate" title={x.client}>{x.investor ?? x.client}</span>
                  <span className="mt-0.5 flex min-w-0 items-center gap-1.5">
                    <CategoryBadge category={x.category} subLabel={x.sub_label} />
                    {x.investor && <span className="min-w-0 truncate text-2xs text-muted" title={x.client}>{x.client}</span>}
                  </span>
                </span>
                <span className="num shrink-0 pt-0.5 text-xs">{fmtInr(Math.abs(x.net_value))}</span>
              </li>
            ))}
          </ul>
        )}
        {intraday > 0 && <div className="mt-1.5 text-2xs text-faint">{intraday} intraday trade{intraday === 1 ? '' : 's'} by trading firms not shown</div>}
      </section>

      <section>
        <Heading>Insider trades</Heading>
        {insider.length === 0 ? <div className="text-xs text-muted">No open-market promoter or insider trades disclosed in {windowText(days)}.</div> : (
          <ul className="space-y-2">
            {insider.slice(0, 5).map((x) => (
              <li key={x.id} className="flex items-start gap-2 text-[13px]">
                <span className="num w-12 shrink-0 pt-0.5 text-xs text-muted" title="Disclosed to NSE">{date(x.disclosed, { year: false })}</span>
                {x.side ? <SidePill side={x.side} /> : <span className="inline-flex h-5 w-11 shrink-0 items-center justify-center text-faint">—</span>}
                <span className="min-w-0 flex-1">
                  <span className="block truncate" title={x.person}>{x.investor ?? x.person}</span>
                  <span className="mt-0.5 flex flex-wrap items-center gap-1">
                    <span className="text-2xs text-muted">{x.investor ? `${x.person} · ` : ''}{x.person_category ?? x.mode ?? '—'}</span>
                    {x.fully_exited && <ExitChip kind="full_exit" />}
                    {x.mode_kind === 'pledge_invoked' && <WarnChip title="A lender sold pledged shares: a forced sale">Pledge sold</WarnChip>}
                  </span>
                </span>
                <span className="num shrink-0 pt-0.5 text-xs">{fmtInr(x.value)}</span>
              </li>
            ))}
          </ul>
        )}
      </section>

      {exits.length > 0 && (
        <section>
          <Heading>Exits / selling</Heading>
          <ul className="space-y-2">
            {exits.slice(0, 3).map((e) => (
              <li key={e.id} className="flex items-start gap-2 text-xs">
                <span className="num w-12 shrink-0 text-muted">{date(e.date, { year: false })}</span>
                <span className="min-w-0 flex-1 leading-snug text-fg" title={e.investor && e.who ? `Filed as ${e.who}` : undefined}>{e.text}</span>
                <ExitChip kind={e.exit_kind} />
              </li>
            ))}
          </ul>
        </section>
      )}
    </>
  )
}

/** "Big investors" block for the Chart side panel (it sits inside a padded section). */
export function SmartMoneyPanel({ symbol, days = 365 }: { symbol: string; days?: number }) {
  const q = useSmStock(symbol, days)
  const d = q.data
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center">
          <div className="eyebrow">Big investors</div>
          <Help text="NSE bulk/block deals, insider filings and the quarterly shareholding pattern. Disclosed data - not live and not a buy/sell signal." />
        </div>
        <MoreLink to={`/smart-money/today?symbol=${encodeURIComponent(symbol)}`}>Details</MoreLink>
      </div>
      {q.error ? <ErrorState error={q.error} onRetry={() => void q.refetch()} compact /> : !d ? (
        <div className="space-y-2" aria-busy="true"><Skeleton className="h-3 w-full" /><Skeleton className="h-3 w-5/6" /><Skeleton className="h-3 w-2/3" /></div>
      ) : !d.has_data ? (
        <div className="text-xs text-muted">
          No bulk/block deals, insider trades or shareholding data for {symbol} yet.
          {d.freshness.refreshed_at == null && <> Refresh on the <Link to="/smart-money" className="link">Smart money page</Link>.</>}
        </div>
      ) : (
        <PanelBody d={d} days={days} />
      )}
      <div className="text-2xs text-faint">Disclosed data, often days or weeks old. Big investors also lose money.</div>
    </div>
  )
}
