// Smart money `/smart-money/:tab`: which stocks big investors are buying, selling or leaving, from NSE's bulk/block
// deals, insider (PIT) filings, quarterly shareholding and FII/DII flows. Disclosed data, shown with its delays; never
// a signal.

import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { ChevronDown, ChevronLeft, ChevronRight, Info, Landmark, RefreshCw, X } from 'lucide-react'
import { isFailure } from '@/api/client'
import {
  CATEGORY_FILTERS, fmtCr, fmtInr, smKeys, useSmDeals, useSmFlows, useSmHoldings, useSmInsider, useSmOverview, useSmRefresh, useSmStatus,
  type SmCategoryFilter, type SmDeal, type SmDealSide, type SmEvent, type SmFlowDay, type SmFreshness, type SmInsiderTrade, type SmRefreshRun,
  type SmSourceKind, type SmStock,
} from '@/api/smartMoney'
import { SidePill, WarnChip } from '@/components/badges'
import { DataTable, SymbolCell, type Col } from '@/components/DataTable'
import { KpiStrip, KpiTile, PageHeader } from '@/components/domain'
import { EmptyState, ErrorState, SkeletonKpis, SkeletonRows } from '@/components/feedback'
import { Price, Pts } from '@/components/num'
import { BigMoneyLive } from '@/components/BigMoneyLive'
import { CategoryBadge, ExitChip } from '@/components/SmartMoneyPanel'
import { useToast } from '@/components/toast'
import { Button, Card, Chip, IconButton, MenuItem, Popover, Segmented, SelectButton, Spinner, Switch, Tabs, Tip } from '@/components/ui'
import { cn } from '@/lib/csv'
import { date, dateTimeIST, monthYear, num, ok, qty, relative, toneClass } from '@/lib/format'
import { useLocalStorage } from '@/lib/useLocalStorage'

type Tab = 'live' | 'today' | 'insider' | 'accumulating' | 'exited' | 'flows'
type HoldView = 'accumulating' | 'exiting'
type SideFilter = 'all' | 'buy' | 'sell'

const TABS: { id: Tab; label: string }[] = [
  { id: 'live', label: 'Big money live' },
  { id: 'today', label: "Today's big trades" },
  { id: 'insider', label: 'Insider & promoter trades' },
  { id: 'accumulating', label: 'Accumulating' },
  { id: 'exited', label: 'Exited / selling' },
  { id: 'flows', label: 'FII/DII flows' },
]

const HONEST_NOTE = 'What you see here are deals and holdings that big investors must report by law. It is not live, and it is not a tip. Bulk and block deals show up after the market closes. Insider trades can be reported up to about 4 trading days late, and shareholding only once a quarter, up to 3 weeks late. Many "bulk deals" are trading firms that buy and sell the same day: we mark those as "intraday" and leave them out of the buyer and seller lists. Studies on Indian stocks find most of the price move around bulk deals happens before or on the deal day. Promoter buying in small companies has been followed by gains on average, but averages hide many losers, and those stocks can be hard to trade. A famous name buying does not mean the price will rise. Big investors also lose money, and they can sell without anyone knowing until the next filing. A stock dropping off the shareholding list only means they now hold less than 1%, not always a full exit. Use this as one clue next to your own analysis, never as a buy or sell signal. This is not investment advice.'
const RULES = [
  'Bulk deal: one client trades more than 0.5% of a company\'s shares in a day. Published after the close.',
  'Block deal: a single trade of at least ₹25 crore in NSE\'s 8:45–9:00 or 2:05–2:20 window, within 3% of the reference price.',
  'Insider trade: promoters, directors and key staff report trades over ₹10 lakh a quarter, within about 4 trading days.',
  'Shareholding: every company files it within 21 days of each quarter end; only holders with 1% or more are named.',
  'FII/DII: market-wide cash-market figures for the day, provisional, in ₹ crore.',
  'Names are matched to types (mutual fund, FII, promoter, …) by rules; a name that looks like a famous investor can be someone else - the filed name is always shown.',
]

const SIDE_ITEMS: { id: SideFilter; label: string }[] = [{ id: 'all', label: 'All' }, { id: 'buy', label: 'Buys' }, { id: 'sell', label: 'Sells' }]
const SOURCE_LABEL: Record<SmSourceKind, string> = { bulk: 'Bulk deal', block: 'Block deal', insider: 'Insider filing', shareholding: 'Shareholding' }

const plural = (n: number, word: string) => `${qty(n)} ${word}${n === 1 ? '' : 's'}`
const pctText = (v: number | null) => (ok(v) ? `${num(v, 2)}%` : '—')

/** '3 days buying' / '2 days selling' / '—' for a signed FII/DII streak. */
function streakText(n: number): string {
  if (!n) return '—'
  const d = Math.abs(n)
  return `${d} day${d === 1 ? '' : 's'} ${n > 0 ? 'buying' : 'selling'}`
}

/** Page number that falls back to 1 whenever the filters (`sig`) change - no effect, so no fetch of a stale page. */
function usePage(sig: string): [number, (p: number) => void] {
  const [s, setS] = useState({ sig, page: 1 })
  return [s.sig === sig ? s.page : 1, (page: number) => setS({ sig, page })]
}

// ------------------------------------------------------------------ small shared pieces
function WhoCell({ name, investor, subLabel }: { name: string; investor: string | null; subLabel: string | null }) {
  const title = subLabel ? `${name} (${subLabel})` : name
  return (
    <div className="flex min-w-0 flex-col leading-tight">
      <span className="max-w-[260px] truncate font-medium" title={title}>{investor ?? name}</span>
      {investor && <span className="max-w-[260px] truncate text-2xs text-muted" title={title}>{name}</span>}
    </div>
  )
}

function DealSide({ side }: { side: SmDealSide }) {
  if (side === 'FLAT') return <span className="tint-muted inline-flex h-5 w-11 shrink-0 items-center justify-center rounded text-2xs font-bold tracking-[0.04em] text-muted">FLAT</span>
  return <SidePill side={side} />
}

