// Number and date formatting (spec 4.7). Indian digit grouping, U+2212 minus, em dash for missing values.
// Every value on screen goes through here so columns line up and signs are consistent.

export const MINUS = '−'
export const DASH = '—'

const cache = new Map<string, Intl.NumberFormat>()
function nf(min: number, max: number): Intl.NumberFormat {
  const k = `${min}:${max}`
  let f = cache.get(k)
  if (!f) {
    f = new Intl.NumberFormat('en-IN', { minimumFractionDigits: min, maximumFractionDigits: max })
    cache.set(k, f)
  }
  return f
}
const F2 = nf(2, 2)
const F0 = nf(0, 0)

export const ok = (x: number | null | undefined): x is number => x != null && Number.isFinite(x)
const sign = (x: number, signed: boolean) => (x < 0 ? MINUS : signed && x > 0 ? '+' : '')
/** Treat values that round to zero as zero so we never print "−0.0". */
const roundsToZero = (x: number, dp: number) => Math.abs(x) < 0.5 * 10 ** -dp

/** Price, always 2 dp: 1,23,456.78 */
export function price(x?: number | null): string {
  if (!ok(x)) return DASH
  if (roundsToZero(x, 2)) return F2.format(0)
  return `${x < 0 ? MINUS : ''}${F2.format(Math.abs(x))}`
}

/** Plain number with fixed decimals (index levels, RSI, scores). */
export function num(x?: number | null, dp = 2): string {
  if (!ok(x)) return DASH
  if (roundsToZero(x, dp)) return nf(dp, dp).format(0)
  return `${x < 0 ? MINUS : ''}${nf(dp, dp).format(Math.abs(x))}`
}

/** Share quantity: 4,866 */
export function qty(x?: number | null): string {
  if (!ok(x)) return DASH
  return `${x < 0 ? MINUS : ''}${F0.format(Math.abs(x))}`
}

/** Rupees: ₹1,23,457 / +₹12,340 / −₹5,000 (whole rupees unless dp: 2). */
export function money(x?: number | null, o: { dp?: 0 | 2; signed?: boolean } = {}): string {
  if (!ok(x)) return DASH
  const dp = o.dp ?? 0
  if (roundsToZero(x, dp)) return `₹${(dp === 2 ? F2 : F0).format(0)}`
  const s = (dp === 2 ? F2 : F0).format(Math.abs(x))
  return `${sign(x, !!o.signed)}₹${s}`
}

/** Compact rupees for KPI tiles only: ₹5.00 L, ₹1.25 Cr. */
export function moneyCompact(x?: number | null, o: { signed?: boolean } = {}): string {
  if (!ok(x)) return DASH
  const a = Math.abs(x)
  const s = sign(x, !!o.signed)
  if (a >= 1e7) return `${s}₹${F2.format(a / 1e7)} Cr`
  if (a >= 1e5) return `${s}₹${F2.format(a / 1e5)} L`
  return money(x, { signed: o.signed })
}

/** Percent: +12.4% / −3.20%. Signed by default; 1 dp by default. */
export function pct(x?: number | null, o: { dp?: number; signed?: boolean } = {}): string {
  if (!ok(x)) return DASH
  const dp = o.dp ?? 1
  const signed = o.signed ?? true
  if (roundsToZero(x, dp)) return `${nf(dp, dp).format(0)}%`
  return `${sign(x, signed)}${nf(dp, dp).format(Math.abs(x))}%`
}

/** Percentage points (edges): +14.9 / −9.5 */
export function pts(x?: number | null, dp = 1): string {
  if (!ok(x)) return DASH
  if (roundsToZero(x, dp)) return nf(dp, dp).format(0)
  return `${sign(x, true)}${nf(dp, dp).format(Math.abs(x))}`
}

/** Ratios (Sharpe, profit factor): 1.62 */
export function ratio(x?: number | null): string {
  if (!ok(x)) return DASH
  return num(x, 2)
}

/** Growth multiple: 12.0× */
export function times(x?: number | null, dp = 1): string {
  if (!ok(x)) return DASH
  return `${num(x, dp)}×`
}

export type ToneKey = 'profit' | 'loss' | 'flat'
export function tone(x?: number | null): ToneKey {
  if (!ok(x) || x === 0) return 'flat'
  return x > 0 ? 'profit' : 'loss'
}

/** Tailwind text class for a signed value. */
export function toneClass(x?: number | null): string {
  const t = tone(x)
  return t === 'profit' ? 'text-profit' : t === 'loss' ? 'text-loss' : 'text-muted'
}

