// Dev-only mock of the Quant Desk API (`npm run dev:mock`). A Vite dev-server middleware: it never ships in
// `vite build` (vite.config.ts only loads it for `serve --mode mock`). It serves the contract-shaped fixtures that
// scripts/make_fixtures.py builds from the real data/ folder, and does the small dynamic parts the real API does
// (range slicing, filtering, paging, allocation what-ifs, a simulated scan).
//
// Scenario flags (comma separated) via the QD_MOCK env var, e.g. `set QD_MOCK=live,noscreener && npm run dev:mock`:
//   noscan      no latest.json yet (onboarding)          live        today's candle is forming (provisional)
//   stale       prices older than the last session        noscreener  screener artifact missing (501)
//   nopaper     no paper journal                          slow        add 600 ms latency to every call
//   holdings    pretend holdings.csv has a few rows       fail        the simulated scan fails

import fs from 'node:fs'
import path from 'node:path'
import type { IncomingMessage, ServerResponse } from 'node:http'
import type { Plugin } from 'vite'
import type {
  AppStatus, ChartMarker, ChartResponse, CostBreakdown, HoldingInput, HoldingsResponse, IndicatorId, IntradayResponse, IntradayRun, Order, ScanStatus,
  ScreenerResponse, ScreenerRow, SignalGroup, SignalsResponse, StrategyDetail, StrategyListResponse, TimeSeries, TradeRow,
} from '../types'
import { allocFor, orderTotals, parseAllocations, sizeOrder } from '../../lib/sizing'

const FIX = path.resolve(__dirname, 'fixtures')
const flags = new Set((process.env.QD_MOCK ?? '').split(',').map((s) => s.trim()).filter(Boolean))
const cache = new Map<string, unknown>()

function fx<T>(name: string): T | null {
  if (cache.has(name)) return cache.get(name) as T
  const p = path.join(FIX, name)
  if (!fs.existsSync(p)) return null
  const v = JSON.parse(fs.readFileSync(p, 'utf-8')) as T
  cache.set(name, v)
  return v
}

class HttpError extends Error {
  status: number
  code: string
  hint: string | null
  details: Record<string, unknown> | null
  constructor(status: number, code: string, message: string, hint: string | null = null, details: Record<string, unknown> | null = null) {
    super(message)
    this.status = status
    this.code = code
    this.hint = hint
    this.details = details
  }
}

const noScan = () => new HttpError(404, 'NO_SCAN', 'No scan results yet.', 'Run the first scan from the top bar.')
function need<T>(name: string): T {
  if (flags.has('noscan') && name !== 'symbols.json') throw noScan()
  const v = fx<T>(name)
  if (v == null) {
    if (!fs.existsSync(FIX)) throw new HttpError(500, 'INTERNAL', 'Mock fixtures are missing.', 'Run `npm run fixtures` in web/ui first.')
    throw new HttpError(404, 'NOT_FOUND', `Not in the mock fixtures: ${name}`)
  }
  return v
}

function withAsOf<T extends { as_of?: unknown }>(o: T): T {
  const st = status()
  if (st.latest && o && typeof o === 'object' && 'as_of' in o) return { ...o, as_of: st.latest }
  return o
}

// ------------------------------------------------------------------ simulated scan
let scanStartedAt: number | null = null
let scanUpdate = true
let lastScanEnd: { ok: boolean; at: number; elapsed: number } | null = null
const SCAN_SECONDS = 14

function scanStatus(): ScanStatus {
  const base = need<AppStatus>('status.json').scan
  if (scanStartedAt != null) {
    const el = (Date.now() - scanStartedAt) / 1000
    if (el < SCAN_SECONDS) {
      const steps = ['Checking Fyers login', 'Downloading history for 2 symbols', 'Repairing with NSE data', 'Testing strategies and computing signals', 'Saving results']
      const pct = Math.min(99, (el / SCAN_SECONDS) * 100)
      return { ...base, state: el < 1.5 ? 'starting' : 'running', running: true, progress_pct: Math.round(pct * 10) / 10,
        message: steps[Math.min(steps.length - 1, Math.floor((el / SCAN_SECONDS) * steps.length))],
        started_at: new Date(scanStartedAt).toISOString(), by: 'platform', pid: 4242, update: scanUpdate, exit_code: null }
    }
    lastScanEnd = { ok: !flags.has('fail'), at: Date.now(), elapsed: SCAN_SECONDS }
    scanStartedAt = null
    if (flags.has('fail')) flags.add('failed-once')
    else flags.delete('noscan')
  }
  if (lastScanEnd) {
    return { ...base, state: lastScanEnd.ok ? 'done' : 'failed', running: false, progress_pct: lastScanEnd.ok ? 100 : null,
      message: lastScanEnd.ok ? `Done in ${lastScanEnd.elapsed.toFixed(1)}s` : 'Scan failed: Yahoo download timed out after 3 retries (see data/logs/scanner.log)',
      started_at: new Date(lastScanEnd.at - lastScanEnd.elapsed * 1000).toISOString(), by: 'platform', pid: null, update: scanUpdate,
      exit_code: lastScanEnd.ok ? 0 : 1 }
  }
  return base
}