function Pager({ page, pageSize, total, onPage }: { page: number; pageSize: number; total: number; onPage: (p: number) => void }) {
  if (total <= pageSize) return null
  const last = Math.ceil(total / pageSize)
  const from = Math.min(total, (page - 1) * pageSize + 1)
  const to = Math.min(total, page * pageSize)
  return (
    <div className="flex items-center justify-end gap-2 border-t border-line px-3 py-1.5 text-xs text-muted">
      <span className="num">{qty(from)}–{qty(to)} of {qty(total)}</span>
      <IconButton size="sm" label="Previous page" disabled={page <= 1} onClick={() => onPage(page - 1)}><ChevronLeft className="h-4 w-4" /></IconButton>
      <IconButton size="sm" label="Next page" disabled={page >= last} onClick={() => onPage(page + 1)}><ChevronRight className="h-4 w-4" /></IconButton>
    </div>
  )
}

function CategoryPicker({ value, onChange }: { value: SmCategoryFilter; onChange: (v: SmCategoryFilter) => void }) {
  const label = CATEGORY_FILTERS.find((c) => c.id === value)?.label ?? 'Everyone'
  return (
    // the button shows the short form ("Big money"); the menu explains it
    <Popover width={320} trigger={({ open, toggle }) => <SelectButton label="Who" value={label.replace(/ \(.*\)$/, '')} open={open} onClick={toggle} />}>
      {(close) => (
        <div className="py-1">
          {CATEGORY_FILTERS.map((c) => (
            <MenuItem key={c.id} active={c.id === value} onClick={() => { onChange(c.id); close() }}>{c.label}</MenuItem>
          ))}
        </div>
      )}
    </Popover>
  )
}

function SymbolFilter({ symbol, onChange }: { symbol: string; onChange: (s: string) => void }) {
  const [text, setText] = useState(symbol)
  useEffect(() => { setText(symbol) }, [symbol])
  return (
    <>
      <input
        value={text}
        onChange={(e) => setText(e.target.value.toUpperCase())}
        onKeyDown={(e) => { if (e.key === 'Enter') onChange(text.trim().toUpperCase()) }}
        placeholder="Filter by symbol"
        aria-label="Filter by symbol (press Enter)"
        title="Type an NSE symbol and press Enter"
        autoCapitalize="characters"
        spellCheck={false}
        className="input h-8 w-[160px] text-xs"
      />
      {symbol && (
        <Chip className="tint-accent text-accent">
          Symbol: {symbol}
          <button type="button" aria-label="Clear the symbol filter" title="Clear the symbol filter" onClick={() => onChange('')} className="focus-ring -mr-1 rounded-full p-0.5 hover:bg-accent/15">
            <X className="h-3 w-3" />
          </button>
        </Chip>
      )}
    </>
  )
}

function FreshnessLine({ f }: { f: SmFreshness }) {
  if (!f.refreshed_at) return <span className="text-xs text-muted">Not downloaded yet</span>
  return (
    <span className="flex flex-wrap items-center gap-x-1 gap-y-1 text-xs text-muted">
      <span className="whitespace-nowrap">Deals {date(f.deals, { year: false })}</span>
      <span aria-hidden>·</span>
      <span className="whitespace-nowrap">Insider {date(f.insider, { year: false })}</span>
      <span aria-hidden>·</span>
      <span className="whitespace-nowrap">Shareholding {monthYear(f.holdings_period)}</span>
      <span aria-hidden>·</span>
      <span className="whitespace-nowrap" title={dateTimeIST(f.refreshed_at)}>refreshed {relative(f.refreshed_at)}</span>
      {f.stale && <WarnChip title="The newest deals are more than 5 days old - refresh">Stale</WarnChip>}
    </span>
  )
}

function HonestNote({ note }: { note?: string }) {
  const [open, setOpen] = useLocalStorage('qd.smartmoney.note', true)
  const toggle = (
    <button type="button" onClick={() => setOpen(!open)} aria-expanded={open} className="focus-ring inline-flex shrink-0 items-center gap-0.5 rounded text-xs font-medium text-accent hover:underline">
      {open ? 'Show less' : 'Show more'}
      <ChevronDown className={cn('h-3.5 w-3.5 transition-transform', open && 'rotate-180')} />
    </button>
  )
  return (
    <div className="flex items-start gap-2.5 rounded-lg border border-info/25 bg-info/[0.06] px-4 py-3 text-[13px]">
      <Info className="mt-0.5 h-4 w-4 shrink-0 text-info" />
      <div className="min-w-0 flex-1">
        {open ? (
          <>
            <div className="flex items-baseline justify-between gap-3">
              <div className="font-semibold text-fg">Read this first</div>
              {toggle}
            </div>
            <p className="mt-1 max-w-[120ch] leading-5 text-fg">{note ?? HONEST_NOTE}</p>
            <div className="eyebrow mt-3">How this works</div>
            <ul className="mt-1.5 max-w-[120ch] space-y-1 text-xs leading-5 text-muted">
              {RULES.map((r) => <li key={r} className="flex gap-2"><span className="mt-2 h-1 w-1 shrink-0 rounded-full bg-info" /><span>{r}</span></li>)}
            </ul>
          </>
        ) : (
          <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
            <span className="font-medium text-fg">Disclosed data, not live, not a tip.</span>
            {toggle}
          </div>
        )}
      </div>
    </div>
  )
}

// ------------------------------------------------------------------ refresh
function RefreshButton() {
  const start = useSmRefresh()
  const running = !!useSmStatus().data?.run.running
  const toast = useToast()
  const qc = useQueryClient()
  const go = () =>
    start.mutate(365, {
      onError: (e) => {
        toast({ tone: 'bad', title: isFailure(e) ? e.message : 'Could not start the smart-money refresh', detail: isFailure(e) ? e.hint ?? undefined : undefined })
        // 409 SCAN_BUSY: a refresh is already running (maybe the daily scan's) - pick up its status and poll it
        void qc.invalidateQueries({ queryKey: smKeys.status })
      },
    })
  return (
    <Button
      size="sm"
      icon={<RefreshCw className="h-3.5 w-3.5" />}
      loading={start.isPending}
      disabled={running}
      onClick={go}
      title="Download the latest NSE deals, insider filings, FII/DII figures and shareholding in the background (1-6 minutes)"
    >
      Refresh data
    </Button>
  )
}