// ------------------------------------------------------------------ dates
// Never `new Date('YYYY-MM-DD')` (parses as UTC midnight). ISO dates are IST trading dates, handled as parts.

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
export const MONTH_SHORT = MONTHS

export interface DateParts { y: number; m: number; d: number }

export function parseISODate(s: string | null | undefined): DateParts | null {
  if (!s) return null
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(s)
  if (!m) return null
  return { y: +m[1], m: +m[2], d: +m[3] }
}

/** '22 Oct 2026' (or '22 Oct' with year: false) */
export function date(s?: string | null, o: { year?: boolean } = {}): string {
  const p = parseISODate(s)
  if (!p) return DASH
  const base = `${p.d} ${MONTHS[p.m - 1]}`
  return o.year === false ? base : `${base} ${p.y}`
}

/** Server-written sentences ('… next review on 30 Oct.'): glue "30 Oct 2026" together with no-break spaces so a
 *  date never splits across two lines. */
export function keepDatesTogether(s: string): string {
  return s.replace(/\b(\d{1,2}) (Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\b( \d{4})?/g, (_m, d, mo, y) => `${d} ${mo}${y ? ` ${y.trim()}` : ''}`)
}

/** 'Oct 2026' */
export function monthYear(s?: string | null): string {
  const p = parseISODate(s)
  return p ? `${MONTHS[p.m - 1]} ${p.y}` : DASH
}

const timeFmt = new Intl.DateTimeFormat('en-IN', { timeZone: 'Asia/Kolkata', hour: '2-digit', minute: '2-digit', hour12: false })
const dtFmt = new Intl.DateTimeFormat('en-IN', {
  timeZone: 'Asia/Kolkata', day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false,
})

/** '09:18 IST' from an ISO datetime. */
export function timeIST(s?: string | null, o: { suffix?: boolean } = {}): string {
  if (!s) return DASH
  const d = new Date(s)
  if (Number.isNaN(d.getTime())) return DASH
  const t = timeFmt.format(d).replace(/^24:/, '00:')
  return o.suffix === false ? t : `${t} IST`
}

/** '23 Oct 2026, 09:18 IST' */
export function dateTimeIST(s?: string | null): string {
  if (!s) return DASH
  const d = new Date(s)
  if (Number.isNaN(d.getTime())) return DASH
  return `${dtFmt.format(d)} IST`
}

/** '9 h ago', '3 min ago', 'just now', '2 d ago' */
export function relative(s?: string | null, now: number = Date.now()): string {
  if (!s) return DASH
  const t = new Date(s).getTime()
  if (Number.isNaN(t)) return DASH
  const sec = Math.round((now - t) / 1000)
  if (sec < 0) return 'in the future'
  if (sec < 45) return 'just now'
  const min = Math.round(sec / 60)
  if (min < 60) return `${min} min ago`
  const h = Math.round(min / 60)
  if (h < 36) return `${h} h ago`
  return `${Math.round(h / 24)} d ago`
}

/** Seconds as '11.6 s' / '2 min 2 s'. */
export function duration(s?: number | null): string {
  if (!ok(s)) return DASH
  if (s < 60) return `${num(s, 1)} s`
  const m = Math.floor(s / 60)
  const r = Math.round(s - m * 60)
  return r ? `${m} min ${r} s` : `${m} min`
}

/** 'in 0 d' style results countdown text. */
export function daysUntil(n?: number | null): string {
  if (!ok(n)) return DASH
  if (n === 0) return 'today'
  if (n === 1) return 'tomorrow'
  if (n < 0) return `${-n} d ago`
  return `in ${n} d`
}

/** Today's date in IST as 'YYYY-MM-DD'. */
export function todayIST(now: Date = new Date()): string {
  const f = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Kolkata', year: 'numeric', month: '2-digit', day: '2-digit' })
  return f.format(now)
}

/** Whole days between two ISO dates (b - a), calendar based, no timezone. */
export function daysBetween(a: string, b: string): number | null {
  const pa = parseISODate(a)
  const pb = parseISODate(b)
  if (!pa || !pb) return null
  const ua = Date.UTC(pa.y, pa.m - 1, pa.d)
  const ub = Date.UTC(pb.y, pb.m - 1, pb.d)
  return Math.round((ub - ua) / 86400000)
}

/** Title-case helper for enum labels. */
export function label(s: string): string {
  return s.replace(/[_-]+/g, ' ').replace(/^\w/, (c) => c.toUpperCase())
}
