import { describe, expect, it } from 'vitest'
import type { Alert, Change } from '@/api/types'
import { groupChanges, groupResultsAlerts } from './overview'

const alert = (over: Partial<Alert>): Alert => ({
  id: 'x', severity: 'info', category: 'holding', title: 't', detail: null, symbol: null, strategy_key: null, href: null, ...over,
})

describe('groupResultsAlerts', () => {
  it('merges results alerts into one line at the first one, keeping the most severe level', () => {
    const a = [
      alert({ id: 'h', severity: 'danger', category: 'holding', title: 'TCS hit its stop-loss' }),
      alert({ id: 'r1', severity: 'info', category: 'results', title: 'DIVISLAB (in Alpha + low volatility, #1 Alpha + low volatility) reports results today' }),
      alert({ id: 'l', severity: 'warn', category: 'login', title: 'Log in to Fyers' }),
      alert({ id: 'r2', severity: 'warn', category: 'results', title: 'CUPID (in Momentum leaders) reports results in 4 days' }),
    ]
    const g = groupResultsAlerts(a)
    expect(g.map((x) => x.id)).toEqual(['h', 'results:group', 'l'])
    const m = g[1]
    expect(m.severity).toBe('warn')
    expect(m.title).toBe('Results soon for 2 stocks you or the models hold')
    expect(m.detail).toMatch(/^DIVISLAB today · CUPID in 4 days\./)
    expect(m.href).toBe('/market/results')
  })
  it('leaves a single results alert as it is', () => {
    const a = [alert({ id: 'r1', category: 'results', title: 'X reports results today' })]
    expect(groupResultsAlerts(a)).toBe(a)
  })
})

describe('groupChanges', () => {
  const ch = (kind: Change['kind'], text: string, strategy_key: string | null = null, symbol: string | null = null): Change => ({ kind, text, strategy_key, symbol })
  it("gathers one strategy's buys and sells into one line each, in order", () => {
    const g = groupChanges([
      ch('status', 'Alpha: mixed -> working', 'alpha'),
      ch('position_opened', 'Turtle / Donchian 55-day breakout bought ANANDRATHI', 'turtle', 'ANANDRATHI'),
      ch('new_order', 'New: BUY SAILIFE (Trend)', 'trend', 'SAILIFE'),
      ch('position_opened', 'Turtle / Donchian 55-day breakout bought BOSCHLTD', 'turtle', 'BOSCHLTD'),
      ch('position_closed', 'Turtle / Donchian 55-day breakout sold TCS', 'turtle', 'TCS'),
      ch('position_opened', 'Trend bought EMCURE', 'trend', 'EMCURE'),
    ])
    expect(g).toHaveLength(5)
    expect(g[0]).toMatchObject({ kind: 'status', text: 'Alpha: mixed -> working' })
    expect(g[1]).toEqual({ kind: 'position_opened', name: 'Turtle / Donchian 55-day breakout', strategy_key: 'turtle', symbols: ['ANANDRATHI', 'BOSCHLTD'] })
    expect(g[2]).toMatchObject({ kind: 'new_order', symbol: 'SAILIFE' })
    expect(g[3]).toEqual({ kind: 'position_closed', name: 'Turtle / Donchian 55-day breakout', strategy_key: 'turtle', symbols: ['TCS'] })
    expect(g[4]).toMatchObject({ kind: 'position_opened', name: 'Trend', symbols: ['EMCURE'] })
  })
})