/** Refresh button + background run state; reloads every smart-money query and toasts when a watched run ends. */
function RefreshControl() {
  const run = useSmStatus().data?.run
  const toast = useToast()
  const qc = useQueryClient()
  const wasRunning = useRef(false)
  useEffect(() => {
    if (!run) return
    if (wasRunning.current && !run.running) {
      void qc.invalidateQueries({ queryKey: smKeys.all })
      if (run.state === 'failed') toast({ tone: 'bad', title: 'Smart-money refresh failed', detail: run.message ?? undefined })
      else if (run.errors.length) toast({ tone: 'info', title: 'Smart-money data refreshed with some gaps', detail: run.errors[0] })
      else toast({ tone: 'good', title: 'Smart-money data refreshed' })
    }
    wasRunning.current = run.running
  }, [run, qc, toast])
  return (
    <>
      {run?.running ? (
        <span className="flex max-w-[320px] items-center gap-1.5 text-xs text-muted" title={run.message ?? undefined}>
          <Spinner className="h-3.5 w-3.5 shrink-0" />
          <span className="truncate">{run.message ?? 'Refreshing…'}</span>
        </span>
      ) : run?.state === 'failed' ? (
        <span className="max-w-[320px] truncate text-xs text-loss" title={run.message ?? undefined}>Last refresh failed{run.message ? `: ${run.message}` : ''}</span>
      ) : null}
      <RefreshButton />
    </>
  )
}

function FirstRun({ run }: { run: SmRefreshRun }) {
  if (run.running) {
    return (
      <div className="card">
        <EmptyState title="Downloading smart-money data…" icon={<Spinner className="h-6 w-6" />}>
          <span className="block">{run.message ?? 'Starting…'}</span>
          <span className="mt-1 block">The first download takes 3-6 minutes and runs in the background. This page fills in by itself when it finishes.</span>
        </EmptyState>
      </div>
    )
  }
  return (
    <div className="card">
      <EmptyState title="No smart-money data yet" icon={<Landmark className="h-6 w-6" strokeWidth={1.5} />} action={<RefreshButton />}>
        Downloads about a year of NSE bulk/block deals and insider filings, today's FII/DII figures and the latest shareholding of your stock list. The first time takes 3-6 minutes; it runs in the background.
        {run.state === 'failed' && run.message && <span className="mt-1 block text-loss">Last try failed: {run.message}</span>}
      </EmptyState>
    </div>
  )
}

function Kpis() {
  const q = useSmOverview(30)
  if (q.error) return <div className="card"><ErrorState error={q.error} onRetry={() => void q.refetch()} compact /></div>
  if (!q.data) return <SkeletonKpis n={7} />
  const k = q.data.kpis
  const flowsOn = k.flows_date ? date(k.flows_date) : 'not downloaded yet'
  return (
    <KpiStrip gridClass="md:grid-cols-4 xl:grid-cols-7">
      <KpiTile label={`Big-money buys (${k.days} d)`} value={fmtInr(k.big_buy_value)} sub={plural(k.stocks_bought, 'stock')} title="Bulk/block net buying by institutions, promoters and well-known investors; intraday trading firms left out" />
      <KpiTile label={`Big-money sells (${k.days} d)`} value={fmtInr(k.big_sell_value)} sub={plural(k.stocks_sold, 'stock')} title="Bulk/block net selling by the same big investors" />
      <KpiTile label="Institutions net" value={fmtInr(k.inst_net_value, true)} tone={toneClass(k.inst_net_value)} sub="FII, MF, insurance, banks, pension" title="Bulk/block buying minus selling by institutions in the last 30 days" />
      <KpiTile label="Promoter/insider buys" value={fmtInr(k.insider_buy_value)} sub={`sells ${fmtInr(k.insider_sell_value)}`} title="Open-market trades disclosed under SEBI's insider rules (no ESOPs, gifts, transfers or pledges)" />
      <KpiTile label="Exits seen" value={qty(k.exits)} sub="full exits or now below 1%" title="Insiders who sold all their shares, 1%+ holders who dropped off the list, and whole groups that sold out" />
      <KpiTile label="FII net (latest)" value={fmtCr(k.fii_net_cr)} tone={toneClass(k.fii_net_cr)} sub={flowsOn} title="Foreign institutions, whole cash market, provisional, ₹ crore - not per stock" />
      <KpiTile label="DII net (latest)" value={fmtCr(k.dii_net_cr)} tone={toneClass(k.dii_net_cr)} sub={flowsOn} title="Domestic institutions, whole cash market, provisional, ₹ crore - not per stock" />
    </KpiStrip>
  )
}

