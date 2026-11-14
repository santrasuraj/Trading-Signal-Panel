// Company page (GET /api/company/{symbol}, GET /api/company/{symbol}/documents; web/api/services/company_svc.py,
// documents_svc.py): ten-plus years of financials, peers and the filings timeline, all from NSE's filings.

import { useQuery } from '@tanstack/react-query'
import { fetchJson } from '@/api/client'

export type LineKind = 'cr' | 'pct' | 'x' | 'num'
export interface StatementRow { key: string; label: string; kind: LineKind; values: (number | null)[] }
export interface Statement {
  periods: string[]; rows: StatementRow[]
  /** Per period: when it was filed, the source (xbrl = the XBRL filing, nse = NSE's own line items) and its link. */
  sources: { filed: string | null; src: string | null; url: string | null }[]
}
export interface PeerRow {
  symbol: string; company: string | null; price: number | null; market_cap_cr: number | null; pe: number | null; pb: number | null
  roce: number | null; roe: number | null; de: number | null; opm: number | null; sales_cagr_3y: number | null; profit_cagr_3y: number | null
  sales_ttm_cr: number | null; profit_ttm_cr: number | null; dividend_yield: number | null
}
export interface Snapshot {
  basis: string; bank?: boolean; year_end?: string | null; ttm_end?: string | null; price?: number | null; market_cap?: number | null
  pe?: number | null; pb?: number | null; sales_ttm?: number | null; profit_ttm?: number | null; roce?: number | null; roe?: number | null
  de?: number | null; opm?: number | null; npm?: number | null; cash_conversion?: number | null; roa?: number | null
  gross_npa_pct?: number | null; net_npa_pct?: number | null; dividend_yield?: number | null; earnings_yield?: number | null
  [k: string]: unknown
}
export interface SegmentSet { period: 'year' | 'quarter'; end: string; segments: { name: string; revenue_cr: number | null; result_cr: number | null }[] }
export interface CompanyView {
  symbol: string; company: string | null; industry: string | null; bank: boolean; basis: 'consolidated' | 'standalone'
  bases: Record<'consolidated' | 'standalone', boolean>; checked: string | null; price: number | null; snapshot: Snapshot
  years: Statement; balance_sheet: Statement; cash_flow: Statement; ratios: Statement; quarters: Statement
  segments: SegmentSet[]; peers: { industry: string | null; rows: PeerRow[]; missing: number; total?: number }; note: string
  /** Our quality / value / momentum score (scanner/qvm.py), 0-100 among `ranked` stocks with stored financials. */
  score: { quality?: number | null; value?: number | null; momentum?: number | null; score?: number | null; ranked: number }
}
export interface DocItem { time: string | null; category: string; subject: string; text: string; url: string | null; size?: string | null }
export interface Documents { symbol: string; categories: { id: string; label: string; count: number }[]; items: DocItem[]; fetched: string | null; note: string }

export const useCompany = (symbol: string, basis?: string) =>
  useQuery({
    queryKey: ['company', symbol, basis ?? 'auto'],
    queryFn: () => fetchJson<CompanyView>(`/api/company/${encodeURIComponent(symbol)}${basis ? `?basis=${basis}` : ''}`),
    staleTime: 30 * 60_000, retry: false, enabled: !!symbol,
  })

export const useDocuments = (symbol: string) =>
  useQuery({
    queryKey: ['company-docs', symbol],
    queryFn: () => fetchJson<Documents>(`/api/company/${encodeURIComponent(symbol)}/documents`),
    staleTime: 30 * 60_000, retry: false, enabled: !!symbol,
  })
