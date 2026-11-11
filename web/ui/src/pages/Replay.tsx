// Replay `/replay`: practise on real past sessions one bar at a time (no hindsight, real charges), and your practice
// record. Intraday (5m / 15m) replays one past session of the ~150 most liquid F&O stocks after two sessions of
// context; Daily replays the next 60 sessions from any date since 2018. Blind mode hides the stock and the date until
// the end. Fills follow lib/replay.ts; a finished session with trades is saved, its P&L recomputed by the server.

import { useEffect, useRef, useState } from 'react'
import { ChevronRight, EyeOff, Flag, Pause, Play, Shuffle } from 'lucide-react'
import {
  randomPick, useReplayBars, useReplayHistory, useReplayInfo, useSaveReplay, type ReplayData, type ReplayStats, type ReplayTf,
} from '@/api/replay'
import { isFailure } from '@/api/client'
import { ReplayChart } from '@/components/charts/ReplayChart'
import { KpiStrip, KpiTile, PageHeader } from '@/components/domain'
import { EmptyState, ErrorState, Skeleton } from '@/components/feedback'
import { Money, Pct } from '@/components/num'
import { Button, Card, KV, Kbd, Segmented } from '@/components/ui'
import { cn } from '@/lib/csv'
import { date, num, price } from '@/lib/format'
import { checkLevels, enter, exit, finish, openPnl, setLevels, start, step, summarize, type Side } from '@/lib/replay'
import { typingTarget } from '@/lib/useMedia'

type Params = { symbol: string; tf: ReplayTf; date: string; blind: boolean }
const TF_ITEMS: { id: ReplayTf; label: string }[] = [{ id: '5m', label: '5 min' }, { id: '15m', label: '15 min' }, { id: '1d', label: 'Daily' }]
const SPEEDS = [{ id: '1', label: '1×' }, { id: '2', label: '2×' }, { id: '5', label: '5×' }, { id: '10', label: '10×' }] as const
type Speed = (typeof SPEEDS)[number]['id']
const tick = (x: number) => Math.round(x / 0.05) * 0.05
const pad2 = (n: number) => String(n).padStart(2, '0')
const barTime = (t: number, intraday: boolean) => {
  const d = new Date(t * 1000).toISOString().slice(0, 10)
  return intraday ? `${date(d)} ${pad2(Math.floor((t % 86400) / 3600))}:${pad2(Math.floor((t % 3600) / 60))}` : date(d)
}

function useDebounced<T>(v: T, ms: number): T {
  const [x, setX] = useState(v)
  useEffect(() => { const id = setTimeout(() => setX(v), ms); return () => clearTimeout(id) }, [v, ms])
  return x
}