// ------------------------------------------------------------------ tab: today's big trades (bulk / block deals)
const dealCols: Col<SmDeal>[] = [
  { id: 'date', header: 'Date', value: (r) => r.date, cell: (r) => <span className="num text-muted">{date(r.date, { year: false })}</span>, width: 72 },
  { id: 'sym', header: 'Symbol', value: (r) => r.symbol, cell: (r) => <SymbolCell symbol={r.symbol} company={r.company} />, sticky: true, minWidth: 150, mobile: 'primary', search: (r) => `${r.symbol} ${r.company ?? ''} ${r.client} ${r.investor ?? ''}`, csvExtra: { label: 'Company', value: (r) => r.company } },
  { id: 'side', header: 'Side', value: (r) => r.side, cell: (r) => <DealSide side={r.side} />, width: 64, mobile: 'secondary' },
  { id: 'who', header: 'Who', value: (r) => r.investor ?? r.client, cell: (r) => <WhoCell name={r.client} investor={r.investor} subLabel={r.sub_label} />, minWidth: 220, csvExtra: { label: 'Name as filed', value: (r) => r.client } },
  { id: 'cat', header: 'Type', value: (r) => r.category_label, cell: (r) => <CategoryBadge category={r.category} subLabel={r.sub_label} />, mobile: 'secondary', label: 'Type' },
  { id: 'kind', header: 'Deal', value: (r) => r.kind, cell: (r) => <span className="text-muted">{r.kind === 'both' ? 'Bulk + block' : r.kind === 'block' ? 'Block' : 'Bulk'}</span>, hideBelow: 1100 },
  { id: 'qty', header: 'Shares', align: 'right', value: (r) => (r.round_trip ? r.buy_qty : Math.abs(r.net_qty)), cell: (r) => <span className="num">{qty(r.round_trip ? r.buy_qty : Math.abs(r.net_qty))}</span> },
  { id: 'price', header: 'Avg ₹', align: 'right', value: (r) => r.avg_price, cell: (r) => <Price v={r.avg_price} /> },
  { id: 'value', header: 'Value', align: 'right', value: (r) => (r.round_trip ? r.buy_value : Math.abs(r.net_value)), cell: (r) => <span className="num">{fmtInr(r.round_trip ? r.buy_value : Math.abs(r.net_value))}</span>, mobile: 'value' },
  { id: 'pct', header: '% of co.', title: "Shares traded as a % of all the company's shares", align: 'right', value: (r) => r.pct_equity, cell: (r) => <span className="num">{pctText(r.pct_equity)}</span>, mobile: 'change' },
  { id: 'other', header: 'Other side', title: 'Block deals: who was on the other side the same day', value: (r) => r.counterparties.join(', '), cell: (r) => <span className="block max-w-[220px] truncate text-muted" title={r.counterparties.join(', ')}>{r.counterparties.join(', ') || '—'}</span>, hideBelow: 1240 },
]

function DealsTab({ symbol, filter }: { symbol: string; filter: ReactNode }) {
  const nav = useNavigate()
  const [days, setDays] = useState(30)          // a month of big trades; 'Latest day' is one click away
  const [side, setSide] = useState<SideFilter>('all')
  const [kind, setKind] = useState<'all' | 'bulk' | 'block'>('all')
  const [category, setCategory] = useState<SmCategoryFilter>('big')
  const [open, setOpen] = useState(false)
  const [page, setPage] = usePage(JSON.stringify([days, side, kind, category, symbol]))
  const sym = symbol || undefined
  const q = useSmDeals({ days, side, kind, category, symbol: sym, page, page_size: 100 })
  const iq = useSmDeals({ days, side, kind, category: 'all', symbol: sym, intraday: true, page: 1, page_size: 200 }, open)
  const d = q.data
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        {filter}
        <Segmented ariaLabel="Window" value={String(days)} onChange={(v) => setDays(Number(v))} items={[{ id: '1', label: 'Latest day' }, { id: '7', label: '1 W' }, { id: '30', label: '1 M' }, { id: '90', label: '3 M' }, { id: '365', label: '1 Y' }]} />
        <Segmented ariaLabel="Buys or sells" value={side} onChange={setSide} items={SIDE_ITEMS} />
        <Segmented ariaLabel="Deal type" value={kind} onChange={setKind} items={[{ id: 'all', label: 'All' }, { id: 'bulk', label: 'Bulk' }, { id: 'block', label: 'Block' }]} />
        <CategoryPicker value={category} onChange={setCategory} />
      </div>
      {q.error ? <div className="card"><ErrorState error={q.error} onRetry={() => void q.refetch()} /></div> : !d ? <div className="card"><SkeletonRows /></div> : (
        <Card
          title={!d.until ? 'Big trades' : d.days === 1 ? `Big trades on ${date(d.until)}` : `Big trades ${date(d.since)} – ${date(d.until)}`}
          subtitle={d.note}
          right={(
            <span className="flex items-center gap-2 text-xs text-muted">
              {q.isFetching && q.isPlaceholderData && <Spinner className="h-3.5 w-3.5" />}
              <span className="num">{qty(d.counts.buys)} buys · {qty(d.counts.sells)} sells</span>
            </span>
          )}
          flush
        >
          <DataTable
            id="sm.deals"
            data={d.rows}
            columns={dealCols}
            rowKey={(r) => r.id}
            onRowClick={(r) => nav(`/chart/${r.symbol}`)}
            exportName="smart-money-deals"
            filterable
            filterPlaceholder="Filter symbol or name…"
            empty={<EmptyState compact title="No big trades in this window">Try a longer window or 'Everyone'.</EmptyState>}
          />
          <Pager page={d.page} pageSize={d.page_size} total={d.total} onPage={setPage} />
          <div className="border-t border-line">
            <button
              type="button"
              onClick={() => setOpen(!open)}
              disabled={!open && d.counts.intraday === 0}
              aria-expanded={open}
              className="focus-ring flex w-full items-center gap-1.5 px-4 py-2.5 text-left text-xs font-medium text-muted hover:text-fg disabled:cursor-default disabled:hover:text-muted"
            >
              <ChevronDown className={cn('h-3.5 w-3.5 transition-transform', open && 'rotate-180')} />
              Intraday / arbitrage trades ({qty(d.counts.intraday)})
            </button>
            {open && (
              <div className="border-t border-line">
                <p className="px-4 py-2 text-xs text-muted">Trading firms that bought and sold about the same number of shares the same day. They keep no stake, so they are left out of the buyer and seller lists.</p>
                {iq.error ? <ErrorState error={iq.error} onRetry={() => void iq.refetch()} compact /> : !iq.data ? <SkeletonRows rows={4} /> : (
                  <DataTable
                    id="sm.deals.intraday"
                    data={iq.data.rows}
                    columns={dealCols}
                    rowKey={(r) => r.id}
                    onRowClick={(r) => nav(`/chart/${r.symbol}`)}
                    exportName="smart-money-intraday"
                    empty={<EmptyState compact title="No intraday trades in this window" />}
                    footer={iq.data.total > iq.data.rows.length ? <p className="border-t border-line px-4 py-2 text-2xs text-faint">Showing the first {qty(iq.data.rows.length)} of {qty(iq.data.total)}.</p> : undefined}
                  />
                )}
              </div>
            )}
          </div>
        </Card>
      )}
    </div>
  )
}