function status(): AppStatus {
  const s = fx<AppStatus>('status.json')
  if (!s) throw new HttpError(500, 'INTERNAL', 'Mock fixtures are missing.', 'Run `npm run fixtures` in web/ui first.')
  const out: AppStatus = { ...s, scan: { ...s.scan } }
  out.scan = scanStatus()
  if (flags.has('noscan')) {
    out.latest = null
    out.ticker = null
  } else if (out.latest) {
    const l = { ...out.latest }
    if (flags.has('live')) { l.live = true; l.live_source = 'Yahoo (~15 min delayed)'; l.data_date = out.clock.now.slice(0, 10) }
    if (flags.has('stale')) { l.stale = true; l.data_date = '2026-10-20' }
    if (lastScanEnd?.ok) { const iso = new Date(lastScanEnd.at).toISOString(); l.scan_id = iso; l.generated_at = iso; l.elapsed_s = lastScanEnd.elapsed }
    out.latest = l
  }
  out.features = { ...out.features, screener_artifact: !flags.has('noscreener'), paper: out.features.paper && !flags.has('nopaper') }
  return out
}

// ------------------------------------------------------------------ helpers
const RANGE_DAYS: Record<string, number> = { '3m': 92, '6m': 183, '1y': 366, '2y': 731, '3y': 1096, '5y': 1827 }
function fromDate(last: string, range: string): string | null {
  const d = RANGE_DAYS[range]
  if (!d) return null
  const t = new Date(`${last}T00:00:00Z`).getTime() - d * 86400000
  return new Date(t).toISOString().slice(0, 10)
}

function q(url: URL, k: string): string | null {
  const v = url.searchParams.get(k)
  return v == null || v === '' ? null : v
}

function sma(c: number[], n: number): (number | null)[] {
  const out: (number | null)[] = []
  let s = 0
  for (let i = 0; i < c.length; i++) {
    s += c[i]
    if (i >= n) s -= c[i - n]
    out.push(i >= n - 1 ? s / n : null)
  }
  return out
}
function ema(c: (number | null)[], n: number): (number | null)[] {
  const k = 2 / (n + 1)
  let prev: number | null = null
  return c.map((x) => {
    if (x == null) return prev
    prev = prev == null ? x : x * k + prev * (1 - k)
    return prev
  })
}
function rsi(c: number[], n = 14): (number | null)[] {
  const out: (number | null)[] = [null]
  let g = 0, l = 0
  for (let i = 1; i < c.length; i++) {
    const d = c[i] - c[i - 1]
    const up = Math.max(d, 0), dn = Math.max(-d, 0)
    if (i <= n) { g += up / n; l += dn / n } else { g = (g * (n - 1) + up) / n; l = (l * (n - 1) + dn) / n }
    out.push(i < n ? null : l === 0 ? 100 : 100 - 100 / (1 + g / l))
  }
  return out
}
function std(c: number[], n: number): (number | null)[] {
  return c.map((_, i) => {
    if (i < n - 1) return null
    const w = c.slice(i - n + 1, i + 1)
    const m = w.reduce((a, b) => a + b, 0) / n
    return Math.sqrt(w.reduce((a, b) => a + (b - m) ** 2, 0) / (n - 1))
  })
}
const r2 = (x: number | null) => (x == null || !Number.isFinite(x) ? null : Math.round(x * 100) / 100)

// ------------------------------------------------------------------ routes
type Handler = (url: URL, m: RegExpMatchArray, body: unknown) => unknown
const routes: [string, RegExp, Handler][] = []
const get = (re: RegExp, h: Handler) => routes.push(['GET', re, h])
const post = (re: RegExp, h: Handler) => routes.push(['POST', re, h])
const put = (re: RegExp, h: Handler) => routes.push(['PUT', re, h])

get(/^\/api\/health$/, () => ({ ok: true, version: 'mock', uptime_s: Math.round(process.uptime()) }))
get(/^\/api\/status$/, () => status())

get(/^\/api\/overview$/, () => {
  const o = withAsOf(need<Record<string, unknown> & { as_of: unknown; orders: Order[]; paper: unknown[] }>('overview.json'))
  const live = flags.has('live')
  return { ...o, orders: o.orders.map((x) => ({ ...x, provisional: live })), paper: flags.has('nopaper') ? [] : o.paper }
})

get(/^\/api\/market\/breadth$/, (url) => {
  const b = need<Record<string, (number | null)[] | string> & { t: string[]; source_date: string }>('breadth.json')
  const from = fromDate(b.source_date, q(url, 'range') ?? '1y')
  const i = from ? Math.max(0, b.t.findIndex((d) => d >= from)) : 0
  const out: Record<string, unknown> = { source_date: b.source_date }
  for (const [k, v] of Object.entries(b)) if (Array.isArray(v)) out[k] = v.slice(i)
  return out
})

