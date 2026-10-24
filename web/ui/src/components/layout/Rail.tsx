import { Link, useLocation } from 'react-router-dom'
import { PanelLeftClose, PanelLeftOpen } from 'lucide-react'
import { NAV, SETTINGS_NAV, type NavItem } from '@/app/nav'
import { cn } from '@/lib/csv'

export function Logo({ compact }: { compact?: boolean }) {
  return (
    <Link to="/" className="focus-ring flex items-center gap-2.5 rounded-md" aria-label="Quant Desk home">
      <span className="grid h-7 w-7 shrink-0 place-items-center rounded-md bg-accent-strong text-[11px] font-bold tracking-tight text-white">QD</span>
      {!compact && (
        <span className="flex flex-col leading-none">
          <span className="text-[13px] font-semibold text-fg">Quant Desk</span>
          <span className="mt-0.5 text-2xs text-faint">NSE research</span>
        </span>
      )}
    </Link>
  )
}

function Item({ it, open, path }: { it: NavItem; open: boolean; path: string }) {
  const active = it.match(path)
  const Icon = it.icon
  return (
    <Link
      to={it.to}
      title={open ? undefined : `${it.label}${it.keys ? `  (${it.keys})` : ''}`}
      aria-current={active ? 'page' : undefined}
      className={cn(
        'focus-ring group relative flex h-9 items-center gap-3 rounded-md px-2.5 text-[13px] font-medium transition-colors duration-100',
        active ? 'bg-raised text-fg' : 'text-muted hover:bg-raised/60 hover:text-fg',
      )}
    >
      {active && <span className="absolute -left-2 top-1.5 h-6 w-0.5 rounded-r bg-accent" />}
      <Icon className={cn('h-[18px] w-[18px] shrink-0', active ? 'text-accent' : '')} strokeWidth={1.75} />
      {open && <span className="min-w-0 flex-1 truncate">{it.label}</span>}
      {open && it.badge && <span className="rounded bg-raised px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-faint">{it.badge}</span>}
      {open && it.keys && !it.badge && <span className="hidden text-2xs text-faint group-hover:inline">{it.keys}</span>}
    </Link>
  )
}

export function Rail({ open, onToggle }: { open: boolean; onToggle: () => void }) {
  const { pathname } = useLocation()
  return (
    <nav
      aria-label="Main"
      className={cn('sticky top-0 hidden h-screen shrink-0 flex-col border-r border-line bg-panel md:flex', open ? 'w-[224px]' : 'w-[60px]')}
    >
      <div className={cn('flex h-12 items-center border-b border-line', open ? 'px-4' : 'justify-center')}>
        <Logo compact={!open} />
      </div>
      <div className="flex flex-1 flex-col gap-0.5 overflow-y-auto px-2 py-3">
        {NAV.map((it) => <Item key={it.id} it={it} open={open} path={pathname} />)}
        <div className="my-2 border-t border-line" />
        <Item it={SETTINGS_NAV} open={open} path={pathname} />
      </div>
      <div className="border-t border-line p-2">
        <button
          type="button"
          onClick={onToggle}
          className="focus-ring flex h-8 w-full items-center gap-3 rounded-md px-2.5 text-xs text-faint hover:bg-raised hover:text-fg"
          aria-label={open ? 'Collapse sidebar' : 'Expand sidebar'}
        >
          {open ? <PanelLeftClose className="h-4 w-4" /> : <PanelLeftOpen className="h-4 w-4" />}
          {open && 'Collapse'}
        </button>
      </div>
    </nav>
  )
}
