import { describe, expect, it, vi } from 'vitest'
import { QuoteStream, summarize } from './liveQuotes'
import { stampText } from '@/components/LivePrice'
import { liveHoldings } from '@/lib/liveHoldings'
import type { HoldingRow, HoldingsResponse, Quote } from './types'

class FakeES {
  static all: FakeES[] = []
  url: string
  closed = false
  handlers: Record<string, (e: { data: string }) => void> = {}
  onopen: (() => void) | null = null
  onerror: (() => void) | null = null
  constructor(url: string) { this.url = url; FakeES.all.push(this) }
  addEventListener(t: string, h: (e: { data: string }) => void) { this.handlers[t] = h }
  close() { this.closed = true }
  emit(d: object) { this.handlers.quotes?.({ data: JSON.stringify(d) }) }
}

const ev = (quotes: Partial<Quote>[], session = 'open') => ({ as_of: 'x', session, source: 'live', delayed: false, note: '', quotes })

describe('QuoteStream', () => {
  it('keeps one stream for the union of wanted symbols and follows it', () => {
    vi.useFakeTimers()
    FakeES.all = []
    const s = new QuoteStream((u) => new FakeES(u) as unknown as EventSource)
    const r1 = s.want(['TCS', 'INFY'])
    const r2 = s.want(['INFY', 'SBIN'])
    vi.advanceTimersByTime(200)
    expect(FakeES.all).toHaveLength(1)                                   // debounced: one connection for both
    expect(decodeURIComponent(FakeES.all[0].url)).toContain('symbols=INFY,SBIN,TCS')
    r1()
    vi.advanceTimersByTime(200)
    expect(FakeES.all[0].closed).toBe(true)
    expect(decodeURIComponent(FakeES.all[1].url)).toContain('symbols=INFY,SBIN')   // INFY still wanted by r2
    r2()
    vi.advanceTimersByTime(200)
    expect(FakeES.all[1].closed).toBe(true)
    expect(FakeES.all).toHaveLength(2)                                   // nothing wanted: no stream
    vi.useRealTimers()
  })

  it('applies snapshots and changes, and notifies listeners', () => {
    const s = new QuoteStream(() => null)
    let n = 0
    s.subscribe(() => { n++ })
    s.apply(ev([{ symbol: 'TCS', price: 100, source: 'live', time: '2026-11-11T10:00:00+05:30' }]) as never, 1000)
    s.apply(ev([{ symbol: 'TCS', price: 101, source: 'live', time: '2026-11-11T10:00:01+05:30' }]) as never, 2000)
    expect(s.get('TCS')?.price).toBe(101)
    expect(s.get('TCS')?.received).toBe(2000)
    expect(s.getMeta()?.session).toBe('open')
    expect(n).toBe(2)
  })
})

describe('summarize and stamps', () => {
  it('names the best source and flags any delayed quote', () => {
    const q = (source: Quote['source'], delayed = false) => ({ symbol: 'X', price: 1, prev_close: null, change_pct: null, time: '', source, delayed })
    expect(summarize([q('live'), q('yahoo', true)], 'open')).toMatchObject({ source: 'live', delayed: true })
    expect(summarize([q('fyers')], 'post_close').note).toContain('15:30')
  })

  it('says live, delayed, last trade or close, and turns amber when a live tick is old', () => {
    const t = '2026-11-11T10:42:17+05:30'
    expect(stampText({ source: 'live', time: t, received: 1000 }, 'open', null, 2000)).toMatchObject({ text: 'Live 10:42:17', tone: 'live' })
    expect(stampText({ source: 'live', time: t, received: 1000 }, 'open', null, 20_000).tone).toBe('stale')
    expect(stampText({ source: 'yahoo', time: '2026-11-11', received: 0 }, 'open').tone).toBe('delayed')
    expect(stampText({ source: 'live', time: '2026-11-11T15:29:58+05:30', received: 0 }, 'post_close').text).toBe('Last trade 15:29:58')
    expect(stampText(undefined, 'closed', '2026-11-10').text).toBe('Close 10 Nov')
  })
})

describe('liveHoldings', () => {
  const row = (o: Partial<HoldingRow>): HoldingRow => ({
    symbol: 'AAA', company: null, industry: null, qty: 10, buy_price: 100, price: 110, change_pct: 1, pnl_pct: 10, pnl_amount: 100,
    stop_price: 92, target_price: 125, momentum_rank: null, rs: null, results_on: null, level: 'ok', alerts: [],
    value: 1100, day_pnl: 10, weight_pct: 100, in_models: [], ...o,
  })
  const resp = (rows: HoldingRow[]): HoldingsResponse => ({
    as_of: null, rows, inputs: [], health_stale: false, by_industry: [], defaults: { stop_loss_pct: 8, target_pct: 25 },
    totals: { count: rows.length, invested: 1000, value: 1100, pnl: 100, pnl_pct: 10, day_pnl: 10, danger: 0, watch: 0 },
  })

  it('marks to the live price and recomputes the totals', () => {
    const h = liveHoldings(resp([row({})]), { AAA: { symbol: 'AAA', price: 120, prev_close: 115, change_pct: 4.35, time: '' } })
    expect(h.rows[0]).toMatchObject({ price: 120, value: 1200, pnl_amount: 200, day_pnl: 50 })
    expect(h.totals).toMatchObject({ value: 1200, pnl: 200, pnl_pct: 20, day_pnl: 50 })
  })

  it('flags a live stop-loss hit as danger between scans', () => {
    const h = liveHoldings(resp([row({})]), { AAA: { symbol: 'AAA', price: 90, prev_close: 95, change_pct: -5.3, time: '' } })
    expect(h.rows[0].level).toBe('danger')
    expect(h.rows[0].alerts[0]).toContain('below stop-loss')
    expect(h.totals.danger).toBe(1)
  })

  it('leaves everything as the scan had it without live quotes', () => {
    const r = resp([row({})])
    expect(liveHoldings(r, {})).toBe(r)
  })
})

describe('alert events', () => {
  it('notifies once per firing, and again when a re-armed alert fires later', () => {
    vi.useFakeTimers()
    FakeES.all = []
    const s = new QuoteStream((u) => new FakeES(u) as unknown as EventSource)
    const got: string[] = []
    s.onAlert((a) => got.push(a.text))
    s.want(['TCS'])
    vi.advanceTimersByTime(200)
    const es = FakeES.all[0]
    const fire = (at: string) => es.handlers.alert?.({ data: JSON.stringify({ alert: { id: 'a1', symbol: 'TCS', fired_at: at }, text: `fired ${at}` }) })
    fire('10:00'); fire('10:00'); fire('10:05')
    expect(got).toEqual(['fired 10:00', 'fired 10:05'])
    vi.useRealTimers()
  })
})
