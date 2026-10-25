import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { useStatus } from '@/api/hooks'
import { cn } from '@/lib/csv'
import { date, duration, money, timeIST } from '@/lib/format'

/** One status-bar fact with its leading separator (so a fact hidden at a breakpoint takes its separator with it). */
function Fact({ children, className, first }: { children: ReactNode; className?: string; first?: boolean }) {
  return (
    <span className={className}>
      {!first && <span className="mx-1.5 text-line-strong" aria-hidden>·</span>}
      {children}
    </span>
  )
}

/**
 * 28 px desktop status bar (spec 2.2). Every fact here comes from /api/status.
 * The disclaimer on the right never shrinks; the facts on the left end in an ellipsis when the window is narrow,
 * and the lower-priority ones (universe, liquid count, capital) only show from xl.
 */
export function StatusBar() {
  const { data: s, error } = useStatus()
  const l = s?.latest
  const biased = l?.backtest_universe === 'current_list'
  const full = l
    ? [
        `Last scan ${timeIST(l.generated_at)} (${duration(l.elapsed_s)})`,
        `Prices ${date(l.data_date, { year: false })} (${l.stale ? 'stale' : l.live ? 'live, provisional' : 'official close'})`,
        l.universe_note, `${l.tradable} liquid`, `Capital ${money(l.capital)}`,
        `Backtests: ${biased ? "today's list (survivorship bias)" : 'point-in-time universe'}`,
        s?.config_changed_since_scan ? 'config changed: needs re-scan' : '',
      ].filter(Boolean).join(' · ')
    : undefined
  return (
    <footer className="sticky bottom-0 z-20 hidden h-7 shrink-0 items-center gap-4 whitespace-nowrap border-t border-line bg-panel px-5 text-2xs text-muted md:flex">
      <div className="min-w-0 flex-1 truncate" title={full}>
        {error && !s ? (
          <span className="text-loss">Server unreachable · retrying</span>
        ) : l ? (
          <>
            <Fact first><Link to="/settings/scan" className="hover:text-fg">Last scan {timeIST(l.generated_at)} ({duration(l.elapsed_s)})</Link></Fact>
            <Fact>
              <span className={cn((l.live || l.stale) && 'text-warn')}>
                Prices {date(l.data_date, { year: false })} ({l.stale ? 'stale' : l.live ? 'live, provisional' : 'official close'})
              </span>
            </Fact>
            {s?.config_changed_since_scan && <Fact><Link to="/settings/strategies" className="text-warn hover:underline">config changed: needs re-scan</Link></Fact>}
            <Fact>
              <Link to="/strategies" className={cn('hover:text-fg', biased && 'text-warn/90')}>
                <span className="xl:hidden">Backtests: {biased ? 'biased list' : 'point-in-time'}</span>
                <span className="hidden xl:inline">Backtests: {biased ? "today's list (survivorship bias)" : 'point-in-time universe'}</span>
              </Link>
            </Fact>
            <Fact className="hidden xl:inline"><span className="num">Capital {money(l.capital)}</span></Fact>
            <Fact className="hidden xl:inline"><span className="num">{l.tradable} liquid</span></Fact>
            <Fact className="hidden 2xl:inline">{l.universe_note}</Fact>
          </>
        ) : (
          <span>No scan yet</span>
        )}
      </div>
      <Link to="/settings/about" className="shrink-0 hover:text-fg">Research tool · not investment advice</Link>
    </footer>
  )
}