get(/^\/api\/strategies$/, (url) => {
  const s = withAsOf(need<StrategyListResponse>('strategies.json'))
  const h = q(url, 'horizon')
  return h ? { ...s, strategies: s.strategies.filter((x) => x.horizon === h), rejected: s.rejected.filter((x) => x.horizon === h),
    rejected_catalogue: s.rejected_catalogue.filter((x) => x.horizon === h) } : s
})

get(/^\/api\/strategies\/([\w-]+)$/, (_u, m) => {
  const d = withAsOf(need<StrategyDetail>(`strategy/${m[1]}.json`))
  if (flags.has('nopaper')) return { ...d, paper: null }
  return d
})

get(/^\/api\/strategies\/([\w-]+)\/curve$/, (url, m) => {
  const key = m[1]
  const range = (q(url, 'range') ?? 'all') as '1y' | '3y' | 'all'
  const det = need<StrategyDetail>(`strategy/${key}.json`)
  const c = need<{ t: string[]; columns: Record<string, (number | null)[]>; capital: number }>('curves.json')
  if (!c.columns[key]) throw new HttpError(404, 'NOT_FOUND', `No curve for ${key}`)
  const from = fromDate(c.t[c.t.length - 1], range)
  let i0 = from ? c.t.findIndex((d) => d >= from) : 0
  // start where the strategy curve has data
  while (i0 < c.t.length && c.columns[key][i0] == null) i0++
  const t = c.t.slice(i0)
  const reb = (v: (number | null)[]) => {
    const s = v.slice(i0)
    const f = s.find((x) => x != null && x !== 0)
    return s.map((x) => (x == null || f == null ? null : Math.round((x / f) * 1e5) / 1e5))
  }
  const fac = det.strategy.factor_benchmark_name
  const series: TimeSeries['series'] = [
    { id: key, label: det.strategy.name, role: 'strategy', v: reb(c.columns[key]) },
    { id: 'NIFTY 500', label: 'Nifty 500', role: 'benchmark', v: reb(c.columns['NIFTY 500']) },
    { id: 'Average stock', label: 'Average stock', role: 'benchmark', v: reb(c.columns['Average stock']) },
    { id: 'NIFTY 50', label: 'Nifty 50', role: 'benchmark', v: reb(c.columns['NIFTY 50']) },
  ]
  if (fac && c.columns[`factor:${fac}`]) series.push({ id: fac, label: fac, role: 'factor', v: reb(c.columns[`factor:${fac}`]) })
  const dd = (v: (number | null)[]) => {
    let pk = -Infinity
    return v.map((x) => { if (x == null) return null; pk = Math.max(pk, x); return Math.round((x / pk - 1) * 10000) / 100 })
  }
  return {
    as_of: status().latest, key, range, capital: c.capital,
    curve: { t, series },
    drawdown: { t, series: [{ id: key, label: det.strategy.name, role: 'strategy', v: dd(series[0].v) }, { id: 'NIFTY 500', label: 'Nifty 500', role: 'benchmark', v: dd(series[1].v) }] },
  }
})

get(/^\/api\/strategies\/([\w-]+)\/trades$/, (url, m) => {
  const det = need<StrategyDetail>(`strategy/${m[1]}.json`)
  let rows: TradeRow[] = det.recent_trades.slice()
  const outcome = q(url, 'outcome') ?? 'all'
  const reason = q(url, 'reason')
  const sym = q(url, 'symbol')?.toUpperCase()
  if (outcome === 'win') rows = rows.filter((r) => (r.ret_pct ?? 0) > 0)
  if (outcome === 'loss') rows = rows.filter((r) => (r.ret_pct ?? 0) <= 0)
  if (reason) rows = rows.filter((r) => r.reason === reason)
  if (sym) rows = rows.filter((r) => r.symbol.includes(sym))
  const sort = q(url, 'sort') ?? '-exit_date'
  const desc = sort.startsWith('-')
  const f = sort.replace(/^-/, '') as keyof TradeRow
  rows.sort((a, b) => { const x = a[f] ?? '', y = b[f] ?? ''; return (x < y ? -1 : x > y ? 1 : 0) * (desc ? -1 : 1) })
  const rets = rows.map((r) => r.ret_pct ?? 0)
  const wins = rets.filter((x) => x > 0), losses = rets.filter((x) => x <= 0)
  const mean = (a: number[]) => (a.length ? a.reduce((s, x) => s + x, 0) / a.length : null)
  const bins: { bin_lo: number; bin_hi: number; count: number }[] = []
  for (let b = -30; b < 100; b += 2) bins.push({ bin_lo: b, bin_hi: b + 2, count: 0 })
  for (const x of rets) bins[Math.floor((Math.max(-30, Math.min(99.999, x)) + 30) / 2)].count++
  const reasons = new Map<string, number[]>()
  for (const r of det.recent_trades) reasons.set(r.reason, [...(reasons.get(r.reason) ?? []), r.ret_pct ?? 0])
  const page = Number(q(url, 'page') ?? 1), size = Number(q(url, 'page_size') ?? 50)
  const sw = wins.reduce((s, x) => s + x, 0), sl = -losses.reduce((s, x) => s + x, 0)
  return {
    as_of: status().latest, key: m[1], source: 'recent_only', total: rows.length, page, page_size: size,
    rows: rows.slice((page - 1) * size, page * size),
    stats: { trades: rows.length, win_rate: rows.length ? (wins.length / rows.length) * 100 : null, avg_win_pct: mean(wins), avg_loss_pct: mean(losses),
      expectancy_pct: mean(rets), profit_factor: sl > 0 ? sw / sl : null, avg_days: mean(rows.map((r) => r.days)) },
    histogram: bins,
    reasons: [...reasons.entries()].map(([reason, v]) => ({ reason, count: v.length, avg_ret_pct: mean(v) })).sort((a, b) => b.count - a.count),
  }
})

