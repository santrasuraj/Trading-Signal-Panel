// Session volume profile (order flow, chart side panel): volume at each price level today, split into buyer- and
// seller-initiated, with the point of control (most traded level) and the 70% value area. An estimate from the FYERS
// feed (scanner/intraday/orderflow.py).

import { Card } from '@/components/ui'
import { cn } from '@/lib/csv'
import { num } from '@/lib/format'

export interface Profile { price: number; buy: number; sell: number }

export function VolumeProfile({ profile, poc, va, totals, note }: { profile: Profile[]; poc: number | null; va: [number, number] | null; totals: { buy: number; sell: number }; note: string }) {
  const rows = [...profile].sort((a, b) => b.price - a.price)
  const show = rows.length > 40 ? rows.filter((_, i) => i % Math.ceil(rows.length / 40) === 0 || rows[i].price === poc) : rows
  const max = Math.max(1, ...rows.map((r) => r.buy + r.sell))
  const tot = totals.buy + totals.sell
  return (
    <Card title="Order flow today" subtitle={tot ? `Bought ${num((totals.buy / tot) * 100, 0)}% · sold ${num((totals.sell / tot) * 100, 0)}% of the volume (estimated)` : undefined}>
      <div className="space-y-px">
        {show.map((r) => {
          const w = ((r.buy + r.sell) / max) * 100
          const inVa = va && r.price >= va[0] && r.price <= va[1]
          return (
            <div key={r.price} className="flex items-center gap-1.5 text-[10px]" title={`${num(r.price, 2)}: bought ${num(r.buy, 0)}, sold ${num(r.sell, 0)}`}>
              <span className={cn('num w-14 text-right', r.price === poc ? 'font-bold text-fg' : inVa ? 'text-muted' : 'text-faint')}>{num(r.price, 2)}</span>
              <div className="flex h-2.5 flex-1">
                <div className="flex h-full" style={{ width: `${w}%` }}>
                  <div className="h-full bg-profit/70" style={{ width: `${(r.buy / Math.max(1, r.buy + r.sell)) * 100}%` }} />
                  <div className="h-full flex-1 bg-loss/70" />
                </div>
              </div>
            </div>
          )
        })}
      </div>
      <p className="mt-2 text-2xs text-faint">Bold: point of control (most traded level){va ? `; value area ${num(va[0], 2)}-${num(va[1], 2)} (70% of the volume)` : ''}. {note}</p>
    </Card>
  )
}
