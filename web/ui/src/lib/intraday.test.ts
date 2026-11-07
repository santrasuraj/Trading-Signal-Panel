import { describe, expect, it } from 'vitest'
import type { IntradayStrategy } from '@/api/types'
import { whyNoEdge } from './intraday'

const s = (gross: number | null, net: number | null, over: Partial<IntradayStrategy['metrics']> = {}): IntradayStrategy =>
  ({ key: 'k', name: 'n', metrics: { avg_trade_gross_pct: gross, avg_trade_pct: net, significant: false, return_pct: -5, ...over } } as unknown as IntradayStrategy)

describe('whyNoEdge', () => {
  it('gives the before-costs range and what costs take per trade', () => {
    const w = whyNoEdge([s(0.319, 0.064), s(-0.021, -0.219), s(0.002, -0.151)])
    expect(w?.grossLo).toBeCloseTo(-0.021)
    expect(w?.grossHi).toBeCloseTo(0.319)
    expect(w?.costLo).toBeCloseTo(0.153)
    expect(w?.costHi).toBeCloseTo(0.255)
  })
  it('says nothing when a strategy has a real edge, or without numbers', () => {
    expect(whyNoEdge([s(0.5, 0.3, { significant: true, return_pct: 12 })])).toBeNull()
    expect(whyNoEdge([s(null, null)])).toBeNull()
    expect(whyNoEdge([])).toBeNull()
  })
})
