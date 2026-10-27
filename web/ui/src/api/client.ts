// Typed client for the Quant Desk API (spec 7). Every non-GET request carries X-Quant-Desk: 1 (CSRF guard);
// errors are parsed from the {"error": {...}} envelope into ApiFailure; network failures become code 'OFFLINE',
// which drives the "server unreachable" banner.

import type {
  ApiError, AppStatus, BreadthResponse, ChartResponse, ChartRange, ChartTf, ClientErrorCode, ConfigResponse, CostPreviewResponse,
  CurveRange, CurveResponse, DataHealth, FactorsResponse, FyersImportResponse, FyersLoginCompleteResponse, FyersLoginMode,
  FyersLoginResponse, FyersStatus, HealthResponse, HoldingInput, HoldingsPutResponse, HoldingsResponse, IndicatorId, IntradayResponse, IntradayRunAccepted, IntradaySignalsResponse, QuotesResponse, TrackRecordResponse, TrackState,
  MoversResponse, OverviewResponse, PaperDetail, PaperListResponse, ResultsResponse, ScanHistoryResponse, ScanLogResponse,
  ScanStartResponse, ScreenerResponse, SectorsResponse, SignalsResponse, SparklinesResponse, StockSnapshot, StrategyDetail,
  StrategyListResponse, SymbolsResponse, TradesPage,
} from './types'

export class ApiFailure extends Error {
  code: ClientErrorCode
  hint: string | null
  status: number
  details: Record<string, unknown> | null
  constructor(code: ClientErrorCode, message: string, status = 0, hint: string | null = null, details: Record<string, unknown> | null = null) {
    super(message)
    this.name = 'ApiFailure'
    this.code = code
    this.hint = hint
    this.status = status
    this.details = details
  }
}

export const isFailure = (e: unknown): e is ApiFailure => e instanceof ApiFailure

const BASE = ''

export async function fetchJson<T>(path: string, init: RequestInit = {}): Promise<T> {
  const method = (init.method ?? 'GET').toUpperCase()
  const headers = new Headers(init.headers)
  headers.set('Accept', 'application/json')
  if (method !== 'GET') {
    headers.set('X-Quant-Desk', '1')
    if (init.body != null && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json')
  }
  let res: Response
  try {
    res = await fetch(BASE + path, { ...init, method, headers, cache: 'no-store' })
  } catch (e) {
    if (e instanceof DOMException && e.name === 'AbortError') throw e
    throw new ApiFailure('OFFLINE', "Can't reach the local server (127.0.0.1:8600).", 0, 'Is 3_dashboard.bat still running?')
  }
  const text = await res.text()
  let body: unknown = null
  if (text) {
    try {
      body = JSON.parse(text)
    } catch {
      body = null
    }
  }
  if (!res.ok) {
    const env = body as Partial<ApiError> | null
    if (env && env.error && typeof env.error === 'object') {
      const e = env.error
      throw new ApiFailure(e.code, e.message, res.status, e.hint ?? null, e.details ?? null)
    }
    // 502/503/504, or a 5xx with no envelope: the Vite dev proxy answers a refused connection with an empty 500.
    // Real API 500s always carry the JSON envelope (web/api/errors.py), so they are handled above.
    if (res.status === 502 || res.status === 503 || res.status === 504 || (body == null && res.status >= 500)) {
      throw new ApiFailure('OFFLINE', "Can't reach the local server (127.0.0.1:8600).", res.status, 'Is 3_dashboard.bat still running?')
    }
    throw new ApiFailure('INTERNAL', `Request failed (${res.status})`, res.status)
  }
  if (body == null) throw new ApiFailure('INTERNAL', 'The server returned an empty or invalid response.', res.status)
  return body as T
}

function qs(params: Record<string, string | number | boolean | null | undefined>): string {
  const sp = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== '') sp.set(k, String(v))
  const s = sp.toString()
  return s ? `?${s}` : ''
}

const enc = encodeURIComponent
const body = (o: unknown) => JSON.stringify(o)

export interface TradesParams { page?: number; page_size?: number; outcome?: 'all' | 'win' | 'loss'; reason?: string; symbol?: string; sort?: string }
export interface ScreenerParams { preset: string; industry?: string; min_turnover_cr?: number; in_models?: boolean; results_within?: number }
export interface ChartParams { tf: ChartTf; range: ChartRange; indicators: IndicatorId[] }

