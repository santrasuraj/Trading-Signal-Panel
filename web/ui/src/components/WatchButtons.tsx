// Chart toolbar: add / remove the stock on your first watchlist, and set a price alert on it.

import { BellPlus, Star } from 'lucide-react'
import { isFailure } from '@/api/client'
import { useAlerts, useSaveWatchlists, useWatchlists } from '@/api/watch'
import { useToast } from '@/components/toast'
import { IconButton, Popover } from '@/components/ui'
import { AlertForm } from '@/pages/Watchlist'
import { cn } from '@/lib/csv'

export function WatchButton({ symbol }: { symbol: string }) {
  const q = useWatchlists()
  const save = useSaveWatchlists()
  const toast = useToast()
  const lists = q.data?.lists ?? []
  const on = lists.some((l) => l.symbols.includes(symbol))
  const first = lists[0]
  const toggle = () => {
    if (!first) return
    const next = on ? lists.map((l) => ({ ...l, symbols: l.symbols.filter((s) => s !== symbol) }))
      : lists.map((l, i) => (i === 0 ? { ...l, symbols: [...l.symbols, symbol] } : l))
    save.mutate(next, {
      onSuccess: () => toast({ tone: 'good', title: on ? `${symbol} removed from your watchlists` : `${symbol} added to ${first.name}`, detail: on ? undefined : 'Streamed live from the next live-feed start.' }),
      onError: (e) => toast({ tone: 'bad', title: 'Watchlist not saved', detail: isFailure(e) ? e.message : undefined }),
    })
  }
  return (
    <IconButton label={on ? `Remove ${symbol} from watchlists` : `Add ${symbol} to ${first?.name ?? 'watchlist'}`} onClick={toggle} disabled={!first || save.isPending}>
      <Star className={cn('h-4 w-4', on && 'fill-warn text-warn')} />
    </IconButton>
  )
}

export function AlertButton({ symbol, price }: { symbol: string; price: number | null }) {
  const alerts = useAlerts()
  const n = alerts.data?.alerts.filter((a) => a.active && a.symbol === symbol).length ?? 0
  return (
    <Popover align="right" width={340} trigger={({ toggle, open }) => (
      <IconButton label={n ? `${n} active alert${n > 1 ? 's' : ''} on ${symbol}: add another` : `Set a price alert on ${symbol}`} onClick={toggle} aria-expanded={open}>
        <BellPlus className={cn('h-4 w-4', n > 0 && 'text-accent')} />
      </IconButton>
    )}>
      {(close) => (
        <div className="space-y-2 p-3">
          <div className="text-[13px] font-semibold">Price alert on {symbol}</div>
          <AlertForm symbol={symbol} price={price} onDone={close} />
          <p className="text-2xs text-faint">Fires once on the live price (FYERS real time, or Yahoo ~15 min late without a login), in the app and on Telegram when set up. Manage alerts on the Watchlist page.</p>
        </div>
      )}
    </Popover>
  )
}
