import {
  Briefcase, CandlestickChart, Crosshair, Globe2, Landmark, LayoutDashboard, ListFilter, NotebookPen, Settings2, Timer, Trophy, type LucideIcon,
} from 'lucide-react'

export interface NavItem { id: string; label: string; to: string; icon: LucideIcon; keys?: string; match: (p: string) => boolean; badge?: string }

export const NAV: NavItem[] = [
  { id: 'overview', label: 'Overview', to: '/', icon: LayoutDashboard, keys: 'g o', match: (p) => p === '/' },
  { id: 'signals', label: 'Signals', to: '/signals', icon: Crosshair, keys: 'g s', match: (p) => p.startsWith('/signals') },
  { id: 'strategies', label: 'Strategies', to: '/strategies', icon: Trophy, keys: 'g t', match: (p) => p.startsWith('/strategies') },
  { id: 'screener', label: 'Screener', to: '/screener', icon: ListFilter, keys: 'g r', match: (p) => p.startsWith('/screener') },
  { id: 'chart', label: 'Chart', to: '/chart', icon: CandlestickChart, keys: 'g c', match: (p) => p.startsWith('/chart') },
  { id: 'portfolio', label: 'Portfolio', to: '/portfolio', icon: Briefcase, keys: 'g p', match: (p) => p.startsWith('/portfolio') },
  { id: 'paper', label: 'Paper', to: '/paper', icon: NotebookPen, keys: 'g a', match: (p) => p.startsWith('/paper') },
  { id: 'market', label: 'Market', to: '/market', icon: Globe2, keys: 'g m', match: (p) => p.startsWith('/market') },
  { id: 'smart-money', label: 'Smart money', to: '/smart-money', icon: Landmark, keys: 'g b', match: (p) => p.startsWith('/smart-money') },
  { id: 'intraday', label: 'Intraday', to: '/intraday', icon: Timer, keys: 'g i', match: (p) => p.startsWith('/intraday'), badge: 'research' },
]
export const SETTINGS_NAV: NavItem = { id: 'settings', label: 'Data & Settings', to: '/settings', icon: Settings2, keys: 'g ,', match: (p) => p.startsWith('/settings') }

export const G_KEYS: Record<string, string> = { o: '/', s: '/signals', t: '/strategies', c: '/chart', p: '/portfolio', m: '/market', b: '/smart-money', ',': '/settings', r: '/screener', i: '/intraday', a: '/paper' }
