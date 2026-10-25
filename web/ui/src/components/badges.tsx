// Domain badges: status, lifecycle, evidence, horizon, side, holding level, results, provisional. Every badge has
// text and (where meaningful) an icon, so colour never carries meaning alone (spec 4.1).

import { AlertTriangle, CalendarClock, Hourglass } from 'lucide-react'
import type { Evidence, HoldingLevel, Horizon, IntradayStrategy, Lifecycle, Side, StrategyStatus, Tone } from '@/api/types'
import { cn } from '@/lib/csv'
import { daysUntil, date } from '@/lib/format'
import { EVIDENCE, EVIDENCE_ICON, FELL_LESS, HORIZON, LIFECYCLE, STATUS, TONE_DOT, TONE_TEXT, TONE_TINT } from '@/lib/vocab'

const pill = 'inline-flex h-5 shrink-0 items-center gap-1 whitespace-nowrap rounded-full px-2 text-2xs font-medium leading-none'

/** `lost`: a 'working' strategy that still lost money over 12 or 6 months shows 'Fell less' (amber), not a green tick. */
export function StatusBadge({ status, short, className, lost }: { status: StrategyStatus; short?: boolean; className?: string; lost?: boolean }) {
  const m = status === 'working' && lost ? FELL_LESS : (STATUS[status] ?? STATUS.unknown)
  const Icon = m.icon
  return (
    <span title={m.help} className={cn(pill, TONE_TINT[m.tone], TONE_TEXT[m.tone], className)}>
      <Icon className="h-3 w-3" strokeWidth={2.25} />
      {short ? m.short : m.label}
    </span>
  )
}

/** Compact status glyph for dense lists (dot + icon tooltip). */
export function StatusDot({ status, className, lost }: { status: StrategyStatus; className?: string; lost?: boolean }) {
  const m = status === 'working' && lost ? FELL_LESS : (STATUS[status] ?? STATUS.unknown)
  const Icon = m.icon
  return (
    <span title={m.label} className={cn('inline-flex shrink-0', TONE_TEXT[m.tone], className)}>
      <Icon className="h-3.5 w-3.5" strokeWidth={2.25} aria-label={m.label} />
    </span>
  )
}

export function LifecycleBadge({ lifecycle }: { lifecycle: Lifecycle }) {
  const m = LIFECYCLE[lifecycle]
  const Icon = m.icon
  return (
    <span className={cn(pill, 'tint-muted text-muted')}>
      <Icon className="h-3 w-3" />
      {m.label}
    </span>
  )
}

export function EvidenceChip({ evidence, className, long }: { evidence: Evidence; className?: string; long?: boolean }) {
  const m = EVIDENCE[evidence] ?? EVIDENCE.EXPERIMENTAL
  const style =
    evidence === 'STRONG' ? 'bg-accent/90 text-white border-transparent' :
    evidence === 'MODERATE' ? 'border-accent/70 text-accent' :
    evidence === 'WEAK' ? 'border-line-strong text-muted' :
    evidence === 'FOLKLORE' ? 'border-dashed border-line-strong text-muted' :
    'border-warn/60 text-warn'
  return (
    <span title={`${m.label}: ${m.help}`} className={cn('inline-flex h-[18px] shrink-0 items-center gap-1 whitespace-nowrap rounded border px-1.5 text-[10px] font-semibold uppercase tracking-[0.04em] leading-none', style, className)}>
      {evidence === 'EXPERIMENTAL' && <EVIDENCE_ICON className="h-2.5 w-2.5" />}
      {long ? m.label : m.short}
    </span>
  )
}

export function HorizonChip({ horizon, letter, className }: { horizon: Horizon; letter?: boolean; className?: string }) {
  const m = HORIZON[horizon]
  const Icon = m.icon
  if (letter) {
    return (
      <span title={m.label} className={cn('inline-flex h-[18px] w-[18px] shrink-0 items-center justify-center rounded border border-line text-[10px] font-semibold text-muted', className)}>
        {m.letter}
      </span>
    )
  }
  return (
    <span title={m.help} className={cn('inline-flex h-[18px] shrink-0 items-center gap-1 whitespace-nowrap rounded border border-line px-1.5 text-[10px] font-semibold uppercase tracking-[0.04em] text-muted', className)}>
      <Icon className="h-2.5 w-2.5" />
      {m.label}
    </span>
  )
}

