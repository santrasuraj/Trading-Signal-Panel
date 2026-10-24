// TanStack Query hooks (spec 6.1 / 7). Scan-derived data never goes stale on a timer: the ScanWatcher in the shell
// invalidates every query when /api/status reports a new scan_id. Only /api/status polls.

import { keepPreviousData, useMutation, useQuery, useQueryClient, type Query } from '@tanstack/react-query'
import { api, isFailure, type ChartParams, type ScreenerParams, type TradesParams } from './client'
import type { AppStatus, CurveRange, HoldingInput, IntradayResponse } from './types'

export const keys = {
  status: ['status'] as const,
  overview: ['overview'] as const,
  breadth: (range: string) => ['breadth', range] as const,
  strategies: (h?: string) => ['strategies', h ?? 'all'] as const,
  strategy: (k: string) => ['strategy', k] as const,
  curve: (k: string, r: string) => ['curve', k, r] as const,
  trades: (k: string, p: TradesParams) => ['trades', k, p] as const,
  signals: (p: object) => ['signals', p] as const,
  screener: (p: ScreenerParams) => ['screener', p] as const,
  sparklines: (s: string) => ['sparklines', s] as const,
  symbols: ['symbols'] as const,
  chart: (s: string, p: ChartParams) => ['chart', s, p] as const,
  stock: (s: string) => ['stock', s] as const,
  holdings: ['holdings'] as const,
  paper: ['paper'] as const,
  paperDetail: (k: string) => ['paper', k] as const,
  movers: ['market', 'movers'] as const,
  sectors: ['market', 'sectors'] as const,
  factors: ['market', 'factors'] as const,
  results: (d: number, r: boolean) => ['market', 'results', d, r] as const,
  scanHistory: ['scan', 'history'] as const,
  scanLog: (level: string) => ['scan', 'log', level] as const,
  fyers: (v: boolean) => ['fyers', v] as const,
  config: ['config'] as const,
  costs: (v: number) => ['costs', v] as const,
  dataHealth: ['data', 'health'] as const,
  intraday: ['intraday'] as const,
}

/** Never retry client errors or missing features; retry network/5xx twice with backoff. */
export function shouldRetry(count: number, err: unknown): boolean {
  if (isFailure(err)) {
    if (err.code === 'OFFLINE' || err.code === 'INTERNAL') return count < 2
    return false
  }
  return count < 1
}

// The query key type must be exactly the one useStatus uses: TanStack's Query is invariant in its key type.
export function statusInterval(q: Query<AppStatus, Error, AppStatus, typeof keys.status>): number {
  const s = q.state.data?.scan
  if (s && (s.running || s.state === 'starting')) return 1000
  if (typeof document !== 'undefined' && document.hidden) return 30000
  if (q.state.error && isFailure(q.state.error) && q.state.error.code === 'OFFLINE') return 5000
  return 10000
}

export const useStatus = () =>
  useQuery({
    queryKey: keys.status,
    queryFn: api.status,
    refetchInterval: statusInterval,
    refetchIntervalInBackground: true,
    staleTime: 0,
    retry: false,
  })

const scan = { staleTime: Infinity, placeholderData: keepPreviousData } as const

export const useOverview = () => useQuery({ queryKey: keys.overview, queryFn: api.overview, ...scan })
export const useBreadth = (range: '1y' | '3y' | 'all') => useQuery({ queryKey: keys.breadth(range), queryFn: () => api.breadth(range), ...scan })
export const useStrategies = (h?: string) => useQuery({ queryKey: keys.strategies(h), queryFn: () => api.strategies(h), ...scan })
export const useStrategy = (k: string) => useQuery({ queryKey: keys.strategy(k), queryFn: () => api.strategy(k), staleTime: Infinity, enabled: !!k })
export const useCurve = (k: string, r: CurveRange) => useQuery({ queryKey: keys.curve(k, r), queryFn: () => api.curve(k, r), ...scan, enabled: !!k })
export const useTrades = (k: string, p: TradesParams) => useQuery({ queryKey: keys.trades(k, p), queryFn: () => api.trades(k, p), ...scan, enabled: !!k })
export const useSignals = (p: { horizon?: string; allocations?: string }) =>
  useQuery({ queryKey: keys.signals(p), queryFn: () => api.signals(p), ...scan })
