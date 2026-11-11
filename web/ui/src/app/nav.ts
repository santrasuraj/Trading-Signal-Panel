import {
  Briefcase, BookOpenCheck, CalendarDays, CandlestickChart, Calculator, History as HistoryIcon, Radio, ShieldAlert, Spline, LayoutGrid, Gamepad2, Hammer, Grid3x3, History, GraduationCap, Crosshair, Gauge, Receipt, Globe2, Landmark, Layers, FlaskConical, LayoutDashboard, ListChecks, ListFilter, NotebookPen, Scale, Settings2, Star, Timer, Trophy, type LucideIcon,
} from 'lucide-react'

export interface NavItem { id: string; label: string; to: string; icon: LucideIcon; keys?: string; match: (p: string) => boolean; badge?: string }

export const NAV: NavItem[] = [
  { id: 'overview', label: 'Overview', to: '/', icon: LayoutDashboard, keys: 'g o', match: (p) => p === '/' },
  { id: 'today', label: 'Today', to: '/today', icon: ListChecks, keys: 'g d', match: (p) => p.startsWith('/today') },
  { id: 'setups', label: 'Live setups', to: '/setups', icon: Radio, keys: 'g g', match: (p) => p.startsWith('/setups') },
  { id: 'watchlist', label: 'Watchlist', to: '/watchlist', icon: Star, keys: 'g w', match: (p) => p.startsWith('/watchlist') },
  { id: 'signals', label: 'Signals', to: '/signals', icon: Crosshair, keys: 'g s', match: (p) => p.startsWith('/signals') },
  { id: 'strategies', label: 'Strategies', to: '/strategies', icon: Trophy, keys: 'g t', match: (p) => p.startsWith('/strategies') },
  { id: 'screener', label: 'Screener', to: '/screener', icon: ListFilter, keys: 'g r', match: (p) => p.startsWith('/screener') },
  { id: 'builder', label: 'Strategy builder', to: '/builder', icon: Hammer, keys: 'g j', match: (p) => p.startsWith('/builder') },
  { id: 'scans', label: 'Scans', to: '/scans', icon: FlaskConical, keys: 'g x', match: (p) => p.startsWith('/scans') },
  { id: 'chart', label: 'Chart', to: '/chart', icon: CandlestickChart, keys: 'g c', match: (p) => p === '/chart' || p.startsWith('/chart/') },
  { id: 'charts', label: 'Multi-chart', to: '/charts', icon: LayoutGrid, keys: 'g l', match: (p) => p === '/charts' },
  { id: 'portfolio', label: 'Portfolio', to: '/portfolio', icon: Briefcase, keys: 'g p', match: (p) => p.startsWith('/portfolio') },
  { id: 'risk', label: 'Risk', to: '/risk', icon: ShieldAlert, keys: 'g z', match: (p) => p.startsWith('/risk') },
  { id: 'tax', label: 'Tax harvesting', to: '/tax', icon: Calculator, match: (p) => p.startsWith('/tax') },
  { id: 'orders', label: 'Orders', to: '/orders', icon: Receipt, keys: 'g e', match: (p) => p.startsWith('/orders') },
  { id: 'sim', label: 'Practice', to: '/sim', icon: Gamepad2, keys: 'g u', match: (p) => p.startsWith('/sim') },
  { id: 'replay', label: 'Replay', to: '/replay', icon: History, keys: 'g y', match: (p) => p.startsWith('/replay') },
  { id: 'journal', label: 'Trade journal', to: '/journal', icon: BookOpenCheck, match: (p) => p.startsWith('/journal') },
  { id: 'coach', label: 'Coach', to: '/coach', icon: GraduationCap, keys: 'g h', match: (p) => p.startsWith('/coach') },
  { id: 'paper', label: 'Paper', to: '/paper', icon: NotebookPen, keys: 'g a', match: (p) => p.startsWith('/paper') },
  { id: 'calendar', label: 'Calendar', to: '/calendar', icon: CalendarDays, keys: 'g q', match: (p) => p.startsWith('/calendar') },
  { id: 'heatmap', label: 'Heatmap', to: '/heatmap', icon: Grid3x3, keys: 'g v', match: (p) => p.startsWith('/heatmap') },
  { id: 'market', label: 'Market', to: '/market', icon: Globe2, keys: 'g m', match: (p) => p.startsWith('/market') },
  { id: 'smart-money', label: 'Smart money', to: '/smart-money', icon: Landmark, keys: 'g b', match: (p) => p.startsWith('/smart-money') },
  { id: 'options', label: 'Options', to: '/options', icon: Layers, keys: 'g n', match: (p) => p.startsWith('/options') },
  { id: 'option-builder', label: 'Option strategies', to: '/option-builder', icon: Spline, match: (p) => p.startsWith('/option-builder') },
  { id: 'options-backtest', label: 'Options backtest', to: '/options-backtest', icon: HistoryIcon, match: (p) => p.startsWith('/options-backtest') },
  { id: 'fno', label: 'F&O positions', to: '/fno', icon: Scale, keys: 'g f', match: (p) => p.startsWith('/fno') },
  { id: 'benchmarks', label: 'Benchmarks', to: '/benchmarks', icon: Gauge, keys: 'g k', match: (p) => p.startsWith('/benchmarks') },
  { id: 'intraday', label: 'Intraday', to: '/intraday', icon: Timer, keys: 'g i', match: (p) => p.startsWith('/intraday'), badge: 'research' },
]
export const SETTINGS_NAV: NavItem = { id: 'settings', label: 'Data & Settings', to: '/settings', icon: Settings2, keys: 'g ,', match: (p) => p.startsWith('/settings') }

export const G_KEYS: Record<string, string> = { g: '/setups', q: '/calendar', z: '/risk', o: '/', d: '/today', w: '/watchlist', x: '/scans', k: '/benchmarks', e: '/orders', l: '/charts', u: '/sim', j: '/builder', v: '/heatmap', y: '/replay', h: '/coach', s: '/signals', t: '/strategies', c: '/chart', p: '/portfolio', m: '/market', b: '/smart-money', ',': '/settings', r: '/screener', i: '/intraday', a: '/paper', n: '/options', f: '/fno' }
