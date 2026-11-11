// Live prices for every page through ONE event stream (GET /api/stream/quotes, Server-Sent Events).
//
// Components ask for symbols with useLiveQuotes(); the store keeps a reference count per symbol and keeps a
// single EventSource open for the union (at most 100, the API's limit), reconnecting shortly after the set
// changes. The server sends a full snapshot, then only the symbols whose price changed: FYERS live-feed ticks
// about a second after the trade, REST / Yahoo quotes every 30 s for symbols the feed doesn't stream.
// EventSource reconnects by itself when the connection drops (server restart, sleep).

import type { MarketSession, Quote, QuoteSource, QuotesResponse } from './types'

export const MAX_STREAM_SYMBOLS = 100
const RECONNECT_DEBOUNCE_MS = 150

export interface LiveQuote extends Quote { received: number }          // received: Date.now() when it arrived
export interface StreamMeta { as_of: string; session: MarketSession; note: string; connected: boolean }

type Listener = () => void

export class QuoteStream {
  private counts = new Map<string, number>()
  private quotes = new Map<string, LiveQuote>()
  private meta: StreamMeta | null = null
  private es: EventSource | null = null
  private key = ''
  private timer: ReturnType<typeof setTimeout> | null = null
  private listeners = new Set<Listener>()
  private version = 0
  private connected = false
  private open: (url: string) => EventSource | null

  constructor(open: (url: string) => EventSource | null = defaultOpen) {
    this.open = open
  }

  subscribe = (l: Listener): (() => void) => {
    this.listeners.add(l)
    return () => { this.listeners.delete(l) }
  }

  getVersion = (): number => this.version

  private alertListeners = new Set<(a: { alert: { id: string; symbol: string }; text: string }) => void>()
  private seenAlerts = new Set<string>()      // one toast per firing, however many reconnects replay it

  /** Called once for every price alert that fires while the app is open (from any source). */
  onAlert(l: (a: { alert: { id: string; symbol: string }; text: string }) => void): () => void {
    this.alertListeners.add(l)
    return () => { this.alertListeners.delete(l) }
  }

  get(sym: string): LiveQuote | undefined { return this.quotes.get(sym) }

  getMeta(): StreamMeta | null { return this.meta && { ...this.meta, connected: this.connected } }

  /** Ask for live prices of `symbols`; returns the release function (call it on unmount). */
  want(symbols: string[]): () => void {
    const list = [...new Set(symbols)]
    for (const s of list) this.counts.set(s, (this.counts.get(s) ?? 0) + 1)
    this.schedule()
    return () => {
      for (const s of list) {
        const n = (this.counts.get(s) ?? 0) - 1
        if (n > 0) this.counts.set(s, n)
        else this.counts.delete(s)
      }
      this.schedule()
    }
  }

  /** The symbols the stream currently carries (tests, diagnostics). */
  streamKey(): string { return this.key }

  /** Apply one server event (exported for tests). */
  apply(d: QuotesResponse & { full?: boolean }, now: number = Date.now()): void {
    for (const q of d.quotes ?? []) this.quotes.set(q.symbol, { ...q, received: now })
    this.meta = { as_of: d.as_of, session: d.session, note: d.note, connected: true }
    this.bump()
  }

  private bump() {
    this.version++
    for (const l of this.listeners) l()
  }

  private schedule() {
    if (this.timer) clearTimeout(this.timer)
    this.timer = setTimeout(() => { this.timer = null; this.reconnect() }, RECONNECT_DEBOUNCE_MS)
  }

  private reconnect() {
    const syms = [...this.counts.keys()].sort().slice(0, MAX_STREAM_SYMBOLS)
    const key = syms.join(',')
    if (key === this.key && (this.es || !syms.length)) return
    this.es?.close()
    this.es = null
    this.key = key
    if (!syms.length) return
    const es = this.open(`/api/stream/quotes?symbols=${encodeURIComponent(key)}`)
    if (!es) return
    es.addEventListener('quotes', (ev) => {
      try { this.apply(JSON.parse((ev as MessageEvent<string>).data)) } catch { /* a malformed event: skip it */ }
    })
    es.addEventListener('alert', (ev) => {
      try {
        const d = JSON.parse((ev as MessageEvent<string>).data) as { alert: { id: string; symbol: string; fired_at?: string | null }; text: string }
        const key = `${d.alert.id}@${d.alert.fired_at ?? ''}`          // a re-armed alert fires again under the same id
        if (this.seenAlerts.has(key)) return
        this.seenAlerts.add(key)
        for (const l of this.alertListeners) l(d)
      } catch { /* skip */ }
    })
    es.onopen = () => { this.connected = true; this.bump() }
    es.onerror = () => { this.connected = false; this.bump() }          // EventSource retries by itself
    this.es = es
  }
}

function defaultOpen(url: string): EventSource | null {
  return typeof EventSource === 'undefined' ? null : new EventSource(url)
}

export const quoteStream = new QuoteStream()

// ---- what a set of quotes says about itself ------------------------------------------------------------------

const RANK: Record<QuoteSource, number> = { live: 0, fyers: 1, yahoo: 2, close: 3 }

export const SOURCE_NOTE: Record<QuoteSource, string> = {
  live: 'Real-time FYERS live feed.',
  fyers: 'Real-time FYERS prices (refreshed every 30 s).',
  yahoo: 'Yahoo prices, ~15 min delayed: log in to FYERS for real time.',
  close: 'Last closing price.',
}

/** Best source and whether any is delayed, for the quotes a component shows. */
export function summarize(quotes: Quote[], session: MarketSession): { source: QuoteSource; delayed: boolean; note: string } {
  const source = quotes.reduce<QuoteSource>((b, q) => (RANK[q.source ?? 'close'] < RANK[b] ? (q.source ?? 'close') : b), 'close')
  const delayed = quotes.some((q) => q.delayed)
  let note = SOURCE_NOTE[source]
  if (session === 'post_close' && source !== 'close') note = 'Market closed at 15:30: last trades of the day (official close after ~18:00).'
  else if (delayed && source !== 'yahoo') note = `${note} Some prices from Yahoo (~15 min delayed): log in to FYERS for real time.`
  return { source, delayed, note }
}
