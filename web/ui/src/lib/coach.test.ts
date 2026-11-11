import { describe, expect, it } from 'vitest'
import { holdingChecks, practiceChecks, type Practice } from './coach'

const g = (trades: number, per_trade: number | null, win_rate: number | null = 50) => ({ trades, per_trade, win_rate, net: (per_trade ?? 0) * trades })

const base: Practice = {
  summary: { trades: 40, wins: 18, win_rate: 45, avg_win: 600, avg_loss: -400, profit_factor: 1.2, net: 2000, expectancy: 50, expectancy_r: 0.2, with_stop_pct: 50, avg_bars_held: 8, exits: { stop: 10, manual: 30 } },
  by_bar_size: {}, long_vs_short: {}, blind_vs_named: {},
  stops: { with_stop_pct: 50, losers: 22, losers_exited_by_stop: 6, avg_loss_stopped: -250, avg_loss_other_exits: -480 },
  holding: { avg_bars_winners: 5, avg_bars_losers: 11 },
  largest_loss: -2400, largest_loss_vs_avg_win: 4,
  overtrading: { sessions: 10, trades_per_session: 4, in_sessions_with_4_plus_trades: g(30, -20), in_sessions_with_up_to_3: g(10, 260) },
  trade_after_a_loss: g(12, -90), charges: { total: 900, pct_of_gross_wins: 8 },
  trend: { last_20: g(20, 120, 55), before: g(20, -20, 40) }, sessions: 10,
}

describe('coach checks', () => {
  it('flags the classic leaks, worst first', () => {
    const c = practiceChecks(base)
    const titles = c.map((x) => x.title)
    expect(titles).toContain('Trades without a stop')
    expect(titles).toContain('You hold losers longer than winners')
    expect(titles).toContain('One loss wipes out several wins')
    expect(titles).toContain('Busy sessions cost you')
    expect(titles).toContain('The trade after a loss is worse')
    expect(c.find((x) => x.title === 'Charges are a small share')?.tone).toBe('good')
    expect(c.find((x) => x.title === 'Improving')?.tone).toBe('good')
    const tones = c.map((x) => x.tone)
    expect(tones.indexOf('bad')).toBeLessThan(tones.lastIndexOf('good'))
    expect(tones.lastIndexOf('bad')).toBeLessThan(tones.indexOf('good'))
  })

  it('says when there are too few trades', () => {
    const c = practiceChecks({ ...base, summary: { ...base.summary, trades: 3 } })
    expect(c[0]).toMatchObject({ tone: 'info', title: 'Too few trades to judge' })
  })

  it('checks holdings against their plan', () => {
    expect(holdingChecks({ count: 0 })).toEqual([])
    const c = holdingChecks({ count: 4, below_their_stop: [{ symbol: 'ABC', pnl_pct: -12 }], without_a_stop: 1, largest_weight_pct: 40, top_industry: { name: 'IT', pct: 60 } })
    expect(c.map((x) => x.tone)).toEqual(['bad', 'warn', 'warn', 'warn'])
    expect(holdingChecks({ count: 3, below_their_stop: [], without_a_stop: 0, largest_weight_pct: 20 })[0].tone).toBe('good')
  })
})