function Setup({ onStart, busy }: { onStart: (p: Params) => void; busy: boolean }) {
  const [tf, setTf] = useState<ReplayTf>('5m')
  const [sym, setSym] = useState('RELIANCE')
  const [day, setDay] = useState('')
  const [blindErr, setBlindErr] = useState<string | null>(null)
  const [rolling, setRolling] = useState(false)
  const s = useDebounced(sym.trim().toUpperCase(), 400)
  const info = useReplayInfo(s || undefined)
  const intraday = tf !== '1d'
  const sessions = info.data?.symbol === s ? [...(info.data.sessions ?? [])].reverse() : []
  const inIntraday = !!info.data?.intraday_symbols.includes(s)
  useEffect(() => {
    if (intraday) setDay(sessions[0] ?? '')
    else if (info.data?.daily_last && !day.match(/^\d{4}-\d{2}-\d{2}$/)) setDay(info.data.daily_first && info.data.daily_first > '2024-11-01' ? info.data.daily_first : '2024-11-01')
  }, [s, tf, info.data]) // eslint-disable-line react-hooks/exhaustive-deps
  const canStart = !!s && !!day && (intraday ? inIntraday && sessions.includes(day) : true)
  const random = async () => {
    setRolling(true); setBlindErr(null)
    try { onStart({ ...(await randomPick(tf)), blind: true }) } catch (e) { setBlindErr(isFailure(e) ? e.message : 'Could not pick a session.') } finally { setRolling(false) }
  }
  return (
    <Card title="Pick a session" subtitle="A stock and a past day, or a random one with the name and date hidden until the end (memory can't help).">
      <div className="flex flex-wrap items-end gap-3">
        <Segmented<ReplayTf> ariaLabel="Bar size" value={tf} onChange={setTf} items={TF_ITEMS} />
        <label className="text-2xs text-muted">Stock
          <input aria-label="Stock" list="replay-symbols" value={sym} onChange={(e) => setSym(e.target.value)} className="input mt-0.5 block h-8 w-36 px-2 uppercase" />
          <datalist id="replay-symbols">{(info.data?.intraday_symbols ?? []).map((x) => <option key={x} value={x} />)}</datalist>
        </label>
        <label className="text-2xs text-muted">{intraday ? 'Session' : 'Start date'}
          {intraday ? (
            <select aria-label="Session" value={day} onChange={(e) => setDay(e.target.value)} disabled={!sessions.length} className="input mt-0.5 block h-8 w-40 px-2">
              {sessions.map((x) => <option key={x} value={x}>{date(x)}</option>)}
            </select>
          ) : (
            <input aria-label="Start date" type="date" value={day} min={info.data?.daily_first} max={info.data?.daily_last} onChange={(e) => setDay(e.target.value)} className="input mt-0.5 block h-8 w-40 px-2" />
          )}
        </label>
        <Button variant="primary" icon={<Play className="h-3.5 w-3.5" />} disabled={!canStart} loading={busy} onClick={() => onStart({ symbol: s, tf, date: day, blind: false })}>Start</Button>
        <Button icon={<Shuffle className="h-3.5 w-3.5" />} loading={rolling} onClick={random}>Random, blind</Button>
      </div>
      {intraday && s && info.data?.symbol === s && !inIntraday && (
        <p className="mt-2 text-xs text-warn">No 5-minute history for {s}: intraday replay covers the {info.data.intraday_symbols.length} most liquid F&O stocks. Daily works for any stock.</p>
      )}
      {blindErr && <p className="mt-2 text-xs text-loss">{blindErr}</p>}
    </Card>
  )
}

