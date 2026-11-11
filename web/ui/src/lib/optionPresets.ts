// Ready-made option strategies for the strategy builder: legs placed around the at-the-money strike, snapped to the
// strikes the chain actually has.

import type { PayoffLegIn } from '@/api/desk'

export type PresetId = 'long_call' | 'long_put' | 'bull_call' | 'bear_put' | 'bull_put' | 'bear_call' | 'long_straddle'
  | 'short_straddle' | 'short_strangle' | 'iron_condor' | 'iron_fly'

export const PRESETS: { id: PresetId; label: string; view: string }[] = [
  { id: 'long_call', label: 'Long call', view: 'Up, big' },
  { id: 'long_put', label: 'Long put', view: 'Down, big' },
  { id: 'bull_call', label: 'Bull call spread', view: 'Up, capped' },
  { id: 'bear_put', label: 'Bear put spread', view: 'Down, capped' },
  { id: 'bull_put', label: 'Bull put spread', view: 'Not down (credit)' },
  { id: 'bear_call', label: 'Bear call spread', view: 'Not up (credit)' },
  { id: 'long_straddle', label: 'Long straddle', view: 'A big move, either way' },
  { id: 'short_straddle', label: 'Short straddle', view: 'No move (unlimited risk)' },
  { id: 'short_strangle', label: 'Short strangle', view: 'A range (unlimited risk)' },
  { id: 'iron_condor', label: 'Iron condor', view: 'A range, risk capped' },
  { id: 'iron_fly', label: 'Iron butterfly', view: 'Pinned near the strike, risk capped' },
]

/** The strike `n` steps from the at-the-money one (negative = below), clamped to the chain's range. */
export function stepStrike(strikes: number[], atm: number, n: number): number {
  const s = [...strikes].sort((a, b) => a - b)
  if (!s.length) return atm
  let i = 0
  for (let k = 1; k < s.length; k++) if (Math.abs(s[k] - atm) < Math.abs(s[i] - atm)) i = k
  return s[Math.max(0, Math.min(s.length - 1, i + n))]
}

export function presetLegs(id: PresetId, strikes: number[], atm: number, lots = 1): PayoffLegIn[] {
  const k = (n: number) => stepStrike(strikes, atm, n)
  const leg = (side: 'buy' | 'sell', kind: 'CE' | 'PE', strike: number): PayoffLegIn => ({ side, kind, strike, lots })
  switch (id) {
    case 'long_call': return [leg('buy', 'CE', k(0))]
    case 'long_put': return [leg('buy', 'PE', k(0))]
    case 'bull_call': return [leg('buy', 'CE', k(0)), leg('sell', 'CE', k(2))]
    case 'bear_put': return [leg('buy', 'PE', k(0)), leg('sell', 'PE', k(-2))]
    case 'bull_put': return [leg('sell', 'PE', k(-1)), leg('buy', 'PE', k(-3))]
    case 'bear_call': return [leg('sell', 'CE', k(1)), leg('buy', 'CE', k(3))]
    case 'long_straddle': return [leg('buy', 'CE', k(0)), leg('buy', 'PE', k(0))]
    case 'short_straddle': return [leg('sell', 'CE', k(0)), leg('sell', 'PE', k(0))]
    case 'short_strangle': return [leg('sell', 'CE', k(3)), leg('sell', 'PE', k(-3))]
    case 'iron_condor': return [leg('buy', 'PE', k(-6)), leg('sell', 'PE', k(-3)), leg('sell', 'CE', k(3)), leg('buy', 'CE', k(6))]
    case 'iron_fly': return [leg('buy', 'PE', k(-4)), leg('sell', 'PE', k(0)), leg('sell', 'CE', k(0)), leg('buy', 'CE', k(4))]
  }
}

/** Index of the grid point nearest x (the grid is sorted). */
export function nearestIndex(grid: number[], x: number): number {
  let lo = 0, hi = grid.length - 1
  if (hi < 0) return -1
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1
    if (grid[mid] <= x) lo = mid
    else hi = mid
  }
  return Math.abs(grid[lo] - x) <= Math.abs(grid[hi] - x) ? lo : hi
}
