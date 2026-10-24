import { useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { MoreHorizontal } from 'lucide-react'
import { NAV, SETTINGS_NAV } from '@/app/nav'
import { cn } from '@/lib/csv'

const PRIMARY = ['overview', 'signals', 'strategies', 'portfolio']

/** Bottom tab bar on phones (spec 3.12): Overview · Signals · Strategies · Portfolio · More. */
export function MobileNav() {
  const { pathname } = useLocation()
  const [more, setMore] = useState(false)
  const items = NAV.filter((n) => PRIMARY.includes(n.id))
  const rest = [...NAV.filter((n) => !PRIMARY.includes(n.id)), SETTINGS_NAV]
  const restActive = rest.some((r) => r.match(pathname))
  return (
    <>
      {more && (
        <div className="fixed inset-0 z-40 md:hidden" onClick={() => setMore(false)}>
          <div className="absolute inset-0 bg-black/50" />
          <div className="animate-in absolute inset-x-3 bottom-[68px] rounded-xl bg-panel p-2 shadow-pop" onClick={(e) => e.stopPropagation()}>
            <div className="grid grid-cols-3 gap-1">
              {rest.map((it) => {
                const Icon = it.icon
                return (
                  <Link key={it.id} to={it.to} onClick={() => setMore(false)} className={cn('focus-ring flex flex-col items-center gap-1 rounded-lg px-2 py-3 text-xs', it.match(pathname) ? 'bg-raised text-fg' : 'text-muted')}>
                    <Icon className="h-5 w-5" strokeWidth={1.75} />
                    {it.label.replace('Data & ', '')}
                  </Link>
                )
              })}
            </div>
          </div>
        </div>
      )}
      <nav aria-label="Main" className="fixed inset-x-0 bottom-0 z-30 grid h-14 grid-cols-5 border-t border-line bg-panel pb-[env(safe-area-inset-bottom)] md:hidden">
        {items.map((it) => {
          const Icon = it.icon
          const on = it.match(pathname)
          return (
            <Link key={it.id} to={it.to} aria-current={on ? 'page' : undefined} className={cn('focus-ring flex flex-col items-center justify-center gap-0.5 text-2xs font-medium', on ? 'text-accent' : 'text-muted')}>
              <Icon className="h-5 w-5" strokeWidth={1.75} />
              {it.label}
            </Link>
          )
        })}
        <button type="button" aria-expanded={more} onClick={() => setMore(!more)} className={cn('focus-ring flex flex-col items-center justify-center gap-0.5 text-2xs font-medium', restActive || more ? 'text-accent' : 'text-muted')}>
          <MoreHorizontal className="h-5 w-5" />
          More
        </button>
      </nav>
    </>
  )
}
