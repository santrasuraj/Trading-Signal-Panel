import { describe, expect, it } from 'vitest'
import { squarify } from './treemap'

describe('squarified treemap', () => {
  it('gives every item an area proportional to its value and fills the box', () => {
    const items = [6, 6, 4, 3, 2, 2, 1]
    const out = squarify(items, (v) => v, { x: 0, y: 0, w: 600, h: 400 })
    expect(out).toHaveLength(items.length)
    const total = items.reduce((a, b) => a + b, 0)
    for (const p of out) expect(p.w * p.h).toBeCloseTo((p.item / total) * 600 * 400, 3)
    expect(out.reduce((a, p) => a + p.w * p.h, 0)).toBeCloseTo(600 * 400, 3)
    for (const p of out) {
      expect(p.x).toBeGreaterThanOrEqual(-1e-9); expect(p.y).toBeGreaterThanOrEqual(-1e-9)
      expect(p.x + p.w).toBeLessThanOrEqual(600 + 1e-6); expect(p.y + p.h).toBeLessThanOrEqual(400 + 1e-6)
    }
  })

  it('keeps boxes near square and skips empty values', () => {
    const out = squarify([1, 1, 1, 1, 0, -2], (v) => v, { x: 0, y: 0, w: 100, h: 100 })
    expect(out).toHaveLength(4)
    for (const p of out) expect(Math.max(p.w / p.h, p.h / p.w)).toBeLessThan(1.01)
    expect(squarify([], (v: number) => v, { x: 0, y: 0, w: 10, h: 10 })).toEqual([])
  })
})