function Session({ d, blind, onAgain }: { d: ReplayData; blind: boolean; onAgain: () => void }) {
  const intraday = d.tf !== '1d'
  const b = d.bars
  const last = b.t.length - 1
  const c = d.costs
  const [sim, setSim] = useState(() => start(d.start))
  const [playing, setPlaying] = useState(false)
  const [speed, setSpeed] = useState<Speed>('2')
  const [done, setDone] = useState(false)
  const [qty, setQty] = useState(d.qty)
  const [stopPct, setStopPct] = useState(intraday ? '1' : '7')
  const [targetPct, setTargetPct] = useState(intraday ? '2' : '15')
  const [err, setErr] = useState<string | null>(null)
  const save = useSaveReplay()
  const saved = useRef(false)
  const hide = blind && !done
  const px = b.c[sim.i]

  const levels = (side: Side, at: number) => {
    const sp = Number(stopPct), tp = Number(targetPct)
    const k = side === 'LONG' ? 1 : -1
    return {
      stop: sp > 0 ? Number(tick(at * (1 - (k * sp) / 100)).toFixed(2)) : null,
      target: tp > 0 ? Number(tick(at * (1 + (k * tp) / 100)).toFixed(2)) : null,
    }
  }

  const doStep = () => setSim((s) => step(s, b, c, d.square_off))
  const end = () => { setPlaying(false); setSim((s) => finish(s, b, c, intraday)); setDone(true) }
  const open = (side: Side) => {
    setErr(null)
    if (side === 'SHORT' && !intraday) { setErr("Delivery shares can't be sold short in India: daily replays are long only."); return }
    setSim((s) => {
      if (s.pos?.side === side) return s
      if (s.pos) return exit(s, b, 'manual', c)                 // the other button closes the open position
      const lv = levels(side, b.c[s.i])
      return enter(s, b, side, qty, lv.stop, lv.target, c)
    })
  }
  const breakeven = () => setSim((s) => (s.pos && checkLevels(s.pos.side, b.c[s.i], s.pos.entry, s.pos.target) == null ? setLevels(s, s.pos.entry, s.pos.target) : s))

  useEffect(() => {
    if (!playing || done) return
    const id = setInterval(doStep, 1000 / Number(speed))
    return () => clearInterval(id)
  }, [playing, speed, done]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (!done && sim.i >= last) end() }, [sim.i]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!done || saved.current || !sim.trades.length) return
    saved.current = true
    save.mutate({
      symbol: d.symbol, tf: d.tf, date: d.date, blind, last_i: sim.i,
      trades: sim.trades.map((t) => ({ side: t.side, qty: t.qty, entry_i: t.entry_i, exit_i: t.exit_i, entry: t.entry, exit: t.exit, stop: t.stop, target: t.target, reason: t.reason })),
    })
  }, [done, sim]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (typingTarget(e) || e.ctrlKey || e.metaKey || e.altKey || done) return
      if (e.key === ' ') { e.preventDefault(); setPlaying((p) => !p) }
      else if (e.key === 'ArrowRight') { e.preventDefault(); setPlaying(false); doStep() }
      else if (e.key === 'b') open('LONG')
      else if (e.key === 's') open('SHORT')
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })

  const sum = summarize(sim.trades)
  const pos = sim.pos
  const opl = openPnl(sim, b, c)
  const n = last - d.start + 1
  const k = sim.i - d.start + 1
  const bh = (b.c[sim.i] / b.c[d.start] - 1) * 100
  const buyLabel = pos?.side === 'SHORT' ? 'Buy to cover' : 'Buy'
  const sellLabel = pos?.side === 'LONG' ? 'Sell to close' : intraday ? 'Sell short' : 'Sell'
  const lvPreview = levels(pos?.side ?? 'LONG', px)
  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_300px]">
      <Card
        title={hide ? <span className="flex items-center gap-1.5"><EyeOff className="h-4 w-4 text-muted" />Mystery stock</span> : <span>{d.symbol} <span className="font-normal text-muted">· {TF_ITEMS.find((x) => x.id === d.tf)?.label} · {date(d.date)}</span></span>}
        subtitle={hide ? `Bar ${k} of ${n}${intraday ? ` · ${barTime(b.t[sim.i], true).slice(-5)}` : ''}` : `${barTime(b.t[sim.i], intraday)} · bar ${k} of ${n}${intraday ? ` after ${d.context.length} sessions of context` : ' after a year of context'}`}
        right={
          <div className="flex items-center gap-2">
            <Button size="sm" variant={playing ? 'secondary' : 'primary'} icon={playing ? <Pause className="h-3.5 w-3.5" /> : <Play className="h-3.5 w-3.5" />} disabled={done} onClick={() => setPlaying((p) => !p)}>{playing ? 'Pause' : 'Play'}</Button>
            <Button size="sm" icon={<ChevronRight className="h-3.5 w-3.5" />} disabled={done} onClick={() => { setPlaying(false); doStep() }}>Next bar</Button>
            <Segmented<Speed> size="xs" ariaLabel="Speed (bars a second)" value={speed} onChange={setSpeed} items={SPEEDS.map((x) => ({ ...x }))} />
            <Button size="sm" variant="ghost" icon={<Flag className="h-3.5 w-3.5" />} disabled={done} onClick={end}>Finish</Button>
          </div>
        }
        bodyClass="p-0"
      >
        <ReplayChart data={d} upto={done ? last : sim.i} blind={hide} trades={sim.trades} pos={pos} height={460} />
        <p className="border-t border-line px-4 py-2 text-2xs text-faint">
          <Kbd>Space</Kbd> play / pause · <Kbd>→</Kbd> next bar · <Kbd>b</Kbd> buy · <Kbd>s</Kbd> sell. {d.note}
        </p>
      </Card>

      <div className="space-y-4">
        <Card title={done ? 'Result' : 'Trade'} subtitle={done ? undefined : `Last price ₹${price(px)}`}>
          {!done ? (
            <div className="space-y-3 text-[13px]">
              {pos ? (
                <div className={cn('rounded-md border p-2.5', pos.side === 'LONG' ? 'border-profit/40' : 'border-loss/40')}>
                  <div className="flex items-baseline justify-between"><span className="font-semibold">{pos.side === 'LONG' ? 'Long' : 'Short'} {pos.qty}</span><span>at ₹{price(pos.entry)}</span></div>
                  <div className="mt-1 flex justify-between text-xs text-muted"><span>Stop {pos.stop != null ? `₹${price(pos.stop)}` : 'none'}</span><span>Target {pos.target != null ? `₹${price(pos.target)}` : 'none'}</span></div>
                  <div className="mt-1.5 flex items-center justify-between"><span className="text-xs text-muted">Open P&L after charges</span><Money v={opl} signed color dp={0} /></div>
                  {opl != null && opl > 0 && pos.stop !== pos.entry && <Button size="xs" variant="subtle" className="mt-2" onClick={breakeven}>Move stop to entry</Button>}
                </div>
              ) : <p className="text-xs text-muted">No position. {intraday ? 'Long or short; squared off at the session close.' : 'Long only (delivery).'}</p>}
              {!pos && (
                <div className="grid grid-cols-3 gap-2">
                  <label className="text-2xs text-muted">Qty<input aria-label="Quantity" inputMode="numeric" value={qty} onChange={(e) => setQty(Math.max(1, Math.floor(Number(e.target.value) || 1)))} className="input num mt-0.5 block h-8 w-full px-2 text-right" /></label>
                  <label className="text-2xs text-muted">Stop %<input aria-label="Stop %" inputMode="decimal" value={stopPct} onChange={(e) => setStopPct(e.target.value)} className="input num mt-0.5 block h-8 w-full px-2 text-right" /></label>
                  <label className="text-2xs text-muted">Target %<input aria-label="Target %" inputMode="decimal" value={targetPct} onChange={(e) => setTargetPct(e.target.value)} className="input num mt-0.5 block h-8 w-full px-2 text-right" /></label>
                </div>
              )}
              {!pos && <p className="text-2xs text-faint">≈ ₹{num(qty * px, 0)} · long: stop ₹{price(lvPreview.stop)}, target ₹{price(lvPreview.target)} (0 % = none)</p>}
              <div className="grid grid-cols-2 gap-2">
                <Button variant="buy" disabled={pos?.side === 'LONG'} onClick={() => open('LONG')}>{buyLabel}</Button>
                <Button variant="sell" disabled={pos?.side === 'SHORT' || (!pos && !intraday)} onClick={() => open('SHORT')}>{sellLabel}</Button>
              </div>
              {err && <p className="text-xs text-loss">{err}</p>}
            </div>
          ) : (
            <div className="space-y-2 text-[13px]">
              {blind && <p className="rounded-md bg-raised px-2.5 py-1.5 text-xs">It was <span className="font-semibold">{d.symbol}</span>, {intraday ? `the session of ${date(d.date)}` : `from ${date(d.date)}`}.</p>}
              <KV k="Net P&L (after charges)" v={<Money v={sum.net} signed color dp={0} />} />
              <KV k="Of your capital" v={<Pct v={(sum.net / d.capital) * 100} dp={2} />} />
              <KV k="Stock over the bars you saw" v={<Pct v={bh} dp={2} />} />
              <KV k="Trades · won" v={`${sum.trades} · ${sum.wins}`} />
              <p className="text-2xs text-faint">{!sim.trades.length ? 'No trades: nothing saved.' : save.isPending ? 'Saving…' : save.isError ? 'Could not save this session.' : save.data ? 'Saved to your practice record (P&L recomputed with exact charges).' : ''}</p>
              <Button variant="primary" className="w-full" onClick={onAgain}>Another random session</Button>
            </div>
          )}
        </Card>
        <Card title="This session">
          <KV k="Net P&L so far" v={<Money v={sum.net + (opl ?? 0)} signed color dp={0} />} />
          <KV k="Charges paid" v={<Money v={sum.charges} dp={0} />} />
          {sim.trades.length > 0 && (
            <ul className="mt-2 space-y-1 text-xs">
              {sim.trades.map((t, i) => (
                <li key={i} className="flex justify-between gap-2">
                  <span>{t.side === 'LONG' ? 'Long' : 'Short'} {t.qty} · {price(t.entry)} → {price(t.exit)} <span className="text-faint">({t.reason.replace('_', ' ')})</span></span>
                  <Money v={t.net} signed color dp={0} />
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </div>
  )
}

function StatsTiles({ s }: { s: ReplayStats }) {
  return (
    <KpiStrip>
      <KpiTile label="Trades" value={s.trades} sub={`${s.wins} won`} />
      <KpiTile label="Win rate" value={s.win_rate == null ? '—' : `${num(s.win_rate, 0)}%`} />
      <KpiTile label="Net after charges" value={<Money v={s.net} signed color dp={0} />} />
      <KpiTile label="Per trade" value={<Money v={s.expectancy} signed color dp={0} />} sub={s.expectancy_r != null ? `${num(s.expectancy_r, 2)} R` : 'set stops to see R'} />
      <KpiTile label="Profit factor" value={s.profit_factor == null ? '—' : num(s.profit_factor, 2)} sub="wins ÷ losses" />
      <KpiTile label="With a stop" value={s.with_stop_pct == null ? '—' : `${num(s.with_stop_pct, 0)}%`} sub={s.avg_bars_held != null ? `${num(s.avg_bars_held, 1)} bars held` : undefined} />
    </KpiStrip>
  )
}

function Record() {
  const q = useReplayHistory()
  if (q.error) return <Card title="Your practice record"><ErrorState error={q.error} compact /></Card>
  const h = q.data
  if (!h) return <Card title="Your practice record"><Skeleton className="h-24 w-full" /></Card>
  if (!h.sessions) return <Card title="Your practice record"><EmptyState compact title="No sessions yet">Finish a replay with at least one trade: it is saved here, and the Coach reads it.</EmptyState></Card>
  return (
    <Card title="Your practice record" subtitle={`${h.sessions} sessions · ${h.note}`}>
      <StatsTiles s={h.overall} />
      <div className="mt-3 overflow-x-auto">
        <table className="w-full text-[13px]">
          <thead className="text-left text-2xs text-muted"><tr><th className="py-1.5">Played</th><th>Stock</th><th>Bars</th><th>Session</th><th className="text-right">Trades</th><th className="text-right">Net</th><th className="text-right">Of capital</th><th className="text-right">Stock moved</th></tr></thead>
          <tbody>
            {h.recent.map((r) => (
              <tr key={r.id} className="border-t border-line">
                <td className="py-1.5 text-muted">{date(r.at.slice(0, 10))}</td>
                <td className="font-medium">{r.symbol}{r.blind && <span className="ml-1 text-2xs text-faint">blind</span>}</td>
                <td>{TF_ITEMS.find((x) => x.id === r.tf)?.label}</td>
                <td className="text-muted">{date(r.date)}</td>
                <td className="num text-right">{r.trades}</td>
                <td className="text-right"><Money v={r.net} signed color dp={0} /></td>
                <td className="text-right"><Pct v={r.ret_pct} dp={2} /></td>
                <td className="text-right"><Pct v={r.buy_hold_pct} dp={2} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  )
}

export default function Replay() {
  const [p, setP] = useState<Params | null>(null)
  const [run, setRun] = useState(0)
  const q = useReplayBars(p)
  const begin = (x: Params) => { setP(x); setRun((n) => n + 1) }
  const again = async () => {
    const tf = p?.tf ?? '5m'
    try { begin({ ...(await randomPick(tf)), blind: true }) } catch { /* the Setup card shows errors on its own button */ }
  }
  return (
    <div className="space-y-4">
      <PageHeader title="Replay" subtitle="Practise on real past sessions one bar at a time: no hindsight, real charges. Your record shows whether your own trading has an edge before real money finds out." />
      <Setup onStart={begin} busy={q.isFetching} />
      {p && q.error && <ErrorState error={q.error} />}
      {p && q.data && <Session key={`${q.data.symbol}:${q.data.tf}:${q.data.date}:${run}`} d={q.data} blind={p.blind} onAgain={again} />}
      <Record />
    </div>
  )
}
