// Smart money API (docs/smart_money_spec.md): types mirroring web/api/models/smart_money.py, fetchers and TanStack
// Query hooks. Data changes only when a refresh finishes (SmartMoney.tsx invalidates ['smart-money'] then); /status
// polls every 3 s only while a refresh runs.

import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { fetchJson } from './client'
import type { ISODate, ISODateTime } from './types'
import { DASH, MINUS, num, ok } from '@/lib/format'

// ------------------------------------------------------------------ types (mirror web/api/models/smart_money.py)
export type SmCategory = 'fii' | 'mf' | 'insurance' | 'bank' | 'pension' | 'promoter' | 'famous' | 'broker' | 'other'
export type SmCategoryFilter = 'all' | 'big' | 'institutions' | SmCategory
export type SmDealKind = 'bulk' | 'block' | 'both'
export type SmDealSide = 'BUY' | 'SELL' | 'FLAT'
export type SmModeKind = 'market' | 'pledge' | 'pledge_invoked' | 'off_market' | 'esop' | 'gift' | 'inter_se' | 'preferential' | 'other'
export type SmEventType = 'deal_buy' | 'deal_sell' | 'insider_buy' | 'insider_sell' | 'insider_exit' | 'pledge_invoked'
  | 'new_holder' | 'holder_added' | 'holder_cut' | 'holder_dropped' | 'category_up' | 'category_down' | 'category_exit'
export type SmExitKind = 'full_exit' | 'below_1pct' | 'sold_part' | 'category_exit'
export type SmSourceKind = 'bulk' | 'block' | 'insider' | 'shareholding'
export type SmRunState = 'idle' | 'running' | 'done' | 'failed'
export type SmSourceState = 'ok' | 'partial' | 'failed' | 'skipped' | 'never'

export interface SmFreshness {
  deals: ISODate | null; insider: ISODate | null; flows: ISODate | null; holdings_period: ISODate | null
  refreshed_at: ISODateTime | null; stale: boolean
}
export interface SmRefreshRun {
  state: SmRunState; running: boolean; message: string | null; started_at: ISODateTime | null
  finished_at: ISODateTime | null; errors: string[]
}
export interface SmSource {
  status: SmSourceState; message: string | null; rows_added: number; last_ok_at: ISODateTime | null; latest_date: ISODate | null
}
export interface SmSources { deals: SmSource; insider: SmSource; flows: SmSource; holdings: SmSource }
export interface SmStatus { run: SmRefreshRun; freshness: SmFreshness; sources: SmSources; errors: string[] }

export interface SmDeal {
  id: string; date: ISODate; symbol: string; company: string | null; kind: SmDealKind; side: SmDealSide
  client: string; client_key: string; category: SmCategory; category_label: string; sub_label: string | null
  investor: string | null; round_trip: boolean; buy_qty: number; sell_qty: number; net_qty: number
  buy_value: number; sell_value: number; net_value: number; avg_price: number | null; pct_equity: number | null
  counterparties: string[]
}
export interface SmDealCounts { buys: number; sells: number; intraday: number; by_category: Record<string, number> }
export interface SmDealsResponse {
  freshness: SmFreshness; days: number; since: ISODate | null; until: ISODate | null; intraday: boolean
  total: number; page: number; page_size: number; rows: SmDeal[]; counts: SmDealCounts; note: string
}

export interface SmInsiderTrade {
  id: string; symbol: string; company: string | null; person: string; role: 'promoter' | 'insider' | 'other'
  person_category: string | null; category: SmCategory; category_label: string; sub_label: string | null
  investor: string | null; side: 'BUY' | 'SELL' | null; mode: string | null; mode_kind: SmModeKind; is_market: boolean
  qty: number | null; value: number | null; avg_price: number | null; before_pct: number | null; after_pct: number | null
  change_pts: number | null; before_shares: number | null; after_shares: number | null; trade_from: ISODate | null
  trade_to: ISODate | null; disclosed: ISODate | null; delay_days: number | null; fully_exited: boolean; xbrl: string | null
}
export interface SmInsiderCounts { buys: number; sells: number; buy_value: number; sell_value: number; pledge_invoked: number; full_exits: number }
export interface SmInsiderResponse {
  freshness: SmFreshness; days: number; since: ISODate | null; until: ISODate | null; total: number; page: number
  page_size: number; rows: SmInsiderTrade[]; counts: SmInsiderCounts; note: string
}

