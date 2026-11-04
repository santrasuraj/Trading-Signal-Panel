// Options verdict (Chart page, top of the Options & F&O card): BUY CALL / BUY PUT / NO TRADE for the nearest expiry,
// every check it passed or failed, the call and put candidates valued on this stock's own history, and the journal's
// record so far (scanner/option_verdict.py). A buy needs a tested direction and an option worth more than it costs.

import { useState } from 'react'
import { Check, X } from 'lucide-react'
import type { OptVerdict, OvCandidate } from '@/api/outlook'
import { Tip } from '@/components/ui'
import { cn } from '@/lib/csv'
import { DASH, date, num, pct, qty } from '@/lib/format'
import { VERDICT_STYLE } from '@/lib/verdict'

function Candidates({ items, title }: { items: OvCandidate[]; title: string }) {
  if (!items.length) return null
  return (
    <div className="min-w-0">
      <div className="eyebrow mb-1">{title}</div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[520px] whitespace-nowrap text-xs">
          <thead><tr className="border-b border-line text-2xs text-muted">
            {['Strike', 'Price', 'Breakeven', 'History-fair', 'Edge', 'Chance ≥ breakeven', 'Spread', 'OI', ''].map((h, i) => <th key={h} className={cn('py-1 font-medium', i ? 'text-right' : 'text-left')}>{h}</th>)}
          </tr></thead>
          <tbody>{items.map((c) => (
            <tr key={`${c.side}${c.strike}`} className="border-b border-line/50 last:border-0">
              <td className="py-1"><span className={cn('font-semibold', c.side === 'ce' ? 'text-profit' : 'text-loss')}>{num(c.strike, 0)} {c.side.toUpperCase()}</span> <span className="text-faint">{c.moneyness}</span></td>
              <td className="num py-1 text-right" title={c.quoted ? `bid ${num(c.bid, 2)} / ask ${num(c.ask, 2)}` : 'no live bid / ask: last traded price'}>{num(c.premium, 2)}{c.quoted ? '' : '*'}</td>
              <td className="num py-1 text-right">{num(c.breakeven, 2)} <span className="text-faint">{pct(c.breakeven_pct, { dp: 1 })}</span></td>
              <td className="num py-1 text-right">{num(c.fair, 2)}</td>
              <td className={cn('num py-1 text-right font-medium', (c.edge_pct ?? 0) >= 0 ? 'text-profit' : 'text-loss')}>{pct(c.edge_pct, { dp: 0 })}</td>
              <td className="num py-1 text-right">{num(c.prob_profit_pct, 0)}%</td>
              <td className="num py-1 text-right text-muted">{c.spread_pct != null ? `${num(c.spread_pct, 1)}%` : DASH}</td>
              <td className="num py-1 text-right text-muted">{qty(c.oi)}</td>
              <td className="py-1 pl-2 text-right">{c.ok ? <span className="text-profit">passes</span> : <Tip text={c.fails.join('; ')}><span className="text-faint underline decoration-dotted">fails {c.fails.length}</span></Tip>}</td>
            </tr>
          ))}</tbody>
        </table>
      </div>
    </div>
  )
}

export function OptionVerdictPanel({ v }: { v: OptVerdict }) {
  const [more, setMore] = useState(false)
  const s = VERDICT_STYLE[v.verdict]
  const t = v.track
  return (
    <div className="space-y-3 rounded-md border border-line p-3">
      <div className="flex flex-wrap items-center gap-3">
        <span className={cn('rounded-md border-2 px-3 py-1 text-[15px] font-bold tracking-wide', s.cls)}>{s.label}</span>
        <div className="min-w-0 flex-1">
          <div className="text-[13px] font-medium">{v.headline}</div>
          <div className="text-2xs text-muted">Nearest expiry {date(v.expiry)} · {num(v.days_to_expiry, 1)} days ({v.trading_days} trading) · implied vol {num(v.iv_pct, 1)}% vs history {num(v.vol_used_pct, 1)}% ({v.iv_vs_hv != null ? (v.iv_vs_hv < 0.9 ? 'options cheap vs history' : v.iv_vs_hv > 1.1 ? 'options expensive vs history' : 'about fair') : 'no ratio'})</div>
        </div>
      </div>
      <ul className="grid gap-1 sm:grid-cols-2">
        {v.checks.map((c) => (
          <li key={c.name} className="flex items-start gap-1.5 text-xs">
            {c.ok ? <Check className="mt-0.5 h-3.5 w-3.5 shrink-0 text-profit" /> : <X className="mt-0.5 h-3.5 w-3.5 shrink-0 text-loss" />}
            <span><span className="font-medium">{c.name}</span> <span className="text-muted">· {c.detail}</span></span>
          </li>
        ))}
      </ul>
      <div className="text-xs">
        <span className="font-medium">Direction: </span>
        <span className={v.direction.bias === 'bullish' ? 'text-profit' : v.direction.bias === 'bearish' ? 'text-loss' : 'text-muted'}>{v.direction.bias === 'none' ? 'no tested direction' : v.direction.bias}</span>
        <span className="text-muted"> - {v.direction.reasons.join(' ')}</span>
      </div>
      {v.exit && (
        <div className="rounded-md bg-raised px-2 py-1.5 text-xs">
          <span className="font-medium">Exit plan: </span>stop if the stock closes {v.verdict === 'BUY_CALL' ? 'below' : 'above'} {num(v.exit.stop_underlying, 2)} · target near {num(v.exit.target_underlying, 2)}. <span className="text-muted">{v.exit.note}</span>
        </div>
      )}
      <button type="button" className="link text-xs" onClick={() => setMore(!more)}>{more ? 'Hide' : 'Show'} every call and put checked</button>
      {more && (
        <div className="space-y-3">
          <Candidates items={v.calls} title="Calls (for a rise)" />
          <Candidates items={v.puts} title="Puts (for a fall)" />
          <p className="text-2xs text-muted">History-fair: the option's average payoff at expiry over every past {v.trading_days}-trading-day move of this stock, re-scaled to today's volatility ({num(v.vol_used_pct, 1)}%/yr) and shifted by the similar setups' median drift. Edge: that value vs the price paid plus ~{num(v.cost_pct, 0)}% costs. A buy needs +{num(v.edge_min_pct, 0)}% edge, a {num(v.prob_min_pct, 0)}% chance to end beyond the breakeven, a spread under 10% and 200+ contracts open. * no live bid / ask (market closed): last traded price.</p>
        </div>
      )}
      <div className="rounded-md border border-line px-2 py-1.5 text-xs">
        <span className="font-medium">Record so far: </span>
        {t.settled === 0
          ? <span className="text-muted">{t.recorded} verdict{t.recorded === 1 ? '' : 's'} journalled{t.first_day ? ` since ${date(t.first_day)}` : ''}, none expired yet. The scan journals each day's verdict and scores it at expiry - judge this only after dozens have settled.</span>
          : <span className="text-muted">{t.settled} settled: {t.buys} buys ({t.buy_wins} won, average {pct(t.buy_avg_return_pct, { dp: 0 })}), {t.no_trades} no-trades. For comparison, always buying the ATM call averaged {pct(t.atm_call_avg_return_pct, { dp: 0 })}, the ATM put {pct(t.atm_put_avg_return_pct, { dp: 0 })}.</span>}
      </div>
      <p className="text-2xs text-muted">{v.note}</p>
    </div>
  )
}
