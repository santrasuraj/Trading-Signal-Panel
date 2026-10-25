// App shell: left rail, top market bar, status bar, global banners, palette, shortcuts, scan watcher (spec 2.2, 7).

import { Suspense, useEffect, useRef, useState } from 'react'
import { Outlet, useLocation, useNavigate } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { WifiOff } from 'lucide-react'
import { useStatus } from '@/api/hooks'
import { isFailure } from '@/api/client'
import { Banner, Skeleton } from '@/components/feedback'
import { FyersLoginDialog } from '@/components/FyersLogin'
import { CommandPalette } from '@/components/layout/CommandPalette'
import { MobileNav } from '@/components/layout/MobileNav'
import { Rail } from '@/components/layout/Rail'
import { StatusBar } from '@/components/layout/StatusBar'
import { TopBar } from '@/components/layout/TopBar'
import { useToast } from '@/components/toast'
import { Button, Dialog, Kbd } from '@/components/ui'
import { duration } from '@/lib/format'
import { useTheme } from '@/lib/theme'
import { readLocal, useLocalStorage, writeLocal } from '@/lib/useLocalStorage'
import { typingTarget, useMedia } from '@/lib/useMedia'
import { G_KEYS } from './nav'
import { useUi } from './uiState'

/** Invalidate every scan-derived query when /api/status reports a new scan_id; toast scan outcomes. */
function ScanWatcher() {
  const { data } = useStatus()
  const qc = useQueryClient()
  const toast = useToast()
  const lastId = useRef<string | null | undefined>(undefined)
  const lastState = useRef<string | undefined>(undefined)
  useEffect(() => {
    if (!data) return
    const id = data.latest?.scan_id ?? null
    if (lastId.current !== undefined && id !== lastId.current) {
      void qc.invalidateQueries({ predicate: (q) => q.queryKey[0] !== 'status' })
    }
    lastId.current = id
    const st = data.scan.state
    if (lastState.current && lastState.current !== st) {
      if (st === 'done' && (lastState.current === 'running' || lastState.current === 'starting')) {
        toast({ tone: 'good', title: `Scan done${data.latest ? ` in ${duration(data.latest.elapsed_s)}` : ''}`, detail: 'Every page has been refreshed with the new results.' })
      } else if (st === 'failed') {
        toast({ tone: 'bad', title: 'Scan failed', detail: data.scan.message ?? 'See Settings › Scan for the log.' })
      }
    }
    lastState.current = st
  }, [data, qc, toast])
  return null
}

/** Dismissed-banner flag for the CURRENT key (keys change once /api/status loads, so derive it on every render). */
function useDismissed(key: string): [boolean, () => void] {
  const [list, setList] = useState<string[]>(() => readLocal<string[]>('qd.dismissed', []))
  const dismiss = () => {
    const xs = [...readLocal<string[]>('qd.dismissed', []).filter((k) => k !== key).slice(-40), key]
    writeLocal('qd.dismissed', xs)
    setList(xs)
  }
  return [list.includes(key), dismiss]
}

function GlobalBanners() {
  const { data: s, error } = useStatus()
  const nav = useNavigate()
  const { setFyersLogin } = useUi()
  const failKey = `scanfail:${s?.scan.started_at ?? ''}`
  const [failDismissed, dismissFail] = useDismissed(failKey)
  const legacyKey = `legacy:${s?.latest?.scan_id ?? ''}`
  const [legacyDismissed, dismissLegacy] = useDismissed(legacyKey)
  const loginKey = `login:${s?.clock.now.slice(0, 10) ?? ''}`
  const [loginDismissed, dismissLogin] = useDismissed(loginKey)
  const offline = error && isFailure(error) && error.code === 'OFFLINE'
  const items: React.ReactNode[] = []
  if (offline || (error && !s)) {
    items.push(
      <Banner key="off" tone="danger" icon={<WifiOff className="h-4 w-4 text-loss" />}>
        <span className="font-medium">Can't reach the local server (127.0.0.1:8600).</span> <span className="text-muted">Is 3_dashboard.bat still running? Retrying automatically…</span>
      </Banner>,
    )
  }
  if (s?.scan.state === 'failed' && !failDismissed) {
    items.push(
      <Banner key="fail" tone="danger" onDismiss={dismissFail} action={<Button size="sm" onClick={() => nav('/settings/scan')}>Open log</Button>}>
        <span className="font-medium">The last scan failed.</span> <span className="text-muted">{s.scan.message}</span>
      </Banner>,
    )
  }
  if (s?.latest?.live) {
    items.push(
      <Banner key="live" tone="warn">
        <span className="font-medium">PROVISIONAL:</span> based on today's still-forming candle. Orders can change before the close; re-check after 3:30 PM, final after ~7 PM.
      </Banner>,
    )
  }
  if (s?.latest?.legacy_producer && !legacyDismissed) {
    items.push(
      <Banner key="legacy" tone="warn" onDismiss={dismissLegacy}>
        <span className="font-medium">These results were written by an older scanner</span> (another checkout shares the data folder). Some pages show less until the platform runs the next scan.
      </Banner>,
    )
  }
  if (s && (s.clock.session === 'open' || s.clock.session === 'pre_open') && s.fyers.configured && !s.fyers.logged_in_today && !loginDismissed) {
    items.push(
      <Banner key="login" tone="warn" onDismiss={dismissLogin} action={<Button size="sm" onClick={() => setFyersLogin(true)}>Log in</Button>}>
        Fyers is not logged in today: live prices come from Yahoo (~15 min delayed).
      </Banner>,
    )
  }
  if (!items.length) return null
  return <div className="space-y-2 px-4 pt-3 md:px-5">{items}</div>
}