export interface SmEvent {
  id: string; date: ISODate; symbol: string; company: string | null; event: SmEventType; direction: 'up' | 'down'
  source: SmSourceKind; who: string | null; investor: string | null; category: SmCategory; category_label: string
  sub_label: string | null; value: number | null; qty: number | null; pct_before: number | null; pct_after: number | null
  change_pts: number | null; pct_equity: number | null; period: ISODate | null; prev_period: ISODate | null
  exit_kind: SmExitKind | null; text: string
}
export interface SmStock {
  symbol: string; company: string | null; direction: 'up' | 'down' | 'mixed'; up_events: number; down_events: number
  up_score: number; down_score: number; deal_buy_value: number; deal_sell_value: number; deal_net_value: number
  inst_buyers: number; inst_sellers: number; famous_buyers: string[]; famous_sellers: string[]
  insider_buy_value: number; insider_sell_value: number; promoter_buying: boolean; promoter_selling: boolean
  pledge_invoked: boolean; exits: number; fii_chg_pts: number | null; dii_chg_pts: number | null
  mf_chg_pts: number | null; promoter_chg_pts: number | null; period: ISODate | null; last_date: ISODate; reasons: string[]
}
export interface SmHoldingsResponse {
  freshness: SmFreshness; view: 'accumulating' | 'exiting' | 'all'; days: number; since: ISODate | null
  latest_period: ISODate | null; previous_period: ISODate | null; coverage: number; stocks: SmStock[]
  events: SmEvent[]; note: string
}
export interface SmFlowDay {
  date: ISODate; fii_buy_cr: number | null; fii_sell_cr: number | null; fii_net_cr: number | null
  dii_buy_cr: number | null; dii_sell_cr: number | null; dii_net_cr: number | null
}
export interface SmFlowsResponse {
  freshness: SmFreshness; days: number; since: ISODate | null; first_date: ISODate | null; rows: SmFlowDay[]
  fii_net_cr_total: number | null; dii_net_cr_total: number | null; fii_streak: number; dii_streak: number; note: string
}
export interface SmKpis {
  days: number; since: ISODate | null; big_buy_value: number; big_sell_value: number; inst_net_value: number
  stocks_bought: number; stocks_sold: number; insider_buy_value: number; insider_sell_value: number; exits: number
  intraday_rows: number; fii_net_cr: number | null; dii_net_cr: number | null; flows_date: ISODate | null
}
export interface SmOverview {
  freshness: SmFreshness; run: SmRefreshRun; days: number; kpis: SmKpis; top_bought: SmStock[]; top_sold: SmStock[]
  latest_deals_date: ISODate | null; latest_deals: SmDeal[]; latest_insider: SmInsiderTrade[]; exits: SmEvent[]
  flows: SmFlowDay[]; has_data: boolean; errors: string[]; note: string
}
export interface SmHoldingPeriod {
  period: ISODate; broadcast: ISODate | null; source: 'xbrl' | 'master'; total_shares: number | null
  promoter_pct: number | null; public_pct: number | null; fii_pct: number | null; dii_pct: number | null
  mf_pct: number | null; insurance_pct: number | null; banks_pct: number | null; pension_pct: number | null; aif_pct: number | null
}
export interface SmHolder {
  holder: string; holder_key: string; group: 'promoter' | 'public'; category: SmCategory; category_label: string
  sub_label: string | null; investor: string | null; pct: number | null; prev_pct: number | null
  change_pts: number | null; shares: number | null; status: 'new' | 'added' | 'cut' | 'same' | 'dropped'
}
export interface SmStockResponse {
  symbol: string; company: string | null; freshness: SmFreshness; days: number; has_data: boolean
  summary: SmStock | null; deals: SmDeal[]; insider: SmInsiderTrade[]; holdings: SmHoldingPeriod[]
  holders_period: ISODate | null; holders_prev_period: ISODate | null; holders: SmHolder[]; events: SmEvent[]; note: string
}
export interface SmRefreshAccepted { accepted: boolean; run: SmRefreshRun }

// ------------------------------------------------------------------ params
export interface SmDealsParams {
  days: number; side?: 'all' | 'buy' | 'sell'; kind?: 'all' | 'bulk' | 'block'; category?: SmCategoryFilter
  symbol?: string; intraday?: boolean; page?: number; page_size?: number
}
export interface SmInsiderParams {
  days: number; side?: 'all' | 'buy' | 'sell'; category?: 'all' | 'promoter' | 'insider'; mode?: 'market' | 'all'
  symbol?: string; page?: number; page_size?: number
}
export interface SmHoldingsParams { view: 'accumulating' | 'exiting' | 'all'; days?: number; category?: SmCategoryFilter; symbol?: string }

// ------------------------------------------------------------------ fetchers (client.ts's qs() is private: own copy)
function qs(params: Record<string, string | number | boolean | null | undefined>): string {
  const sp = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== '') sp.set(k, String(v))
  const s = sp.toString()
  return s ? `?${s}` : ''
}

const BASE = '/api/smart-money'
export const smApi = {
  status: () => fetchJson<SmStatus>(`${BASE}/status`),
  overview: (days = 30) => fetchJson<SmOverview>(`${BASE}/overview${qs({ days })}`),
  deals: (p: SmDealsParams) => fetchJson<SmDealsResponse>(`${BASE}/deals${qs({ ...p })}`),
  insider: (p: SmInsiderParams) => fetchJson<SmInsiderResponse>(`${BASE}/insider${qs({ ...p })}`),
  holdings: (p: SmHoldingsParams) => fetchJson<SmHoldingsResponse>(`${BASE}/holdings${qs({ ...p })}`),
  flows: (days = 30) => fetchJson<SmFlowsResponse>(`${BASE}/flows${qs({ days })}`),
  stock: (symbol: string, days = 365) => fetchJson<SmStockResponse>(`${BASE}/stock/${encodeURIComponent(symbol)}${qs({ days })}`),
  refresh: (days = 365) => fetchJson<SmRefreshAccepted>(`${BASE}/refresh`, { method: 'POST', body: JSON.stringify({ days }) }),
}