// ------------------------------------------------------------------ tab: insider & promoter trades (SEBI PIT)
const insiderCols: Col<SmInsiderTrade>[] = [
  { id: 'disc', header: 'Disclosed', value: (r) => r.disclosed, cell: (r) => <span className="num text-muted">{date(r.disclosed, { year: false })}</span>, width: 84 },
  { id: 'sym', header: 'Symbol', value: (r) => r.symbol, cell: (r) => <SymbolCell symbol={r.symbol} company={r.company} />, sticky: true, minWidth: 150, mobile: 'primary', search: (r) => `${r.symbol} ${r.company ?? ''} ${r.person}`, csvExtra: { label: 'Company', value: (r) => r.company } },
  { id: 'person', header: 'Person', value: (r) => r.person, cell: (r) => (
    <div className="flex min-w-0 flex-col leading-tight">
      <span className="max-w-[220px] truncate font-medium" title={r.person}>{r.investor ?? r.person}</span>
      <span className="max-w-[220px] truncate text-2xs text-muted">{r.investor ? `${r.person} · ` : ''}{r.person_category ?? '—'}</span>
    </div>
  ), minWidth: 200, csvExtra: { label: 'Person category', value: (r) => r.person_category } },
  { id: 'side', header: 'Side', value: (r) => r.side, cell: (r) => (r.side ? <SidePill side={r.side} /> : <span className="text-faint">—</span>), width: 64, mobile: 'secondary' },
  { id: 'how', header: 'How', value: (r) => r.mode, cell: (r) => (
    <span className="flex items-center gap-1">
      <span className={r.is_market ? 'text-fg' : 'text-muted'}>{r.mode ?? '—'}</span>
      {r.fully_exited && <ExitChip kind="full_exit" />}
      {r.mode_kind === 'pledge_invoked' && <WarnChip title="A lender sold pledged shares: a forced sale">Pledge sold</WarnChip>}
    </span>
  ) },
  { id: 'qty', header: 'Shares', align: 'right', value: (r) => r.qty, cell: (r) => <span className="num">{qty(r.qty)}</span> },
  { id: 'value', header: 'Value', align: 'right', value: (r) => r.value, cell: (r) => <span className="num">{fmtInr(r.value)}</span>, mobile: 'value' },
  { id: 'price', header: 'Avg ₹', align: 'right', value: (r) => r.avg_price, cell: (r) => <Price v={r.avg_price} />, hideBelow: 1100 },
  { id: 'stake', header: 'Stake', title: 'Their holding before → after, % of the company', align: 'right', value: (r) => r.after_pct, cell: (r) => (
    <span className="num" title={`${qty(r.before_shares)} → ${qty(r.after_shares)} shares`}>{r.before_pct == null && r.after_pct == null ? '—' : `${pctText(r.before_pct)} → ${pctText(r.after_pct)}`}</span>
  ), mobile: 'change' },
  { id: 'trade', header: 'Traded', value: (r) => r.trade_from, cell: (r) => <span className="num text-muted">{r.trade_from === r.trade_to || !r.trade_to ? date(r.trade_from, { year: false }) : `${date(r.trade_from, { year: false })} – ${date(r.trade_to, { year: false })}`}</span>, hideBelow: 1180 },
  { id: 'delay', header: 'Delay', title: 'Days from the trade to the filing reaching NSE', align: 'right', value: (r) => r.delay_days, cell: (r) => <span className="num text-muted">{r.delay_days == null ? '—' : `${r.delay_days} d`}</span>, hideBelow: 1240 },
]

function InsiderTab({ symbol, filter }: { symbol: string; filter: ReactNode }) {
  const nav = useNavigate()
  const [days, setDays] = useState(30)
  const [side, setSide] = useState<SideFilter>('all')
  const [who, setWho] = useState<'all' | 'promoter' | 'insider'>('all')
  const [marketOnly, setMarketOnly] = useState(true)
  const [page, setPage] = usePage(JSON.stringify([days, side, who, marketOnly, symbol]))
  const q = useSmInsider({ days, side, category: who, mode: marketOnly ? 'market' : 'all', symbol: symbol || undefined, page, page_size: 100 })
  const d = q.data
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        {filter}
        <Segmented ariaLabel="Window" value={String(days)} onChange={(v) => setDays(Number(v))} items={[{ id: '7', label: '1 W' }, { id: '30', label: '1 M' }, { id: '90', label: '3 M' }, { id: '365', label: '1 Y' }]} />
        <Segmented ariaLabel="Buys or sells" value={side} onChange={setSide} items={SIDE_ITEMS} />
        <Segmented ariaLabel="Who" value={who} onChange={setWho} items={[{ id: 'all', label: 'Everyone' }, { id: 'promoter', label: 'Promoters' }, { id: 'insider', label: 'Directors & staff' }]} />
        <span title="Shows open-market buys and sells and forced pledge sales; hides ESOPs, gifts, transfers and new pledges">
          <Switch checked={marketOnly} onChange={setMarketOnly} label="Market trades only" />
        </span>
      </div>
      {q.error ? <div className="card"><ErrorState error={q.error} onRetry={() => void q.refetch()} /></div> : !d ? <div className="card"><SkeletonRows /></div> : (
        <Card
          title={d.until ? `Insider & promoter trades disclosed ${date(d.since)} – ${date(d.until)}` : 'Insider & promoter trades'}
          subtitle={d.note}
          right={(
            <span className="flex flex-wrap items-center justify-end gap-2 text-xs text-muted">
              {q.isFetching && q.isPlaceholderData && <Spinner className="h-3.5 w-3.5" />}
              <span className="num">{qty(d.counts.buys)} buys ({fmtInr(d.counts.buy_value)}) · {qty(d.counts.sells)} sells ({fmtInr(d.counts.sell_value)})</span>
              {d.counts.pledge_invoked > 0 && <WarnChip title="A lender sold pledged shares: a forced sale, often a warning sign">{plural(d.counts.pledge_invoked, 'pledge sale')}</WarnChip>}
              {d.counts.full_exits > 0 && <Chip className="tint-loss text-loss" title="Insiders whose holding after the sale is zero">{qty(d.counts.full_exits)} fully exited</Chip>}
            </span>
          )}
          flush
        >
          <DataTable
            id="sm.insider"
            data={d.rows}
            columns={insiderCols}
            rowKey={(r) => r.id}
            onRowClick={(r) => nav(`/chart/${r.symbol}`)}
            exportName="smart-money-insider"
            filterable
            filterPlaceholder="Filter symbol or person…"
            empty={<EmptyState compact title="No insider trades in this window">{marketOnly ? "Try a longer window, or switch off 'Market trades only'." : 'Try a longer window.'}</EmptyState>}
          />
          <Pager page={d.page} pageSize={d.page_size} total={d.total} onPage={setPage} />
        </Card>
      )}
    </div>
  )
}

