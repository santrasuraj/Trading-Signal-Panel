// Market depth ladder (chart side panel): FYERS' five best offers above, five best bids below, with quantity bars and
// the book's total buy / sell quantity. Off until you open it (each refresh is a FYERS call, every 2 s); click a price
// to open an order ticket there (an offer: buy at it; a bid: sell at it). Needs today's FYERS login.

import { useState } from 'react'
import { Layers3 } from 'lucide-react'
import { isFailure } from '@/api/client'
import { useDepth } from '@/api/sim'
import { Button, Card } from '@/components/ui'
import { cn } from '@/lib/csv'
import { num } from '@/lib/format'

export function DepthLadder({ symbol, onPick }: { symbol: string; onPick: (side: 'BUY' | 'SELL', price: number) => void }) {
  const [on, setOn] = useState(false)
  const q = useDepth(symbol, on)
  const d = q.data?.symbol === symbol ? q.data : undefined
  const max = Math.max(1, ...(d ? [...d.bids, ...d.asks].map((r) => r.qty) : [1]))
  const row = (r: { price: number; qty: number; orders: number }, side: 'bid' | 'ask') => (
    <button key={`${side}${r.price}`} type="button" onClick={() => onPick(side === 'ask' ? 'BUY' : 'SELL', r.price)}
      title={side === 'ask' ? `Buy at ${num(r.price, 2)}` : `Sell at ${num(r.price, 2)}`}
      className="relative flex w-full items-center justify-between px-3 py-1 text-xs hover:bg-raised">
      <span className={cn('absolute inset-y-0 right-0 opacity-20', side === 'ask' ? 'bg-loss' : 'bg-profit')} style={{ width: `${(r.qty / max) * 100}%` }} />
      <span className={cn('num relative font-medium', side === 'ask' ? 'text-loss' : 'text-profit')}>{num(r.price, 2)}</span>
      <span className="num relative text-muted">{r.qty.toLocaleString('en-IN')} <span className="text-faint">({r.orders})</span></span>
    </button>
  )
  return (
    <Card title={<span className="flex items-center gap-1.5"><Layers3 className="h-4 w-4 text-muted" />Market depth</span>}
      right={<Button size="xs" variant={on ? 'secondary' : 'subtle'} onClick={() => setOn((x) => !x)}>{on ? 'Hide' : 'Show'}</Button>} flush>
      {!on ? <p className="px-4 py-3 text-xs text-muted">FYERS' five best bids and offers, refreshed every 2 seconds while open. Click a price to trade there.</p>
        : q.error ? <p className="px-4 py-3 text-xs text-warn">{isFailure(q.error) ? `${q.error.message} ${q.error.hint ?? ''}` : 'Depth unavailable.'}</p>
        : !d ? <p className="px-4 py-3 text-xs text-muted">Loading…</p> : (
          <div className="py-1">
            {[...d.asks].reverse().map((r) => row(r, 'ask'))}
            <div className="border-y border-line px-3 py-1 text-center text-xs">Last <span className="num font-semibold">{num(d.ltp, 2)}</span></div>
            {d.bids.map((r) => row(r, 'bid'))}
            <p className="px-3 pt-1 text-2xs text-muted">Book: buy <span className="num">{d.total_buy.toLocaleString('en-IN')}</span> · sell <span className="num">{d.total_sell.toLocaleString('en-IN')}</span></p>
          </div>
        )}
    </Card>
  )
}
