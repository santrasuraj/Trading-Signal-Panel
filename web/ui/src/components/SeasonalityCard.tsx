// Seasonality (chart side panel): the stock's average return in each calendar month over the years in the store, the
// share of up years, and only months with |t| >= 2 marked as a pattern (the rest is noise). Details: every year.

import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { CalendarRange } from 'lucide-react'
import { fetchJson } from '@/api/client'
import { Button, Card, Dialog } from '@/components/ui'
import { cn } from '@/lib/csv'

interface Month { month: number; name: string; n: number; avg: number | null; median: number | null; up_pct: number | null; t: number | null; pattern: boolean; vs_nifty: { avg: number | null } | null }
interface Season { symbol: string; first_year: number; last_year: number; months: Month[]; years: { year: number; rets: (number | null)[] }[]; note: string }

const fmt = (v: number | null) => (v == null ? '—' : `${v >= 0 ? '+' : ''}${v.toFixed(1)}%`)

export function SeasonalityCard({ symbol }: { symbol: string }) {
  const q = useQuery({ queryKey: ['seasonality', symbol], queryFn: () => fetchJson<Season>(`/api/seasonality/${encodeURIComponent(symbol)}`), staleTime: 60 * 60_000, retry: false })
  const [open, setOpen] = useState(false)
  const d = q.data?.symbol === symbol ? q.data : undefined
  const now = new Date().getMonth() + 1
  const max = d ? Math.max(1, ...d.months.map((m) => Math.abs(m.avg ?? 0))) : 1
  const cur = d?.months.find((m) => m.month === now)
  return (
    <Card title={<span className="flex items-center gap-1.5"><CalendarRange className="h-4 w-4 text-muted" />Seasonality</span>}
      right={d ? <Button size="xs" variant="ghost" onClick={() => setOpen(true)}>Every year</Button> : undefined}>
      {q.error ? <p className="text-xs text-muted">No seasonality for {symbol}.</p> : !d ? <p className="text-xs text-muted">Loading…</p> : (
        <>
          <div className="flex h-24 items-center gap-0.5">
            {d.months.map((m) => {
              const h = ((Math.abs(m.avg ?? 0)) / max) * 44
              return (
                <div key={m.month} className="flex h-full flex-1 flex-col items-center" title={`${m.name}: average ${fmt(m.avg)}, up in ${m.up_pct ?? '—'}% of ${m.n} years, t ${m.t ?? '—'}${m.pattern ? ' (a pattern)' : ' (noise)'}`}>
                  <div className="flex h-1/2 w-full items-end justify-center">{(m.avg ?? 0) > 0 && <div className={cn('w-3/4 rounded-t-sm', m.pattern ? 'bg-profit' : 'bg-profit/40')} style={{ height: h }} />}</div>
                  <div className="flex h-1/2 w-full items-start justify-center">{(m.avg ?? 0) < 0 && <div className={cn('w-3/4 rounded-b-sm', m.pattern ? 'bg-loss' : 'bg-loss/40')} style={{ height: h }} />}</div>
                  <span className={cn('mt-0.5 text-[9px]', m.month === now ? 'font-bold text-fg' : 'text-faint')}>{m.name[0]}</span>
                </div>
              )
            })}
          </div>
          {cur && <p className="mt-2 text-xs text-muted">{cur.name}: average <span className="num text-fg">{fmt(cur.avg)}</span>, up in {cur.up_pct ?? '—'}% of {cur.n} years ({d.first_year}-{d.last_year}){cur.vs_nifty?.avg != null && <>, {fmt(cur.vs_nifty.avg)} against the Nifty</>}. {cur.pattern ? 'Strong enough to call a pattern (t ' + cur.t + ').' : 'Within noise.'}</p>}
          <p className="mt-1 text-2xs text-faint">Solid bars: |t| ≥ 2 over 8+ years; faded: noise. Not a forecast.</p>
          <Dialog open={open} onClose={() => setOpen(false)} width={760} title={`${symbol}: monthly returns`}>
            <div className="scroll-x">
              <table className="w-full text-[12px]">
                <thead className="text-2xs text-muted"><tr><th className="text-left">Year</th>{d.months.map((m) => <th key={m.month} className="text-right">{m.name}</th>)}</tr></thead>
                <tbody>
                  {d.years.map((y) => (
                    <tr key={y.year} className="border-t border-line"><td className="py-1">{y.year}</td>{y.rets.map((v, i) => <td key={i} className={cn('num text-right', v == null ? 'text-faint' : v >= 0 ? 'text-profit' : 'text-loss')}>{v == null ? '' : v.toFixed(1)}</td>)}</tr>
                  ))}
                  <tr className="border-t-2 border-line font-medium"><td className="py-1">Average</td>{d.months.map((m) => <td key={m.month} className="num text-right">{m.avg == null ? '' : m.avg.toFixed(1)}</td>)}</tr>
                  <tr><td className="py-1 text-muted">Up years</td>{d.months.map((m) => <td key={m.month} className="num text-right text-muted">{m.up_pct == null ? '' : `${m.up_pct}%`}</td>)}</tr>
                  <tr><td className="py-1 text-muted">t</td>{d.months.map((m) => <td key={m.month} className={cn('num text-right', m.pattern ? 'font-semibold text-fg' : 'text-faint')}>{m.t ?? ''}</td>)}</tr>
                </tbody>
              </table>
            </div>
            <p className="mt-2 text-2xs text-faint">{d.note}</p>
          </Dialog>
        </>
      )}
    </Card>
  )
}
