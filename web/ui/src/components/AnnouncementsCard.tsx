// Company announcements from NSE (web/api/services/calendar_svc.py announcements): one stock's (chart side panel) or
// your holdings' and watchlists' (Calendar). Routine filings are hidden unless asked for; each links to NSE's PDF.

import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Megaphone } from 'lucide-react'
import { fetchJson } from '@/api/client'
import { Button, Card } from '@/components/ui'

interface Ann { symbol: string; company: string | null; time: string | null; subject: string; text: string; url: string | null; routine: boolean }
interface AnnResponse { items: Ann[]; hidden: number; days?: number; note: string }

export function AnnouncementsCard({ symbol, days = 14, limit = 8, title }: { symbol?: string; days?: number; limit?: number; title?: string }) {
  const [routine, setRoutine] = useState(false)
  const qs = new URLSearchParams({ days: String(days), limit: String(limit), routine: String(routine) })
  if (symbol) qs.set('symbol', symbol)
  const q = useQuery({ queryKey: ['announcements', symbol ?? 'mine', days, routine, limit], queryFn: () => fetchJson<AnnResponse>(`/api/announcements?${qs}`), staleTime: 15 * 60_000, retry: false })
  const d = q.data
  return (
    <Card title={<span className="flex items-center gap-1.5"><Megaphone className="h-4 w-4 text-muted" />{title ?? 'Announcements'}</span>}
      subtitle={`NSE filings, last ${days} days`}
      right={d && (d.hidden > 0 || routine) ? <Button size="xs" variant="ghost" onClick={() => setRoutine(!routine)}>{routine ? 'Hide routine' : `+${d.hidden} routine`}</Button> : undefined}>
      {!d ? <p className="text-xs text-muted">{q.error ? 'NSE did not answer.' : 'Loading…'}</p> : d.items.length === 0 ? (
        <p className="text-xs text-muted">{symbol ? 'No important filings in this window.' : 'No important filings from your holdings or watchlists in this window.'}</p>
      ) : (
        <ul className="space-y-2.5">{d.items.map((a, i) => (
          <li key={i} className="text-[13px] leading-snug">
            <div className="flex items-baseline justify-between gap-2">
              <span className="font-medium text-fg">{!symbol && <Link to={`/chart/${a.symbol}`} className="mr-1 font-semibold hover:text-accent">{a.symbol}</Link>}{a.subject}</span>
              <span className="shrink-0 text-2xs text-muted">{a.time ? a.time.slice(0, 16).replace('T', ' ') : ''}</span>
            </div>
            {a.text && <p className="mt-0.5 line-clamp-2 text-xs text-muted">{a.text}</p>}
            {a.url && <a className="link text-2xs" href={a.url} target="_blank" rel="noreferrer noopener">PDF on NSE</a>}
          </li>))}</ul>
      )}
    </Card>
  )
}
