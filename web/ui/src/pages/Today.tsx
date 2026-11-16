// Today `/today`: every tested BUY and SELL for the next open (your holdings' exits first) and every HOLD, one answer
// per stock. When there is none, it says so plainly, with how often tested actions come at all.

import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { ShoppingBasket } from 'lucide-react'
import { useToday } from '@/api/action'
import { useLiveQuotes } from '@/api/hooks'
import { BasketDialog } from '@/components/BasketDialog'
import { ActionCardView, cardTicket } from '@/components/ActionCard'
import { AsOfLine, KpiStrip, KpiTile, PageHeader } from '@/components/domain'
import { EmptyState, ErrorState, SkeletonKpis, SkeletonRows } from '@/components/feedback'
import { Button, Card } from '@/components/ui'

export default function Today() {
  const q = useToday()
  const d = q.data
  const [basket, setBasket] = useState(false)
  const actionable = useMemo(() => (d?.actions ?? []).filter((a) => a.state === 'BUY' || a.state === 'SELL'), [d])
  const lq = useLiveQuotes(actionable.map((a) => a.symbol))
  const tickets = useMemo(() => actionable.map((a) => cardTicket(a, a.state === 'BUY' ? 'BUY' : 'SELL', lq.quotes[a.symbol]?.price ?? a.primary?.price ?? a.holding?.price ?? null)), [actionable, lq.quotes])
  return (
    <div>
      <PageHeader title="Today" subtitle={<>One answer per stock: BUY, SELL (exit), HOLD or NO EDGE, only from strategies whose own backtest is working · {d ? <AsOfLine a={d.as_of} /> : '…'}</>} />
      {q.error && !d ? <div className="card"><ErrorState error={q.error} onRetry={() => void q.refetch()} /></div> : !d ? (
        <div className="space-y-3"><SkeletonKpis n={3} /><div className="card"><SkeletonRows /></div></div>
      ) : (
        <div className="space-y-3">
          <KpiStrip min={140}>
            <KpiTile label="BUY" value={d.counts.buy} tone={d.counts.buy ? 'text-profit' : 'text-muted'} />
            <KpiTile label="SELL (exit)" value={d.counts.sell} tone={d.counts.sell ? 'text-loss' : 'text-muted'} />
            <KpiTile label="HOLD" value={d.counts.hold} />
          </KpiStrip>
          <Card title="Actions for the next open" subtitle="Exits of your holdings first, then buys by signal strength"
            right={tickets.length > 1 ? <Button size="sm" icon={<ShoppingBasket className="h-3.5 w-3.5" />} onClick={() => setBasket(true)}>Review all {tickets.length}</Button> : undefined}>
            {d.actions.length ? (
              <div className="space-y-2">{d.actions.map((a) => <ActionCardView key={a.symbol} a={a} compact />)}</div>
            ) : (
              <EmptyState compact title="No tested BUY or SELL today">
                {d.empty_note}{' '}
                {d.unproven_strategies.length > 0 && <>Unproven strategies with buys today (comparison only): {d.unproven_strategies.join(', ')}. </>}
                See <Link to="/signals" className="link">Signals</Link> for every strategy's orders and <Link to="/strategies" className="link">Strategies</Link> for which ones are working.
              </EmptyState>
            )}
          </Card>
          {d.holds.length > 0 && (
            <Card title="Your holdings: HOLD" subtitle="No exit has fired; the live price is checked against your stop-loss">
              <div className="space-y-2">{d.holds.map((a) => <ActionCardView key={a.symbol} a={a} compact />)}</div>
            </Card>
          )}
          <p className="text-2xs text-faint">{d.note}</p>
          {basket && <BasketDialog open={basket} onClose={() => setBasket(false)} tickets={tickets} />}
        </div>
      )}
    </div>
  )
}
