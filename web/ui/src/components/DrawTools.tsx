// Chart drawing tools (daily chart): a level, a text note or an anchored VWAP (1 click); a trendline, a Fibonacci
// retracement or a zone (2 clicks), saved per symbol on this PC (data/drawings.json). A level or a trendline can become
// an alert in one click (a trendline alert follows the line as it rises or falls).

import { useEffect, useRef, useState, type RefObject } from 'react'
import { Anchor, ArrowDown, ArrowUp, BellPlus, GitFork, Minus, MoveUpRight, PenLine, RectangleHorizontal, Ruler, Rows3, Spline, Trash2, TrendingUp, Type } from 'lucide-react'
import type { MouseEventParams } from 'lightweight-charts'
import { isFailure } from '@/api/client'
import { useAlertMutations, useDrawings, useSaveDrawings } from '@/api/watch'
import type { PriceChartHandle } from '@/components/charts/PriceChart'
import { useToast } from '@/components/toast'
import { Button, IconButton, Popover } from '@/components/ui'
import { cn } from '@/lib/csv'
import { date, num, todayIST } from '@/lib/format'
import { lineLevel, newId, timeToISO, type DrawKind, type DrawPt, type UserDrawing } from '@/lib/userDrawings'

const TOOLS: { kind: DrawKind; label: string; icon: typeof Minus; clicks: number }[] = [
  { kind: 'hline', label: 'Level', icon: Minus, clicks: 1 },
  { kind: 'trend', label: 'Trendline', icon: TrendingUp, clicks: 2 },
  { kind: 'fib', label: 'Fibonacci', icon: Spline, clicks: 2 },
  { kind: 'rect', label: 'Zone', icon: RectangleHorizontal, clicks: 2 },
  { kind: 'text', label: 'Text', icon: Type, clicks: 1 },
  { kind: 'avwap', label: 'Anchored VWAP', icon: Anchor, clicks: 1 },
  { kind: 'ray', label: 'Ray', icon: MoveUpRight, clicks: 2 },
  { kind: 'channel', label: 'Channel', icon: Rows3, clicks: 3 },
  { kind: 'pitchfork', label: 'Pitchfork', icon: GitFork, clicks: 3 },
  { kind: 'measure', label: 'Measure', icon: Ruler, clicks: 2 },
]
const ARROWS: { note: 'up' | 'down'; label: string; icon: typeof Minus }[] = [{ note: 'up', label: 'Arrow up', icon: ArrowUp }, { note: 'down', label: 'Arrow down', icon: ArrowDown }]
const NAME: Record<DrawKind, string> = { hline: 'Level', trend: 'Trendline', fib: 'Fibonacci', rect: 'Zone', text: 'Note', avwap: 'Anchored VWAP', ray: 'Ray', channel: 'Channel', pitchfork: 'Pitchfork', measure: 'Measure', arrow: 'Arrow' }
const CLICKS = (k: DrawKind) => TOOLS.find((t) => t.kind === k)?.clicks ?? 1