get(/^\/api\/signals$/, (url) => {
  const s = withAsOf(need<SignalsResponse>('signals.json'))
  const st = status()
  const live = !!st.latest?.live
  const allocQ = parseAllocations(q(url, 'allocations'))
  const hasQ = Object.keys(allocQ).length > 0
  const h = q(url, 'horizon')
  const groups: SignalGroup[] = s.groups
    .filter((g) => !h || g.strategy.horizon === h)
    .map((g) => {
      const alloc = allocFor(g.strategy.key, s.capital, allocQ)
      const orders = g.orders.map((o) => {
        const z = sizeOrder({ action: o.action, price: o.price, stop: o.stop, alloc, max_positions: g.sizing.max_positions, sizing: g.sizing.sizing,
          risk_pct: g.sizing.risk_pct, min_position: s.min_position, you_hold_qty: o.you_hold_qty })
        return hasQ && o.action === 'BUY' ? { ...o, ...z, provisional: live } : { ...o, provisional: live }
      })
      return { ...g, orders, sizing: { ...g.sizing, capital: alloc, per_position: alloc / Math.max(1, g.sizing.max_positions) } }
    })
  const t = orderTotals(groups.flatMap((g) => g.orders))
  return {
    ...s, groups, allocation_source: hasQ ? 'query' : 'none', sized_like_scan: !hasQ,
    allocation_warning: hasQ ? (Object.values(allocQ).reduce((a, b) => a + b, 0) > 100 ? 'Allocations add up to more than 100% of capital.' : null) : s.allocation_warning,
    allocations: Object.entries(allocQ).map(([k, p]) => ({ strategy_key: k, pct: p, capital: (s.capital * p) / 100 })),
    totals: { ...t, sell_amount: t.sell_amount },
  }
})

get(/^\/api\/screener$/, (url) => {
  if (flags.has('noscreener')) {
    throw new HttpError(501, 'FEATURE_UNAVAILABLE', 'The screener appears after the next scan.', 'It needs screener.parquet, which the next scan writes.', { feature: 'screener' })
  }
  const s = withAsOf(need<ScreenerResponse>('screener.json'))
  const preset = q(url, 'preset') ?? 'momentum'
  let rows: ScreenerRow[] = s.rows.slice()
  const by = (k: keyof ScreenerRow, desc = true) => (a: ScreenerRow, b: ScreenerRow) => {
    const x = a[k] as number | null, y = b[k] as number | null
    if (x == null) return 1
    if (y == null) return -1
    return desc ? y - x : x - y
  }
  if (preset === 'momentum') rows = rows.filter((r) => r.above_sma200).sort(by('momentum_score'))
  else if (preset === 'rs') rows.sort(by('rs'))
  else if (preset === 'near_high') rows = rows.filter((r) => r.above_sma200 && r.sma50_above_sma200).sort(by('pct_from_52w_high'))
  else if (preset === 'low_vol') rows = rows.sort(by('turnover_cr')).slice(0, 150).sort(by('vol_ann_pct', false))
  else if (preset === 'volume') rows = rows.filter((r) => (r.vol_ratio ?? 0) >= 3).sort(by('vol_ratio'))
  else if (preset === 'uptrend') rows = rows.filter((r) => r.above_sma200 && r.sma50_above_sma200).sort(by('ret_6m_pct'))
  else rows.sort(by('momentum_score'))
  const ind = q(url, 'industry')
  if (ind) { const set = new Set(ind.split(',')); rows = rows.filter((r) => r.industry && set.has(r.industry)) }
  const mt = Number(q(url, 'min_turnover_cr') ?? 0)
  if (mt > 0) rows = rows.filter((r) => (r.turnover_cr ?? 0) >= mt)
  if (q(url, 'in_models') === 'true') rows = rows.filter((r) => r.in_models.length > 0)
  const rw = q(url, 'results_within')
  if (rw) {
    const today = status().clock.now.slice(0, 10)
    const lim = new Date(new Date(`${today}T00:00:00Z`).getTime() + Number(rw) * 86400000).toISOString().slice(0, 10)
    rows = rows.filter((r) => r.results_on && r.results_on >= today && r.results_on <= lim)
  }
  return { ...s, preset, total: rows.length, rows }
})