// ------------------------------------------------------------------ tabs: accumulating / exited (all sources per stock)
function stockColumns(view: HoldView): Col<SmStock>[] {
  return [
    { id: 'sym', header: 'Symbol', value: (r) => r.symbol, cell: (r) => <SymbolCell symbol={r.symbol} company={r.company} />, mobileCell: (r) => (
      // phones have no Why column: the top reason goes under the symbol
      <div className="flex min-w-0 flex-col gap-0.5">
        <SymbolCell symbol={r.symbol} company={r.company} />
        {r.reasons[0] && <span className="whitespace-normal text-xs leading-snug text-muted">{r.reasons[0]}</span>}
      </div>
    ), sticky: true, minWidth: 150, mobile: 'primary', search: (r) => `${r.symbol} ${r.company ?? ''} ${r.reasons.join(' ')}`, csvExtra: { label: 'Company', value: (r) => r.company } },
    { id: 'why', header: 'Why', value: (r) => r.reasons[0] ?? '', sortable: false, cell: (r) => (
      <Tip text={<ul className="space-y-1">{r.reasons.map((x) => <li key={x}>{x}</li>)}</ul>}>
        <span className="block max-w-[420px] truncate">{r.reasons[0] ?? '—'}{r.reasons.length > 1 && <span className="text-faint"> +{r.reasons.length - 1} more</span>}</span>
      </Tip>
    ), minWidth: 300 },
    { id: 'deals', header: 'Big-money deals', title: 'Bulk/block buying minus selling by institutions, promoters and well-known investors (no intraday)', align: 'right', value: (r) => r.deal_net_value, cell: (r) => <span className={cn('num', toneClass(r.deal_net_value))}>{r.deal_net_value === 0 ? '—' : fmtInr(r.deal_net_value, true)}</span>, mobile: 'value' },
    { id: 'inst', header: 'Institutions', title: 'Distinct institutions buying / selling via bulk or block deals', align: 'right', value: (r) => r.inst_buyers - r.inst_sellers, cell: (r) => <span className="num"><span className="text-profit">{r.inst_buyers}</span><span className="text-faint"> / </span><span className="text-loss">{r.inst_sellers}</span></span> },
    { id: 'famous', header: 'Well-known', value: (r) => [...r.famous_buyers, ...r.famous_sellers].join(', '), cell: (r) => <span className="block max-w-[200px] truncate" title={[...r.famous_buyers.map((x) => `${x} bought`), ...r.famous_sellers.map((x) => `${x} sold`)].join(', ')}>{[...r.famous_buyers, ...r.famous_sellers].join(', ') || '—'}</span>, hideBelow: 1100 },
    { id: 'insider', header: 'Promoter / insider', title: 'Open-market buying minus selling by promoters, directors and key staff', align: 'right', value: (r) => r.insider_buy_value - r.insider_sell_value, cell: (r) => <span className={cn('num', toneClass(r.insider_buy_value - r.insider_sell_value))}>{r.insider_buy_value || r.insider_sell_value ? fmtInr(r.insider_buy_value - r.insider_sell_value, true) : '—'}</span> },
    { id: 'fii', header: 'FII Δ', title: 'Change in FII/FPI holding, latest quarter vs the one before (percentage points)', align: 'right', value: (r) => r.fii_chg_pts, cell: (r) => <Pts v={r.fii_chg_pts} /> },
    { id: 'mf', header: 'MF Δ', title: 'Change in mutual-fund holding, latest quarter vs the one before (percentage points)', align: 'right', value: (r) => r.mf_chg_pts, cell: (r) => <Pts v={r.mf_chg_pts} />, mobile: 'change' },
    { id: 'prom', header: 'Promoter Δ', title: 'Change in promoter holding, latest quarter vs the one before (percentage points)', align: 'right', value: (r) => r.promoter_chg_pts, cell: (r) => <Pts v={r.promoter_chg_pts} />, hideBelow: 1180 },
    { id: 'exits', header: 'Exits', title: 'Full exits, holders now below 1% and whole groups that sold out', align: 'right', value: (r) => r.exits, cell: (r) => <span className="num">{r.exits || '—'}</span>, defaultHidden: view === 'accumulating' },
    { id: 'last', header: 'Latest', value: (r) => r.last_date, cell: (r) => <span className="num text-muted">{date(r.last_date, { year: false })}</span>, hideBelow: 1240 },
  ]
}

function eventColumns(view: HoldView): Col<SmEvent>[] {
  return [
    { id: 'date', header: 'Date', value: (r) => r.date, cell: (r) => <span className="num text-muted">{date(r.date, { year: false })}</span>, width: 72 },
    { id: 'sym', header: 'Symbol', value: (r) => r.symbol, cell: (r) => <SymbolCell symbol={r.symbol} company={r.company} />, sticky: true, minWidth: 140, mobile: 'primary', search: (r) => `${r.symbol} ${r.company ?? ''} ${r.who ?? ''} ${r.investor ?? ''}`, csvExtra: { label: 'Company', value: (r) => r.company } },
    // whitespace-normal on the inner span: cn does not merge Tailwind classes and the cell itself is whitespace-nowrap.
    // The text names a well-known investor by display name, so the filed name goes under it.
    { id: 'what', header: 'What happened', value: (r) => r.text, sortable: false, cell: (r) => (
      <span className="block min-w-[280px] max-w-[560px] whitespace-normal py-1 leading-snug">
        {r.text}
        {r.investor && r.who && <span className="block text-2xs text-muted">Filed as {r.who}</span>}
      </span>
    ), minWidth: 320, mobile: 'secondary', label: 'What', csvExtra: { label: 'Name as filed', value: (r) => r.who } },
    { id: 'cat', header: 'Type', value: (r) => r.category_label, cell: (r) => <CategoryBadge category={r.category} subLabel={r.sub_label} /> },
    { id: 'exit', header: 'Exit?', value: (r) => r.exit_kind, cell: (r) => <ExitChip kind={r.exit_kind} />, defaultHidden: view === 'accumulating' },
    { id: 'src', header: 'Source', value: (r) => r.source, cell: (r) => <span className="text-muted">{SOURCE_LABEL[r.source]}</span>, hideBelow: 1100 },
  ]
}

