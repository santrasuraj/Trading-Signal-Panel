// Market calendar, tax harvesting, options payoff and portfolio risk (web/api/routers/desk.py).

import { useQuery } from '@tanstack/react-query'
import { fetchJson } from './client'

export type CalKind = 'results' | 'dividend' | 'rights' | 'bonus' | 'split' | 'buyback' | 'expiry' | 'holiday' | 'meeting'
export interface CalEvent {
  date: string; kind: CalKind; symbol: string | null; company: string | null; detail: string; mine: boolean; watch: boolean
  price: number | null; amount?: number | null; yield_pct?: number | null; buy_by?: string; monthly?: boolean
}
export interface CalendarResponse { from: string; to: string; days: number; events: CalEvent[]; counts: Record<CalKind, number>; mine: number; watch: number; notes: string[] }

export interface TaxLot {
  id: number; symbol: string; qty: number | null; buy_price: number | null; buy_date: string | null; price: number | null
  value: number | null; gain: number | null; gain_pct: number | null; term: 'short' | 'long' | 'unknown'
  lt_from: string | null; days_to_lt: number | null; grandfathered: boolean
}
export interface HarvestRow { id: number; symbol: string; qty: number; of_qty: number; price: number; value: number; gain?: number; loss?: number; term?: string; tax_saved?: number; cost: number }
export interface Harvest { rows: HarvestRow[]; gain?: number; loss?: number; tax_saved: number; cost: number; net: number; worth_it: boolean }
export interface TaxPosition { tax: number; st_net: number; lt_net: number; taxable_lt: number; exempt: number; exempt_used: number; exempt_left: number; carry_forward: number }
export interface TaxResponse {
  fy: string; today: string; fy_end: string; trade_by: string; days_left: number
  rates: { stcg_pct: number; ltcg_pct: number; exempt: number }
  booked: { st: number; lt: number; source: 'input' | 'fills'; fills: { st: number; lt: number; trades: number } }
  position: TaxPosition; lots: TaxLot[]; unrealised: { st: number; lt: number; unknown: number }
  harvest_gains: Harvest; harvest_losses: Harvest
  wait: { id: number; symbol: string; qty: number; gain: number; lt_from: string; days: number; tax_saved: number }[]
  notes: string[]; price_source: string
}

export interface PayoffLegIn { kind: 'CE' | 'PE' | 'FUT'; side: 'buy' | 'sell'; strike: number | null; lots: number; price?: number | null; iv_pct?: number | null }
export interface PayoffLegOut { kind: 'CE' | 'PE' | 'FUT'; side: 'buy' | 'sell'; strike: number; qty: number; lots: number; price: number; iv_pct: number; ltp: number | null; bid: number | null; ask: number | null }
export interface Payoff {
  symbol: string; expiry: string; time: string; spot: number; forward: number; lot: number; days_to_expiry: number; atm_iv_pct: number
  legs: PayoffLegOut[]; days: number; iv_shift: number; grid: number[]; at_expiry: number[]; today: number[]
  breakevens: number[]; max_profit: number | null; max_loss: number | null; premium: number; kind: 'credit' | 'debit' | 'none'
  greeks: { delta: number; gamma: number; theta: number; vega: number }; pop_pct: number | null; one_sd: [number, number]
  reward_risk: number | null; note: string
}

export interface RiskPosition { symbol: string; qty: number; price: number; value: number; at_risk: number; weight_pct: number; industry: string; beta: number | null }
export interface RiskLot { symbol: string; qty: number; price: number; stop: number; stop_pct: number; stop_hit: boolean; at_risk: number; loss_if_hit: number | null }
export interface RiskResponse {
  empty: boolean; value?: number; count?: number; positions: RiskPosition[]; lots: RiskLot[]; at_risk?: number; at_risk_pct?: number
  concentration?: { top_pct: number; top_symbol: string; top5_pct: number; effective_n: number | null; industries: { industry: string; weight_pct: number }[] }
  beta?: number | null
  risk?: { days?: number; var95?: number; var95_pct?: number; es95?: number | null; var99?: number; var99_pct?: number; es99?: number | null; vol_pct?: number; covered_pct?: number; max_drawdown_pct?: number | null; nifty_vol_pct?: number | null }
  worst_day?: { date: string; pct: number; amount: number; nifty_pct: number | null } | null
  shocks?: { nifty_pct: number; pct: number; amount: number }[]
  correlation?: { symbols: string[]; matrix: (number | null)[][]; high_pairs: { a: string; b: string; corr: number }[]; average: number | null }
  flags?: string[]; notes: string[]; price_source?: string; as_of?: string
}

export const deskApi = {
  calendar: (days: number) => fetchJson<CalendarResponse>(`/api/calendar?days=${days}`),
  tax: (st: number | null, lt: number | null) => {
    const p = new URLSearchParams()
    if (st != null) p.set('st', String(st))
    if (lt != null) p.set('lt', String(lt))
    const qs = p.toString()
    return fetchJson<TaxResponse>(`/api/tax${qs ? `?${qs}` : ''}`)
  },
  payoff: (body: { symbol: string; expiry?: string; legs: PayoffLegIn[]; days: number; iv_shift: number; lot?: number | null }) =>
    fetchJson<Payoff>('/api/options/payoff', { method: 'POST', body: JSON.stringify(body) }),
  risk: () => fetchJson<RiskResponse>('/api/risk'),
}

export const useCalendar = (days: number) => useQuery({ queryKey: ['calendar', days], queryFn: () => deskApi.calendar(days), staleTime: 10 * 60_000 })
export const useTax = (st: number | null, lt: number | null) => useQuery({ queryKey: ['tax', st, lt], queryFn: () => deskApi.tax(st, lt), staleTime: 60_000 })
export const useRisk = () => useQuery({ queryKey: ['risk'], queryFn: deskApi.risk, staleTime: 60_000 })
