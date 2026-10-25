import { Link } from 'react-router-dom'
import { Minus, Moon, Search, Sun, TrendingDown, TrendingUp } from 'lucide-react'
import { useIsFetching } from '@tanstack/react-query'
import { useStatus } from '@/api/hooks'
import type { AppStatus } from '@/api/types'
import { useUi } from '@/app/uiState'
import { cn } from '@/lib/csv'
import { date, num, pct } from '@/lib/format'
import { useTheme } from '@/lib/theme'
import { useIsMobile } from '@/lib/useMedia'
import { IconButton, Kbd } from '../ui'
import { Logo } from './Rail'
import { ScanButton } from './ScanButton'

export function RegimePill({ label }: { label: 'Bullish' | 'Mixed' | 'Bearish' }) {
  const Icon = label === 'Bullish' ? TrendingUp : label === 'Bearish' ? TrendingDown : Minus
  const cls = label === 'Bullish' ? 'tint-profit text-profit' : label === 'Bearish' ? 'tint-loss text-loss' : 'tint-warn text-warn'
  return (
    <Link to="/" title="Market regime (Nifty vs its 200-day average, breadth)" className={cn('focus-ring inline-flex h-6 shrink-0 items-center gap-1 rounded-full px-2 text-2xs font-bold uppercase tracking-[0.06em]', cls)}>
      <Icon className="h-3.5 w-3.5" strokeWidth={2.25} />
      {label}
    </Link>
  )
}

export function FreshnessPill({ s, compact }: { s: AppStatus; compact?: boolean }) {
  const l = s.latest
  if (!l) return <span className="inline-flex h-6 items-center rounded-full border border-line px-2 text-2xs font-medium text-muted">No scan yet</span>
  const live = l.live && !l.stale          // a live snapshot is stale once that day's official close exists
  const stale = l.stale
  const text = compact ? (live ? 'LIVE' : stale ? 'STALE' : 'EOD')
    : live ? `LIVE · ${l.live_source?.split(' ')[0] ?? 'intraday'} · provisional` : stale ? `STALE · ${date(l.data_date, { year: false })}` : `EOD ${date(l.data_date, { year: false })} · NSE`
  const title = live
    ? "Today's candle is still forming: every order is provisional. Re-check after 3:30 PM; final after ~7 PM."
    : stale ? `Prices are from ${date(l.data_date)}; the last completed session is ${date(s.clock.last_completed_day)}. Run a scan.`
    : `Prices of ${date(l.data_date)} (official close${l.complete_upto ? `, NSE complete up to ${date(l.complete_upto)}` : ''}).`
  return (
    <Link to="/settings/data" title={title} className={cn('focus-ring inline-flex h-6 shrink-0 items-center gap-1.5 rounded-full px-2 text-2xs font-semibold tracking-[0.02em]',
      live ? 'striped-warn text-warn' : stale ? 'tint-warn text-warn' : 'border border-line text-muted hover:text-fg')}>
      <span className={cn('h-1.5 w-1.5 rounded-full', live ? 'bg-warn' : stale ? 'bg-warn' : 'bg-profit')} />
      {text}
    </Link>
  )
}

function FyersDot({ s }: { s: AppStatus }) {
  const f = s.fyers
  const { setFyersLogin } = useUi()
  const state = !f.configured ? 'off' : f.logged_in_today ? 'on' : 'stale'
  const title = !f.configured ? 'Fyers not configured: prices from Yahoo (~15 min delayed)' : f.logged_in_today ? `Fyers logged in today${f.user_name ? ` as ${f.user_name}` : ''}` : 'Fyers not logged in today: prices from Yahoo (~15 min delayed). Click to log in.'
  return (
    <button type="button" onClick={() => setFyersLogin(true)} title={title} className="focus-ring inline-flex h-6 shrink-0 items-center gap-1.5 rounded-full border border-line px-2 text-2xs font-medium text-muted hover:text-fg">
      <span className={cn('h-1.5 w-1.5 rounded-full', state === 'on' ? 'bg-profit' : state === 'stale' ? 'bg-warn' : 'bg-faint')} />
      Fyers
    </button>
  )
}

