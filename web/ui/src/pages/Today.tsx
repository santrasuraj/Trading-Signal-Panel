// Today `/today`: every tested BUY and SELL for the next open (your holdings' exits first) and every HOLD, one answer
// per stock. When there is none, it says so plainly, with how often tested actions come at all.

import { Link } from 'react-router-dom'
import { useToday } from '@/api/action'
import { ActionCardView } from '@/components/ActionCard'
import { AsOfLine, KpiStrip, KpiTile, PageHeader } from '@/components/domain'
import { EmptyState, ErrorState, SkeletonKpis, SkeletonRows } from '@/components/feedback'
import { Card } from '@/components/ui'

export default function Today() {
  const q = useToday()
  const d = q.data
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
          <Card title="Actions for the next open" subtitle="Exits of your holdings first, then buys by signal strength">
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
        </div>
      )}
    </div>
  )
}
