// Shared domain components: page header, KPI tiles, strategy name cell, survivorship note, orders table.

import { useState, type ReactNode } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { AlertTriangle, CandlestickChart, Check, ChevronRight, Copy, ExternalLink } from 'lucide-react'
import type { AsOf, Order, ResultsEvent, StrategySummary } from '@/api/types'
import { cn } from '@/lib/csv'
import { date, pct, qty } from '@/lib/format'
import { orderClipboard } from '@/lib/sizing'
import { lostMoney } from '@/lib/vocab'
import { EvidenceChip, EtfChip, HorizonChip, ProvisionalChip, ResultsChip, SidePill, StatusDot, WarnChip } from './badges'
import { DataTable, SymbolCell, type Col } from './DataTable'
import { Chip, IconButton, Tip } from './ui'
import { useToast } from './toast'
import { Money, Pct, Price } from './num'

export function PageHeader({ title, subtitle, right, children }: { title: ReactNode; subtitle?: ReactNode; right?: ReactNode; children?: ReactNode }) {
  return (
    <div className="mb-4 flex flex-col gap-3">
      <div className="flex flex-wrap items-end justify-between gap-x-4 gap-y-2">
        <div className="min-w-0">
          <h1 className="text-xl font-semibold tracking-[-0.01em] text-fg">{title}</h1>
          {subtitle && <div className="mt-0.5 text-xs text-muted">{subtitle}</div>}
        </div>
        {right && <div className="flex min-w-0 max-w-full flex-wrap items-center gap-2">{right}</div>}
      </div>
      {children}
    </div>
  )
}

export function AsOfLine({ a }: { a: AsOf }) {
  return (
    <span>
      Prices <span className="whitespace-nowrap">{date(a.data_date)}</span> · {a.stale ? <span className="text-warn">stale</span> : a.live ? <span className="text-warn">live candle, provisional</span> : <span className="whitespace-nowrap">official close</span>}
    </span>
  )
}

/** KPI tile. Label, value and sub-line stack from the top, so values in one row line up whether or not a tile has a
 *  sub-line; the sub-line wraps to two lines instead of losing its number to an ellipsis. */
export function KpiTile({ label, value, sub, title, tone, className }: { label: ReactNode; value: ReactNode; sub?: ReactNode; title?: string; tone?: string; className?: string }) {
  const subText = typeof sub === 'string' ? sub : undefined
  return (
    <div
      className={cn('flex min-h-[72px] min-w-0 snap-start flex-col gap-0.5 bg-panel px-3.5 py-2.5 shadow-[0_0_0_1px_rgb(var(--line))] max-md:min-w-[156px]', className)}
      title={title}
    >
      <div className="truncate text-2xs font-medium text-muted" title={typeof label === 'string' ? label : undefined}>{label}</div>
      <div className={cn('num truncate text-[22px] font-semibold leading-7 tracking-[-0.01em]', tone ?? 'text-fg')}>{value}</div>
      {sub != null && <div className="num line-clamp-2 text-2xs text-muted" title={subText}>{sub}</div>}
    </div>
  )
}

/** KPI strip: 1 px lines between tiles (each tile's 1 px outline fills the grid gap); scrolls horizontally with snap
 *  on phones. `gridClass` (e.g. 'md:grid-cols-5 min-[1600px]:grid-cols-10') gives a fixed layout instead of auto-fit,
 *  so a strip of ten never leaves one tile alone on a second row. The strip background is the panel colour, so an
 *  unfilled cell on the last row stays white instead of showing as a grey block. */
export function KpiStrip({ children, min = 132, gridClass }: { children: ReactNode; min?: number; gridClass?: string }) {
  return (
    <div className="overflow-hidden rounded-lg border border-line bg-panel">
      <div className={cn('grid snap-x gap-px max-md:flex max-md:overflow-x-auto', gridClass)} style={gridClass ? undefined : { gridTemplateColumns: `repeat(auto-fit, minmax(${min}px, 1fr))` }}>
        {children}
      </div>
    </div>
  )
}

export function StrategyNameCell({ s, link = true, compact }: { s: Pick<StrategySummary, 'key' | 'name' | 'horizon' | 'evidence' | 'universe' | 'status'> & { headline?: StrategySummary['headline'] }; link?: boolean; compact?: boolean }) {
  const name = <span className="truncate font-semibold text-fg">{s.name}</span>
  return (
    <div className="flex min-w-0 items-center gap-2">
      <StatusDot status={s.status} lost={s.headline ? lostMoney(s.headline) : false} />
      <div className="flex min-w-0 flex-col gap-0.5">
        {link ? <Link to={`/strategies/${s.key}`} className="truncate hover:underline" onClick={(e) => e.stopPropagation()}>{name}</Link> : name}
        {!compact && (
          <span className="flex items-center gap-1">
            <HorizonChip horizon={s.horizon} letter />
            <EvidenceChip evidence={s.evidence} />
            {s.universe === 'etfs' && <EtfChip />}
          </span>
        )}
      </div>
    </div>
  )
}