function TickerItem({ label, value, chg, dp = 2, chgDp = 2, to }: { label: string; value: number | null; chg: number | null; dp?: number; chgDp?: number; to: string }) {
  return (
    <Link to={to} className="focus-ring flex shrink-0 items-baseline gap-1.5 rounded px-1 text-xs hover:bg-raised">
      <span className="text-2xs font-semibold uppercase tracking-[0.04em] text-faint">{label}</span>
      <span className="num font-medium text-fg">{num(value, dp)}</span>
      <span className={cn('num', chg == null ? 'text-faint' : chg > 0 ? 'text-profit' : chg < 0 ? 'text-loss' : 'text-muted')}>{pct(chg, { dp: chgDp })}</span>
    </Link>
  )
}

export function TopBar() {
  const { data: s } = useStatus()
  const { setPalette } = useUi()
  const { resolved, toggle } = useTheme()
  const fetching = useIsFetching({ predicate: (q) => q.queryKey[0] !== 'status' && q.state.data !== undefined })
  const t = s?.ticker
  const mobile = useIsMobile()
  return (
    <header className="sticky top-0 z-30 border-b border-line bg-panel/95 backdrop-blur supports-[backdrop-filter]:bg-panel/85">
      <div className="flex h-12 items-center gap-3 px-4 md:px-5">
        <div className="md:hidden"><Logo compact /></div>
        <button
          type="button"
          onClick={() => setPalette(true)}
          title="Search stocks, strategies, pages and actions (Ctrl K)"
          className="focus-ring hidden h-8 w-[200px] shrink-0 items-center gap-2 rounded-md border border-line bg-raised px-2.5 text-left text-[13px] text-faint transition-colors hover:border-line-strong lg:flex 3xl:w-[300px]"
        >
          <Search className="h-3.5 w-3.5 shrink-0" />
          <span className="min-w-0 flex-1 truncate"><span className="3xl:hidden">Search…</span><span className="hidden 3xl:inline">Search stocks, strategies…</span></span>
          <Kbd>Ctrl K</Kbd>
        </button>
        <IconButton label="Search (Ctrl K)" className="lg:hidden" onClick={() => setPalette(true)}><Search className="h-4 w-4" /></IconButton>

        {t && (
          // Items that don't fit wrap onto a hidden second line instead of being cut mid-number ("VIX 15.7"), so a
          // narrower window shows Nifty first, then N500, VIX and A/D as room allows (qd-ticker hides the whole strip
          // when not even one item fits).
          <div className="qd-ticker-box hidden min-w-0 flex-1 lg:block">
          <div className="qd-ticker flex h-5 flex-wrap items-center gap-x-3 gap-y-8 overflow-hidden">
            <TickerItem label="Nifty" value={t.nifty} chg={t.nifty_change_pct} to="/market/factors" />
            <TickerItem label="N500" value={t.nifty500} chg={t.nifty500_change_pct} to="/market/factors" />
            <TickerItem label="VIX" value={t.vix} chg={t.vix_change_pct} to="/market/breadth" />
            <Link to="/market/breadth" className="focus-ring flex shrink-0 items-baseline gap-1.5 rounded px-1 text-xs hover:bg-raised" title="Advancing : declining stocks in the universe">
              <span className="text-2xs font-semibold uppercase tracking-[0.04em] text-faint">A/D</span>
              <span className="num"><span className="text-profit">{t.advances}</span><span className="text-faint">:</span><span className="text-loss">{t.declines}</span></span>
            </Link>
          </div>
          </div>
        )}
        {!t && <div className="flex-1" />}
        <div className="flex-1 lg:hidden" />
        <div className="flex items-center gap-2">
          {t && <RegimePill label={t.label} />}
          {s && <span className="hidden sm:inline-flex"><FreshnessPill s={s} /></span>}
          {s && <span className="inline-flex sm:hidden"><FreshnessPill s={s} compact /></span>}
          {s && <span className="hidden lg:inline-flex"><FyersDot s={s} /></span>}
          <ScanButton compact={mobile} />
          <IconButton label={`Switch to ${resolved === 'dark' ? 'light' : 'dark'} theme (Shift T)`} onClick={toggle} className="max-sm:hidden">
            {resolved === 'dark' ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
          </IconButton>
        </div>
      </div>
      <div className={cn('qd-progress relative h-0.5 overflow-hidden', fetching ? 'opacity-100' : 'opacity-0')} aria-hidden />
    </header>
  )
}
