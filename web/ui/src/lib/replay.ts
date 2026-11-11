// Market replay simulation (pages/Replay.tsx). One position at a time, filled the way the server checks it when the
// session is saved (web/api/services/replay_svc.py):
//   - a market order fills at the last revealed close plus slippage (buying pays up, selling gets less);
//   - a stop or target fills on the bars after the entry, at the open when the price gaps past it, and the stop first
//     when one bar touches both (we can't know which came first, so assume the worse);
//   - an intraday position is squared off at the close of the session's last bar.
// Charges are a flat % per side from the server's cost model (≈; the saved record uses the exact rupee charges).

export interface Bars { t: number[]; o: number[]; h: number[]; l: number[]; c: number[]; v: number[] }
export type Side = 'LONG' | 'SHORT'
export type ExitReason = 'manual' | 'stop' | 'target' | 'square_off' | 'end'
export interface Position { side: Side; qty: number; entry: number; entry_i: number; stop: number | null; target: number | null }
export interface ClosedTrade extends Position { exit: number; exit_i: number; reason: ExitReason; gross: number; charges: number; net: number }
export interface SimCosts { slippage_pct: number; charges_pct: number }
export interface SimState { i: number; pos: Position | null; trades: ClosedTrade[] }

const r2 = (x: number) => Math.round(x * 100) / 100
const sgn = (s: Side) => (s === 'LONG' ? 1 : -1)

export const start = (i: number): SimState => ({ i, pos: null, trades: [] })

/** The price a market order gets: `buying` pays the slippage, selling gives it up. */
export function marketFill(px: number, buying: boolean, c: SimCosts): number {
  return r2(px * (1 + ((buying ? 1 : -1) * c.slippage_pct) / 100))
}

function closed(p: Position, exit: number, exit_i: number, reason: ExitReason, c: SimCosts): ClosedTrade {
  const gross = r2((exit - p.entry) * p.qty * sgn(p.side))
  const charges = r2(((p.entry + exit) * p.qty * c.charges_pct) / 100)
  return { ...p, exit, exit_i, reason, gross, charges, net: r2(gross - charges) }
}

/** Why a stop / target can't be used for this side at this price, or null when they are fine. */
export function checkLevels(side: Side, px: number, stop: number | null, target: number | null): string | null {
  const s = sgn(side)
  if (stop != null && !((px - stop) * s > 0)) return side === 'LONG' ? 'The stop must be below the price.' : 'The stop must be above the price (short).'
  if (target != null && !((target - px) * s > 0)) return side === 'LONG' ? 'The target must be above the price.' : 'The target must be below the price (short).'
  return null
}

/** Enter at the current bar's close (closing an opposite position first). Same side again: ignored. */
export function enter(st: SimState, b: Bars, side: Side, qty: number, stop: number | null, target: number | null, c: SimCosts): SimState {
  if (qty < 1 || (st.pos && st.pos.side === side)) return st
  const base = st.pos ? exit(st, b, 'manual', c) : st
  const entry = marketFill(b.c[st.i], side === 'LONG', c)
  return { ...base, pos: { side, qty: Math.floor(qty), entry, entry_i: st.i, stop, target } }
}

/** Close the open position at the current bar's close. */
export function exit(st: SimState, b: Bars, reason: ExitReason, c: SimCosts): SimState {
  const p = st.pos
  if (!p) return st
  const px = marketFill(b.c[st.i], p.side === 'SHORT', c)
  return { ...st, pos: null, trades: [...st.trades, closed(p, px, st.i, reason, c)] }
}

export function setLevels(st: SimState, stop: number | null, target: number | null): SimState {
  return st.pos ? { ...st, pos: { ...st.pos, stop, target } } : st
}

/** Stop / target hit inside bar `i`, with its fill price. */
export function triggered(p: Position, b: Bars, i: number, c: SimCosts): { px: number; reason: 'stop' | 'target' } | null {
  const o = b.o[i], h = b.h[i], l = b.l[i]
  if (p.side === 'LONG') {
    if (p.stop != null && o <= p.stop) return { px: marketFill(o, false, c), reason: 'stop' }
    if (p.stop != null && l <= p.stop) return { px: marketFill(p.stop, false, c), reason: 'stop' }
    if (p.target != null && o >= p.target) return { px: o, reason: 'target' }
    if (p.target != null && h >= p.target) return { px: p.target, reason: 'target' }
  } else {
    if (p.stop != null && o >= p.stop) return { px: marketFill(o, true, c), reason: 'stop' }
    if (p.stop != null && h >= p.stop) return { px: marketFill(p.stop, true, c), reason: 'stop' }
    if (p.target != null && o <= p.target) return { px: o, reason: 'target' }
    if (p.target != null && l <= p.target) return { px: p.target, reason: 'target' }
  }
  return null
}

/** Reveal the next bar: the stop / target are checked on it, and at `squareOff` an intraday position is closed. */
export function step(st: SimState, b: Bars, c: SimCosts, squareOff: number | null): SimState {
  const last = b.t.length - 1
  if (st.i >= last) return st
  const i = st.i + 1
  let next: SimState = { ...st, i }
  const p = next.pos
  if (p) {
    const hit = triggered(p, b, i, c)
    if (hit) next = { ...next, pos: null, trades: [...next.trades, closed(p, hit.px, i, hit.reason, c)] }
  }
  if (next.pos && squareOff != null && i >= squareOff) next = exit(next, b, 'square_off', c)
  return next
}

/** Close whatever is open at the current bar (the session ends here). */
export function finish(st: SimState, b: Bars, c: SimCosts, intraday: boolean): SimState {
  return st.pos ? exit(st, b, intraday ? 'square_off' : 'end', c) : st
}

/** The open position's P&L at the current close, after the round trip's charges. */
export function openPnl(st: SimState, b: Bars, c: SimCosts): number | null {
  const p = st.pos
  if (!p) return null
  return closed(p, marketFill(b.c[st.i], p.side === 'SHORT', c), st.i, 'manual', c).net
}

export interface Summary { trades: number; wins: number; net: number; gross: number; charges: number; winRate: number | null }
export function summarize(trades: ClosedTrade[]): Summary {
  const wins = trades.filter((t) => t.net > 0).length
  const sum = (k: 'net' | 'gross' | 'charges') => r2(trades.reduce((a, t) => a + t[k], 0))
  return { trades: trades.length, wins, net: sum('net'), gross: sum('gross'), charges: sum('charges'), winRate: trades.length ? (wins / trades.length) * 100 : null }
}
