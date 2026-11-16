// Market heatmap `/heatmap`: today's universe grouped by industry, each stock sized by its traded value and coloured
// by its move (web/api/services/market_views.py). From 09:15 to 18:00 the day's move is the freshest price the server
// already has; it refreshes the rest in the background, so while it does the page asks again every few seconds, and
// a line under the title says where the moves came from and how old they are. Click a stock for its chart.

import { useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { fetchJson } from '@/api/client'
import { PageHeader } from '@/components/domain'
import { ErrorState, Skeleton } from '@/components/feedback'
import { Segmented } from '@/components/ui'
import { useWidth } from '@/lib/useWidth'
import { squarify } from '@/lib/treemap'
import { provenance, sourceLabel, type HeatProvenance, type MoveSource } from '@/lib/heatmap'
import { useLocalStorage } from '@/lib/useLocalStorage'

type Period = '1d' | '1w' | '1m' | '3m' | '12m'
interface Stock { symbol: string; company: string | null; price: number | null; size: number; move: number | null; source: MoveSource }
interface Group { industry: string; size: number; move: number | null; up: number; down: number; stocks: Stock[] }
interface Heat extends HeatProvenance { period: Period; groups: Group[]; stocks: number; live: number; note: string; as_of: string }

const RANGE: Record<Period, number> = { '1d': 3, '1w': 6, '1m': 12, '3m': 20, '12m': 40 }   // the move that gets full colour

function colour(move: number | null, full: number): string {
  if (move == null) return 'rgb(var(--raised))'
  const k = Math.min(1, Math.abs(move) / full)
  const a = 0.18 + 0.72 * k
  return move >= 0 ? `rgb(var(--profit) / ${a})` : `rgb(var(--loss) / ${a})`
}

export default function Heatmap() {
  const nav = useNavigate()
  const [period, setPeriod] = useLocalStorage<Period>('qd.heatmap.period', '1d')
  const q = useQuery({ queryKey: ['heatmap', period], queryFn: () => fetchJson<Heat>(`/api/heatmap?period=${period}`), staleTime: 30_000,
    // while the server fetches quotes in the background, ask again soon: each answer is instant (no network)
    refetchInterval: (qq) => (period !== '1d' ? false : qq.state.data?.refreshing ? 5_000 : 60_000) })
  const [ref, width] = useWidth<HTMLDivElement>()
  const height = Math.max(520, typeof window !== 'undefined' ? window.innerHeight - 230 : 700)
  const boxes = useMemo(() => {
    if (!q.data || !width) return []
    return squarify(q.data.groups, (g) => g.size, { x: 0, y: 0, w: width, h: height }).map((g) => ({
      ...g, stocks: squarify(g.item.stocks, (s) => s.size, { x: g.x + 1, y: g.y + 16, w: Math.max(0, g.w - 2), h: Math.max(0, g.h - 17) }),
    }))
  }, [q.data, width, height])
  const full = RANGE[period]
  return (
    <div>
      <PageHeader title="Market heatmap" subtitle={q.data ? `${q.data.stocks} stocks by industry · ${q.data.note}` : 'Today\'s universe by industry'}
        right={<Segmented<Period> ariaLabel="Period" value={period} onChange={setPeriod} items={[{ id: '1d', label: 'Today' }, { id: '1w', label: '1W' }, { id: '1m', label: '1M' }, { id: '3m', label: '3M' }, { id: '12m', label: '12M' }]} />}>
        {q.data && q.data.period === '1d' && (
          <div className="-mt-2 text-xs text-muted" aria-live="polite">
            Today&apos;s moves:{' '}
            {provenance(q.data).map((p, i) => (
              <span key={p.text}>{i > 0 && ' · '}<span className={p.warn ? 'text-warn' : undefined}>{p.text}</span></span>
            ))}
          </div>
        )}
      </PageHeader>
      {q.error ? <ErrorState error={q.error} /> : (
        <div ref={ref} className="relative w-full overflow-hidden rounded-md border border-line bg-panel" style={{ height }}>
          {!q.data ? <Skeleton className="h-full w-full" /> : boxes.map((g) => (
            <div key={g.item.industry}>
              <div className="absolute truncate px-1 text-2xs font-semibold text-fg" style={{ left: g.x, top: g.y, width: g.w, height: 16 }}
                title={`${g.item.industry}: ${g.item.move != null ? `${g.item.move >= 0 ? '+' : ''}${g.item.move}%` : ''} · ${g.item.up} up, ${g.item.down} down`}>
                {g.item.industry} {g.item.move != null && <span className={g.item.move >= 0 ? 'text-profit' : 'text-loss'}>{g.item.move >= 0 ? '+' : ''}{g.item.move.toFixed(1)}%</span>}
              </div>
              {g.stocks.map((s) => (
                <button key={s.item.symbol} type="button" onClick={() => nav(`/chart/${s.item.symbol}`)}
                  title={`${s.item.symbol} · ${s.item.company ?? ''}\n${s.item.move != null ? `${s.item.move >= 0 ? '+' : ''}${s.item.move}%` : 'no move'} · ₹${s.item.price ?? '—'} · traded ₹${Math.round(s.item.size)} cr a day${period === '1d' ? `\nMove from: ${sourceLabel(s.item.source, q.data?.scan_date ?? null)}` : ''}`}
                  className="absolute overflow-hidden border border-bg/60 text-left leading-tight hover:outline hover:outline-2 hover:outline-accent"
                  style={{ left: s.x, top: s.y, width: s.w, height: s.h, background: colour(s.item.move, full) }}>
                  {s.w > 42 && s.h > 22 && (
                    <span className="block px-1 pt-0.5 text-[11px] font-semibold text-fg">{s.item.symbol}
                      {s.h > 34 && s.item.move != null && <span className="block font-normal">{s.item.move >= 0 ? '+' : ''}{s.item.move.toFixed(1)}%</span>}</span>
                  )}
                </button>
              ))}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