function HoldingsTab({ view, symbol, filter }: { view: HoldView; symbol: string; filter: ReactNode }) {
  const nav = useNavigate()
  const [days, setDays] = useState(90)          // shareholding changes are quarterly: a full quarter of filings
  const [category, setCategory] = useState<SmCategoryFilter>('big')
  const q = useSmHoldings({ view, days, category, symbol: symbol || undefined })
  const stockCols = useMemo(() => stockColumns(view), [view])
  const eventCols = useMemo(() => eventColumns(view), [view])
  const d = q.data
  const buying = view === 'accumulating'
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        {filter}
        <Segmented ariaLabel="Window" value={String(days)} onChange={(v) => setDays(Number(v))} items={[{ id: '30', label: '1 M' }, { id: '90', label: '3 M' }]} />
        <CategoryPicker value={category} onChange={setCategory} />
      </div>
      {q.error ? <div className="card"><ErrorState error={q.error} onRetry={() => void q.refetch()} /></div> : !d ? <div className="card"><SkeletonRows /></div> : (
        <>
          <Card
            title={buying ? 'Stocks big investors are adding' : 'Stocks big investors are selling or leaving'}
            subtitle={`${d.note}${d.latest_period ? ` Shareholding: quarter to ${monthYear(d.latest_period)} vs ${monthYear(d.previous_period)}, ${d.coverage} stocks.` : ' Shareholding not downloaded yet.'}`}
            right={(
              <span className="flex items-center gap-2 text-xs text-muted">
                {q.isFetching && q.isPlaceholderData && <Spinner className="h-3.5 w-3.5" />}
                <span className="num">{plural(d.stocks.length, 'stock')}</span>
              </span>
            )}
            flush
          >
            <DataTable
              id={`sm.${view}`}
              data={d.stocks}
              columns={stockCols}
              rowKey={(r) => r.symbol}
              onRowClick={(r) => nav(`/chart/${r.symbol}`)}
              exportName={`smart-money-${view}`}
              filterable
              filterPlaceholder="Filter symbol or reason…"
              pageSize={50}
              empty={<EmptyState compact title={buying ? 'No stocks with big-money buying in this window' : 'No stocks with big-money selling in this window'}>Try 3 M or 'Everyone'.</EmptyState>}
            />
          </Card>
          <Card
            title={buying ? 'What they did (buying)' : 'What they did (selling and exits)'}
            subtitle={buying
              ? 'Bulk/block buys, open-market promoter and insider buys, new 1%+ holders and bigger stakes, newest first.'
              : "'Fully exited' is certain: their holding after the sale is zero. 'Now below 1%' only means they are no longer listed as a 1%+ holder - they sold some or all."}
            flush
          >
            <DataTable
              id={`sm.${view}.events`}
              data={d.events}
              columns={eventCols}
              rowKey={(r) => r.id}
              onRowClick={(r) => nav(`/chart/${r.symbol}`)}
              exportName={`smart-money-${view}-events`}
              filterable
              filterPlaceholder="Filter symbol or name…"
              pageSize={50}
              empty={<EmptyState compact title="Nothing in this window">Shareholding changes appear after companies file (within 21 days of the quarter end); deals and insider trades after each refresh.</EmptyState>}
            />
          </Card>
        </>
      )}
    </div>
  )
}

// ------------------------------------------------------------------ tab: FII/DII flows (market-wide)
const flowCols: Col<SmFlowDay>[] = [
  { id: 'date', header: 'Date', value: (r) => r.date, cell: (r) => <span className="num text-muted">{date(r.date)}</span>, sticky: true, minWidth: 110, mobile: 'primary' },
  { id: 'fb', header: 'FII buy', align: 'right', value: (r) => r.fii_buy_cr, cell: (r) => <span className="num">{fmtCr(r.fii_buy_cr, false)}</span> },
  { id: 'fs', header: 'FII sell', align: 'right', value: (r) => r.fii_sell_cr, cell: (r) => <span className="num">{fmtCr(r.fii_sell_cr, false)}</span> },
  { id: 'fn', header: 'FII net', align: 'right', value: (r) => r.fii_net_cr, cell: (r) => <span className={cn('num', toneClass(r.fii_net_cr))}>{fmtCr(r.fii_net_cr)}</span>, mobile: 'secondary', label: 'FII net' },
  { id: 'db', header: 'DII buy', align: 'right', value: (r) => r.dii_buy_cr, cell: (r) => <span className="num">{fmtCr(r.dii_buy_cr, false)}</span> },
  { id: 'ds', header: 'DII sell', align: 'right', value: (r) => r.dii_sell_cr, cell: (r) => <span className="num">{fmtCr(r.dii_sell_cr, false)}</span> },
  { id: 'dn', header: 'DII net', align: 'right', value: (r) => r.dii_net_cr, cell: (r) => <span className={cn('num', toneClass(r.dii_net_cr))}>{fmtCr(r.dii_net_cr)}</span>, mobile: 'secondary', label: 'DII net' },
]

/** One row per day (newest first): a centred bar, green to the right for net buying, red to the left for net selling,
 *  scaled to the largest day shown. SignedBars is not used: it prints percent. */
