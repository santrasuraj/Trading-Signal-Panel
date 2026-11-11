// Your own scans (web/api/routers/scans.py, scanner/scans.py) and strategy robustness (services/robustness.py).

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { fetchJson } from './client'

export type ScanOp = '>' | '>=' | '<' | '<=' | 'crosses_above' | 'crosses_below'
export interface ScanRule { left: string; op: ScanOp; right: { value?: number; field?: string; mult?: number } }
export interface Scan { name: string; match: 'all' | 'any'; direction: 'long' | 'short'; rules: ScanRule[] }
export interface SavedScan extends Scan { id: string; updated: string }
export interface ScanField { key: string; label: string; group: string; unit: string }
export interface ScanCatalog { fields: ScanField[]; ops: ScanOp[]; presets: Scan[]; max_rules: number }

export interface ScanRunRow {
  symbol: string; company: string | null; industry: string | null; close: number | null; change_pct: number | null
  rs_rating: number | null; new_today: boolean; values: Record<string, number | null>
}
export interface ScanRun {
  scan: Scan; date: string; universe_size: number; count: number; rows: ScanRunRow[]; fields: string[]
  rules_text: string[]; elapsed_s: number
}
export interface HorizonStats { n: number; months: number; excess_pct: number | null; median_pct: number | null; hit_pct: number | null; t: number | null; after_cost_pct: number | null }
export type StudyVerdict = 'edge' | 'edge_before_costs' | 'no_edge' | 'opposite' | 'no_direction' | 'too_few'
export interface ScanBacktest {
  scan: Scan; rules_text: string[]; events: number; horizons: Record<string, HorizonStats>; primary: number; verdict: StudyVerdict
  yearly: { year: number; events: number; excess_pct: number | null; hit_pct: number | null; return_pct: number | null }[]
  recent: { date: string; symbol: string; return_pct: number | null; excess_pct: number | null }[]
  first_day: string; last_day: string; cost_pct: number; elapsed_s: number; note: string
}

export const OP_LABEL: Record<ScanOp, string> = {
  '>': '>', '>=': '≥', '<': '<', '<=': '≤', crosses_above: 'crosses above', crosses_below: 'crosses below',
}
export const VERDICT_TEXT: Record<StudyVerdict, { label: string; tone: 'good' | 'neutral' | 'bad' }> = {
  edge: { label: 'Edge after costs', tone: 'good' },
  edge_before_costs: { label: 'Edge before costs only', tone: 'neutral' },
  no_edge: { label: 'No edge', tone: 'neutral' },
  opposite: { label: 'Worked in reverse', tone: 'bad' },
  no_direction: { label: 'No direction', tone: 'neutral' },
  too_few: { label: 'Too few events to test', tone: 'neutral' },
}

const post = <T,>(path: string, body: unknown) => fetchJson<T>(path, { method: 'POST', body: JSON.stringify(body) })

export const useScanCatalog = () => useQuery({ queryKey: ['scans', 'catalog'], queryFn: () => fetchJson<ScanCatalog>('/api/scans/catalog'), staleTime: Infinity })
export const useSavedScans = () => useQuery({ queryKey: ['scans', 'saved'], queryFn: () => fetchJson<{ scans: SavedScan[] }>('/api/scans'), staleTime: 30_000 })
export const useRunScan = () => useMutation({ mutationFn: (s: Scan) => post<ScanRun>('/api/scans/run', s) })
export const useBacktestScan = () => useMutation({ mutationFn: (s: Scan) => post<ScanBacktest>('/api/scans/backtest', s) })

export function useScanStore() {
  const qc = useQueryClient()
  const done = () => { void qc.invalidateQueries({ queryKey: ['scans', 'saved'] }) }
  return {
    save: useMutation({
      mutationFn: (v: { scan: Scan; id?: string }) => (v.id
        ? fetchJson<SavedScan>(`/api/scans/${v.id}`, { method: 'PUT', body: JSON.stringify(v.scan) })
        : post<SavedScan>('/api/scans', v.scan)),
      onSuccess: done,
    }),
    remove: useMutation({ mutationFn: (id: string) => fetchJson<{ deleted: boolean }>(`/api/scans/${id}`, { method: 'DELETE' }), onSuccess: done }),
  }
}

export interface Robustness {
  key: string; from: string; to: string; days: number; benchmark: string | null
  actual: { cagr_pct: number | null; max_dd_pct: number | null; bench_cagr_pct: number | null }
  monte_carlo: { paths?: number; block_days?: number; cagr_pct?: Record<'p5' | 'p25' | 'p50' | 'p75' | 'p95', number | null>
    max_dd_pct?: Record<'p5' | 'p50' | 'p95', number | null>; prob_loss_pct?: number | null; prob_beat_bench_pct?: number | null }
  deflated_sharpe: { sharpe_ann?: number | null; expected_max_sharpe_ann?: number | null; trials?: number; deflated_pct?: number | null
    probabilistic_pct?: number | null; skew?: number | null; kurtosis?: number | null }
  consistency: { windows?: number; worst_12m_pct?: number | null; best_12m_pct?: number | null; beat_bench_pct?: number | null
    first_half_cagr_pct?: number | null; second_half_cagr_pct?: number | null; first_half_bench_pct?: number | null
    second_half_bench_pct?: number | null; split_at?: string }
  verdict: 'likely_real' | 'maybe_luck' | 'likely_luck'; note: string
}

export const useRobustness = (key: string) =>
  useQuery({ queryKey: ['robustness', key], queryFn: () => fetchJson<Robustness>(`/api/strategies/${key}/robustness`), staleTime: Infinity, enabled: !!key })

export interface ScanFromText { scan: Scan; rules_text: string[]; explanation: string; unsupported: string; model: string }
export const useScanFromText = () => useMutation({ mutationFn: (text: string) => post<ScanFromText>('/api/scans/from-text', { text }) })
export const useAiConfigured = () =>
  useQuery({ queryKey: ['ai', 'status'], queryFn: () => fetchJson<{ configured: boolean }>('/api/ai/status'), staleTime: 60_000 })