// ------------------------------------------------------------------ hooks
export const smKeys = {
  all: ['smart-money'] as const,
  status: ['smart-money', 'status'] as const,
  overview: (days: number) => ['smart-money', 'overview', days] as const,
  deals: (p: SmDealsParams) => ['smart-money', 'deals', p] as const,
  insider: (p: SmInsiderParams) => ['smart-money', 'insider', p] as const,
  holdings: (p: SmHoldingsParams) => ['smart-money', 'holdings', p] as const,
  flows: (days: number) => ['smart-money', 'flows', days] as const,
  stock: (symbol: string, days: number) => ['smart-money', 'stock', symbol, days] as const,
}

const keep = { staleTime: 5 * 60_000, placeholderData: keepPreviousData } as const

export const useSmStatus = () =>
  useQuery({ queryKey: smKeys.status, queryFn: smApi.status, staleTime: 2000, refetchInterval: (q) => (q.state.data?.run.running ? 3000 : false) })
export const useSmOverview = (days: number) => useQuery({ queryKey: smKeys.overview(days), queryFn: () => smApi.overview(days), ...keep })
export const useSmDeals = (p: SmDealsParams, enabled = true) => useQuery({ queryKey: smKeys.deals(p), queryFn: () => smApi.deals(p), ...keep, enabled })
export const useSmInsider = (p: SmInsiderParams) => useQuery({ queryKey: smKeys.insider(p), queryFn: () => smApi.insider(p), ...keep })
export const useSmHoldings = (p: SmHoldingsParams) => useQuery({ queryKey: smKeys.holdings(p), queryFn: () => smApi.holdings(p), ...keep })
export const useSmFlows = (days: number) => useQuery({ queryKey: smKeys.flows(days), queryFn: () => smApi.flows(days), ...keep })
/** No keepPreviousData: switching symbols on the chart must never show the previous stock's investors. */
export const useSmStock = (symbol: string, days = 365) =>
  useQuery({ queryKey: smKeys.stock(symbol, days), queryFn: () => smApi.stock(symbol, days), staleTime: 5 * 60_000, enabled: !!symbol })

export function useSmRefresh() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (days: number) => smApi.refresh(days),
    onSuccess: (r) => {
      qc.setQueryData<SmStatus>(smKeys.status, (s) => (s ? { ...s, run: r.run } : s))
      void qc.invalidateQueries({ queryKey: smKeys.status })
    },
  })
}

// ------------------------------------------------------------------ labels and formatting
export const CATEGORY_LABEL: Record<SmCategory, string> = {
  fii: 'FII/FPI', mf: 'Mutual fund', insurance: 'Insurance', bank: 'Bank/NBFC', pension: 'Pension/sovereign',
  promoter: 'Promoter', famous: 'Well-known investor', broker: 'Broker/prop', other: 'Other',
}
export const CATEGORY_FILTERS: { id: SmCategoryFilter; label: string }[] = [
  { id: 'all', label: 'Everyone' }, { id: 'big', label: 'Big money (institutions, promoters, well-known)' },
  { id: 'institutions', label: 'Institutions only' }, { id: 'fii', label: 'FII/FPI' }, { id: 'mf', label: 'Mutual funds' },
  { id: 'insurance', label: 'Insurance' }, { id: 'bank', label: 'Banks/NBFCs' }, { id: 'pension', label: 'Pension/sovereign' },
  { id: 'promoter', label: 'Promoters' }, { id: 'famous', label: 'Well-known investors' }, { id: 'broker', label: 'Brokers/prop' },
  { id: 'other', label: 'Others' },
]
/** Sub-labels the server writes (scanner/smart_money.py ODI_LABEL / LIKELY_PROMOTER); the badges treat them specially. */
export const ODI_LABEL = 'ODI/arbitrage desk - often hedging clients, weak signal'
export const LIKELY_PROMOTER = 'Likely promoter (name match)'

/** Deal sizes: ₹32.26 cr / ₹62.5 L / ₹9,500 (signed adds '+'). */
export function fmtInr(v: number | null | undefined, signed = false): string {
  if (!ok(v)) return DASH
  const a = Math.abs(v)
  const s = v < 0 ? MINUS : signed && v > 0 ? '+' : ''
  if (a >= 1e7) return `${s}₹${num(a / 1e7, 2)} cr`
  if (a >= 1e5) return `${s}₹${num(a / 1e5, 1)} L`
  return `${s}₹${num(a, 0)}`
}
/** FII/DII figures, already in crore: +₹2,358 cr / −₹1,888 cr. */
export function fmtCr(v: number | null | undefined, signed = true): string {
  if (!ok(v)) return DASH
  const s = v < 0 ? MINUS : signed && v > 0 ? '+' : ''
  return `${s}₹${num(Math.abs(v), 0)} cr`
}
