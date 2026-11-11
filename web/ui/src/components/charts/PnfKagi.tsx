// Point & Figure (X / O columns) and Kagi (a line that turns on reversals, thick above the last shoulder, thin below the
// last waist) as SVG charts: both leave time out, so they get their own simple view (lib/chartTypes.ts).

import { useMemo, useState } from 'react'
import { useWidth } from '@/lib/useWidth'
import { kagi, pnf, volumeByPrice, type Ohlcv } from '@/lib/chartTypes'
import { Card } from '@/components/ui'
import { num } from '@/lib/format'
import { cn } from '@/lib/csv'

const AXIS = 64

export function PnfChart({ bars, boxPct, height }: { bars: Ohlcv; boxPct: number; height: number }) {
  const [ref, w] = useWidth<HTMLDivElement>()
  const { cols, boxPrice } = useMemo(() => pnf(bars, boxPct, 3), [bars, boxPct])
  const [hover, setHover] = useState<number | null>(null)
  const show = cols.slice(-Math.max(10, Math.floor(((w || 800) - AXIS) / 12)))
  if (!show.length) return <div ref={ref} className="p-4 text-xs text-muted">Not enough movement for a {boxPct}% box.</div>
  const lo = Math.min(...show.map((c) => Math.min(c.from, c.to))), hi = Math.max(...show.map((c) => Math.max(c.from, c.to)))
  const rows = hi - lo + 1
  const cell = Math.max(6, Math.min(16, Math.floor((height - 20) / rows), Math.floor(((w || 800) - AXIS) / show.length)))
  const H = rows * cell + 20
  const y = (i: number) => (hi - i) * cell + 10
  const every = Math.max(1, Math.ceil(rows / 14))
  return (
    <div ref={ref} className="relative w-full overflow-x-auto">
      <svg width={Math.max(w, show.length * cell + AXIS)} height={H} role="img" aria-label="Point and figure chart" onMouseLeave={() => setHover(null)}>
        {Array.from({ length: rows }, (_, k) => lo + k).filter((i) => (i - lo) % every === 0).map((i) => (
          <g key={i}><line x1={0} x2={show.length * cell} y1={y(i)} y2={y(i)} stroke="rgb(var(--line))" strokeWidth={0.5} />
            <text x={show.length * cell + 4} y={y(i) + 3} className="fill-[rgb(var(--muted))] text-[10px]">{num(boxPrice(i), 2)}</text></g>))}
        {show.map((c, x) => {
          const a = Math.min(c.from, c.to), z = Math.max(c.from, c.to)
          return (
            <g key={x} onMouseEnter={() => setHover(x)}>
              <rect x={x * cell} y={y(z) - cell / 2} width={cell} height={(z - a + 1) * cell} fill="transparent" />
              {Array.from({ length: z - a + 1 }, (_, k) => a + k).map((i) => (
                <text key={i} x={x * cell + cell / 2} y={y(i) + cell * 0.35} textAnchor="middle" fontSize={cell * 0.9}
                  className={c.up ? 'fill-[rgb(var(--profit))]' : 'fill-[rgb(var(--loss))]'}>{c.up ? '×' : '○'}</text>))}
            </g>)
        })}
      </svg>
      {hover != null && show[hover] && (
        <div className="pointer-events-none absolute left-2 top-2 rounded border border-line bg-panel px-2 py-1 text-2xs shadow">
          {show[hover].up ? 'Rising (X)' : 'Falling (O)'} column · {num(boxPrice(Math.min(show[hover].from, show[hover].to)), 2)} – {num(boxPrice(Math.max(show[hover].from, show[hover].to)), 2)} · {show[hover].start} → {show[hover].end}
        </div>)}
    </div>
  )
}

export function KagiChart({ bars, revPct, height }: { bars: Ohlcv; revPct: number; height: number }) {
  const [ref, w] = useWidth<HTMLDivElement>()
  const segs = useMemo(() => kagi(bars, revPct), [bars, revPct])
  const show = segs.slice(-Math.max(10, Math.floor(((w || 800) - AXIS) / 10)))
  if (!show.length) return <div ref={ref} className="p-4 text-xs text-muted">No {revPct}% reversal in this range.</div>
  const vals = show.flatMap((s) => [s.from, s.to])
  const lo = Math.min(...vals), hi = Math.max(...vals)
  const step = Math.max(6, Math.min(24, Math.floor(((w || 800) - AXIS) / show.length)))
  const Y = (v: number) => 10 + ((hi - v) / (hi - lo || 1)) * (height - 20)
  const ticks = Array.from({ length: 6 }, (_, i) => lo + ((hi - lo) * i) / 5)
  return (
    <div ref={ref} className="w-full overflow-x-auto">
      <svg width={Math.max(w, show.length * step + AXIS)} height={height} role="img" aria-label="Kagi chart">
        {ticks.map((t) => <g key={t}><line x1={0} x2={show.length * step} y1={Y(t)} y2={Y(t)} stroke="rgb(var(--line))" strokeWidth={0.5} /><text x={show.length * step + 4} y={Y(t) + 3} className="fill-[rgb(var(--muted))] text-[10px]">{num(t, 2)}</text></g>)}
        {show.map((s, i) => (
          <g key={i}>
            <line x1={i * step} x2={i * step} y1={Y(s.from)} y2={Y(s.to)} strokeWidth={s.thick ? 3 : 1.2} stroke={s.thick ? 'rgb(var(--profit))' : 'rgb(var(--loss))'}><title>{`${s.start} → ${s.end}: ${num(s.from, 2)} → ${num(s.to, 2)}`}</title></line>
            {i + 1 < show.length && <line x1={i * step} x2={(i + 1) * step} y1={Y(s.to)} y2={Y(s.to)} strokeWidth={s.thick ? 3 : 1.2} stroke={s.thick ? 'rgb(var(--profit))' : 'rgb(var(--loss))'} />}
          </g>))}
      </svg>
    </div>
  )
}

export function VolumeByPriceCard({ bars, last }: { bars: Ohlcv; last: number | null }) {
  const r = useMemo(() => volumeByPrice(bars, 30), [bars])
  if (!r.profile.length) return null
  const max = Math.max(...r.profile.map((p) => p.vol))
  const rows = [...r.profile].sort((a, b) => b.price - a.price)
  return (
    <Card title="Volume by price" subtitle={`Over the bars shown · most traded ${num(r.poc, 2)} · 70% of volume ${num(r.va?.[0], 2)}–${num(r.va?.[1], 2)}`}>
      <div className="space-y-px">{rows.map((p) => {
        const inVa = r.va && p.price >= r.va[0] && p.price <= r.va[1]
        const here = last != null && Math.abs(p.price - last) <= (rows[0].price - rows[rows.length - 1].price) / rows.length / 2
        return (
          <div key={p.price} className="flex items-center gap-1.5 text-[10px]">
            <span className={cn('num w-14 text-right', p.price === r.poc ? 'font-bold text-fg' : inVa ? 'text-muted' : 'text-faint', here && 'text-accent')}>{num(p.price, 2)}</span>
            <div className="h-2 flex-1"><div className={cn('h-full', p.price === r.poc ? 'bg-warn' : inVa ? 'bg-accent/60' : 'bg-accent/25')} style={{ width: `${(p.vol / max) * 100}%` }} /></div>
          </div>)
      })}</div>
      <p className="mt-2 text-2xs text-faint">Each day's volume spread over its high-low range (daily bars have no tick detail). Heavily traded levels often act as support or resistance; not a tested edge here.</p>
    </Card>
  )
}
