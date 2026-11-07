// Chart patterns (scanner/levels.py) as drawings on the daily price chart: the shape through the swing points, the
// pattern's own lines (neckline, trendlines, flag box), the textbook target and the level that voids the pattern,
// with labels (1 / N / 2, LS / H / RS, the pattern's name). Pure, so it is unit-tested (patternDrawing.test.ts).
// Bars are placed by `ago` (bars before the pattern's last bar), not by date: a line that began before the chart's
// range is then cut exactly at the first bar shown, keeping its slope.

import type { LvChartPattern } from '@/api/levels'

export type DrawTone = 'profit' | 'loss' | 'info' | 'warn'
export interface DrawPoint { t: string; v: number }
export interface DrawLabel { t: string; price: number; text: string; position: 'atPriceTop' | 'atPriceBottom' }
export interface DrawLine {
  id: string
  /** shape: through the swing points; line: neckline / trendline / flag box; target / stop: horizontal levels */
  role: 'shape' | 'line' | 'target' | 'stop'
  points: DrawPoint[]
  tone: DrawTone
  style: 'solid' | 'dashed' | 'dotted'
  width: 1 | 2
  labels: DrawLabel[]
  /** a level's name on the price axis (like the chart's other levels), instead of text over the candles */
  axisLabel?: string
}

/** Patterns made of two trendlines: the lines ARE the pattern, so no zigzag is drawn through their touches (it
 *  would hide the lines, and often doubles another pattern's swing points). */
const LINE_PATTERNS = new Set(['ascending_triangle', 'descending_triangle', 'symmetrical_triangle', 'rectangle', 'rising_wedge', 'falling_wedge'])
/** Names short enough to sit on the chart (the legend shows the full name). */
const SHORT: Record<string, string> = { head_shoulders: 'H&S', inverse_head_shoulders: 'Inverse H&S', symmetrical_triangle: 'Sym. triangle' }
export interface PatternDrawing { key: string; name: string; tone: DrawTone; status: LvChartPattern['status']; lines: DrawLine[] }

/** Green for a pattern that points up, red for down, blue for a neutral one that hasn't broken out yet. */
export function patternTone(p: Pick<LvChartPattern, 'bias' | 'direction'>): DrawTone {
  if (p.direction === 'up') return 'profit'
  if (p.direction === 'down') return 'loss'
  return p.bias === 'bullish' ? 'profit' : p.bias === 'bearish' ? 'loss' : 'info'
}

interface At { idx: number; v: number }

/** Cut a polyline (bar positions ascending) at bar 0: earlier points go, and a segment that crosses bar 0 starts
 *  there at its own value (so the line keeps its slope). */
export function clipAtStart(pts: At[]): At[] {
  const k = pts.findIndex((p) => p.idx >= 0)
  if (k < 0) return []
  const out = pts.slice(k)
  if (k > 0 && out[0].idx > 0) {
    const a = pts[k - 1], b = pts[k]
    out.unshift({ idx: 0, v: a.v + ((b.v - a.v) * (0 - a.idx)) / (b.idx - a.idx) })
  }
  return out
}

const near = (a: number, b: number) => Math.abs(a - b) <= Math.abs(b) * 0.0005

/** Drawings for the patterns whose last bar (`end`) is a bar of this chart (`t`: the chart's bar dates, oldest
 *  first). Daily bars only: on a weekly chart `ago` counts days, not weeks, so the caller passes no patterns. */
export function patternDrawings(patterns: LvChartPattern[], t: string[]): PatternDrawing[] {
  const out: PatternDrawing[] = []
  for (const p of patterns) {
    const anchor = t.lastIndexOf(p.end)
    if (anchor < 1) continue                          // the chart doesn't reach the pattern's last bar
    const tone = patternTone(p)
    const done = p.status === 'confirmed'
    const id = `${p.key}:${p.start}`
    const toPts = (xs: At[]) => xs.map((x) => ({ t: t[x.idx], v: x.v }))
    const lines: DrawLine[] = []

    // 1. the shape: its swing points joined oldest to newest (the M of a double top, a triangle's zigzag)
    const pts = p.points
      .filter((x) => x.price != null)
      .map((x) => ({ idx: anchor - x.ago, v: x.price as number, label: x.label, side: x.side }))
      .sort((a, b) => a.idx - b.idx)
    const latest = pts.length ? pts[pts.length - 1] : null
    const short = SHORT[p.key] ?? p.name
    const tag = done ? `${short} ✓` : `${short} (forming)`
    const byLines = LINE_PATTERNS.has(p.key)
    const shape = byLines ? [] : clipAtStart(pts)
    if (shape.length >= 2 && latest) {
      const labels: DrawLabel[] = pts
        .filter((q) => q.idx >= 0 && (q.label || q === latest))
        .map((q) => ({
          t: t[q.idx], price: q.v, position: q.side === 'high' ? 'atPriceTop' : 'atPriceBottom',
          text: q === latest ? (q.label ? `${q.label} · ${tag}` : tag) : q.label,
        }))
      lines.push({ id: `${id}:shape`, role: 'shape', points: toPts(shape), tone, style: 'solid', width: 2, labels })
    }

    // 2. the pattern's lines: dashed while it forms, solid once a close broke through. A two-line pattern's lines are
    // drawn thicker and carry its name in the middle of the upper line's visible part (its start can be cut by the
    // chart's range and sit under the price legend). The middle point lies on the line, so it stays straight.
    p.lines.forEach((ln, k) => {
      if (ln.p1 == null || ln.p2 == null) return
      const seg = clipAtStart([{ idx: anchor - ln.ago1, v: ln.p1 }, { idx: anchor - ln.ago2, v: ln.p2 }])
      if (seg.length < 2 || seg[0].idx === seg[1].idx) return
      const labels: DrawLabel[] = []
      if (byLines && k === 0) {
        const [a, b] = seg
        const mid = Math.round((a.idx + b.idx) / 2)
        if (mid > a.idx && mid < b.idx) seg.splice(1, 0, { idx: mid, v: a.v + ((b.v - a.v) * (mid - a.idx)) / (b.idx - a.idx) })
        labels.push({ t: t[seg[1].idx], price: seg[1].v, text: tag, position: 'atPriceTop' })
      }
      lines.push({ id: `${id}:line${k}`, role: 'line', points: toPts(seg), tone, style: done ? 'solid' : 'dashed', width: byLines ? 2 : 1, labels })
    })

    // 3. the levels: from the breakout bar (or the last swing point) to the pattern's last bar, named on the axis
    const from = Math.max(0, Math.min(anchor - 1, done && p.confirmed_bars_ago != null ? anchor - p.confirmed_bars_ago : latest?.idx ?? anchor - 1))
    const level = (role: 'target' | 'stop', v: number | null, axisLabel: string, lt: DrawTone) => {
      if (v == null || from >= anchor) return
      lines.push({ id: `${id}:${role}`, role, points: [{ t: t[from], v }, { t: t[anchor], v }], tone: lt, style: 'dotted', width: 1, labels: [], axisLabel })
    }
    level('target', p.target, `${short} target`, tone)
    // The void level is drawn only where no line of the pattern already shows it (a triangle's other line, a flag's
    // box): a double top's tops, a head and shoulders' right shoulder.
    const inv = p.invalidation
    if (inv != null && !p.lines.some((ln) => ln.p2 != null && near(ln.p2, inv))) level('stop', inv, `${short} void`, 'warn')
    if (lines.length) out.push({ key: p.key, name: p.name, tone, status: p.status, lines })
  }
  return out
}
