// Trade coach (pages/Coach.tsx): the API's numbers (web/api/services/coach_svc.py) turned into plain process checks.
// Each check says what was measured and whether it is fine, a warning or a leak; groups with few trades say so.

export interface Group { trades: number; win_rate: number | null; net: number; per_trade: number | null }
export interface Practice {
  summary: { trades: number; wins: number; win_rate: number | null; avg_win: number | null; avg_loss: number | null; profit_factor: number | null
    net: number; expectancy: number | null; expectancy_r: number | null; with_stop_pct: number | null; avg_bars_held: number | null; exits: Record<string, number> }
  by_bar_size: Record<string, Group>; long_vs_short: Record<string, Group>; blind_vs_named: Record<string, Group>
  stops: { with_stop_pct: number | null; losers: number; losers_exited_by_stop: number; avg_loss_stopped: number | null; avg_loss_other_exits: number | null }
  holding: { avg_bars_winners: number | null; avg_bars_losers: number | null }
  largest_loss: number | null; largest_loss_vs_avg_win: number | null
  overtrading: { sessions: number; trades_per_session: number; in_sessions_with_4_plus_trades: Group; in_sessions_with_up_to_3: Group }
  trade_after_a_loss: Group; charges: { total: number; pct_of_gross_wins: number | null }
  trend: { last_20: Group; before: Group } | null; sessions: number
}
export interface RealMoney {
  fills: number; closed: Group & { avg_win: number | null; avg_loss: number | null; with_stop_pct: number | null }
  from_a_signal: Group; off_signal: Group; still_open_lots: number; avg_slippage_pct: number | null; note: string
}
export interface HoldingsNow {
  count: number; value?: number; unrealised_pnl?: number | null; losing?: number; below_their_stop?: { symbol: string; pnl_pct: number | null }[]
  without_a_stop?: number; largest_weight_pct?: number | null; top_industry?: { name: string; pct: number } | null; in_a_tested_strategy?: number; stale?: boolean
}
export interface CoachFacts {
  practice: Practice | null; real_money: RealMoney | null; holdings: HoldingsNow
  sample: { practice_trades: number; real_round_trips: number; enough: boolean; rule_of_thumb: string }
}

export type Tone = 'good' | 'warn' | 'bad' | 'info'
export interface Check { tone: Tone; title: string; detail: string }

const rs = (x: number | null | undefined) => (x == null ? '—' : `₹${Math.round(Math.abs(x)).toLocaleString('en-IN')}`)
const SMALL = 10