get(/^\/api\/sparklines$/, (url) => {
  const s = need<{ source_date: string; days: number; series: Record<string, (number | null)[]> }>('sparklines.json')
  const syms = (q(url, 'symbols') ?? '').split(',').filter(Boolean).slice(0, 500)
  const days = Number(q(url, 'days') ?? 60)
  const series: Record<string, (number | null)[]> = {}
  for (const k of syms) if (s.series[k]) series[k] = s.series[k].slice(-days)
  return { source_date: s.source_date, days, series }
})

get(/^\/api\/symbols$/, () => {
  const s = need<{ symbols: unknown[] }>('symbols.json')
  return { as_of: status().latest, symbols: s.symbols }
})

get(/^\/api\/chart\/([\w&-]+)$/, (url, m) => {
  const sym = decodeURIComponent(m[1]).toUpperCase()
  const raw = fx<Omit<ChartResponse, 'tf' | 'range' | 'indicators'> & { past_results: string[] }>(`chart/${sym}.json`)
  if (!raw) throw new HttpError(404, 'NOT_FOUND', `${sym}: no bars in the mock fixtures.`, 'The mock carries bars for about 70 symbols (indices, ETFs, model holdings, orders, top-ranked, movers). The real API serves every stored symbol.')
  const tf = (q(url, 'tf') ?? '1d') as '1d' | '1w'
  const range = q(url, 'range') ?? '1y'
  const want = new Set((q(url, 'indicators') ?? 'sma20,sma50,sma200,rsi14').split(','))
  let { t, o, h, l, c, v } = raw.bars
  if (tf === '1w') {
    const T: string[] = [], O: number[] = [], H: number[] = [], L: number[] = [], C: number[] = [], V: number[] = []
    const weekKey = (d: string) => { const x = new Date(`${d}T00:00:00Z`); const day = (x.getUTCDay() + 6) % 7; return new Date(x.getTime() - day * 86400000).toISOString().slice(0, 10) }
    let cur = ''
    for (let i = 0; i < t.length; i++) {
      const k = weekKey(t[i])
      if (k !== cur) { cur = k; T.push(t[i]); O.push(o[i]); H.push(h[i]); L.push(l[i]); C.push(c[i]); V.push(v[i]) } else {
        const j = T.length - 1
        T[j] = t[i]; H[j] = Math.max(H[j], h[i]); L[j] = Math.min(L[j], l[i]); C[j] = c[i]; V[j] += v[i]
      }
    }
    t = T; o = O; h = H; l = L; c = C; v = V
  }
  const ind: Partial<Record<IndicatorId, (number | null)[]>> = {}
  const add = (k: IndicatorId, f: () => (number | null)[]) => { if (want.has(k)) ind[k] = f().map(r2) }
  add('sma20', () => sma(c, 20)); add('sma50', () => sma(c, 50)); add('sma200', () => sma(c, 200)); add('ema21', () => ema(c, 21))
  if (want.has('bb_upper') || want.has('bb_mid') || want.has('bb_lower')) {
    const mid = sma(c, 20), sd = std(c, 20)
    ind.bb_mid = mid.map(r2); ind.bb_upper = mid.map((x, i) => r2(x == null || sd[i] == null ? null : x + 2 * sd[i]!)); ind.bb_lower = mid.map((x, i) => r2(x == null || sd[i] == null ? null : x - 2 * sd[i]!))
  }
  add('rsi14', () => rsi(c))
  if (want.has('macd') || want.has('macd_signal') || want.has('macd_hist')) {
    const e12 = ema(c, 12), e26 = ema(c, 26)
    const macd = c.map((_, i) => (i < 25 ? null : e12[i]! - e26[i]!))
    const sig = ema(macd, 9)
    ind.macd = macd.map(r2); ind.macd_signal = sig.map((x, i) => (macd[i] == null ? null : r2(x))); ind.macd_hist = macd.map((x, i) => (x == null || sig[i] == null ? null : r2(x - sig[i]!)))
  }
  add('vol_avg20', () => [null, ...sma(v, 20).slice(0, -1)])
  const from = fromDate(t[t.length - 1], range)
  const i0 = from ? Math.max(0, t.findIndex((d) => d >= from)) : 0
  const sl = <T,>(a: T[]) => a.slice(i0)
  const indicators: Partial<Record<IndicatorId, (number | null)[]>> = {}
  for (const [k, a] of Object.entries(ind)) indicators[k as IndicatorId] = sl(a!)
  const t0 = t[i0]
  const snapWeek = (d: string) => (tf === '1w' ? t.find((x) => x >= d) ?? t[t.length - 1] : d)
  const markers: ChartMarker[] = raw.markers.filter((mk) => mk.t >= t0).map((mk) => ({ ...mk, t: snapWeek(mk.t) }))
  for (const d of raw.past_results) {
    if (d >= t0 && d <= t[t.length - 1]) markers.push({ t: snapWeek(d), position: 'aboveBar', shape: 'circle', kind: 'results', tone: 'neutral', text: 'R', detail: 'Quarterly results', strategy_key: null })
  }
  return { ...raw, tf, range, bars: { t: sl(t), o: sl(o), h: sl(h), l: sl(l), c: sl(c), v: sl(v) }, indicators, markers }
})