export const useScreener = (p: ScreenerParams) => useQuery({ queryKey: keys.screener(p), queryFn: () => api.screener(p), ...scan })
export const useSparklines = (symbols: string[]) => {
  const k = symbols.slice(0, 500).join(',')
  return useQuery({ queryKey: keys.sparklines(k), queryFn: () => api.sparklines(symbols), staleTime: Infinity, enabled: symbols.length > 0 })
}
export const useSymbols = () => useQuery({ queryKey: keys.symbols, queryFn: api.symbols, staleTime: Infinity })
export const useChart = (s: string, p: ChartParams) =>
  useQuery({ queryKey: keys.chart(s, p), queryFn: () => api.chart(s, p), staleTime: 10 * 60_000, placeholderData: keepPreviousData, enabled: !!s })
export const useStock = (s: string) => useQuery({ queryKey: keys.stock(s), queryFn: () => api.stock(s), staleTime: Infinity, enabled: !!s })
export const useHoldings = () => useQuery({ queryKey: keys.holdings, queryFn: api.holdings, staleTime: Infinity })
export const usePaper = () => useQuery({ queryKey: keys.paper, queryFn: api.paper, staleTime: Infinity })
export const usePaperDetail = (k: string) => useQuery({ queryKey: keys.paperDetail(k), queryFn: () => api.paperDetail(k), staleTime: Infinity, enabled: !!k })
export const useMovers = () => useQuery({ queryKey: keys.movers, queryFn: api.movers, ...scan })
export const useSectors = () => useQuery({ queryKey: keys.sectors, queryFn: api.sectors, ...scan })
export const useFactors = () => useQuery({ queryKey: keys.factors, queryFn: api.factors, ...scan })
export const useResults = (days: number, relevant: boolean) =>
  useQuery({ queryKey: keys.results(days, relevant), queryFn: () => api.results(days, relevant), ...scan })
export const useScanHistory = () => useQuery({ queryKey: keys.scanHistory, queryFn: () => api.scanHistory(60), ...scan })
export const useScanLog = (level: 'all' | 'error') => useQuery({ queryKey: keys.scanLog(level), queryFn: () => api.scanLog(200, level), staleTime: 5000 })
export const useFyersStatus = (verify: boolean) =>
  useQuery({ queryKey: keys.fyers(verify), queryFn: () => api.fyersStatus(verify), staleTime: verify ? 5 * 60_000 : 10_000, enabled: verify })
export const useConfig = () => useQuery({ queryKey: keys.config, queryFn: api.config, staleTime: 30_000 })
export const useCostPreview = (v: number) => useQuery({ queryKey: keys.costs(v), queryFn: () => api.costPreview(v), staleTime: Infinity, placeholderData: keepPreviousData, enabled: v > 0 })
export const useDataHealth = () => useQuery({ queryKey: keys.dataHealth, queryFn: api.dataHealth, staleTime: 30_000 })
/** Polls every 5 s only while a background re-run (POST /api/intraday/run) is in progress. */
export const useIntraday = () =>
  useQuery({ queryKey: keys.intraday, queryFn: api.intraday, staleTime: 60_000, refetchInterval: (q) => (q.state.data?.run?.running ? 5000 : false) })

export function useStartScan() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (update: boolean) => api.startScan(update),
    onSuccess: (r) => {
      qc.setQueryData<AppStatus>(keys.status, (s) => (s ? { ...s, scan: r.status } : s))
      void qc.invalidateQueries({ queryKey: keys.status })
    },
  })
}

export function useSaveHoldings() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (rows: HoldingInput[]) => api.saveHoldings(rows),
    onSuccess: () => void qc.invalidateQueries({ queryKey: keys.holdings }),
  })
}

export function useIntradayRun() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (update: boolean) => api.intradayRun(update),
    onSuccess: (r) => {
      qc.setQueryData<IntradayResponse>(keys.intraday, (d) => (d ? { ...d, run: r.run } : d))
      void qc.invalidateQueries({ queryKey: keys.intraday })
    },
  })
}

export const useImportFyers = () => useMutation({ mutationFn: api.importFyers })
export const useFyersLogin = () => useMutation({ mutationFn: api.fyersLogin })
export function useFyersComplete() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: api.fyersComplete,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: keys.status })
      void qc.invalidateQueries({ queryKey: ['fyers'] })
    },
  })
}