export function EtfChip() {
  return <span className="inline-flex h-[18px] items-center rounded border border-line px-1.5 text-[10px] font-semibold uppercase tracking-[0.04em] text-info">ETF</span>
}

export function SidePill({ side, muted }: { side: Side; muted?: boolean }) {
  return (
    <span className={cn('inline-flex h-5 w-11 shrink-0 items-center justify-center rounded text-2xs font-bold tracking-[0.04em]',
      muted ? 'tint-muted text-muted' : side === 'BUY' ? 'tint-profit text-profit' : 'tint-loss text-loss')}>
      {side}
    </span>
  )
}

const LEVEL: Record<HoldingLevel, { label: string; tone: 'loss' | 'warn' | 'profit' | 'muted' | 'faint' }> = {
  danger: { label: 'Danger', tone: 'loss' }, watch: { label: 'Watch', tone: 'warn' }, good: { label: 'Target hit', tone: 'profit' },
  ok: { label: 'OK', tone: 'muted' }, unknown: { label: 'No data', tone: 'faint' },
}
export function LevelPill({ level }: { level: HoldingLevel }) {
  const m = LEVEL[level] ?? LEVEL.unknown
  return <span className={cn(pill, TONE_TINT[m.tone], TONE_TEXT[m.tone])}>{m.label}</span>
}

export function TonePill({ tone, children }: { tone: Tone; children: React.ReactNode }) {
  const t = tone === 'good' ? 'profit' : tone === 'bad' ? 'loss' : 'muted'
  return <span className={cn(pill, TONE_TINT[t], TONE_TEXT[t])}>{children}</span>
}

/** Results-date chip: red today/tomorrow, amber within a week, muted later. */
export function ResultsChip({ on, inDays, compact }: { on: string | null; inDays: number | null; compact?: boolean }) {
  if (!on) return null
  const d = inDays
  const tone = d == null ? 'muted' : d <= 1 ? 'loss' : d <= 7 ? 'warn' : 'muted'
  return (
    <span title={`Quarterly results ${date(on)}`} className={cn(pill, TONE_TINT[tone], TONE_TEXT[tone])}>
      <CalendarClock className="h-3 w-3" />
      {compact ? (d != null ? daysUntil(d) : date(on, { year: false })) : `Results ${d != null ? daysUntil(d) : date(on, { year: false })}`}
    </span>
  )
}

export function ProvisionalChip() {
  return (
    <span title="Based on today's still-forming candle. Re-check after 3:30 PM; final after ~7 PM." className={cn(pill, 'striped-warn text-warn')}>
      <Hourglass className="h-3 w-3" />
      Provisional
    </span>
  )
}

export function WarnChip({ children, title }: { children: React.ReactNode; title?: string }) {
  return (
    <span title={title} className={cn(pill, 'tint-warn text-warn')}>
      <AlertTriangle className="h-3 w-3" />
      {children}
    </span>
  )
}

export function Dot({ tone, className }: { tone: keyof typeof TONE_DOT; className?: string }) {
  return <span className={cn('inline-block h-1.5 w-1.5 shrink-0 rounded-full', TONE_DOT[tone], className)} />
}

/** 'yes' only for a statistically significant PROFIT; a significant loss is 'loses'. */
export function edgeVerdict(s: Pick<IntradayStrategy, 'metrics'>): 'yes' | 'loses' | 'no' {
  if (!s.metrics.significant) return 'no'
  return (s.metrics.avg_day_pct ?? s.metrics.return_pct ?? 0) > 0 ? 'yes' : 'loses'
}

export function EdgeVerdict({ s }: { s: Pick<IntradayStrategy, 'metrics'> }) {
  const v = edgeVerdict(s)
  return v === 'yes' ? <span className="font-medium text-profit">yes</span>
    : v === 'loses' ? <span className="text-loss" title="The average day is a loss beyond luck (95% confidence)">loses (significant)</span>
    : <span className="text-faint">no</span>
}
