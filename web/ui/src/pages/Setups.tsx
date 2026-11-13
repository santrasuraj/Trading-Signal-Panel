// Live setups `/setups`: today's intraday events from the live bars, newest first (web/api/services/setups_svc.py):
// gaps, opening-range breaks, fresh highs / lows, VWAP crosses, volume spikes, 52-week breaks. Facts about the tape,
// not tested signals. Optional desktop notifications for new events while the page is open.

import { useEffect, useMemo, useRef } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Radio } from 'lucide-react'
import { fetchJson } from '@/api/client'
import { PageHeader } from '@/components/domain'
import { Banner, EmptyState, ErrorState, SkeletonRows } from '@/components/feedback'
import { Card, Segmented } from '@/components/ui'
import { pct } from '@/lib/format'
import { askPermission, notify } from '@/lib/notify'
import { useLocalStorage } from '@/lib/useLocalStorage'
import { cn } from '@/lib/csv'
import { SetupsTelegram } from '@/components/TelegramSettings'

interface SetupEvent {
  time: string; symbol: string; company: string | null; kind: string; label: string; bullish: boolean | null
  price: number; change_pct: number | null; value_cr: number | null; detail: string; mine: boolean
}
interface SetupsResponse {
  mode: 'live' | 'last_session' | 'none'; day: string; interval: string; symbols: number; last_bar: string | null; as_of: string
  counts: Record<string, number>; total: number; events: SetupEvent[]; labels: Record<string, string>; note: string
}
type Group = 'all' | 'bull' | 'bear' | 'breaks' | 'vwap' | 'volume'
const GROUPS: Record<Group, string[] | null> = {
  all: null, bull: ['gap_up', 'orb_up', 'new_high', 'vwap_up', 'high_52w'], bear: ['gap_down', 'orb_down', 'new_low', 'vwap_down', 'low_52w'],
  breaks: ['orb_up', 'orb_down', 'high_52w', 'low_52w'], vwap: ['vwap_up', 'vwap_down'], volume: ['volume_spike'],
}
type Notify = 'off' | 'mine' | 'all'

export default function Setups() {
  const [group, setGroup] = useLocalStorage<Group>('qd.setups.group', 'all')
  const [scope, setScope] = useLocalStorage<'all' | 'mine'>('qd.setups.scope', 'all')
  const [notifyMode, setNotifyMode] = useLocalStorage<Notify>('qd.setups.notify', 'off')
  const kinds = GROUPS[group]
  const q = useQuery({
    queryKey: ['setups', group, scope],
    queryFn: () => fetchJson<SetupsResponse>(`/api/setups?scope=${scope}&limit=300${kinds ? `&kinds=${kinds.join(',')}` : ''}`),
    refetchInterval: (query) => (query.state.data?.mode === 'live' ? 15_000 : false),
  })
  const d = q.data
  const seen = useRef<Set<string> | null>(null)
  useEffect(() => {
    if (!d) return
    const keys = d.events.map((e) => `${e.time}|${e.symbol}|${e.kind}`)
    if (seen.current && d.mode === 'live' && notifyMode !== 'off') {
      const fresh = d.events.filter((e, i) => !seen.current!.has(keys[i]) && (notifyMode === 'all' || e.mine))
      for (const e of fresh.slice(0, 3)) void notify(`${e.symbol}: ${e.label}`, `${e.detail} · ₹${e.price}`, `/chart/${e.symbol}`, `setup-${e.symbol}-${e.kind}`)
    }
    seen.current = new Set(keys)
  }, [d, notifyMode])
  const byTime = useMemo(() => d?.events ?? [], [d])
  return (
    <div>
      <PageHeader title="Live setups"
        subtitle={d ? `${d.mode === 'live' ? 'Live' : d.mode === 'last_session' ? `Session of ${d.day}` : 'No bars yet'} · ${d.symbols} stocks · ${d.interval} bars · ${d.total} events${d.last_bar ? ` · last bar ${d.last_bar.slice(11, 16)}` : ''}` : 'Gaps, breakouts, VWAP crosses and volume spikes as they happen'}
        right={<>
          <Segmented<Group> ariaLabel="Event group" value={group} onChange={setGroup} items={[{ id: 'all', label: 'All' }, { id: 'bull', label: 'Up' }, { id: 'bear', label: 'Down' }, { id: 'breaks', label: 'Breakouts' }, { id: 'vwap', label: 'VWAP' }, { id: 'volume', label: 'Volume' }]} />
          <Segmented<'all' | 'mine'> ariaLabel="Stocks" value={scope} onChange={setScope} items={[{ id: 'all', label: 'All stocks' }, { id: 'mine', label: 'Watchlist + holdings' }]} />
          <SetupsTelegram scope={scope} />
          <select aria-label="Desktop notifications" className="input h-8 px-2 text-[13px]" value={notifyMode}
            onChange={(e) => { const v = e.target.value as Notify; setNotifyMode(v); if (v !== 'off') void askPermission() }}>
            <option value="off">Notify: off</option><option value="mine">Notify: my stocks</option><option value="all">Notify: every event</option>
          </select>
        </>} />
      {d && <div className="mb-3"><Banner tone={d.mode === 'live' ? 'info' : 'warn'}>{d.note}</Banner></div>}
      {q.error ? <ErrorState error={q.error} onRetry={() => q.refetch()} /> : !d ? <Card><SkeletonRows rows={12} cols={5} /></Card> : byTime.length === 0 ? (
        <EmptyState icon={<Radio />} title="No events">{scope === 'mine' ? 'None of your watchlist or holdings stocks has an event yet.' : 'Nothing has happened yet in this group.'}</EmptyState>
      ) : (
        <Card flush>
          <div className="overflow-x-auto">
            <table className="w-full text-[13px]">
              <thead className="text-2xs text-muted"><tr className="text-left"><th className="px-4 py-1.5">Time</th><th className="px-2">Stock</th><th className="px-2">Event</th><th className="px-2 text-right">Price</th><th className="px-2 text-right">Day</th><th className="px-4">Detail</th></tr></thead>
              <tbody className="divide-y divide-line">{byTime.map((e) => (
                <tr key={`${e.time}${e.symbol}${e.kind}`} className={cn(e.mine && 'bg-accent/5')}>
                  <td className="num px-4 py-1.5 text-muted">{e.time.slice(11, 16)}</td>
                  <td className="px-2"><Link to={`/chart/${e.symbol}`} className="font-semibold hover:text-accent">{e.symbol}</Link>{e.mine && <span className="ml-1 text-2xs text-accent">yours</span>}</td>
                  <td className={cn('px-2 font-medium', e.bullish === true ? 'text-profit' : e.bullish === false ? 'text-loss' : 'text-warn')}>{e.label}</td>
                  <td className="num px-2 text-right">{e.price.toLocaleString('en-IN', { maximumFractionDigits: 2 })}</td>
                  <td className={cn('num px-2 text-right', (e.change_pct ?? 0) >= 0 ? 'text-profit' : 'text-loss')}>{pct(e.change_pct)}</td>
                  <td className="px-4 text-muted">{e.detail}{e.value_cr != null && ` · ₹${e.value_cr} cr in the bar`}</td>
                </tr>))}</tbody>
            </table>
          </div>
        </Card>
      )}
      <p className="mt-4 text-2xs text-faint">Completed bars only, so an event never disappears once shown. None of these events has a tested edge in this app: use them to look, then check the chart and the Action card.</p>
    </div>
  )
}
