import { describe, expect, it } from 'vitest'
import { nearestIndex, presetLegs, stepStrike } from './optionPresets'

const strikes = [24800, 24850, 24900, 24950, 25000, 25050, 25100, 25150, 25200]

describe('option presets', () => {
  it('steps from the strike nearest the money and clamps to the chain', () => {
    expect(stepStrike(strikes, 25010, 0)).toBe(25000)
    expect(stepStrike(strikes, 25010, 2)).toBe(25100)
    expect(stepStrike(strikes, 25010, -9)).toBe(24800)
  })
  it('builds an iron condor with the wings outside the short strikes', () => {
    const legs = presetLegs('iron_condor', strikes, 25000)
    expect(legs.map((l) => `${l.side} ${l.kind} ${l.strike}`)).toEqual(['buy PE 24800', 'sell PE 24850', 'sell CE 25150', 'buy CE 25200'])
  })
  it('a bull call spread buys the lower strike', () => {
    const [a, b] = presetLegs('bull_call', strikes, 25000, 2)
    expect(a).toEqual({ side: 'buy', kind: 'CE', strike: 25000, lots: 2 })
    expect(b.side).toBe('sell'); expect(b.strike).toBe(25100)
  })
  it('finds the nearest grid point', () => {
    expect(nearestIndex([1, 2, 4, 8], 5.9)).toBe(2)
    expect(nearestIndex([1, 2, 4, 8], 100)).toBe(3)
    expect(nearestIndex([], 1)).toBe(-1)
  })
})
