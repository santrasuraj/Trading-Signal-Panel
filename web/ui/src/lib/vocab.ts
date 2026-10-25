// Status, evidence, horizon and lifecycle vocabulary (spec 4.2). One place for labels, icons and tones.

import {
  Activity, Ban, CalendarRange, CheckCircle2, CircleDashed, Clock, FlaskConical, PowerOff, Timer, XCircle, type LucideIcon,
} from 'lucide-react'
import type { Evidence, Horizon, Lifecycle, StrategyStatus } from '@/api/types'

export type ToneName = 'profit' | 'loss' | 'warn' | 'info' | 'accent' | 'muted' | 'faint'

export const STATUS: Record<StrategyStatus, { label: string; short: string; tone: ToneName; icon: LucideIcon; help: string }> = {
  working: { label: 'Working now', short: 'Working', tone: 'profit', icon: CheckCircle2, help: 'Beat both Nifty 50 and the average stock over the last 12 and 6 months. Relative only: in a falling market it can still have lost money.' },
  mixed: { label: 'Mixed', short: 'Mixed', tone: 'warn', icon: CircleDashed, help: 'Beat the better of Nifty 50 and the average stock in one of the last two windows (12 and 6 months) but not in the other.' },
  'not-working': { label: 'Not working', short: 'Not working', tone: 'loss', icon: XCircle, help: 'Behind Nifty 50 / the average stock over the last 12 and 6 months. Shown for comparison only; its orders are not counted.' },
  unknown: { label: 'Too new', short: 'Too new', tone: 'faint', icon: Clock, help: 'Not enough history to judge.' },
}

/** 'working' (it beat the market) but still lost money over 12 or 6 months: amber, not a green tick. */
export const FELL_LESS: (typeof STATUS)[StrategyStatus] = {
  label: 'Beat a falling market', short: 'Fell less', tone: 'warn', icon: CircleDashed,
  help: 'Beat Nifty 50 and the average stock over the last 12 and 6 months, but still lost money in at least one of them: it only fell less than the market.',
}
export const lostMoney = (h: { ret_12m_pct: number | null; ret_6m_pct: number | null }) =>
  (h.ret_12m_pct ?? 0) < 0 || (h.ret_6m_pct ?? 0) < 0

export const LIFECYCLE: Record<Lifecycle, { label: string; icon: LucideIcon }> = {
  active: { label: 'Active', icon: CheckCircle2 },
  rejected: { label: 'Tested & rejected', icon: Ban },
  disabled: { label: 'Off', icon: PowerOff },
}

export const EVIDENCE: Record<Evidence, { label: string; short: string; help: string }> = {
  STRONG: { label: 'Strong evidence', short: 'Strong', help: 'Peer-reviewed, replicated, out-of-sample or live record, with Indian evidence.' },
  MODERATE: { label: 'Moderate evidence', short: 'Moderate', help: 'Peer-reviewed abroad; mixed or thin Indian evidence, or a live index record only.' },
  WEAK: { label: 'Weak evidence', short: 'Weak', help: 'Working papers, author backtests, or one market only.' },
  FOLKLORE: { label: 'Folklore', short: 'Folklore', help: 'Practitioner books or forums with no systematic test.' },
  EXPERIMENTAL: { label: 'Experimental', short: 'Experimental', help: 'Our own tests are inconclusive; shown for comparison.' },
}
export const EVIDENCE_ICON = FlaskConical

export const HORIZON: Record<Horizon, { label: string; letter: string; icon: LucideIcon; help: string }> = {
  longterm: { label: 'Long-term', letter: 'L', icon: CalendarRange, help: 'Months to years; reviewed monthly or quarterly.' },
  swing: { label: 'Swing', letter: 'S', icon: Activity, help: 'Days to weeks; signal-based entries with stops.' },
  intraday: { label: 'Intraday', letter: 'I', icon: Timer, help: 'Same day; squared off before the close.' },
}

export const HORIZONS: Horizon[] = ['longterm', 'swing', 'intraday']

export const TONE_TEXT: Record<ToneName, string> = {
  profit: 'text-profit', loss: 'text-loss', warn: 'text-warn', info: 'text-info', accent: 'text-accent', muted: 'text-muted', faint: 'text-faint',
}
export const TONE_TINT: Record<ToneName, string> = {
  profit: 'tint-profit', loss: 'tint-loss', warn: 'tint-warn', info: 'tint-info', accent: 'tint-accent', muted: 'tint-muted', faint: 'tint-muted',
}
export const TONE_DOT: Record<ToneName, string> = {
  profit: 'bg-profit', loss: 'bg-loss', warn: 'bg-warn', info: 'bg-info', accent: 'bg-accent', muted: 'bg-muted', faint: 'bg-faint',
}

export function kindLabel(kind: 'rank' | 'event', rebalance?: string | null): string {
  return kind === 'rank' ? `Ranked portfolio${rebalance ? `, ${rebalance}` : ''}` : 'Signal-based'
}
