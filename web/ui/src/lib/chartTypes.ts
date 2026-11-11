// Other chart types from the same daily / weekly bars (pages/Chart.tsx): Heikin Ashi keeps the dates (indicators and
// markers still line up); Renko and three-line break drop time and draw only price moves, so they get their own
// simple chart (components/charts/BrickChart.tsx). Also the anchored VWAP of a drawing. Pure, so they are tested.

export interface Ohlcv { t: string[]; o: number[]; h: number[]; l: number[]; c: number[]; v: number[] }
export interface Brick { t: number; o: number; h: number; l: number; c: number; day: string }
export type ChartType = 'candles' | 'heikin' | 'renko' | 'linebreak' | 'pnf' | 'kagi'

/** Heikin Ashi: close = average of the bar, open = midpoint of the previous HA body; smooths trends. */
export function heikinAshi(b: Ohlcv): Ohlcv {
  const n = b.t.length
  const o: number[] = new Array(n), h: number[] = new Array(n), l: number[] = new Array(n), c: number[] = new Array(n)
  for (let i = 0; i < n; i++) {
    c[i] = (b.o[i] + b.h[i] + b.l[i] + b.c[i]) / 4
    o[i] = i === 0 ? (b.o[0] + b.c[0]) / 2 : (o[i - 1] + c[i - 1]) / 2
    h[i] = Math.max(b.h[i], o[i], c[i])
    l[i] = Math.min(b.l[i], o[i], c[i])
  }
  const r2 = (x: number) => Math.round(x * 100) / 100
  return { t: b.t, o: o.map(r2), h: h.map(r2), l: l.map(r2), c: c.map(r2), v: b.v }
}

const epoch = (iso: string) => Math.floor(Date.parse(`${iso}T00:00:00Z`) / 1000)

/** Bricks get the date of the bar that completed them; several bricks on one bar get 1-second steps so the chart's
 *  time axis keeps them in order. */
function stamp(day: string, prev: number): number {
  const t = epoch(day)
  return t > prev ? t : prev + 1
}

/** Renko on closes: a brick of `boxPct` % of the first close, drawn each time the close moves a full brick beyond the
 *  last one (a reversal needs two bricks). Returns the bricks and the box size in rupees. */
export function renko(b: Ohlcv, boxPct = 2): { bricks: Brick[]; box: number } {
  const out: Brick[] = []
  if (!b.c.length) return { bricks: out, box: 0 }
  const box = Math.max(0.05, Math.round(b.c[0] * boxPct) / 100)
  const r2 = (x: number) => Math.round(x * 100) / 100
  let last = b.c[0], dir = 0, stampT = 0
  for (let i = 1; i < b.c.length; i++) {
    const c = b.c[i]
    const add = (o: number, cl: number) => {
      stampT = stamp(b.t[i], stampT)
      out.push({ t: stampT, o: r2(o), h: r2(Math.max(o, cl)), l: r2(Math.min(o, cl)), c: r2(cl), day: b.t[i] })
    }
    const up = () => { while (c >= last + box) { add(last, last + box); last += box } }
    const down = () => { while (c <= last - box) { add(last, last - box); last -= box } }
    if (dir === 0) {
      if (c >= last + box) { up(); dir = 1 } else if (c <= last - box) { down(); dir = -1 }
    } else if (dir === 1) {
      up()
      if (c <= last - 2 * box) { add(last - box, last - 2 * box); last -= 2 * box; dir = -1; down() }
    } else {
      down()
      if (c >= last + 2 * box) { add(last + box, last + 2 * box); last += 2 * box; dir = 1; up() }
    }
  }
  return { bricks: out, box }
}

/** Three-line break: a new line when the close goes beyond the last line; a reversal must break the extreme of the
 *  last `n` lines. */
export function lineBreak(b: Ohlcv, n = 3): Brick[] {
  const out: Brick[] = []
  if (b.c.length < 2) return out
  let last = 0
  const push = (i: number, o: number, c: number) => {
    last = stamp(b.t[i], last)
    out.push({ t: last, o, h: Math.max(o, c), l: Math.min(o, c), c, day: b.t[i] })
  }
  let i0 = 1
  while (i0 < b.c.length && b.c[i0] === b.c[0]) i0++
  if (i0 >= b.c.length) return out
  push(i0, b.c[0], b.c[i0])
  for (let i = i0 + 1; i < b.c.length; i++) {
    const c = b.c[i]
    const lastLine = out[out.length - 1]
    const up = lastLine.c > lastLine.o
    const recent = out.slice(-n)
    if (up) {
      if (c > lastLine.c) push(i, lastLine.c, c)
      else if (c < Math.min(...recent.map((x) => x.l))) push(i, lastLine.o, c)
    } else {
      if (c < lastLine.c) push(i, lastLine.c, c)
      else if (c > Math.max(...recent.map((x) => x.h))) push(i, lastLine.o, c)
    }
  }
  return out
}

/** Anchored VWAP from the bar on `from` (or the next one) to the end: cumulative (typical price x volume) / volume.
 *  null where there is no volume yet (an index has none). */
export function anchoredVwap(b: Ohlcv, from: string): { t: string; v: number }[] {
  const out: { t: string; v: number }[] = []
  let pv = 0, vol = 0
  for (let i = 0; i < b.t.length; i++) {
    if (b.t[i] < from) continue
    const tp = (b.h[i] + b.l[i] + b.c[i]) / 3
    pv += tp * (b.v[i] || 0)
    vol += b.v[i] || 0
    if (vol > 0) out.push({ t: b.t[i], v: Math.round((pv / vol) * 100) / 100 })
  }
  return out
}

