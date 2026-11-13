// Watchlist `/watchlist`: your own lists with live prices and each stock's one tested answer, plus price alerts.
// Watchlist and alert symbols are streamed by the live service from its next start (scanner/watch.py), so alerts
// fire on real-time ticks even with Quant Desk closed.

import { useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { BellRing, Plus, RotateCcw, Trash2, X } from 'lucide-react'
import { isFailure } from '@/api/client'
import { useLiveQuotes, useSymbols } from '@/api/hooks'
import { useSavedScans } from '@/api/scans'
import { useFormulas } from '@/components/FormulaMenu'
import { ALERT_KIND_LABEL, FORM_KINDS, alertValueText, useActions, useAlertMutations, useAlerts, useSaveWatchlists, useWatchlists, type AlertKind, type Watchlist as WL } from '@/api/watch'
import { ActionBadge } from '@/components/ActionCard'
import { PriceStamp } from '@/components/LivePrice'
import { PageHeader } from '@/components/domain'
import { EmptyState, ErrorState, SkeletonRows } from '@/components/feedback'
import { Pct } from '@/components/num'
import { useToast } from '@/components/toast'
import { Button, Card, IconButton, Segmented } from '@/components/ui'
import { cn } from '@/lib/csv'
import { dateTimeIST, num } from '@/lib/format'
import { askPermission, notifyState } from '@/lib/notify'

function errText(e: unknown): string {
  return isFailure(e) ? e.message : 'Something went wrong.'
}

function AddSymbol({ onAdd, placeholder = 'Add symbol, e.g. RELIANCE' }: { onAdd: (s: string) => void; placeholder?: string }) {
  const [v, setV] = useState('')
  const syms = useSymbols()
  const known = useMemo(() => new Set(syms.data?.symbols.map((s) => s.symbol) ?? []), [syms.data])
  const s = v.trim().toUpperCase()
  const bad = !!s && known.size > 0 && !known.has(s)
  return (
    <form className="flex items-center gap-2" onSubmit={(e) => { e.preventDefault(); if (s && !bad) { onAdd(s); setV('') } }}>
      <input list="qd-symbols" aria-label="Symbol" value={v} onChange={(e) => setV(e.target.value)} placeholder={placeholder}
        className={cn('input h-8 w-56 px-2 text-[13px] uppercase', bad && 'border-loss/70')} />
      <datalist id="qd-symbols">{syms.data?.symbols.slice(0, 3000).map((x) => <option key={x.symbol} value={x.symbol}>{x.company ?? ''}</option>)}</datalist>
      <Button size="sm" type="submit" icon={<Plus className="h-3.5 w-3.5" />} disabled={!s || bad}>Add</Button>
      {bad && <span className="text-2xs text-loss">Not in the price store</span>}
    </form>
  )
}

function ListTable({ list, onRemove }: { list: WL; onRemove: (s: string) => void }) {
  const lq = useLiveQuotes(list.symbols)
  const acts = useActions(list.symbols)
  const nav = useNavigate()
  const card = useMemo(() => new Map((acts.data?.cards ?? []).map((c) => [c.symbol, c])), [acts.data])
  if (!list.symbols.length) {
    return <EmptyState compact title="This list is empty">Add stocks above. They get live prices here, their tested answer, and the live feed streams them from its next start.</EmptyState>
  }
  return (
    <div className="scroll-x">
      <table className="w-full text-[13px]">
        <thead className="text-2xs uppercase tracking-[0.04em] text-faint">
          <tr className="border-b border-line">
            <th className="px-3 py-2 text-left font-semibold">Symbol</th>
            <th className="px-3 py-2 text-right font-semibold">Price</th>
            <th className="px-3 py-2 text-right font-semibold">Day</th>
            <th className="px-3 py-2 text-left font-semibold">Source</th>
            <th className="px-3 py-2 text-left font-semibold">Answer</th>
            <th className="w-10" />
          </tr>
        </thead>
        <tbody>
          {list.symbols.map((s) => {
            const q = lq.quotes[s]
            const c = card.get(s)
            return (
              <tr key={s} className="cursor-pointer border-b border-line/60 hover:bg-raised" onClick={() => nav(`/chart/${s}`)}>
                <td className="px-3 py-2"><span className="font-semibold">{s}</span>{c?.company && <span className="block max-w-[220px] truncate text-2xs text-muted">{c.company}</span>}</td>
                <td className="num px-3 py-2 text-right">{q ? num(q.price, 2) : '—'}</td>
                <td className="px-3 py-2 text-right">{q ? <Pct v={q.change_pct} dp={2} /> : '—'}</td>
                <td className="px-3 py-2" onClick={(e) => e.stopPropagation()}><PriceStamp q={q} session={lq.data?.session} fallbackDate={c?.as_of.data_date} /></td>
                <td className="px-3 py-2">{c ? <span className="flex items-center gap-2"><ActionBadge state={c.state} small /><span className="hidden max-w-[420px] truncate text-xs text-muted xl:inline" title={c.headline}>{c.headline}</span></span> : <span className="text-faint">…</span>}</td>
                <td className="px-1 py-2" onClick={(e) => e.stopPropagation()}><IconButton label={`Remove ${s}`} onClick={() => onRemove(s)}><X className="h-3.5 w-3.5" /></IconButton></td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

export function AlertForm({ symbol: initial = '', price, onDone }: { symbol?: string; price?: number | null; onDone?: () => void }) {
  const [symbol, setSymbol] = useState(initial)
  const [kind, setKind] = useState<AlertKind>('above')
  const [value, setValue] = useState(price ? String(Math.round(price * 1.02 * 20) / 20) : '')
  const [note, setNote] = useState('')
  const [sma, setSma] = useState('50')
  const [ref, setRef] = useState('')
  const saved = useSavedScans()
  const m = useAlertMutations()
  const toast = useToast()
  const v = Number(value)
  const isScan = kind === 'scan_hit', isPattern = kind === 'pattern', isSma = kind.startsWith('sma'), isRsi = kind.startsWith('rsi'), isFormula = kind.startsWith('formula')
  const formulas = useFormulas()
  const ok = isScan ? !!ref : !!symbol.trim() && (isPattern || isSma || (isFormula ? !!ref && value.trim() !== '' && Number.isFinite(v) : value.trim() !== '' && Number.isFinite(v) && (kind.startsWith('change') || (isRsi ? v > 0 && v < 100 : v > 0))))
  const pick = (k: AlertKind) => { setKind(k); if (k.startsWith('rsi')) setValue(k === 'rsi_above' ? '70' : '30') }
  return (
    <form className="flex flex-wrap items-end gap-2" onSubmit={(e) => {
      e.preventDefault()
      if (!ok) return
      const body = isScan ? { symbol: 'ALL', kind, ref, note: saved.data?.scans.find((x) => x.id === ref)?.name ?? '' }
        : { symbol: symbol.trim().toUpperCase(), kind, value: isPattern ? 0 : isSma ? Number(sma) : v, note, ...(isFormula ? { ref } : {}) }
      m.create.mutate(body, {
        onSuccess: (a) => { toast({ tone: 'good', title: `Alert set${a.symbol !== 'ALL' ? `: ${a.symbol}` : ''}`, detail: `${ALERT_KIND_LABEL[a.kind]} ${alertValueText(a)}` }); setNote(''); onDone?.() },
        onError: (err) => toast({ tone: 'bad', title: 'Alert not saved', detail: errText(err) }),
      })
    }}>
      {!initial && !isScan && <label className="text-2xs text-muted">Symbol<input aria-label="Alert symbol" value={symbol} onChange={(e) => setSymbol(e.target.value)} className="input mt-0.5 block h-8 w-36 px-2 text-[13px] uppercase" /></label>}
      <label className="text-2xs text-muted">When
        <select aria-label="Alert condition" value={kind} onChange={(e) => pick(e.target.value as AlertKind)} className="input mt-0.5 block h-8 px-2 text-[13px]">
          {FORM_KINDS.map((k) => <option key={k} value={k}>{ALERT_KIND_LABEL[k]}</option>)}
        </select>
      </label>
      {isSma ? (
        <label className="text-2xs text-muted">Average<select aria-label="Average period" value={sma} onChange={(e) => setSma(e.target.value)} className="input mt-0.5 block h-8 px-2 text-[13px]">{['10', '20', '50', '100', '200'].map((n) => <option key={n} value={n}>{n}-day</option>)}</select></label>
      ) : isScan ? (
        <label className="text-2xs text-muted">Saved scan<select aria-label="Saved scan" value={ref} onChange={(e) => setRef(e.target.value)} className="input mt-0.5 block h-8 w-48 px-2 text-[13px]">
          <option value="">{saved.data?.scans.length ? 'Pick a scan' : 'No saved scans yet'}</option>
          {(saved.data?.scans ?? []).map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}
        </select></label>
      ) : isFormula ? (
        <>
          <label className="text-2xs text-muted">Formula<select aria-label="Your formula" value={ref} onChange={(e) => setRef(e.target.value)} className="input mt-0.5 block h-8 w-48 px-2 text-[13px]">
            <option value="">{formulas.data?.formulas.length ? 'Pick a formula' : 'Save one on the Chart page first'}</option>
            {(formulas.data?.formulas ?? []).map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}
          </select></label>
          <label className="text-2xs text-muted">Level<input aria-label="Formula level" inputMode="decimal" value={value} onChange={(e) => setValue(e.target.value)} className="input num mt-0.5 block h-8 w-24 px-2 text-right text-[13px]" /></label>
        </>
      ) : !isPattern && (
        <label className="text-2xs text-muted">{kind.startsWith('change') ? 'Change %' : isRsi ? 'RSI' : 'Price ₹'}<input aria-label="Alert level" inputMode="decimal" value={value} onChange={(e) => setValue(e.target.value)} className="input num mt-0.5 block h-8 w-28 px-2 text-right text-[13px]" /></label>
      )}
      <label className="text-2xs text-muted">Note (optional)<input aria-label="Alert note" value={note} maxLength={120} onChange={(e) => setNote(e.target.value)} className="input mt-0.5 block h-8 w-48 px-2 text-[13px]" /></label>
      <Button type="submit" size="sm" variant="primary" icon={<BellRing className="h-3.5 w-3.5" />} disabled={!ok} loading={m.create.isPending}>Set alert</Button>
    </form>
  )
}

/** Desktop notifications for fired alerts and order updates (lib/notify.ts): the browser asks once. */
function NotifyButton() {
  const [st, setSt] = useState(notifyState())
  if (st === 'granted' || st === 'unsupported') return st === 'granted' ? <span className="text-2xs text-muted">Desktop notifications on</span> : null
  return <Button size="xs" variant="subtle" icon={<BellRing className="h-3.5 w-3.5" />} disabled={st === 'denied'}
    title={st === 'denied' ? 'Blocked in the browser: allow notifications for this site in its settings' : 'Show a desktop notification when an alert fires or an order fills'}
    onClick={() => { void askPermission().then(setSt) }}>{st === 'denied' ? 'Notifications blocked' : 'Turn on notifications'}</Button>
}

function Alerts() {
  const q = useAlerts()
  const m = useAlertMutations()
  const toast = useToast()
  const d = q.data
  const active = d?.alerts.filter((a) => a.active) ?? []
  const done = d?.alerts.filter((a) => !a.active) ?? []
  const lq = useLiveQuotes(active.filter((a) => a.symbol !== 'ALL').map((a) => a.symbol))
  const fail = (err: unknown) => toast({ tone: 'bad', title: 'Not changed', detail: errText(err) })
  return (
    <Card title="Alerts" subtitle={d?.note} right={<NotifyButton />}>
      <AlertForm />
      {q.error && !d ? <div className="mt-3"><ErrorState error={q.error} compact /></div> : !d ? <div className="mt-3"><SkeletonRows rows={3} /></div> : (
        <div className="mt-3 space-y-3">
          {active.length === 0 && done.length === 0 && <p className="text-xs text-muted">No alerts yet. Set one above, or with the bell on any chart.</p>}
          {active.length > 0 && (
            <ul className="divide-y divide-line/60 rounded-md border border-line">
              {active.map((a) => {
                const p = lq.quotes[a.symbol]
                return (
                  <li key={a.id} className="flex flex-wrap items-center gap-2 px-3 py-2 text-[13px]">
                    <BellRing className="h-3.5 w-3.5 text-accent" />
                    {a.symbol === 'ALL' ? <span className="font-semibold">{a.note || 'Scan'}</span> : <Link to={`/chart/${a.symbol}`} className="font-semibold hover:underline">{a.symbol}</Link>}
                    <span className="text-muted">{ALERT_KIND_LABEL[a.kind].toLowerCase()} <span className="num text-fg">{alertValueText(a)}</span></span>
                    {a.note && <span className="text-xs text-faint">· {a.note}</span>}
                    <span className="ml-auto flex items-center gap-2 text-xs text-muted">{p && <>now <span className="num text-fg">{num(a.kind.startsWith('change') ? p.change_pct : p.price, 2)}{a.kind.startsWith('change') ? '%' : ''}</span></>}
                      <IconButton label="Delete alert" onClick={() => m.remove.mutate(a.id, { onError: fail })}><Trash2 className="h-3.5 w-3.5" /></IconButton></span>
                  </li>
                )
              })}
            </ul>
          )}
          {done.length > 0 && (
            <div>
              <div className="eyebrow mb-1">Fired or paused</div>
              <ul className="divide-y divide-line/60 rounded-md border border-line">
                {done.map((a) => (
                  <li key={a.id} className="flex flex-wrap items-center gap-2 px-3 py-2 text-[13px] text-muted">
                    <span className="font-semibold text-fg">{a.symbol}</span>
                    <span>{ALERT_KIND_LABEL[a.kind].toLowerCase()} {alertValueText(a)}</span>
                    {a.fired_at && <span className="text-xs">fired {dateTimeIST(a.fired_at)}{a.fired_price != null && <> at <span className="num">{num(a.fired_price, 2)}</span></>}{a.source === 'yahoo' ? ' (Yahoo, ~15 min late)' : ''}{a.detail ? ` · ${a.detail}` : ''}</span>}
                    <span className="ml-auto flex gap-1">
                      <Button size="sm" variant="ghost" icon={<RotateCcw className="h-3.5 w-3.5" />} onClick={() => m.setActive.mutate({ id: a.id, active: true }, { onError: fail })}>Re-arm</Button>
                      <IconButton label="Delete alert" onClick={() => m.remove.mutate(a.id, { onError: fail })}><Trash2 className="h-3.5 w-3.5" /></IconButton>
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </Card>
  )
}

export default function Watchlist() {
  const q = useWatchlists()
  const save = useSaveWatchlists()
  const toast = useToast()
  const [sel, setSel] = useState(0)
  const lists = q.data?.lists ?? []
  const cur = lists[Math.min(sel, Math.max(lists.length - 1, 0))]
  const put = (next: WL[]) => save.mutate(next, { onError: (e) => toast({ tone: 'bad', title: 'Watchlist not saved', detail: errText(e) }) })
  const update = (fn: (l: WL) => WL) => put(lists.map((l) => (l === cur ? fn(l) : l)))
  const smart = useSavedScans()
  return (
    <div>
      <PageHeader title="Watchlist" subtitle="Your own lists: live prices, each stock's one tested answer, and price alerts. Watchlist and alert symbols are streamed by the live feed from its next start." />
      <div className="space-y-3">
        <Card flush>
          {q.error && !q.data ? <ErrorState error={q.error} onRetry={() => void q.refetch()} /> : !q.data || !cur ? <SkeletonRows rows={5} /> : (
            <>
              <div className="flex flex-wrap items-center gap-2 border-b border-line px-3 py-2">
                <Segmented<string> ariaLabel="List" value={cur.name} onChange={(v) => setSel(lists.findIndex((l) => l.name === v))}
                  items={lists.map((l) => ({ id: l.name, label: `${l.name} · ${l.symbols.length}` }))} className="scroll-x no-scrollbar max-w-full" />
                <Button size="sm" variant="ghost" icon={<Plus className="h-3.5 w-3.5" />} onClick={() => {
                  const name = window.prompt('Name of the new list')?.trim()
                  if (name) { put([...lists, { name, symbols: [] }]); setSel(lists.length) }
                }}>New list</Button>
                <select aria-label="Smart list from a saved scan" value="" className="input h-8 px-2 text-[13px]" title="A list that fills itself with a saved scan's stocks after each scan"
                  onChange={(e) => { const s = smart.data?.scans.find((x) => x.id === e.target.value); if (s) { put([...lists, { name: s.name.slice(0, 40), symbols: [], scan_id: s.id }]); setSel(lists.length) } }}>
                  <option value="">Smart list from a scan…</option>
                  {(smart.data?.scans ?? []).map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
                </select>
                {lists.length > 1 && <Button size="sm" variant="ghost" icon={<Trash2 className="h-3.5 w-3.5" />} onClick={() => {
                  if (window.confirm(`Delete the list "${cur.name}"? Its stocks are only removed from this list.`)) { put(lists.filter((l) => l !== cur)); setSel(0) }
                }}>Delete list</Button>}
                {cur.scan_id ? <span className="ml-auto text-2xs text-muted">Smart list: filled by the scan "{smart.data?.scans.find((x) => x.id === cur.scan_id)?.name ?? cur.scan_id}" after each scan</span>
                  : <div className="ml-auto"><AddSymbol onAdd={(s) => update((l) => (l.symbols.includes(s) ? l : { ...l, symbols: [...l.symbols, s] }))} /></div>}
              </div>
              <ListTable list={cur} onRemove={(s) => update((l) => ({ ...l, symbols: l.symbols.filter((x) => x !== s) }))} />
            </>
          )}
        </Card>
        <Alerts />
      </div>
    </div>
  )
}
