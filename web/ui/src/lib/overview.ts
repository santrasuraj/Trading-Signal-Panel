// Overview helpers that turn repetitive rows into one line each (pure, so unit-tested in overview.test.ts).

import type { Alert, Change } from '@/api/types'

const SEV_RANK: Record<Alert['severity'], number> = { danger: 0, warn: 1, info: 2, good: 3 }

/** Results alerts as one line: "DIVISLAB today · CUPID in 4 days · …" (the Results card beside it has the list).
 *  Six separate "X reports results … Expect a big move either way." rows said the same thing six times. The merged
 *  alert keeps the most severe level and sits where the first results alert was. */
export function groupResultsAlerts(alerts: Alert[]): Alert[] {
  const res = alerts.filter((a) => a.category === 'results')
  if (res.length < 2) return alerts
  const when = (a: Alert) => {
    const m = /^(\S+)(?: \(.*\))? reports results (.+)$/.exec(a.title)
    return m ? `${m[1]} ${m[2]}` : a.title
  }
  const merged: Alert = {
    id: 'results:group', category: 'results', symbol: null, strategy_key: null, href: '/market/results',
    severity: res.reduce((s, a) => (SEV_RANK[a.severity] < SEV_RANK[s] ? a.severity : s), res[0].severity),
    title: `Results soon for ${res.length} stocks you or the models hold`,
    detail: `${res.map(when).join(' · ')}. Results days often bring a big move either way.`,
  }
  const at = alerts.findIndex((a) => a.category === 'results')
  const rest = alerts.filter((a) => a.category !== 'results')
  return [...rest.slice(0, at), merged, ...rest.slice(at)]
}

export type ChangeLine =
  | { kind: Change['kind']; text: string; strategy_key: string | null; symbol: string | null }
  | { kind: 'position_opened' | 'position_closed'; name: string; strategy_key: string; symbols: string[] }

/** One line per strategy for its buys and its sells ("Turtle … bought 10: ANANDRATHI, AUROPHARMA, +8") instead of
 *  one line per stock: a busy scan listed 18 near-identical lines. Status, regime and new-order lines stay as they
 *  are, in their order. */
export function groupChanges(items: Change[]): ChangeLine[] {
  const out: ChangeLine[] = []
  const groups = new Map<string, Extract<ChangeLine, { symbols: string[] }>>()
  for (const it of items) {
    if ((it.kind === 'position_opened' || it.kind === 'position_closed') && it.strategy_key && it.symbol) {
      const verb = it.kind === 'position_opened' ? ' bought ' : ' sold '
      const key = `${it.kind}|${it.strategy_key}`
      let g = groups.get(key)
      if (!g) {
        const name = it.text.includes(verb) ? it.text.slice(0, it.text.lastIndexOf(verb)) : it.strategy_key
        g = { kind: it.kind, name, strategy_key: it.strategy_key, symbols: [] }
        groups.set(key, g)
        out.push(g)
      }
      g.symbols.push(it.symbol)
    } else {
      out.push({ kind: it.kind, text: it.text, strategy_key: it.strategy_key, symbol: it.symbol })
    }
  }
  return out
}
