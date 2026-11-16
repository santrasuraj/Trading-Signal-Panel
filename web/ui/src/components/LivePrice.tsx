// Where a price comes from and how old it is, next to the price itself: "Live 10:42:17", "DELAYED 15 MIN",
// "Last trade 15:29:58", "Close 11 Nov". Every live price on every page carries one, so a stale number can never
// pass for a live one.

import { useEffect, useState } from 'react'
import { Radio } from 'lucide-react'
import type { LiveQuote } from '@/api/liveQuotes'
import type { MarketSession } from '@/api/types'
import { useUi } from '@/app/uiState'
import { cn } from '@/lib/csv'
import { date, num } from '@/lib/format'
import { Pct } from '@/components/num'

const STALE_MS = 10_000          // a live-feed price this long without a new tick turns amber

const secFmt = new Intl.DateTimeFormat('en-IN', { timeZone: 'Asia/Kolkata', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false })

export function hms(iso?: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? '—' : secFmt.format(d).replace(/^24:/, '00:')
}

/** Re-render every `ms` while mounted (staleness colours). */
function useTick(ms: number, on = true) {
  const [, set] = useState(0)
  useEffect(() => {
    if (!on) return
    const t = setInterval(() => set((n) => n + 1), ms)
    return () => clearInterval(t)
  }, [ms, on])
}

export interface StampText { text: string; tone: 'live' | 'stale' | 'delayed' | 'closed'; title: string }

export function stampText(q: Pick<LiveQuote, 'source' | 'time' | 'received'> | undefined, session: MarketSession | undefined,
                          fallbackDate?: string | null, now: number = Date.now()): StampText {
  if (!q) {
    return { text: fallbackDate ? `Close ${date(fallbackDate, { year: false })}` : 'Close', tone: 'closed', title: 'Closing price from the last scan (official NSE data).' }
  }
  const src = q.source ?? 'close'
  if (src === 'yahoo') return { text: 'Delayed 15 min', tone: 'delayed', title: 'Yahoo price, about 15 minutes behind the market. Log in to FYERS for real-time prices.' }
  if (src === 'close') return { text: `Close ${date(q.time.slice(0, 10), { year: false })}`, tone: 'closed', title: 'Last stored daily close.' }
  if (session === 'post_close') return { text: `Last trade ${hms(q.time)}`, tone: 'closed', title: 'Market closed at 15:30. NSE publishes the official close after about 18:00.' }
  const stale = src === 'live' && now - q.received > STALE_MS
  return {
    text: `${src === 'live' ? 'Live' : 'FYERS'} ${hms(q.time)}`,
    tone: stale ? 'stale' : 'live',
    title: src === 'live'
      ? (stale ? 'No new trade for a few seconds (live FYERS feed).' : 'Real-time FYERS live feed: last trade time.')
      : 'Real-time FYERS quote, refreshed every 30 s (the live feed streams this symbol within seconds of opening it).',
  }
}

const TONE = {
  live: 'text-profit',
  stale: 'text-warn',
  delayed: 'text-loss',
  closed: 'text-faint',
}

/** The source / age stamp for one quote. `fallbackDate`: the scan's date when there is no live quote. */
export function PriceStamp({ q, session, fallbackDate, className, login = true, compact }: {
  q?: LiveQuote; session?: MarketSession; fallbackDate?: string | null; className?: string; login?: boolean
  compact?: boolean          // top bar: the time only when live, 'Delayed' when Yahoo
}) {
  useTick(1000, q?.source === 'live' && session === 'open')
  const { setFyersLogin } = useUi()
  const s = stampText(q, session, fallbackDate)
  const pulse = s.tone === 'live' && q?.source === 'live' && Date.now() - (q?.received ?? 0) < 1500
  const body = (
    <>
      {(s.tone === 'live' || s.tone === 'stale') && <span className={cn('h-1.5 w-1.5 shrink-0 rounded-full', s.tone === 'live' ? 'bg-profit' : 'bg-warn', pulse && 'animate-ping')} />}
      {s.tone === 'delayed' && <Radio className="h-3 w-3 shrink-0" />}
      <span className={cn('num', compact && 'hidden xl:inline')}>{compact ? (s.tone === 'delayed' ? 'Delayed' : s.tone === 'closed' ? s.text : hms(q?.time)) : s.text}</span>
    </>
  )
  const cls = cn('inline-flex items-center gap-1 whitespace-nowrap text-2xs font-semibold uppercase tracking-[0.04em]', TONE[s.tone],
    s.tone === 'delayed' && 'rounded border border-loss/40 bg-loss/10 px-1', className)
  if (s.tone === 'delayed' && login) {
    return <button type="button" title={`${s.title} Click to log in.`} onClick={() => setFyersLogin(true)} className={cn(cls, 'hover:bg-loss/20')}>{body}</button>
  }
  return <span title={s.title} className={cls}>{body}</span>
}

/** A price with its change and stamp: the live quote when there is one, else the scan's value. */
export function LivePrice({ q, session, fallback, fallbackChange, fallbackDate, dp = 2, className, stamp = true }: {
  q?: LiveQuote; session?: MarketSession; fallback?: number | null; fallbackChange?: number | null; fallbackDate?: string | null
  dp?: number; className?: string; stamp?: boolean
}) {
  const price = q?.price ?? fallback
  const chg = q ? q.change_pct : fallbackChange
  return (
    <span className={cn('inline-flex flex-wrap items-baseline gap-x-1.5', className)}>
      <span className="num font-medium text-fg">{price == null ? '—' : num(price, dp)}</span>
      {chg !== undefined && <Pct v={chg} dp={2} />}
      {stamp && <PriceStamp q={q} session={session} fallbackDate={fallbackDate} />}
    </span>
  )
}