/** The scan's own caveat when a backtest is flattered (sector rotation: industries unknown for part of the test). */
export function flatteredNote(s: Pick<StrategySummary, 'status_reason'>): string | null {
  return s.status_reason && s.status_reason.startsWith('Flattered:') ? s.status_reason : null
}

/** Survivorship-bias context; shown next to backtest numbers while backtests use today's list. */
export function BiasNote({ asOf, gap, className }: { asOf: AsOf; gap?: number | null; className?: string }) {
  if (asOf.backtest_universe !== 'current_list') return null
  return (
    <div className={cn('flex items-start gap-2 rounded-md border border-warn/25 bg-warn/[0.06] px-3 py-2 text-xs text-muted', className)}>
      <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-warn" />
      <span>
        Backtests use <span className="text-fg">today's</span> Nifty 500 list (survivorship bias)
        {gap != null && <>: the average stock in it beat the real Nifty 500 by <span className="num font-medium text-fg">{pct(gap, { signed: false })}/yr</span></>}.
        Judge strategies by <span className="font-medium text-fg">edge vs the average stock</span>, and expect live results below the backtest.
      </span>
    </div>
  )
}

function CopyOrder({ o }: { o: Order }) {
  const [done, setDone] = useState(false)
  const toast = useToast()
  return (
    <IconButton
      size="sm"
      label={`Copy "${orderClipboard(o)}"`}
      onClick={(e) => {
        e.stopPropagation()
        const text = orderClipboard(o)
        const ok = () => { setDone(true); setTimeout(() => setDone(false), 1500) }
        const fallback = () => {
          // clipboard API refused (window not focused, no permission): hidden textarea + execCommand('copy')
          const ta = document.createElement('textarea')
          ta.value = text
          ta.setAttribute('readonly', '')
          ta.style.position = 'fixed'
          ta.style.opacity = '0'
          document.body.appendChild(ta)
          ta.select()
          let copied = false
          try { copied = document.execCommand('copy') } catch { copied = false }
          ta.remove()
          if (copied) ok()
          else toast({ tone: 'bad', title: 'Could not copy the order', detail: `Type it in Fyers yourself: ${text}` })
        }
        if (navigator.clipboard?.writeText) navigator.clipboard.writeText(text).then(ok, fallback)
        else fallback()
      }}
    >
      {done ? <Check className="h-3.5 w-3.5 text-profit" /> : <Copy className="h-3.5 w-3.5" />}
    </IconButton>
  )
}

const QTY_BASIS: Record<Order['qty_basis'], string> = {
  sized: 'Sized to the allocation',
  your_holding: 'Your holding (holdings.csv)',
  model_weight: "Model weight × your allocation (you don't hold it)",
}

export function OrderFlags({ o }: { o: Order }) {
  return (
    <span className="flex items-center gap-1">
      {o.provisional && <ProvisionalChip />}
      <ResultsChip on={o.results_on} inDays={o.results_in_days} compact />
      {o.below_min_position && <WarnChip title="Smaller than your minimum position: the backtest would skip it">Below min</WarnChip>}
      {o.you_hold_qty != null && <span className="inline-flex h-5 items-center rounded-full border border-line px-2 text-2xs text-muted">You hold {qty(o.you_hold_qty)}</span>}
    </span>
  )
}

