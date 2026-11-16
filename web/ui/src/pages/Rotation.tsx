// Sector rotation `/rotation`: NSE sector indices on a relative rotation graph against the Nifty 50 (rrg_svc.py),
// each with a tail of its last weeks, and the tested record of what each quadrant said about the next 4 weeks.

import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { fetchJson } from '@/api/client'
import { PageHeader } from '@/components/domain'
import { ErrorState, SkeletonChart } from '@/components/feedback'
import { Card, Segmented } from '@/components/ui'
import { date as fmtDate, pct } from '@/lib/format'
import { useLocalStorage } from '@/lib/useLocalStorage'
import { useWidth } from '@/lib/useWidth'
import { cn } from '@/lib/csv'

interface Pt { t: string; x: number; y: number }
interface Sector { name: string; full: string; tail: Pt[]; quadrant: string; ret_4: number | null; vs_nifty_4: number | null }
interface Rec { quadrant: string; n: number; avg_pct: number | null; hit_pct: number | null; t: number | null }
interface Rrg { tf: string; as_of: string; sectors: Sector[]; record: Rec[]; fwd: number; note: string }

const Q_COLOR: Record<string, string> = { Leading: 'profit', Weakening: 'warn', Lagging: 'loss', Improving: 'info' }

function Graph({ d }: { d: Rrg }) {
  const [ref, w] = useWidth<HTMLDivElement>()
  const [hover, setHover] = useState<string | null>(null)
  const W = Math.max(w, 320), H = Math.min(560, Math.max(360, W * 0.7)), P = 28
  const all = d.sectors.flatMap((s) => s.tail)
  const span = Math.max(2.2, ...all.map((p) => Math.max(Math.abs(p.x - 100), Math.abs(p.y - 100)))) * 1.08
  const X = (x: number) => P + ((x - (100 - span)) / (2 * span)) * (W - 2 * P)
  const Y = (y: number) => P + (((100 + span) - y) / (2 * span)) * (H - 2 * P)
  return (
    <div ref={ref} className="w-full">
      <svg width={W} height={H} role="img" aria-label="Relative rotation graph">
        <rect x={X(100)} y={Y(100 + span)} width={X(100 + span) - X(100)} height={Y(100) - Y(100 + span)} fill="rgb(var(--profit) / 0.06)" />
        <rect x={X(100)} y={Y(100)} width={X(100 + span) - X(100)} height={Y(100 - span) - Y(100)} fill="rgb(var(--warn) / 0.06)" />
        <rect x={X(100 - span)} y={Y(100)} width={X(100) - X(100 - span)} height={Y(100 - span) - Y(100)} fill="rgb(var(--loss) / 0.06)" />
        <rect x={X(100 - span)} y={Y(100 + span)} width={X(100) - X(100 - span)} height={Y(100) - Y(100 + span)} fill="rgb(var(--info) / 0.06)" />
        <line x1={X(100)} x2={X(100)} y1={P} y2={H - P} stroke="rgb(var(--line-strong))" />
        <line x1={P} x2={W - P} y1={Y(100)} y2={Y(100)} stroke="rgb(var(--line-strong))" />
        <text x={W - P - 4} y={P + 12} textAnchor="end" className="fill-[rgb(var(--profit))] text-[11px] font-semibold">Leading</text>
        <text x={W - P - 4} y={H - P - 6} textAnchor="end" className="fill-[rgb(var(--warn))] text-[11px] font-semibold">Weakening</text>
        <text x={P + 4} y={H - P - 6} className="fill-[rgb(var(--loss))] text-[11px] font-semibold">Lagging</text>
        <text x={P + 4} y={P + 12} className="fill-[rgb(var(--info))] text-[11px] font-semibold">Improving</text>
        <text x={W / 2} y={H - 6} textAnchor="middle" className="fill-[rgb(var(--muted))] text-[10px]">RS-Ratio (strength vs Nifty) →</text>
        <text x={10} y={H / 2} transform={`rotate(-90 10 ${H / 2})`} textAnchor="middle" className="fill-[rgb(var(--muted))] text-[10px]">RS-Momentum →</text>
        {d.sectors.map((s) => {
          const c = Q_COLOR[s.quadrant] ?? 'muted'
          const dim = hover && hover !== s.name
          const last = s.tail[s.tail.length - 1]
          return (
            <g key={s.name} opacity={dim ? 0.15 : 1} onMouseEnter={() => setHover(s.name)} onMouseLeave={() => setHover(null)}>
              <path d={s.tail.map((p, i) => `${i ? 'L' : 'M'}${X(p.x)},${Y(p.y)}`).join('')} fill="none" stroke={`rgb(var(--${c}))`} strokeWidth={1.5} opacity={0.7} />
              {s.tail.slice(0, -1).map((p) => <circle key={p.t} cx={X(p.x)} cy={Y(p.y)} r={1.8} fill={`rgb(var(--${c}))`} opacity={0.6} />)}
              <circle cx={X(last.x)} cy={Y(last.y)} r={4.5} fill={`rgb(var(--${c}))`}><title>{`${s.full}: RS-Ratio ${last.x.toFixed(1)}, momentum ${last.y.toFixed(1)} (${s.quadrant})`}</title></circle>
              <text x={X(last.x) + 6} y={Y(last.y) + 3} className="fill-[rgb(var(--fg))] text-[10px]">{s.name}</text>
            </g>)
        })}
      </svg>
    </div>
  )
}

