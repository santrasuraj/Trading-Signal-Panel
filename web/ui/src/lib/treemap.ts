// Squarified treemap (Bruls, Huizing, van Wijk 2000): boxes whose areas match the values, kept as close to squares as
// possible, laid out row by row along the shorter side. Pure, so it is tested (treemap.test.ts).

export interface Rect { x: number; y: number; w: number; h: number }
export interface Placed<T> extends Rect { item: T }

function worst(row: number[], side: number): number {
  const s = row.reduce((a, b) => a + b, 0)
  if (!s || !side) return Infinity
  const mx = Math.max(...row), mn = Math.min(...row)
  return Math.max((side * side * mx) / (s * s), (s * s) / (side * side * mn))
}

/** Lay `items` (any order; sorted by value inside) into `box`; items with a value of 0 or less are left out. */
export function squarify<T>(items: T[], value: (t: T) => number, box: Rect): Placed<T>[] {
  const list = items.map((item) => ({ item, v: Math.max(0, value(item)) })).filter((x) => x.v > 0).sort((a, b) => b.v - a.v)
  const total = list.reduce((a, b) => a + b.v, 0)
  if (!total || box.w <= 0 || box.h <= 0) return []
  const scale = (box.w * box.h) / total
  const areas = list.map((x) => x.v * scale)
  const out: Placed<T>[] = []
  let { x, y, w, h } = box
  let i = 0
  while (i < areas.length) {
    const side = Math.min(w, h)
    const row: number[] = [areas[i]]
    let j = i + 1
    while (j < areas.length && worst([...row, areas[j]], side) <= worst(row, side)) { row.push(areas[j]); j++ }
    const sum = row.reduce((a, b) => a + b, 0)
    if (w >= h) {                                   // a column on the left, as wide as the row needs
      const cw = sum / h
      let cy = y
      row.forEach((a, k) => { const ch = a / cw; out.push({ item: list[i + k].item, x, y: cy, w: cw, h: ch }); cy += ch })
      x += cw; w -= cw
    } else {                                        // a row along the top
      const rh = sum / w
      let cx = x
      row.forEach((a, k) => { const rw = a / rh; out.push({ item: list[i + k].item, x: cx, y, w: rw, h: rh }); cx += rw })
      y += rh; h -= rh
    }
    i = j
  }
  return out
}