const HELP: [string, string][] = [
  ['Ctrl K', 'Command palette: stocks, strategies, pages, actions'],
  ['g o / g s / g t', 'Go to Overview / Signals / Strategies'],
  ['g c / g p / g m / g b', 'Go to Chart / Portfolio / Market / Smart money'],
  ['g r / g a / g i / g ,', 'Go to Screener / Paper / Intraday / Settings'],
  ['/', "Focus the current table's filter"],
  ['j / k, Enter', 'Move the table selection; open it'],
  ['[ / ]', 'Previous / next strategy (detail) or symbol (chart)'],
  ['1 … 6', 'Chart range 3M 6M 1Y 2Y 5Y Max'],
  ['d / w', 'Chart timeframe daily / weekly'],
  ['Shift T', 'Toggle dark / light'],
  ['?', 'This help'],
]

function Shortcuts() {
  const nav = useNavigate()
  const { setPalette, help, setHelp } = useUi()
  const { toggle } = useTheme()
  const pending = useRef<number | null>(null)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); setPalette(true); return }
      if (typingTarget(e) || e.ctrlKey || e.metaKey || e.altKey) return
      if (pending.current) {
        const to = G_KEYS[e.key]
        window.clearTimeout(pending.current)
        pending.current = null
        if (to) { e.preventDefault(); nav(to) }
        return
      }
      if (e.key === 'g') { pending.current = window.setTimeout(() => { pending.current = null }, 1200); return }
      if (e.key === 'T' && e.shiftKey) { e.preventDefault(); toggle(); return }
      if (e.key === '?') { e.preventDefault(); setHelp(true) }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [nav, setPalette, setHelp, toggle])
  return (
    <Dialog open={help} onClose={() => setHelp(false)} title="Keyboard shortcuts" width={520}>
      <dl className="divide-y divide-line">
        {HELP.map(([k, v]) => (
          <div key={k} className="flex flex-col gap-1 py-2 text-[13px] sm:flex-row sm:items-center sm:justify-between sm:gap-4">
            <dt className="flex shrink-0 flex-wrap gap-1">{k.split(' ').map((p, i) => (p === '/' && k !== '/' ? <span key={i} className="px-0.5 text-faint">/</span> : <Kbd key={i}>{p}</Kbd>))}</dt>
            <dd className="text-muted sm:text-right">{v}</dd>
          </div>
        ))}
      </dl>
    </Dialog>
  )
}

function FirstRunNotice() {
  const [seen, setSeen] = useLocalStorage('qd.disclaimerSeen', false)
  const { data: st } = useStatus()                 // before the early return: hooks run on every render
  if (seen) return null
  const pit = st?.latest?.backtest_universe === 'point_in_time'
  return (
    <Dialog open onClose={() => setSeen(true)} title="Before you start" footer={<Button variant="primary" onClick={() => setSeen(true)}>I understand</Button>}>
      <div className="space-y-3 text-[13px] text-muted">
        <p className="text-fg">Quant Desk is a personal research tool, not investment advice.</p>
        <p>Every number is a <span className="text-fg">backtest</span> on past NSE data with realistic Indian costs, unless it says <span className="text-fg">paper</span> or <span className="text-fg">live</span>. {pit
          ? "Backtests use a point-in-time universe (each past day's 500 most-traded NSE stocks, including companies that later dropped out), so they are free of survivorship bias; live results are still usually worse than backtests."
          : "Backtests use today's index list, so they include survivorship bias: stocks that dropped out of the index are missing and results look better than reality."}</p>
        <p>Orders shown are what a model portfolio would do at the next open. You decide and place every trade yourself in the Fyers app.</p>
      </div>
    </Dialog>
  )
}

function PageFallback() {
  return (
    <div className="space-y-3 p-5">
      <Skeleton className="h-6 w-48" />
      <Skeleton className="h-[72px] w-full" />
      <Skeleton className="h-[320px] w-full" />
    </div>
  )
}

export function AppShell() {
  // The rail opens by itself only on really wide screens: at 1440 the 224 px rail made the content narrower than
  // at 1280 (tables cut, ticker items hidden). It can always be pinned open with the toggle.
  const wide = useMedia('(min-width: 1680px)')
  const [railPref, setRailPref] = useLocalStorage<'auto' | 'open' | 'closed'>('qd.rail', 'auto')
  const railOpen = railPref === 'auto' ? wide : railPref === 'open'
  const { pathname } = useLocation()
  useEffect(() => { window.scrollTo(0, 0) }, [pathname])
  return (
    <div className="flex min-h-screen">
      <Rail open={railOpen} onToggle={() => setRailPref(railOpen ? 'closed' : 'open')} />
      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar />
        <GlobalBanners />
        {/* overflow-x clip (not hidden: sticky headers keep working): nothing may make the PAGE scroll sideways */}
        <main className="min-w-0 flex-1 overflow-x-clip px-4 pb-20 pt-4 md:px-5 md:pb-6">
          <Suspense fallback={<PageFallback />}>
            <Outlet />
          </Suspense>
        </main>
        <StatusBar />
      </div>
      <MobileNav />
      <CommandPalette />
      <FyersLoginDialog />
      <Shortcuts />
      <ScanWatcher />
      <FirstRunNotice />
    </div>
  )
}