get(/^\/api\/stock\/([\w&-]+)$/, (_u, m) => {
  const sym = decodeURIComponent(m[1]).toUpperCase()
  const all = need<Record<string, unknown>>('stocks.json')
  const s = all[sym] as Record<string, unknown> | undefined
  if (!s) throw new HttpError(404, 'NOT_FOUND', `Unknown symbol ${sym}`)
  return { ...s, as_of: status().latest }
})

// holdings: in-memory edits so the editor round-trips
let holdingsOverride: HoldingInput[] | null = null
const DEMO_HOLDINGS: HoldingInput[] = [
  { symbol: 'IGIL', qty: 120, buy_price: 330, buy_date: '2026-09-15', stop_loss_pct: null, target_pct: null },
  { symbol: 'KEI', qty: 10, buy_price: 4400, buy_date: '2026-06-02', stop_loss_pct: 8, target_pct: 25 },
  { symbol: 'CUPID', qty: 300, buy_price: 210.5, buy_date: '2026-03-10', stop_loss_pct: null, target_pct: null },
]
get(/^\/api\/holdings$/, () => {
  const h = withAsOf(need<HoldingsResponse>('holdings.json'))
  const inputs = holdingsOverride ?? (flags.has('holdings') ? DEMO_HOLDINGS : h.inputs)
  if (inputs.length === 0 || h.rows.length) return { ...h, inputs }
  // Derive demo health rows from stock snapshots so the table can be exercised (the real API reads latest.holdings).
  const stocks = need<Record<string, { price: number | null; change_pct: number | null; company: string | null; industry: string | null; momentum_rank: number | null; rs: number | null; results_on: string | null }>>('stocks.json')
  const rows = inputs.map((i) => {
    const s = stocks[i.symbol]
    if (!s || s.price == null || i.qty == null || i.buy_price == null) return { symbol: i.symbol, company: null, industry: null, qty: null, buy_price: null, price: null, change_pct: null, pnl_pct: null, pnl_amount: null, stop_price: null, target_price: null, momentum_rank: null, rs: null, results_on: null, level: 'unknown' as const, alerts: ['No fresh price for this symbol'], value: null, day_pnl: null, weight_pct: null, in_models: [] }
    const stop = i.buy_price * (1 - (i.stop_loss_pct ?? h.defaults.stop_loss_pct) / 100)
    const target = i.buy_price * (1 + (i.target_pct ?? h.defaults.target_pct) / 100)
    const pnl_pct = (s.price / i.buy_price - 1) * 100
    const alerts: string[] = []
    let level: 'ok' | 'good' | 'watch' | 'danger' = 'ok'
    if (s.price <= stop) { level = 'danger'; alerts.push(`STOP-LOSS HIT: down ${Math.abs(pnl_pct).toFixed(1)}% from your buy price`) }
    else if (s.price >= target) { level = 'good'; alerts.push(`TARGET REACHED: up ${pnl_pct.toFixed(1)}%`) }
    if (s.results_on) { if (level === 'ok') level = 'watch'; alerts.push(`Quarterly results on ${s.results_on}: expect a big move either way`) }
    const value = i.qty * s.price
    return { symbol: i.symbol, company: s.company, industry: s.industry, qty: i.qty, buy_price: i.buy_price, price: s.price, change_pct: s.change_pct,
      pnl_pct, pnl_amount: value - i.qty * i.buy_price, stop_price: stop, target_price: target, momentum_rank: s.momentum_rank, rs: s.rs,
      results_on: s.results_on, level, alerts, value, day_pnl: s.change_pct == null ? null : (value * s.change_pct) / (100 + s.change_pct), weight_pct: null as number | null, in_models: [] as string[] }
  })
  const tv = rows.reduce((a, r) => a + (r.value ?? 0), 0)
  for (const r of rows) r.weight_pct = r.value != null && tv ? (r.value / tv) * 100 : null
  const inv = rows.reduce((a, r) => a + (r.qty ?? 0) * (r.buy_price ?? 0), 0)
  const byInd = new Map<string, number>()
  for (const r of rows) byInd.set(r.industry ?? 'Other', (byInd.get(r.industry ?? 'Other') ?? 0) + (r.weight_pct ?? 0))
  return { ...h, inputs, rows, health_stale: holdingsOverride != null,
    totals: { count: rows.length, invested: inv, value: tv, pnl: tv - inv, pnl_pct: inv ? (tv / inv - 1) * 100 : null, day_pnl: rows.reduce((a, r) => a + (r.day_pnl ?? 0), 0),
      danger: rows.filter((r) => r.level === 'danger').length, watch: rows.filter((r) => r.level === 'watch').length },
    by_industry: [...byInd.entries()].map(([industry, weight_pct]) => ({ industry, weight_pct })).sort((a, b) => b.weight_pct - a.weight_pct) }
})
put(/^\/api\/holdings$/, (_u, _m, body) => {
  const rows = ((body as { rows?: HoldingInput[] })?.rows ?? [])
  const rejected: { index: number; symbol: string; reason: string }[] = []
  const today = status().clock.now.slice(0, 10)
  const ok: HoldingInput[] = []
  rows.forEach((r, index) => {
    if (!r.symbol?.trim()) rejected.push({ index, symbol: r.symbol, reason: 'Empty symbol' })
    else if (r.qty != null && r.qty < 0) rejected.push({ index, symbol: r.symbol, reason: 'Quantity cannot be negative' })
    else if (r.buy_price != null && r.buy_price <= 0) rejected.push({ index, symbol: r.symbol, reason: 'Buy price must be above zero' })
    else if (r.buy_date && r.buy_date > today) rejected.push({ index, symbol: r.symbol, reason: 'Buy date is in the future' })
    else ok.push({ ...r, symbol: r.symbol.trim().toUpperCase() })
  })
  holdingsOverride = ok
  const known = new Set((need<{ symbols: { symbol: string }[] }>('symbols.json').symbols).map((s) => s.symbol))
  return { saved: ok.length, rejected, unknown_symbols: ok.filter((r) => !known.has(r.symbol)).map((r) => r.symbol) }
})
post(/^\/api\/holdings\/import\/fyers$/, () => {
  throw new HttpError(409, 'FYERS_LOGIN_REQUIRED', 'Log in to Fyers first.', 'Settings › Fyers › Log in. The import needs today’s login.')
})