/** Process checks on practice trades, worst first. */
export function practiceChecks(p: Practice): Check[] {
  const out: Check[] = []
  const s = p.summary
  const ws = p.stops.with_stop_pct
  if (ws != null) {
    out.push({
      tone: ws >= 90 ? 'good' : ws >= 60 ? 'warn' : 'bad',
      title: ws >= 90 ? 'You trade with a stop' : 'Trades without a stop',
      detail: `${Math.round(ws)}% of trades had a stop.` + (p.stops.losers ? ` ${p.stops.losers_exited_by_stop} of ${p.stops.losers} losing trades ended at the stop` +
        (p.stops.avg_loss_stopped != null && p.stops.avg_loss_other_exits != null ? `; they lost ${rs(p.stops.avg_loss_stopped)} on average against ${rs(p.stops.avg_loss_other_exits)} for the others.` : '.') : ''),
    })
  }
  const hw = p.holding.avg_bars_winners, hl = p.holding.avg_bars_losers
  if (hw != null && hl != null) {
    const longer = hl > hw * 1.2
    out.push({
      tone: longer ? 'bad' : 'good',
      title: longer ? 'You hold losers longer than winners' : 'You cut losers at least as fast as winners',
      detail: `Winners held ${hw.toFixed(1)} bars, losers ${hl.toFixed(1)} bars.${longer ? ' Hoping a loser comes back is the most common way small losses grow.' : ''}`,
    })
  }
  if (p.largest_loss_vs_avg_win != null) {
    const k = p.largest_loss_vs_avg_win
    out.push({
      tone: k > 3 ? 'bad' : k > 2 ? 'warn' : 'good',
      title: k > 2 ? 'One loss wipes out several wins' : 'Your largest loss is contained',
      detail: `Largest loss ${rs(p.largest_loss)} = ${k.toFixed(1)}× your average win (${rs(s.avg_win)}).`,
    })
  }
  const busy = p.overtrading.in_sessions_with_4_plus_trades, calm = p.overtrading.in_sessions_with_up_to_3
  if (busy.trades >= 4 && calm.trades >= 1 && busy.per_trade != null && calm.per_trade != null) {
    const worse = busy.per_trade < calm.per_trade
    out.push({
      tone: worse && busy.per_trade < 0 ? 'bad' : worse ? 'warn' : 'good',
      title: worse ? 'Busy sessions cost you' : 'Trading more has not hurt',
      detail: `Per trade: ${busy.per_trade < 0 ? '−' : '+'}${rs(busy.per_trade)} in sessions with 4+ trades (${busy.trades} trades) against ${calm.per_trade < 0 ? '−' : '+'}${rs(calm.per_trade)} with up to 3 (${calm.trades}).`,
    })
  }
  const al = p.trade_after_a_loss
  if (al.trades >= 3 && al.per_trade != null && s.expectancy != null) {
    const worse = al.per_trade < s.expectancy
    out.push({
      tone: worse && al.per_trade < 0 ? 'bad' : worse ? 'warn' : 'good',
      title: worse ? 'The trade after a loss is worse' : 'You stay steady after a loss',
      detail: `Right after a losing trade: ${al.per_trade < 0 ? '−' : '+'}${rs(al.per_trade)} per trade (${al.trades} trades), against ${s.expectancy < 0 ? '−' : '+'}${rs(s.expectancy)} overall.`,
    })
  }
  const cp = p.charges.pct_of_gross_wins
  if (cp != null) {
    out.push({
      tone: cp > 30 ? 'bad' : cp > 15 ? 'warn' : 'good',
      title: cp > 15 ? 'Charges eat your wins' : 'Charges are a small share',
      detail: `Charges ${rs(p.charges.total)}: ${cp.toFixed(0)}% of what your winning trades made before charges.`,
    })
  }
  if (p.trend) {
    const a = p.trend.last_20, b = p.trend.before
    if (a.per_trade != null && b.per_trade != null) {
      out.push({
        tone: a.per_trade >= b.per_trade ? 'good' : 'warn',
        title: a.per_trade >= b.per_trade ? 'Improving' : 'Recent trades are worse',
        detail: `Last ${a.trades} trades: ${a.per_trade < 0 ? '−' : '+'}${rs(a.per_trade)} per trade, ${a.win_rate ?? 0}% won; the ${b.trades} before: ${b.per_trade < 0 ? '−' : '+'}${rs(b.per_trade)}, ${b.win_rate ?? 0}% won.`,
      })
    }
  }
  if (s.trades < SMALL) out.unshift({ tone: 'info', title: 'Too few trades to judge', detail: `${s.trades} practice trade${s.trades === 1 ? '' : 's'} so far: these are first hints. 30+ make the patterns mean something.` })
  const rank: Record<Tone, number> = { info: 0, bad: 1, warn: 2, good: 3 }
  return out.sort((x, y) => rank[x.tone] - rank[y.tone])
}

/** Checks on what you hold now. */
export function holdingChecks(h: HoldingsNow): Check[] {
  if (!h.count) return []
  const out: Check[] = []
  const below = h.below_their_stop ?? []
  if (below.length) out.push({ tone: 'bad', title: `${below.length} holding${below.length === 1 ? ' is' : 's are'} below the stop`, detail: below.map((b) => b.symbol).join(', ') + ': the plan said sell.' })
  if (h.without_a_stop) out.push({ tone: 'warn', title: `${h.without_a_stop} holding${h.without_a_stop === 1 ? ' has' : 's have'} no stop`, detail: 'Set a stop-loss % on the Portfolio page.' })
  if (h.largest_weight_pct != null && h.largest_weight_pct > 25) out.push({ tone: 'warn', title: 'One stock is a big part of your money', detail: `Largest holding: ${h.largest_weight_pct.toFixed(0)}% of the portfolio.` })
  if (h.top_industry && h.top_industry.pct > 40 && h.count > 2) out.push({ tone: 'warn', title: 'Concentrated in one industry', detail: `${h.top_industry.name}: ${h.top_industry.pct.toFixed(0)}% of the portfolio.` })
  if (!out.length) out.push({ tone: 'good', title: 'Holdings are inside their plan', detail: `${h.count} holdings, none below its stop.` })
  return out
}
