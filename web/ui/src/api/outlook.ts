// Outlook API (web/api/routers/outlook.py): types mirroring web/api/models/outlook.py and the query hook.
// Base rates of similar setups, ranges, levels, signals and derivatives positioning for one symbol - never a forecast.

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { fetchJson } from './client'
import type { ISODate, ISODateTime } from './types'

export type OlVerdict = 'better' | 'worse' | 'same' | 'unknown'
export type OlBias = 'bullish' | 'bearish' | 'neutral'
export type OlSource = 'strategy' | 'pattern' | 'chart_pattern' | 'trend' | 'volume' | 'options' | 'futures' | 'intraday' | 'event'

export interface OlFeature { feature: string; code: number; label: string; short: string }
export interface OlDist {
  n: number; mean_pct: number | null; median_pct: number | null; up_pct: number | null
  p10_pct: number | null; p25_pct: number | null; p75_pct: number | null; p90_pct: number | null
  excess_pct: number | null; beat_pct: number | null; t: number | null
}
export interface OlHorizon {
  days: number; setup: OlDist | null; base: OlDist | null; verdict: OlVerdict; after_cost_excess_pct: number | null
  price_p10: number | null; price_p25: number | null; price_median: number | null; price_p75: number | null; price_p90: number | null
  own_n: number | null; own_median_pct: number | null; own_up_pct: number | null
}
export interface OlTouch { days: number; pct: number; up_pct: number | null; down_pct: number | null }
export interface OlAnalogs {
  level: string[]; dropped: string[]; n: number; months: number; first_day: ISODate | null; last_day: ISODate | null
  universe: string; horizons: OlHorizon[]; touch: OlTouch; base_touch: OlTouch; cost_pct: number; generated_at: ISODateTime | null
}
export interface OlRange {
  source: 'options' | 'realized' | 'analogs'; label: string; days: number; low: number | null; high: number | null
  pct: number | null; prob_pct: number | null
}
export interface OlExpected {
  close: number | null; atr: number | null; atr_pct: number | null; realized_vol_pct: number | null
  iv_pct: number | null; iv_expiry: ISODate | null; ranges: OlRange[]
}
export interface OlLevel { price: number; label: string; kind: string; dist_pct: number | null; strength: number | null }
export interface OlScenarios { above: OlLevel[]; below: OlLevel[]; flips: string[] }
export interface OlSignal {
  source: OlSource; bias: OlBias; title: string; detail: string; tested: string | null
  tone: 'good' | 'neutral' | 'bad' | null; when: ISODate | null
}
export interface OlChain {
  symbol: string; expiry: ISODate; time: ISODateTime; stale: boolean; day: ISODate; old: boolean
  spot: number | null; forward: number | null; days_to_expiry: number | null; pcr_oi: number | null
  max_pain: number | null; max_pain_gap_pct: number | null; atm_iv_pct: number | null; expected_move_pct: number | null
  range_low: number | null; range_high: number | null; call_wall: number | null; put_wall: number | null; readings: string[]
}
export interface OlFutures {
  date: ISODate; close: number | null; chg_pct: number | null; oi_chg_pct: number | null; basis_pct: number | null
  buildup: string | null; pcr: number | null; call_wall: number | null; put_wall: number | null
}
export interface OvCandidate {
  side: 'ce' | 'pe'; strike: number | null; moneyness: string; premium: number | null; bid: number | null; ask: number | null
  quoted: boolean; spread_pct: number | null; oi: number | null; iv_pct: number | null; delta: number | null
  breakeven: number | null; breakeven_pct: number | null; fair: number | null; edge_pct: number | null
  prob_profit_pct: number | null; prob_itm_pct: number | null; exp_return_pct: number | null; ok: boolean; fails: string[]
}
export interface OvCheck { name: string; ok: boolean; detail: string }
export interface OvTrack {
  recorded: number; settled: number; open: number; buys: number; buy_wins: number; buy_avg_return_pct: number | null
  no_trades: number; atm_call_avg_return_pct: number | null; atm_put_avg_return_pct: number | null; first_day: ISODate | null
}
export type OvKind = 'BUY_CALL' | 'BUY_PUT' | 'NO_TRADE' | 'NO_DATA'
export interface OptVerdict {
  verdict: OvKind; headline: string; symbol: string | null; expiry: ISODate | null; chain_time: ISODateTime | null
  spot: number | null; days_to_expiry: number | null; trading_days: number; iv_pct: number | null; hv20_pct: number | null
  hv252_pct: number | null; vol_used_pct: number | null; iv_vs_hv: number | null
  direction: { bias: 'bullish' | 'bearish' | 'none'; reasons: string[] }
  pick: OvCandidate | null; calls: OvCandidate[]; puts: OvCandidate[]; checks: OvCheck[]
  exit: { stop_underlying: number | null; target_underlying: number | null; note: string } | null
  edge_min_pct: number; prob_min_pct: number; cost_pct: number; track: OvTrack; note: string
}
export interface OlDerivatives { fno: boolean; options_symbol: string | null; chain: OlChain | null; futures: OlFutures | null; verdict: OptVerdict | null }
export interface BmPledge {
  quarter: ISODate | null; broadcast: ISODateTime | null; promoter_pct: number | null; promoter_pledged_pct: number | null
  promoter_pledged_total_pct: number | null; promoter_pledged_shares: number | null; depository_pledged_pct: number | null
  depository_pledged_shares: number | null; source: string
}
export interface BmFiling {
  filed: ISODateTime | null; period: string | null; acquirer: string; side: 'BUY' | 'SELL'; mode: string | null
  security: string | null; promoter: boolean; regulation: string | null; shares: number | null; pct: number | null
  after_pct: number | null; link: string | null
}
export interface BmTested { n: number; months: number; verdict: string; excess_pct: number | null; hit_pct: number | null; t: number | null; after_cost_pct: number | null }
export interface BmDelivery {
  date: ISODate; deliv_pct: number | null; deliv_pct_avg20: number | null; deliv_qty: number | null; deliv_ratio: number | null
  state: 'accumulation' | 'distribution' | 'normal'
  events: { date: ISODate; kind: 'accumulation' | 'distribution'; ratio: number | null; deliv_pct: number | null; chg_pct: number | null }[]
  tested_accumulation: BmTested | null; tested_distribution: BmTested | null; rule: string | null
}
export interface BigMoney {
  pledge: BmPledge | null; pledge_checked: boolean; filings: BmFiling[]; filings_note: string | null
  ban: { trade_date: ISODate | null; in_ban: boolean; symbols: string[]; source: string } | null
  delivery: BmDelivery | null; refreshed_at: ISODateTime | null; refreshing: boolean; note: string
}
export interface OlEvent { date: ISODate; kind: 'results' | 'expiry' | 'corporate_action'; label: string }
export interface OutlookResponse {
  symbol: string; kind: 'stock' | 'etf' | 'index'; date: ISODate; close: number | null; provisional: boolean
  setup: OlFeature[]; headline: string; analogs: OlAnalogs | null; study_hint: string | null; expected: OlExpected
  scenarios: OlScenarios; signals: OlSignal[]; derivatives: OlDerivatives; big_money: BigMoney; events: OlEvent[]; note: string
}

/** Changes with a scan, a new option chain or F&O day: refetched every 2 minutes while the market is open, and every
 *  3 s while a big-money refresh runs. */
export const useOutlook = (symbol: string, live: boolean) =>
  useQuery({
    queryKey: ['outlook', symbol],
    queryFn: () => fetchJson<OutlookResponse>(`/api/outlook/${encodeURIComponent(symbol)}`),
    enabled: !!symbol,
    staleTime: 60_000,
    refetchInterval: (q) => (q.state.data?.big_money.refreshing ? 3000 : live ? 120_000 : false),
  })

/** Fetch this symbol's NSE disclosures (pledges, acquisition filings, F&O ban list) in the background. */
export function useBigMoneyRefresh(symbol: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => fetchJson<{ accepted: boolean; running: boolean; symbol: string }>(`/api/outlook/${encodeURIComponent(symbol)}/big-money/refresh`, { method: 'POST' }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['outlook', symbol] }),
  })
}