get(/^\/api\/paper$/, () => {
  if (flags.has('nopaper')) return { available: false, journal: null, survivorship_haircut_pct: 8, min_days_to_judge: 21, strategies: [] }
  return need('paper.json')
})
get(/^\/api\/paper\/([\w-]+)$/, (_u, m) => {
  if (flags.has('nopaper')) throw new HttpError(501, 'FEATURE_UNAVAILABLE', 'No paper journal yet.', null, { feature: 'paper' })
  return need(`paper/${m[1]}.json`)
})

get(/^\/api\/market\/movers$/, () => withAsOf(need<{ as_of: unknown }>('market_movers.json')))
get(/^\/api\/market\/sectors$/, () => withAsOf(need<{ as_of: unknown }>('market_sectors.json')))
get(/^\/api\/market\/factors$/, () => withAsOf(need<{ as_of: unknown }>('market_factors.json')))
get(/^\/api\/market\/results$/, (url) => {
  const r = need<{ events: { days_until: number; you_hold: boolean; in_models: string[]; in_orders: string[]; momentum_rank: number | null }[] }>('market_results.json')
  const days = Number(q(url, 'days') ?? 14)
  const rel = q(url, 'relevant') === 'true'
  return { ...r, events: r.events.filter((e) => e.days_until <= days && (!rel || e.you_hold || e.in_models.length || e.in_orders.length || e.momentum_rank != null)) }
})

post(/^\/api\/scan$/, (_u, _m, body) => {
  if (scanStartedAt != null) {
    throw new HttpError(409, 'SCAN_BUSY', 'A scan is already running.', 'Wait for it to finish; this page follows it.', { started: new Date(scanStartedAt).toISOString(), by: 'platform', pid: 4242 })
  }
  scanStartedAt = Date.now()
  scanUpdate = (body as { update?: boolean })?.update !== false
  lastScanEnd = null
  return { accepted: true, status: scanStatus() }
})
get(/^\/api\/scan\/history$/, () => need('scan_history.json'))
get(/^\/api\/scan\/log$/, (url) => {
  const l = need<{ path: string; lines: string[] }>('scan_log.json')
  const lines = q(url, 'level') === 'error' ? l.lines.filter((x) => /ERROR|WARNING/.test(x)) : l.lines
  return { path: l.path, lines: lines.slice(-Number(q(url, 'lines') ?? 200)) }
})

get(/^\/api\/fyers\/status$/, () => status().fyers)
post(/^\/api\/fyers\/login$/, (_u, _m, body) => {
  const st = status().fyers
  if (!st.configured) throw new HttpError(409, 'FYERS_NOT_CONFIGURED', 'Fyers app credentials are missing.', 'Add FYERS_CLIENT_ID and FYERS_SECRET_KEY to .env (see README), then restart the server.')
  const mode = (body as { mode?: string })?.mode === 'window' ? 'window' : 'paste'
  return { mode, login_url: mode === 'paste' ? 'https://api-t1.fyers.in/api/v3/generate-authcode?mock=1' : null,
    expires_at: new Date(Date.now() + 600000).toISOString(),
    instructions: mode === 'paste'
      ? ['A Fyers login tab opens. Log in with your Fyers ID, PIN and TOTP.', 'After login the browser lands on your redirect address (the page may not load: that is fine).', 'Copy the full address from the address bar and paste it below.']
      : ['A console window opens and runs 1_login.bat.', 'Follow it; this page notices the new login automatically.'] }
})
post(/^\/api\/fyers\/login\/complete$/, () => {
  throw new HttpError(502, 'FYERS_AUTH', 'Fyers rejected the code (mock).', 'The mock cannot log in. Use the real API on :8600.')
})

