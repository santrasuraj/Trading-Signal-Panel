// Where the heatmap's day moves came from and how old they are (GET /api/heatmap, web/api/services/market_views.py).
// From 09:15 to 18:00 the server answers at once with what it has - live feed ticks, today's FYERS / Yahoo quotes,
// else the last scan's move - and fetches the stale quotes in the background, so the page says which is which.

import { date, timeIST, todayIST } from './format'

export type MoveSource = 'live' | 'fyers' | 'yahoo' | 'scan'

export interface HeatProvenance {
  session: string | null
  sources: Partial<Record<MoveSource, number>>
  quotes_from: string | null
  quotes_to: string | null
  refreshing: boolean
  scan_date: string | null
}

export interface SourcePart { text: string; warn: boolean }

const IN_SESSION = new Set(['open', 'post_close'])

/** One stock's source, for its tooltip. */
export function sourceLabel(s: MoveSource | undefined, scanDate: string | null): string {
  if (s === 'live') return 'live feed'
  if (s === 'fyers') return 'FYERS'
  if (s === 'yahoo') return 'Yahoo, ~15 min late'
  return `last scan${scanDate ? ` (${date(scanDate, { year: false })})` : ''}`
}

/** '1 live feed', '300 Yahoo (~15 min late)', '179 from the 13 Nov scan' (flagged from 09:15 to 18:00 when the scan
 *  is an earlier day's: those moves are not today's), then the quotes' time and whether a refresh is running. */
export function provenance(h: HeatProvenance, today: string = todayIST()): SourcePart[] {
  const n = h.sources
  const parts: SourcePart[] = []
  if (n.live) parts.push({ text: `${n.live} live feed`, warn: false })
  if (n.fyers) parts.push({ text: `${n.fyers} FYERS`, warn: false })
  if (n.yahoo) parts.push({ text: `${n.yahoo} Yahoo (~15 min late)`, warn: false })
  if (n.scan) {
    const when = h.scan_date ? `the ${date(h.scan_date, { year: false })}` : 'the last'
    parts.push({ text: `${n.scan} from ${when} scan`, warn: IN_SESSION.has(h.session ?? '') && h.scan_date !== today })
  }
  if (h.quotes_from) {
    const a = timeIST(h.quotes_from, { suffix: false })
    const b = timeIST(h.quotes_to ?? h.quotes_from, { suffix: false })
    parts.push({ text: `quotes from ${a === b ? a : `${a}–${b}`} IST`, warn: false })
  }
  if (h.refreshing) parts.push({ text: 'refreshing…', warn: false })
  return parts
}