// ---- Point & Figure: columns of X (rising) and O (falling) on a percentage box grid; a new column only after the
// price reverses `rev` boxes. Highs and lows decide (the high-low method). Time is left out.
export interface PnfColumn { up: boolean; from: number; to: number; start: string; end: string }   // box indexes, inclusive

export function pnf(b: Ohlcv, boxPct = 2, rev = 3): { cols: PnfColumn[]; boxPrice: (i: number) => number } {
  const k = Math.log(1 + boxPct / 100)
  const boxPrice = (i: number) => Math.exp(i * k)
  const cols: PnfColumn[] = []
  if (!b.c.length) return { cols, boxPrice }
  const fl = (x: number) => Math.floor(Math.log(x) / k + 1e-9)
  const ce = (x: number) => Math.ceil(Math.log(x) / k - 1e-9)
  let cur: PnfColumn | null = null
  for (let i = 0; i < b.c.length; i++) {
    const hi = fl(b.h[i]), lo = ce(b.l[i])
    if (!cur) {
      const first = fl(b.c[0])
      if (hi > first) cur = { up: true, from: first, to: hi, start: b.t[i], end: b.t[i] }
      else if (lo < first) cur = { up: false, from: first, to: lo, start: b.t[i], end: b.t[i] }
      continue
    }
    if (cur.up) {
      if (hi > cur.to) { cur.to = hi; cur.end = b.t[i] }
      else if (lo <= cur.to - rev) { cols.push(cur); cur = { up: false, from: cur.to - 1, to: lo, start: b.t[i], end: b.t[i] } }
    } else {
      if (lo < cur.to) { cur.to = lo; cur.end = b.t[i] }
      else if (hi >= cur.to + rev) { cols.push(cur); cur = { up: true, from: cur.to + 1, to: hi, start: b.t[i], end: b.t[i] } }
    }
  }
  if (cur) cols.push(cur)
  return { cols, boxPrice }
}

// ---- Kagi: a line that turns only when the close reverses `revPct` % from its extreme; it thickens (yang) when it
// rises above the last shoulder and thins (yin) when it falls below the last waist.
export interface KagiSeg { from: number; to: number; thick: boolean; start: string; end: string }

export function kagi(b: Ohlcv, revPct = 4): KagiSeg[] {
  const out: KagiSeg[] = []
  if (b.c.length < 2) return out
  let dir = 0, ext = b.c[0], startV = b.c[0], startT = b.t[0], endT = b.t[0]
  let thick = true, shoulder = -Infinity, waist = Infinity
  for (let i = 1; i < b.c.length; i++) {
    const c = b.c[i]
    if (dir === 0) {
      if (c >= startV * (1 + revPct / 100)) { dir = 1; ext = c; endT = b.t[i] }
      else if (c <= startV * (1 - revPct / 100)) { dir = -1; ext = c; endT = b.t[i] }
      continue
    }
    if (dir === 1) {
      if (c > ext) { ext = c; endT = b.t[i] }
      else if (c <= ext * (1 - revPct / 100)) {
        if (ext > shoulder && shoulder !== -Infinity) thick = true
        out.push({ from: startV, to: ext, thick, start: startT, end: endT })
        shoulder = ext; startV = ext; startT = endT; dir = -1; ext = c; endT = b.t[i]
      }
    } else {
      if (c < ext) { ext = c; endT = b.t[i] }
      else if (c >= ext * (1 + revPct / 100)) {
        if (ext < waist && waist !== Infinity) thick = false
        out.push({ from: startV, to: ext, thick, start: startT, end: endT })
        waist = ext; startV = ext; startT = endT; dir = 1; ext = c; endT = b.t[i]
      }
    }
  }
  if (dir !== 0) out.push({ from: startV, to: ext, thick: dir === 1 ? (ext > shoulder ? true : thick) : (ext < waist ? false : thick), start: startT, end: endT })
  return out
}

// ---- Volume by price over the bars shown: each bar's volume spread evenly over its high-low range, in `bins`
// levels; the point of control (most volume) and the value area (70% of the volume around it).
export function volumeByPrice(b: Ohlcv, bins = 40): { profile: { price: number; vol: number }[]; poc: number | null; va: [number, number] | null } {
  const n = b.c.length
  if (!n) return { profile: [], poc: null, va: null }
  const lo = Math.min(...b.l), hi = Math.max(...b.h)
  if (!(hi > lo)) return { profile: [], poc: null, va: null }
  const step = (hi - lo) / bins
  const vol = new Array(bins).fill(0)
  for (let i = 0; i < n; i++) {
    const a = Math.max(0, Math.floor((b.l[i] - lo) / step)), z = Math.min(bins - 1, Math.floor((b.h[i] - lo) / step))
    const share = b.v[i] / (z - a + 1)
    for (let j = a; j <= z; j++) vol[j] += share
  }
  const profile = vol.map((v, j) => ({ price: Math.round((lo + (j + 0.5) * step) * 100) / 100, vol: v }))
  let p = 0
  for (let j = 1; j < bins; j++) if (vol[j] > vol[p]) p = j
  const total = vol.reduce((x, y) => x + y, 0)
  let a = p, z = p, got = vol[p]
  while (got < total * 0.7 && (a > 0 || z < bins - 1)) {
    const up = z < bins - 1 ? vol[z + 1] : -1, dn = a > 0 ? vol[a - 1] : -1
    if (up >= dn) { z += 1; got += vol[z] } else { a -= 1; got += vol[a] }
  }
  return { profile, poc: profile[p].price, va: [profile[a].price, profile[z].price] }
}