export const api = {
  health: () => fetchJson<HealthResponse>('/api/health'),
  status: () => fetchJson<AppStatus>('/api/status'),
  overview: () => fetchJson<OverviewResponse>('/api/overview'),
  breadth: (range: '1y' | '3y' | 'all') => fetchJson<BreadthResponse>(`/api/market/breadth${qs({ range })}`),

  strategies: (horizon?: string) => fetchJson<StrategyListResponse>(`/api/strategies${qs({ horizon })}`),
  strategy: (key: string) => fetchJson<StrategyDetail>(`/api/strategies/${enc(key)}`),
  curve: (key: string, range: CurveRange) => fetchJson<CurveResponse>(`/api/strategies/${enc(key)}/curve${qs({ range })}`),
  trades: (key: string, p: TradesParams) => fetchJson<TradesPage>(`/api/strategies/${enc(key)}/trades${qs({ ...p })}`),

  signals: (p: { horizon?: string; allocations?: string }) => fetchJson<SignalsResponse>(`/api/signals${qs(p)}`),
  screener: (p: ScreenerParams) => fetchJson<ScreenerResponse>(`/api/screener${qs({ ...p })}`),
  sparklines: (symbols: string[], days = 60) =>
    fetchJson<SparklinesResponse>(`/api/sparklines${qs({ symbols: symbols.slice(0, 500).join(','), days })}`),
  symbols: () => fetchJson<SymbolsResponse>('/api/symbols'),
  chart: (symbol: string, p: ChartParams) =>
    fetchJson<ChartResponse>(`/api/chart/${enc(symbol)}${qs({ tf: p.tf, range: p.range, indicators: p.indicators.join(',') })}`),
  stock: (symbol: string) => fetchJson<StockSnapshot>(`/api/stock/${enc(symbol)}`),

  holdings: () => fetchJson<HoldingsResponse>('/api/holdings'),
  saveHoldings: (rows: HoldingInput[]) => fetchJson<HoldingsPutResponse>('/api/holdings', { method: 'PUT', body: body({ rows }) }),
  importFyers: () => fetchJson<FyersImportResponse>('/api/holdings/import/fyers', { method: 'POST' }),

  paper: () => fetchJson<PaperListResponse>('/api/paper'),
  quotes: (symbols: string[]) => fetchJson<QuotesResponse>(`/api/quotes${qs({ symbols: symbols.join(',') })}`),
  trackRecord: (p: { strategy?: string; state?: TrackState } = {}) => fetchJson<TrackRecordResponse>(`/api/signals/track-record${qs(p)}`),
  paperDetail: (key: string) => fetchJson<PaperDetail>(`/api/paper/${enc(key)}`),

  movers: () => fetchJson<MoversResponse>('/api/market/movers'),
  sectors: () => fetchJson<SectorsResponse>('/api/market/sectors'),
  factors: () => fetchJson<FactorsResponse>('/api/market/factors'),
  results: (days = 14, relevant = false) => fetchJson<ResultsResponse>(`/api/market/results${qs({ days, relevant })}`),

  startScan: (update: boolean) => fetchJson<ScanStartResponse>('/api/scan', { method: 'POST', body: body({ update }) }),
  scanHistory: (limit = 60) => fetchJson<ScanHistoryResponse>(`/api/scan/history${qs({ limit })}`),
  scanLog: (lines = 200, level: 'all' | 'error' = 'all') => fetchJson<ScanLogResponse>(`/api/scan/log${qs({ lines, level })}`),

  fyersStatus: (verify = false) => fetchJson<FyersStatus>(`/api/fyers/status${qs({ verify })}`),
  fyersLogin: (mode: FyersLoginMode) => fetchJson<FyersLoginResponse>('/api/fyers/login', { method: 'POST', body: body({ mode }) }),
  fyersComplete: (redirect_url: string) =>
    fetchJson<FyersLoginCompleteResponse>('/api/fyers/login/complete', { method: 'POST', body: body({ redirect_url }) }),

  config: () => fetchJson<ConfigResponse>('/api/config'),
  costPreview: (value: number) => fetchJson<CostPreviewResponse>(`/api/costs/preview${qs({ value: Math.round(value) })}`),
  dataHealth: () => fetchJson<DataHealth>('/api/data/health'),
  intraday: () => fetchJson<IntradayResponse>('/api/intraday'),
  intradaySignals: () => fetchJson<IntradaySignalsResponse>('/api/intraday/signals'),
  intradayRun: (update = true) => fetchJson<IntradayRunAccepted>('/api/intraday/run', { method: 'POST', body: body({ update }) }),
}