function FlowBars({ rows, field }: { rows: SmFlowDay[]; field: 'fii_net_cr' | 'dii_net_cr' }) {
  const items = rows.slice(0, 30)
  const max = Math.max(1, ...items.map((r) => Math.abs(r[field] ?? 0)))
  return (
    <div className="space-y-1">
      {items.map((r) => {
        const v = r[field]
        return (
          <div key={r.date} className="grid grid-cols-[52px_1fr_92px] items-center gap-2 text-xs">
            <span className="num text-muted">{date(r.date, { year: false })}</span>
            <div className="relative h-3.5">
              <div className="absolute inset-y-0 left-1/2 w-px bg-line" />
              {ok(v) && v !== 0 && (
                <div className={cn('absolute inset-y-0.5 rounded-sm', v > 0 ? 'bg-profit/60' : 'bg-loss/60')} style={v > 0 ? { left: '50%', width: `${(Math.abs(v) / max) * 50}%` } : { right: '50%', width: `${(Math.abs(v) / max) * 50}%` }} />
              )}
            </div>
            <span className={cn('num text-right', toneClass(v))}>{fmtCr(v)}</span>
          </div>
        )
      })}
    </div>
  )
}

function FlowsTab() {
  const [days, setDays] = useState(30)
  const q = useSmFlows(days)
  const d = q.data
  const r0 = d && d.rows.length > 0 ? d.rows[0] : null
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <Segmented ariaLabel="Window" value={String(days)} onChange={(v) => setDays(Number(v))} items={[{ id: '30', label: '1 M' }, { id: '90', label: '3 M' }, { id: '365', label: '1 Y' }]} />
        <span className="text-xs text-muted">Whole market, not per stock · ₹ crore · provisional</span>
      </div>
      {q.error ? <div className="card"><ErrorState error={q.error} onRetry={() => void q.refetch()} /></div> : !d ? <div className="card"><SkeletonRows /></div> : !r0 ? (
        <div className="card"><EmptyState compact title="No FII/DII figures yet">{d.note}</EmptyState></div>
      ) : (
        <>
          <KpiStrip gridClass="md:grid-cols-3 xl:grid-cols-6">
            <KpiTile label="FII/FPI net (latest)" value={fmtCr(r0.fii_net_cr)} tone={toneClass(r0.fii_net_cr)} sub={date(r0.date)} title="Foreign institutions: buying minus selling in the cash market that day" />
            <KpiTile label="DII net (latest)" value={fmtCr(r0.dii_net_cr)} tone={toneClass(r0.dii_net_cr)} sub={date(r0.date)} title="Domestic institutions (mutual funds, insurers, banks, pension funds): buying minus selling that day" />
            <KpiTile label="FII streak" value={streakText(d.fii_streak)} tone={toneClass(d.fii_streak)} title="Trading days in a row up to the latest with the same direction" />
            <KpiTile label="DII streak" value={streakText(d.dii_streak)} tone={toneClass(d.dii_streak)} title="Trading days in a row up to the latest with the same direction" />
            <KpiTile label={`FII net (${d.days} d)`} value={fmtCr(d.fii_net_cr_total)} tone={toneClass(d.fii_net_cr_total)} sub={`${plural(d.rows.length, 'trading day')} stored`} />
            <KpiTile label={`DII net (${d.days} d)`} value={fmtCr(d.dii_net_cr_total)} tone={toneClass(d.dii_net_cr_total)} sub={`${plural(d.rows.length, 'trading day')} stored`} />
          </KpiStrip>
          <div className="grid gap-3 lg:grid-cols-2">
            <Card title="FII/FPI net, ₹ crore" subtitle="Green: bought more than sold that day. Red: sold more."><FlowBars rows={d.rows} field="fii_net_cr" /></Card>
            <Card title="DII net, ₹ crore" subtitle="Green: bought more than sold that day. Red: sold more."><FlowBars rows={d.rows} field="dii_net_cr" /></Card>
          </div>
          <Card title="Daily FII/DII figures" subtitle={`${d.note}${d.first_date ? ` History since ${date(d.first_date)}.` : ''}`} flush>
            <DataTable id="sm.flows" data={d.rows} columns={flowCols} rowKey={(r) => r.date} exportName="fii-dii-flows" pageSize={60} />
          </Card>
        </>
      )}
    </div>
  )
}

// ------------------------------------------------------------------ page
export default function SmartMoney() {
  const { tab = 'today' } = useParams()
  const t: Tab = TABS.find((x) => x.id === tab)?.id ?? 'today'
  const [sp, setSp] = useSearchParams()
  const symbol = (sp.get('symbol') ?? '').trim().toUpperCase()
  const setSymbol = (v: string) => setSp((p) => {
    const n = new URLSearchParams(p)
    if (v) n.set('symbol', v)
    else n.delete('symbol')
    return n
  }, { replace: true })
  const status = useSmStatus().data
  const overview = useSmOverview(30)
  const keep = symbol ? `?symbol=${encodeURIComponent(symbol)}` : ''
  const filter = <SymbolFilter symbol={symbol} onChange={setSymbol} />
  return (
    <div>
      <PageHeader
        title="Smart money"
        subtitle="Which stocks big investors are buying, selling or leaving - from what they must disclose to NSE"
        right={<>{status && <FreshnessLine f={status.freshness} />}<RefreshControl /></>}
      />
      <div className="space-y-3">
        <HonestNote note={overview.data?.note} />
        {status && status.freshness.refreshed_at == null ? <FirstRun run={status.run} /> : (
          <>
            <Kpis />
            <div>
              <div className="mb-3 border-b border-line">
                <Tabs<Tab> value={t} items={TABS.map((x) => ({ id: x.id, label: x.label, to: `/smart-money/${x.id}${keep}` }))} />
              </div>
              {t === 'live' && <BigMoneyLive />}
              {t === 'today' && <DealsTab symbol={symbol} filter={filter} />}
              {t === 'insider' && <InsiderTab symbol={symbol} filter={filter} />}
              {(t === 'accumulating' || t === 'exited') && <HoldingsTab key={t} view={t === 'exited' ? 'exiting' : 'accumulating'} symbol={symbol} filter={filter} />}
              {t === 'flows' && <FlowsTab />}
            </div>
          </>
        )}
      </div>
    </div>
  )
}