export function DrawTools({ symbol, chartRef, price, enabled }: { symbol: string; chartRef: RefObject<PriceChartHandle | null>; price: number | null; enabled: boolean }) {
  const q = useDrawings(symbol)
  const save = useSaveDrawings(symbol)
  const alerts = useAlertMutations()
  const toast = useToast()
  const [mode, setMode] = useState<DrawKind | null>(null)
  const [first, setFirst] = useState<DrawPt[]>([])
  const firstRef = useRef<DrawPt[]>([])                // the click handler reads this: quick clicks never race a re-render
  const [arrow, setArrow] = useState<'up' | 'down'>('up')
  const items = q.data?.drawings ?? []
  const pick = (p: DrawPt[]) => { firstRef.current = p; setFirst(p) }
  const put = (next: UserDrawing[]) => save.mutate(next, { onError: (e) => toast({ tone: 'bad', title: 'Drawing not saved', detail: isFailure(e) ? e.message : undefined }) })

  useEffect(() => { setMode(null); pick([]) }, [symbol])
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
      } else if (mode === 'text') {
        const text = window.prompt('Note on the chart (up to 60 characters)')?.trim().slice(0, 60)
        if (text) put([...items, { id: newId(), kind: 'text', a: pt, note: text }])
        setMode(null)
      } else if (mode === 'avwap') {
        put([...items, { id: newId(), kind: 'avwap', a: pt }])
        setMode(null)
      } else if (mode === 'arrow') {
        put([...items, { id: newId(), kind: 'arrow', a: pt, note: arrow }])
        setMode(null)
      } else if (firstRef.current.length + 1 < CLICKS(mode)) {
        pick([...firstRef.current, pt])
      } else {
        const [a, b] = [...firstRef.current, pt]
        const c = CLICKS(mode) === 3 ? pt : undefined
        put([...items, { id: newId(), kind: mode, a, b: CLICKS(mode) === 3 ? firstRef.current[1] : b, ...(c ? { c } : {}) }])
        setMode(null)
        pick([])
      }
    }
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') { setMode(null); pick([]) } }
    chart.subscribeClick(onClick)
    window.addEventListener('keydown', onKey)
    return () => { chart.unsubscribeClick(onClick); window.removeEventListener('keydown', onKey) }
  }, [mode, items, enabled, chartRef, arrow]) // eslint-disable-line react-hooks/exhaustive-deps

  const alertOn = (lvl: number) => {
    const kind = price != null && price > lvl ? 'below' : 'above'
    alerts.create.mutate({ symbol, kind, value: lvl, note: 'chart level' }, {
      onSuccess: () => toast({ tone: 'good', title: `Alert set: ${symbol} ${kind === 'below' ? 'at or below' : 'at or above'} ${num(lvl, 2)}` }),
      onError: (e) => toast({ tone: 'bad', title: 'Alert not saved', detail: isFailure(e) ? e.message : undefined }),
    })
  }
  const lineAlert = (d: UserDrawing) => {
    if (!d.a || !d.b) return
    const lvl = lineLevel(d.a, d.b, todayIST())
    const kind = price != null && price > lvl ? 'line_below' : 'line_above'
    alerts.create.mutate({ symbol, kind, a: d.a, b: d.b, note: 'chart trendline' }, {
      onSuccess: () => toast({ tone: 'good', title: `Alert set: ${symbol} ${kind === 'line_below' ? 'below' : 'above'} the trendline (today ${num(lvl, 2)})` }),
      onError: (e) => toast({ tone: 'bad', title: 'Alert not saved', detail: isFailure(e) ? e.message : undefined }),
    })
  }
  const one = mode === 'hline' || mode === 'text' || mode === 'avwap' || mode === 'arrow'
  const third = mode === 'channel' ? 'Click a point the parallel line passes through' : 'Click the second swing'
  const hint = mode && (one ? (mode === 'avwap' ? 'Click the bar to anchor the VWAP' : mode === 'text' ? 'Click where the note goes' : mode === 'arrow' ? 'Click where the arrow goes' : 'Click the chart at the level')
    : first.length === 2 ? third : first.length === 1 ? (mode === 'pitchfork' ? 'Click the first swing' : 'Click the second point') : mode === 'pitchfork' ? 'Click the pivot' : 'Click the first point')

  return (
    <>
      <Popover align="right" width={300} trigger={({ toggle, open }) => (
        <Button icon={<PenLine className="h-3.5 w-3.5" />} onClick={toggle} aria-expanded={open} disabled={!enabled}
          title={enabled ? 'Draw levels, trendlines, Fibonacci, zones, notes and anchored VWAPs' : 'Drawing works on the 1D / 1W chart'} className={cn('max-sm:px-2.5', mode && 'border-accent text-accent')}>
          <span className="max-sm:hidden">Draw</span>{items.length ? ` · ${items.length}` : ''}
        </Button>
      )}>
        {(close) => (
          <div className="space-y-2 p-2.5">
            <div className="flex flex-wrap gap-1.5">{TOOLS.map((t) => (
              <Button key={t.kind} size="sm" variant={mode === t.kind ? 'primary' : 'secondary'} icon={<t.icon className="h-3.5 w-3.5" />}
                onClick={() => { setMode(t.kind); pick([]); close() }}>{t.label}</Button>
            ))}
            {ARROWS.map((t) => (
              <Button key={t.note} size="sm" variant={mode === 'arrow' && arrow === t.note ? 'primary' : 'secondary'} icon={<t.icon className="h-3.5 w-3.5" />}
                onClick={() => { setArrow(t.note); setMode('arrow'); pick([]); close() }}>{t.label}</Button>
            ))}</div>
            {items.length === 0 ? <p className="text-xs text-muted">No drawings on {symbol} yet. Pick a tool, then click the chart.</p> : (
              <ul className="max-h-60 space-y-0.5 overflow-auto">{items.map((d) => (
                <li key={d.id} className="flex items-center gap-1.5 rounded px-1 py-0.5 text-xs hover:bg-raised">
                  <span className="min-w-0 flex-1 truncate">
                    {d.kind === 'hline' ? <>Level <span className="num">{num(d.price, 2)}</span></>
                      : d.kind === 'text' ? <>Note <span className="text-muted">"{d.note}" · {date(d.a?.t, { year: false })}</span></>
                      : d.kind === 'avwap' ? <>Anchored VWAP <span className="text-muted">from {date(d.a?.t, { year: false })}</span></>
                      : d.kind === 'arrow' ? <>Arrow {d.note === 'up' ? '▲' : '▼'} <span className="text-muted">{date(d.a?.t, { year: false })}</span></>
                      : <>{NAME[d.kind]} <span className="text-muted">{date(d.a?.t, { year: false })} <span className="num">{num(d.a?.v, 2)}</span> → {date(d.b?.t, { year: false })} <span className="num">{num(d.b?.v, 2)}</span></span></>}
                  </span>
                  {d.kind === 'hline' && d.price != null && <IconButton label="Alert at this level" onClick={() => alertOn(d.price!)}><BellPlus className="h-3.5 w-3.5" /></IconButton>}
                  {d.kind === 'trend' && <IconButton label="Alert when the price crosses this trendline" onClick={() => lineAlert(d)}><BellPlus className="h-3.5 w-3.5" /></IconButton>}
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
