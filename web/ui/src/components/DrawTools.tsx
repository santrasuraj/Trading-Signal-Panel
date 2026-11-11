// Chart drawing tools (daily chart): a level (1 click), a trendline or a Fibonacci retracement (2 clicks), saved per
// symbol on this PC (data/drawings.json). A level can become a price alert in one click.

import { useEffect, useRef, useState, type RefObject } from 'react'
import { BellPlus, Minus, PenLine, Spline, Trash2, TrendingUp } from 'lucide-react'
import type { MouseEventParams } from 'lightweight-charts'
import { isFailure } from '@/api/client'
import { useAlertMutations, useDrawings, useSaveDrawings } from '@/api/watch'
import type { PriceChartHandle } from '@/components/charts/PriceChart'
import { useToast } from '@/components/toast'
import { Button, IconButton, Popover } from '@/components/ui'
import { cn } from '@/lib/csv'
import { date, num } from '@/lib/format'
import { newId, timeToISO, type DrawKind, type DrawPt, type UserDrawing } from '@/lib/userDrawings'

const TOOLS: { kind: DrawKind; label: string; icon: typeof Minus; clicks: number }[] = [
  { kind: 'hline', label: 'Level', icon: Minus, clicks: 1 },
  { kind: 'trend', label: 'Trendline', icon: TrendingUp, clicks: 2 },
  { kind: 'fib', label: 'Fibonacci', icon: Spline, clicks: 2 },
]

export function DrawTools({ symbol, chartRef, price, enabled }: { symbol: string; chartRef: RefObject<PriceChartHandle | null>; price: number | null; enabled: boolean }) {
  const q = useDrawings(symbol)
  const save = useSaveDrawings(symbol)
  const alerts = useAlertMutations()
  const toast = useToast()
  const [mode, setMode] = useState<DrawKind | null>(null)
  const [first, setFirst] = useState<DrawPt | null>(null)
  const firstRef = useRef<DrawPt | null>(null)          // the click handler reads this: two quick clicks never race a re-render
  const items = q.data?.drawings ?? []
  const pick = (p: DrawPt | null) => { firstRef.current = p; setFirst(p) }
  const put = (next: UserDrawing[]) => save.mutate(next, { onError: (e) => toast({ tone: 'bad', title: 'Drawing not saved', detail: isFailure(e) ? e.message : undefined }) })

  useEffect(() => { setMode(null); pick(null) }, [symbol])
  useEffect(() => {
    if (!mode || !enabled) return
    const chart = chartRef.current?.chart()
    const series = chartRef.current?.series()
    if (!chart || !series) return
    const onClick = (p: MouseEventParams) => {
      const t = timeToISO(p.time)
      const v = p.point ? series.coordinateToPrice(p.point.y) : null
      if (!t || v == null || !(v > 0)) return
      const pt = { t, v: Math.round(v * 100) / 100 }
      if (mode === 'hline') {
        put([...items, { id: newId(), kind: 'hline', price: pt.v }])
        setMode(null)
      } else if (!firstRef.current) {
        pick(pt)
      } else {
        put([...items, { id: newId(), kind: mode, a: firstRef.current, b: pt }])
        setMode(null)
        pick(null)
      }
    }
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') { setMode(null); pick(null) } }
    chart.subscribeClick(onClick)
    window.addEventListener('keydown', onKey)
    return () => { chart.unsubscribeClick(onClick); window.removeEventListener('keydown', onKey) }
  }, [mode, items, enabled, chartRef]) // eslint-disable-line react-hooks/exhaustive-deps

  const alertOn = (lvl: number) => {
    const kind = price != null && price > lvl ? 'below' : 'above'
    alerts.create.mutate({ symbol, kind, value: lvl, note: 'chart level' }, {
      onSuccess: () => toast({ tone: 'good', title: `Alert set: ${symbol} ${kind === 'below' ? 'at or below' : 'at or above'} ${num(lvl, 2)}` }),
      onError: (e) => toast({ tone: 'bad', title: 'Alert not saved', detail: isFailure(e) ? e.message : undefined }),
    })
  }
  const hint = mode && (mode === 'hline' ? 'Click the chart at the level' : first ? 'Click the second point' : 'Click the first point')

  return (
    <>
      <Popover align="right" width={300} trigger={({ toggle, open }) => (
        <Button icon={<PenLine className="h-3.5 w-3.5" />} onClick={toggle} aria-expanded={open} disabled={!enabled}
          title={enabled ? 'Draw levels, trendlines and Fibonacci retracements' : 'Drawing works on the 1D / 1W chart'} className={cn('max-sm:px-2.5', mode && 'border-accent text-accent')}>
          <span className="max-sm:hidden">Draw</span>{items.length ? ` · ${items.length}` : ''}
        </Button>
      )}>
        {(close) => (
          <div className="space-y-2 p-2.5">
            <div className="flex gap-1.5">{TOOLS.map((t) => (
              <Button key={t.kind} size="sm" variant={mode === t.kind ? 'primary' : 'secondary'} icon={<t.icon className="h-3.5 w-3.5" />}
                onClick={() => { setMode(t.kind); pick(null); close() }}>{t.label}</Button>
            ))}</div>
            {items.length === 0 ? <p className="text-xs text-muted">No drawings on {symbol} yet. Pick a tool, then click the chart.</p> : (
              <ul className="max-h-60 space-y-0.5 overflow-auto">{items.map((d) => (
                <li key={d.id} className="flex items-center gap-1.5 rounded px-1 py-0.5 text-xs hover:bg-raised">
                  <span className="min-w-0 flex-1 truncate">
                    {d.kind === 'hline' ? <>Level <span className="num">{num(d.price, 2)}</span></>
                      : <>{d.kind === 'trend' ? 'Trendline' : 'Fibonacci'} <span className="text-muted">{date(d.a?.t, { year: false })} <span className="num">{num(d.a?.v, 2)}</span> → {date(d.b?.t, { year: false })} <span className="num">{num(d.b?.v, 2)}</span></span></>}
                  </span>
                  {d.kind === 'hline' && d.price != null && <IconButton label="Alert at this level" onClick={() => alertOn(d.price!)}><BellPlus className="h-3.5 w-3.5" /></IconButton>}
                  <IconButton label="Delete drawing" onClick={() => put(items.filter((x) => x.id !== d.id))}><Trash2 className="h-3.5 w-3.5" /></IconButton>
                </li>
              ))}</ul>
            )}
            {items.length > 1 && <Button size="sm" variant="ghost" onClick={() => put([])}>Clear all</Button>}
          </div>
        )}
      </Popover>
      {hint && <span className="rounded-md bg-accent/10 px-2 py-1 text-2xs font-medium text-accent">{hint} · Esc to cancel</span>}
    </>
  )
}