/** Orders for the next open (Signals, Overview, Strategy detail all use this one component). */
export function OrdersTable({ id, orders, showStrategy, compact }: { id: string; orders: Order[]; showStrategy?: boolean; compact?: boolean }) {
  const nav = useNavigate()
  const cols: Col<Order>[] = [
    { id: 'action', header: 'Side', value: (o) => o.action, cell: (o) => <SidePill side={o.action} muted={o.comparison_only} />, width: 64, mobile: 'secondary' },
    { id: 'symbol', header: 'Symbol', value: (o) => o.symbol, cell: (o) => <SymbolCell symbol={o.symbol} company={compact ? null : o.company} />, sticky: true, minWidth: 140, mobile: 'primary' },
    ...(showStrategy ? [{ id: 'strategy', header: 'Strategy', value: (o: Order) => o.strategy_name, cell: (o: Order) => (
      <Link to={`/strategies/${o.strategy_key}`} onClick={(e) => e.stopPropagation()} className="flex items-center gap-1.5 hover:underline">
        <StatusDot status={o.strategy_status} /><span className="max-w-[180px] truncate" title={o.strategy_name}>{o.strategy_name}</span>
      </Link>) } as Col<Order>] : []),
    ...(!compact ? [{ id: 'industry', header: 'Sector', value: (o: Order) => o.industry, cell: (o: Order) => <span className="block max-w-[150px] truncate text-muted 2xl:max-w-[240px]" title={o.industry ?? undefined}>{o.industry ?? '—'}</span>, defaultHidden: showStrategy, hideBelow: 1100 } as Col<Order>] : []),
    { id: 'price', header: 'Last ₹', align: 'right', value: (o) => o.price, cell: (o) => <Price v={o.price} /> },
    { id: 'qty', header: 'Qty', align: 'right', value: (o) => o.qty, title: 'Shares for your capital/allocation', cell: (o) => (
      <span title={QTY_BASIS[o.qty_basis]} className={cn('num', o.qty_basis !== 'sized' && 'underline decoration-dotted decoration-faint underline-offset-2')}>{o.qty == null ? '—' : qty(o.qty)}</span>
    ), mobile: 'value' },
    { id: 'amount', header: 'Amount ₹', align: 'right', value: (o) => o.amount, cell: (o) => <Money v={o.amount} />, mobile: 'secondary', label: 'Amount' },
    { id: 'stop', header: 'Stop ₹', align: 'right', value: (o) => o.stop, cell: (o) => <Price v={o.stop} />, mobile: 'secondary', label: 'Stop' },
    { id: 'dist', header: 'Dist', title: 'Stop distance from the price', align: 'right', value: (o) => o.stop_distance_pct, cell: (o) => <Pct v={o.stop_distance_pct} color={false} /> },
    { id: 'risk', header: 'Risk ₹', title: 'Qty × (price − stop): what you lose if the stop is hit', align: 'right', value: (o) => o.risk_amount, cell: (o) => <Money v={o.risk_amount} /> },
    { id: 'reason', header: 'Why', value: (o) => o.reason, cell: (o) => <span className="block max-w-[200px] truncate text-muted" title={o.reason}>{o.reason}</span>, defaultHidden: compact, hideBelow: 1240 },
    { id: 'flags', header: 'Flags', value: (o) => [o.provisional && 'provisional', o.results_warning && 'results', o.below_min_position && 'below-min'].filter(Boolean).join(' '), cell: (o) => <OrderFlags o={o} />, sortable: false },
    { id: 'act', header: '', value: () => null, sortable: false, cell: (o) => (
      <span className="flex justify-end gap-0.5 opacity-60 group-hover:opacity-100">
        <IconButton size="sm" label="Open chart" onClick={(e) => { e.stopPropagation(); nav(`/chart/${o.symbol}?s=${o.strategy_key}`) }}><CandlestickChart className="h-3.5 w-3.5" /></IconButton>
        <CopyOrder o={o} />
        <a href="https://trade.fyers.in" target="_blank" rel="noopener noreferrer" title="Open Fyers web (place the order yourself)" onClick={(e) => e.stopPropagation()} className="focus-ring inline-flex h-7 w-7 items-center justify-center rounded-md text-muted hover:bg-raised hover:text-fg">
          <ExternalLink className="h-3.5 w-3.5" />
        </a>
      </span>
    ) },
  ]
  return (
    <DataTable
      id={`orders.${id}`}
      data={orders}
      columns={cols}
      rowKey={(o) => `${o.strategy_key}:${o.action}:${o.symbol}`}
      onRowClick={(o) => nav(`/chart/${o.symbol}?s=${o.strategy_key}`)}
      rowClassName={(o) => (o.comparison_only ? 'opacity-60' : undefined)}
      sortable={false}
    />
  )
}

export function MoreLink({ to, children }: { to: string; children: ReactNode }) {
  return (
    <Link to={to} className="focus-ring inline-flex items-center gap-0.5 rounded text-xs font-medium text-accent hover:underline">
      {children}
      <ChevronRight className="h-3.5 w-3.5" />
    </Link>
  )
}

export function Help({ text }: { text: string }) {
  return (
    <Tip text={text}>
      <span className="ml-1 inline-flex h-3.5 w-3.5 cursor-help items-center justify-center rounded-full border border-line-strong text-[9px] font-bold text-faint">?</span>
    </Tip>
  )
}

/** Results chips: why the stock is relevant to you (never the universe momentum rank of every stock). */
export function ResultsWhy({ e }: { e: ResultsEvent }) {
  return (
    <>
      {e.you_hold && <Chip className="tint-accent text-accent">You hold</Chip>}
      {e.in_orders.length > 0 && <Chip className="tint-warn text-warn" title={e.in_orders.join(', ')}>Order</Chip>}
      {e.in_models.length > 0 && <Chip title={`Held by ${e.in_models.join(', ')}`}>Model</Chip>}
      {e.strategy_rank != null && <Chip title={`#${e.strategy_rank} in ${e.ranked_by ?? 'a strategy'}'s ranking`}>#{e.strategy_rank} {e.ranked_by ? e.ranked_by.split(' ')[0] : ''}</Chip>}
    </>
  )
}