get(/^\/api\/config$/, () => need('config.json'))
get(/^\/api\/costs\/preview$/, (url) => {
  const value = Math.max(1, Number(q(url, 'value') ?? 33333))
  const c = need<{ values: { costs: Record<string, number> } }>('config.json').values.costs
  const side = (s: 'buy' | 'sell'): CostBreakdown => {
    const brokerage = Math.min((value * c.brokerage_pct) / 100, c.brokerage_max)
    const exchange = (value * c.exchange_pct) / 100
    const sebi = (value * c.sebi_pct) / 100
    const gst = ((brokerage + exchange + sebi) * c.gst_pct) / 100
    const stt = (value * c.stt_pct) / 100
    const stamp = s === 'buy' ? (value * c.stamp_buy_pct) / 100 : 0
    const dp = s === 'sell' ? c.dp_per_sell : 0
    const slippage = (value * c.slippage_pct) / 100
    const total = brokerage + exchange + sebi + gst + stt + stamp + dp + slippage
    return { value, side: s, brokerage, stt, exchange, sebi, stamp, gst, dp, slippage, total, total_pct: (total / value) * 100 }
  }
  const buy = side('buy'), sell = side('sell')
  return { value, buy, sell, round_trip_pct: ((buy.total + sell.total) / value) * 100 }
})
get(/^\/api\/data\/health$/, () => need('data_health.json'))
// intraday: older fixtures lack summary/run; a POST /api/intraday/run "runs" for 10 s (fixtures stay unchanged)
let intradayRunAt: number | null = null
function intradayRun(): IntradayRun {
  if (intradayRunAt == null) return { state: 'idle', running: false, message: null, started_at: null, pid: null, exit_code: null }
  const running = Date.now() - intradayRunAt < 10_000
  return { state: running ? 'running' : 'done', running, message: running ? 'Re-testing intraday strategies (mock)' : 'Done (mock): fixtures unchanged',
    started_at: new Date(intradayRunAt).toISOString(), pid: running ? 4343 : null, exit_code: running ? null : 0 }
}
get(/^\/api\/intraday$/, () => {
  const r = need<Omit<IntradayResponse, 'summary' | 'run'> & { summary?: string }>('intraday.json')
  const n = r.strategies.length
  const losers = r.strategies.filter((s) => (s.metrics.return_pct ?? 0) <= 0).length
  const summary = r.summary ?? (n ? `${losers === n ? `All ${n}` : `${losers} of ${n}`} intraday strategies lost money after costs (mock). Intraday results are research only: no intraday orders are produced.` : 'Intraday backtest not run yet.')
  return { ...r, summary, run: intradayRun() }
})
post(/^\/api\/intraday\/run$/, () => {
  if (intradayRun().running) throw new HttpError(409, 'SCAN_BUSY', 'The intraday backtest is already running.', null, { started: 'running', by: 'platform', pid: 4343 })
  intradayRunAt = Date.now()
  return { accepted: true, run: intradayRun() }
})

// ------------------------------------------------------------------ middleware
function send(res: ServerResponse, status: number, body: unknown) {
  res.statusCode = status
  res.setHeader('Content-Type', 'application/json; charset=utf-8')
  res.setHeader('Cache-Control', 'no-store')
  res.end(JSON.stringify(body))
}

async function readBody(req: IncomingMessage): Promise<unknown> {
  const chunks: Buffer[] = []
  for await (const c of req) chunks.push(c as Buffer)
  if (!chunks.length) return null
  try { return JSON.parse(Buffer.concat(chunks).toString('utf-8')) } catch { return null }
}

export function mockApiPlugin(): Plugin {
  return {
    name: 'quant-desk-mock-api',
    apply: 'serve',
    configureServer(server) {
      server.config.logger.info(`\n  Quant Desk MOCK API on /api (fixtures: ${FIX}) flags: ${[...flags].join(',') || 'none'}\n`)
      server.middlewares.use(async (req, res, next) => {
        if (!req.url?.startsWith('/api/')) return next()
        const url = new URL(req.url, 'http://127.0.0.1')
        const method = req.method ?? 'GET'
        if (method !== 'GET' && req.headers['x-quant-desk'] !== '1') {
          return send(res, 403, { error: { code: 'CSRF', message: 'Missing X-Quant-Desk header.', hint: null, details: null } })
        }
        if (flags.has('slow')) await new Promise((r) => setTimeout(r, 600))
        const body = method === 'GET' ? null : await readBody(req)
        for (const [m, re, h] of routes) {
          if (m !== method) continue
          const match = url.pathname.match(re)
          if (!match) continue
          try {
            return send(res, method === 'POST' && url.pathname === '/api/scan' ? 202 : 200, h(url, match, body))
          } catch (e) {
            if (e instanceof HttpError) return send(res, e.status, { error: { code: e.code, message: e.message, hint: e.hint, details: e.details } })
            const msg = e instanceof Error ? e.message : String(e)
            return send(res, 500, { error: { code: 'INTERNAL', message: msg, hint: null, details: null } })
          }
        }
        send(res, 404, { error: { code: 'NOT_FOUND', message: `No mock route for ${method} ${url.pathname}`, hint: null, details: null } })
      })
    },
  }
}
