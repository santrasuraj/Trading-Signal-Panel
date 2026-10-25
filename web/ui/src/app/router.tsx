import { lazy, type ReactNode } from 'react'
import { createBrowserRouter, Navigate, useLocation, useRouteError } from 'react-router-dom'
import { useStatus } from '@/api/hooks'
import { AppShell } from './AppShell'
import { Onboarding } from '@/pages/Onboarding'

// Every page is its own chunk: lightweight-charts and TanStack Table load only with the pages that use them.
const Overview = lazy(() => import('@/pages/Overview'))
const Signals = lazy(() => import('@/pages/Signals'))
const Strategies = lazy(() => import('@/pages/Strategies'))
const StrategyDetail = lazy(() => import('@/pages/StrategyDetail'))
const Screener = lazy(() => import('@/pages/Screener'))
const Chart = lazy(() => import('@/pages/Chart'))
const Portfolio = lazy(() => import('@/pages/Portfolio'))
const Paper = lazy(() => import('@/pages/Paper'))
const Market = lazy(() => import('@/pages/Market'))
const SmartMoney = lazy(() => import('@/pages/SmartMoney'))
const Intraday = lazy(() => import('@/pages/Intraday'))
const Settings = lazy(() => import('@/pages/Settings'))
const NotFound = lazy(() => import('@/pages/NotFound'))

/** No latest.json yet -> onboarding everywhere except Settings (data health, Fyers, scan stay reachable). */
function ScanGate({ children }: { children: ReactNode }) {
  const { data } = useStatus()
  const { pathname } = useLocation()
  if (data && data.latest === null && !pathname.startsWith('/settings') && !pathname.startsWith('/intraday')) return <Onboarding />
  return <>{children}</>
}

const g = (el: ReactNode) => <ScanGate>{el}</ScanGate>

/** Last-resort error screen (a page crashed or a code chunk failed to load after an update). */
function RouteError({ inline }: { inline?: boolean }) {
  const err = useRouteError() as Error | undefined
  const chunk = /dynamically imported module|Importing a module script failed/i.test(String(err?.message ?? err))
  return (
    <div className={inline ? "grid place-items-center p-6 pt-[10vh]" : "grid min-h-screen place-items-center bg-bg p-6"}>
      <div className="card max-w-md p-6">
        <h1 className="text-base font-semibold">{chunk ? 'The app was updated' : 'Something broke on this page'}</h1>
        <p className="mt-2 text-[13px] text-muted">{chunk ? 'Reload to get the new version.' : String(err?.message ?? err)}</p>
        <button type="button" onClick={() => window.location.reload()} className="mt-4 h-8 rounded-md bg-accent-strong px-3 text-[13px] font-medium text-white">Reload</button>
      </div>
    </div>
  )
}

export const router = createBrowserRouter([
  {
    path: '/',
    element: <AppShell />,
    errorElement: <RouteError />,
    children: [{ errorElement: <RouteError inline />, children: [
      { index: true, element: g(<Overview />) },
      { path: 'signals', element: g(<Signals />) },
      { path: 'strategies', element: g(<Strategies />) },
      { path: 'strategies/:key', element: g(<StrategyDetail />) },
      { path: 'strategies/:key/:tab', element: g(<StrategyDetail />) },
      { path: 'screener', element: g(<Screener />) },
      { path: 'chart', element: <Navigate to="/chart/NIFTY50" replace /> },
      { path: 'chart/:symbol', element: g(<Chart />) },
      { path: 'portfolio', element: g(<Portfolio />) },
      { path: 'paper', element: g(<Paper />) },
      { path: 'paper/:key', element: g(<Paper />) },
      { path: 'market', element: <Navigate to="/market/movers" replace /> },
      { path: 'market/:tab', element: g(<Market />) },
      { path: 'smart-money', element: <Navigate to="/smart-money/today" replace /> },
      { path: 'smart-money/:tab', element: <SmartMoney /> },
      { path: 'intraday', element: <Intraday /> },
      { path: 'settings', element: <Navigate to="/settings/data" replace /> },
      { path: 'settings/:section', element: <Settings /> },
      { path: '*', element: <NotFound /> },
    ] }],
  },
], {
  // opt in to the React Router v7 behaviour now (silences the six future-flag warnings on every load)
  future: { v7_relativeSplatPath: true, v7_fetcherPersist: true, v7_normalizeFormMethod: true, v7_partialHydration: true, v7_skipActionErrorRevalidation: true },
})