export default function Rotation() {
  const [tf, setTf] = useLocalStorage<'weekly' | 'daily'>('qd.rrg.tf', 'weekly')
  const [tail, setTail] = useLocalStorage<number>('qd.rrg.tail', 8)
  const q = useQuery({ queryKey: ['rrg', tf, tail], queryFn: () => fetchJson<Rrg>(`/api/rrg?tf=${tf}&tail=${tail}`), staleTime: 10 * 60_000 })
  const d = q.data
  const sorted = useMemo(() => [...(d?.sectors ?? [])].sort((a, b) => ['Leading', 'Improving', 'Weakening', 'Lagging'].indexOf(a.quadrant) - ['Leading', 'Improving', 'Weakening', 'Lagging'].indexOf(b.quadrant) || (b.vs_nifty_4 ?? 0) - (a.vs_nifty_4 ?? 0)), [d])
  return (
    <div>
      <PageHeader title="Sector rotation" subtitle={d ? `NSE sector indices against the Nifty 50 · ${tf} · as of ${fmtDate(d.as_of)}` : 'Which sectors lead, weaken, lag or improve'}
        right={<>
          <Segmented<'weekly' | 'daily'> ariaLabel="Timeframe" value={tf} onChange={setTf} items={[{ id: 'weekly', label: 'Weekly' }, { id: 'daily', label: 'Daily' }]} />
          <Segmented<string> ariaLabel="Tail length" value={String(tail)} onChange={(v) => setTail(Number(v))} items={['4', '8', '13'].map((n) => ({ id: n, label: `${n} ${tf === 'weekly' ? 'wk' : 'd'}` }))} />
        </>} />
      {q.error ? <ErrorState error={q.error} onRetry={() => q.refetch()} /> : !d ? <SkeletonChart height={480} /> : (
        <div className="grid gap-3 xl:grid-cols-3">
          <Card className="xl:col-span-2" title="Relative rotation graph" subtitle="Each dot: a sector now; its tail: the path of the last periods. Sectors usually move clockwise."><Graph d={d} /></Card>
          <div className="space-y-3">
            <Card flush title="Sectors" subtitle="Last 4 weeks, and against the Nifty 50">
              <table className="w-full text-[13px]"><tbody className="divide-y divide-line">{sorted.map((s) => (
                <tr key={s.name}><td className="px-4 py-1.5">{s.name}</td><td className={cn('px-2 text-2xs font-semibold', `text-${Q_COLOR[s.quadrant]}`)}>{s.quadrant}</td>
                  <td className={cn('num px-2 text-right', (s.ret_4 ?? 0) >= 0 ? 'text-profit' : 'text-loss')}>{pct(s.ret_4)}</td>
                  <td className={cn('num px-4 text-right', (s.vs_nifty_4 ?? 0) >= 0 ? 'text-profit' : 'text-loss')}>{pct(s.vs_nifty_4)}</td></tr>))}</tbody></table>
            </Card>
            <Card flush title={`Does the quadrant predict? Next ${d.fwd} ${tf === 'weekly' ? 'weeks' : 'days'} vs Nifty`} subtitle="Every sector, every period since 2018">
              <table className="w-full text-[13px]"><tbody className="divide-y divide-line">{d.record.map((r) => (
                <tr key={r.quadrant}><td className={cn('px-4 py-1.5 font-medium', `text-${Q_COLOR[r.quadrant]}`)}>{r.quadrant}</td>
                  <td className={cn('num px-2 text-right', (r.avg_pct ?? 0) >= 0 ? 'text-profit' : 'text-loss')}>{pct(r.avg_pct, { dp: 2 })}</td>
                  <td className="num px-2 text-right text-muted">{r.hit_pct?.toFixed(0)}% up</td><td className="num px-4 text-right text-muted">t {r.t?.toFixed(1) ?? '—'}</td></tr>))}</tbody></table>
              <p className="px-4 py-2 text-2xs text-muted">Compare the quadrants with each other: when they all land close together, the quadrant tells little about the next weeks.</p>
            </Card>
          </div>
        </div>
      )}
      {d && <p className="mt-3 text-2xs text-faint">{d.note}</p>}
    </div>
  )
}
