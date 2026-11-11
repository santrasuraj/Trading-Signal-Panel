// Scans `/scans`: build your own scan from rules, run it on today's market, and back-test it on 8 years of the
// survivorship-free top 500 in one click (the same event study every pattern in this app went through).

import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { FlaskConical, Play, Plus, Save, Trash2, X } from 'lucide-react'
import { isFailure } from '@/api/client'
import { useLiveQuotes } from '@/api/hooks'
import {
  OP_LABEL, VERDICT_TEXT, useBacktestScan, useRunScan, useSavedScans, useScanCatalog, useScanStore,
  type Scan, type ScanBacktest, type ScanField, type ScanOp, type ScanRule, type ScanRun,
} from '@/api/scans'
import { PageHeader } from '@/components/domain'
import { EmptyState, ErrorState, Skeleton } from '@/components/feedback'
import { Pct } from '@/components/num'
import { useToast } from '@/components/toast'
import { Button, Card, Chip, IconButton, Segmented } from '@/components/ui'
import { cn } from '@/lib/csv'
import { date, num, pct } from '@/lib/format'

const BLANK: Scan = { name: 'My scan', match: 'all', direction: 'long', rules: [{ left: 'close', op: '>', right: { field: 'sma200', mult: 1 } }] }

function FieldSelect({ value, onChange, fields, label }: { value: string; onChange: (v: string) => void; fields: ScanField[]; label: string }) {
  const groups = useMemo(() => [...new Set(fields.map((f) => f.group))], [fields])
  return (
    <select aria-label={label} value={value} onChange={(e) => onChange(e.target.value)} className="input h-8 max-w-[220px] px-2 text-[13px]">
      {groups.map((g) => <optgroup key={g} label={g}>{fields.filter((f) => f.group === g).map((f) => <option key={f.key} value={f.key}>{f.label}</option>)}</optgroup>)}
    </select>
  )
}

function RuleRow({ r, i, fields, ops, onChange, onRemove }: {
  r: ScanRule; i: number; fields: ScanField[]; ops: ScanOp[]; onChange: (r: ScanRule) => void; onRemove: () => void
}) {
  const byField = r.right.field != null
  return (
    <div className="flex flex-wrap items-center gap-2 rounded-md border border-line bg-raised/40 px-2 py-1.5">
      <span className="w-5 text-2xs text-faint">{i + 1}</span>
      <FieldSelect label={`Rule ${i + 1} field`} value={r.left} fields={fields} onChange={(v) => onChange({ ...r, left: v })} />
      <select aria-label={`Rule ${i + 1} comparison`} value={r.op} onChange={(e) => onChange({ ...r, op: e.target.value as ScanOp })} className="input h-8 px-2 text-[13px]">
        {ops.map((o) => <option key={o} value={o}>{OP_LABEL[o]}</option>)}
      </select>
      <Segmented<'value' | 'field'> size="xs" ariaLabel="Compare with" value={byField ? 'field' : 'value'}
        onChange={(v) => onChange({ ...r, right: v === 'field' ? { field: 'sma50', mult: 1 } : { value: 0 } })}
        items={[{ id: 'value', label: 'number' }, { id: 'field', label: 'field' }]} />
      {byField ? (
        <>
          <input aria-label={`Rule ${i + 1} multiplier`} inputMode="decimal" value={r.right.mult ?? 1} onChange={(e) => onChange({ ...r, right: { ...r.right, mult: Number(e.target.value) || 1 } })}
            className="input num h-8 w-16 px-2 text-right text-[13px]" title="Multiplier, e.g. 1.05 = 5% above" />
          <span className="text-xs text-faint">×</span>
          <FieldSelect label={`Rule ${i + 1} compared field`} value={r.right.field!} fields={fields} onChange={(v) => onChange({ ...r, right: { ...r.right, field: v } })} />
        </>
      ) : (
        <input aria-label={`Rule ${i + 1} number`} inputMode="decimal" value={r.right.value ?? 0} onChange={(e) => onChange({ ...r, right: { value: Number(e.target.value) } })}
          className="input num h-8 w-24 px-2 text-right text-[13px]" />
      )}
      <IconButton label={`Remove rule ${i + 1}`} onClick={onRemove} className="ml-auto"><X className="h-3.5 w-3.5" /></IconButton>
    </div>
  )
}

function Results({ r, fields }: { r: ScanRun; fields: ScanField[] }) {
  const nav = useNavigate()
  const lq = useLiveQuotes(r.rows.slice(0, 100).map((x) => x.symbol))
  const label = (k: string) => fields.find((f) => f.key === k)?.label ?? k
  return (
    <Card title={`Today: ${r.count} of ${r.universe_size} stocks match`} subtitle={`On the stored prices of ${date(r.date)} · ${r.rules_text.join(r.scan.match === 'all' ? ' AND ' : ' OR ')} · ${num(r.elapsed_s, 2)} s`} flush>
      {r.rows.length === 0 ? <EmptyState compact title="No stock matches today" /> : (
        <div className="scroll-x">
          <table className="w-full text-[13px]">
            <thead className="text-2xs uppercase tracking-[0.04em] text-faint">
              <tr className="border-b border-line">
                <th className="px-3 py-2 text-left font-semibold">Symbol</th>
                <th className="px-3 py-2 text-right font-semibold">Price</th>
                <th className="px-3 py-2 text-right font-semibold">Day</th>
                <th className="px-3 py-2 text-right font-semibold">RS</th>
                {r.fields.filter((k) => k !== 'close').slice(0, 5).map((k) => <th key={k} className="px-3 py-2 text-right font-semibold" title={label(k)}>{label(k).replace(/ \(.*\)/, '')}</th>)}
              </tr>
            </thead>
            <tbody>
              {r.rows.map((x) => {
                const q = lq.quotes[x.symbol]
                return (
                  <tr key={x.symbol} className="cursor-pointer border-b border-line/60 hover:bg-raised" onClick={() => nav(`/chart/${x.symbol}`)}>
                    <td className="px-3 py-1.5"><span className="font-semibold">{x.symbol}</span>{x.new_today && <Chip className="tint-accent ml-1.5 h-4 px-1.5 text-[10px] text-accent">new</Chip>}<span className="block max-w-[220px] truncate text-2xs text-muted">{x.company}</span></td>
                    <td className="num px-3 py-1.5 text-right">{num(q?.price ?? x.close, 2)}</td>
                    <td className="px-3 py-1.5 text-right"><Pct v={q ? q.change_pct : x.change_pct} dp={2} /></td>
                    <td className="num px-3 py-1.5 text-right">{num(x.rs_rating, 0)}</td>
                    {r.fields.filter((k) => k !== 'close').slice(0, 5).map((k) => <td key={k} className="num px-3 py-1.5 text-right">{num(x.values[k], 2)}</td>)}
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
      <p className="border-t border-line px-3 py-2 text-2xs text-faint">"new" = started to match on this day (the event the backtest measures). Prices follow the live price while the market is open. A match is a screen, not a signal: see the backtest for whether it has ever paid.</p>
    </Card>
  )
}

function Backtest({ b }: { b: ScanBacktest }) {
  const v = VERDICT_TEXT[b.verdict]
  return (
    <Card title="Backtest: 8 years, survivorship-free top 500" subtitle={`${b.events.toLocaleString('en-IN')} events, ${date(b.first_day)} to ${date(b.last_day)} · ${num(b.elapsed_s, 1)} s`}>
      <div className="flex flex-wrap items-center gap-3">
        <span className={cn('rounded-md px-2.5 py-1 text-sm font-bold', v.tone === 'good' ? 'bg-profit text-white' : v.tone === 'bad' ? 'bg-loss text-white' : 'border border-line-strong bg-raised text-fg')}>{v.label.toUpperCase()}</span>
        <span className="text-xs text-muted">Measured at {b.primary} days: buy at the next open after the stock starts to match, vs the average top-500 stock over the same days, {pct(b.cost_pct, { signed: false, dp: 2 })} round-trip costs subtracted.</span>
      </div>
      <div className="scroll-x mt-3">
        <table className="w-full text-[13px]">
          <thead className="text-2xs uppercase tracking-[0.04em] text-faint">
            <tr className="border-b border-line"><th className="py-1.5 text-left font-semibold">Hold</th><th className="py-1.5 text-right font-semibold">Events</th><th className="py-1.5 text-right font-semibold">vs avg stock</th><th className="py-1.5 text-right font-semibold">After costs</th><th className="py-1.5 text-right font-semibold">Median</th><th className="py-1.5 text-right font-semibold">Beat it</th><th className="py-1.5 text-right font-semibold" title="t-statistic on monthly averages: 2+ is unlikely to be luck">t</th></tr>
          </thead>
          <tbody>
            {Object.entries(b.horizons).map(([h, s]) => (
              <tr key={h} className={cn('border-b border-line/60', Number(h) === b.primary && 'font-medium')}>
                <td className="py-1.5">{h} days</td>
                <td className="num py-1.5 text-right">{s.n.toLocaleString('en-IN')}</td>
                <td className="py-1.5 text-right"><Pct v={s.excess_pct} dp={2} /></td>
                <td className="py-1.5 text-right"><Pct v={s.after_cost_pct} dp={2} /></td>
                <td className="py-1.5 text-right"><Pct v={s.median_pct} dp={2} /></td>
                <td className="num py-1.5 text-right">{s.hit_pct != null ? `${num(s.hit_pct, 0)}%` : '—'}</td>
                <td className={cn('num py-1.5 text-right', s.t != null && Math.abs(s.t) >= 2 && (s.t > 0 ? 'text-profit' : 'text-loss'))}>{num(s.t, 1)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {b.yearly.length > 0 && (
        <div className="mt-3">
          <div className="eyebrow mb-1">By year ({b.primary} days, vs the average stock)</div>
          <div className="flex flex-wrap gap-1.5">{b.yearly.map((y) => (
            <span key={y.year} className="rounded-md border border-line px-2 py-1 text-xs" title={`${y.events} events · beat it ${num(y.hit_pct, 0)}% · raw return ${pct(y.return_pct)}`}>
              <span className="text-muted">{y.year}</span> <Pct v={y.excess_pct} dp={2} /> <span className="text-faint">({y.events})</span>
            </span>
          ))}</div>
        </div>
      )}
      {b.recent.length > 0 && (
        <details className="mt-3 text-xs">
          <summary className="cursor-pointer text-muted">Last {b.recent.length} events</summary>
          <ul className="mt-1 grid gap-x-4 sm:grid-cols-2 lg:grid-cols-3">{b.recent.map((e) => (
            <li key={`${e.date}${e.symbol}`} className="flex justify-between gap-2 border-b border-line/50 py-1"><span><span className="text-muted">{date(e.date, { year: false })}</span> <Link to={`/chart/${e.symbol}`} className="font-medium hover:underline">{e.symbol}</Link></span><span><Pct v={e.return_pct} dp={1} /> <span className="text-faint">vs avg</span> <Pct v={e.excess_pct} dp={1} /></span></li>
          ))}</ul>
        </details>
      )}
      <p className="mt-3 text-2xs text-faint">{b.note}</p>
    </Card>
  )
}

export default function Scans() {
  const cat = useScanCatalog()
  const saved = useSavedScans()
  const store = useScanStore()
  const runM = useRunScan()
  const btM = useBacktestScan()
  const toast = useToast()
  const [scan, setScan] = useState<Scan>(BLANK)
  const [id, setId] = useState<string | undefined>()
  const fields = cat.data?.fields ?? []
  const fail = (title: string) => (e: unknown) => toast({ tone: 'bad', title, detail: isFailure(e) ? e.message : undefined })
  const run = (s: Scan = scan) => { runM.mutate(s, { onError: fail('Scan failed') }) }
  const backtest = (s: Scan = scan) => { btM.mutate(s, { onError: fail('Backtest failed') }) }
  useEffect(() => { if (cat.data && !runM.data && !runM.isPending) run() }, [cat.data]) // eslint-disable-line react-hooks/exhaustive-deps
  const load = (s: Scan, sid?: string) => { setScan({ name: s.name, match: s.match, direction: s.direction, rules: s.rules }); setId(sid); btM.reset(); run(s) }
  const setRule = (i: number, r: ScanRule) => setScan((s) => ({ ...s, rules: s.rules.map((x, j) => (j === i ? r : x)) }))
  return (
    <div>
      <PageHeader title="Scans" subtitle="Build a scan from rules, see today's matches, and test it on 8 years of the survivorship-free top 500 in one click." />
      {cat.error ? <div className="card"><ErrorState error={cat.error} /></div> : !cat.data ? <Skeleton className="h-40 w-full" /> : (
        <div className="grid gap-3 xl:grid-cols-[minmax(0,1fr)_280px]">
          <div className="min-w-0 space-y-3">
            <Card title="Rules">
              <div className="mb-2 flex flex-wrap items-center gap-2">
                <input aria-label="Scan name" value={scan.name} maxLength={60} onChange={(e) => setScan({ ...scan, name: e.target.value })} className="input h-8 w-64 px-2 text-[13px] font-medium" />
                <Segmented<'all' | 'any'> ariaLabel="Match" value={scan.match} onChange={(v) => setScan({ ...scan, match: v })} items={[{ id: 'all', label: 'All rules' }, { id: 'any', label: 'Any rule' }]} />
                <Segmented<'long' | 'short'> ariaLabel="Direction" value={scan.direction} onChange={(v) => setScan({ ...scan, direction: v })} items={[{ id: 'long', label: 'Bullish setup', title: 'Tested as a buy' }, { id: 'short', label: 'Bearish setup', title: 'Tested as a short (the stock should lag)' }]} />
              </div>
              <div className="space-y-1.5">
                {scan.rules.map((r, i) => <RuleRow key={i} r={r} i={i} fields={fields} ops={cat.data!.ops} onChange={(x) => setRule(i, x)} onRemove={() => setScan((s) => ({ ...s, rules: s.rules.filter((_, j) => j !== i) }))} />)}
              </div>
              <div className="mt-2 flex flex-wrap gap-2">
                <Button size="sm" variant="ghost" icon={<Plus className="h-3.5 w-3.5" />} disabled={scan.rules.length >= cat.data.max_rules} onClick={() => setScan((s) => ({ ...s, rules: [...s.rules, { left: 'rsi14', op: '>', right: { value: 50 } }] }))}>Add rule</Button>
                <div className="flex-1" />
                <Button size="sm" icon={<Play className="h-3.5 w-3.5" />} disabled={!scan.rules.length} loading={runM.isPending} onClick={() => run()}>Run today</Button>
                <Button size="sm" variant="primary" icon={<FlaskConical className="h-3.5 w-3.5" />} disabled={!scan.rules.length} loading={btM.isPending} onClick={() => backtest()}>Backtest 8 years</Button>
                <Button size="sm" icon={<Save className="h-3.5 w-3.5" />} disabled={!scan.rules.length} loading={store.save.isPending}
                  onClick={() => store.save.mutate({ scan, id }, { onSuccess: (s) => { setId(s.id); toast({ tone: 'good', title: `Saved: ${s.name}` }) }, onError: fail('Not saved') })}>{id ? 'Save' : 'Save as new'}</Button>
              </div>
              {btM.isPending && <p className="mt-2 text-2xs text-muted">Testing on 8 years: a few seconds (the first test after a while loads the data, ~5 s more).</p>}
            </Card>
            {btM.data && <Backtest b={btM.data} />}
            {runM.error && !runM.data && <div className="card"><ErrorState error={runM.error} compact /></div>}
            {runM.data && <Results r={runM.data} fields={fields} />}
          </div>
          <div className="space-y-3">
            <Card title="Your scans">
              {saved.data?.scans.length ? (
                <ul className="space-y-1">{saved.data.scans.map((s) => (
                  <li key={s.id} className={cn('flex items-center gap-1 rounded px-1.5 py-1 text-[13px] hover:bg-raised', s.id === id && 'bg-raised')}>
                    <button type="button" className="min-w-0 flex-1 truncate text-left" onClick={() => load(s, s.id)} title={s.name}>{s.name}</button>
                    <IconButton label={`Delete ${s.name}`} onClick={() => { if (window.confirm(`Delete the scan "${s.name}"?`)) store.remove.mutate(s.id, { onSuccess: () => { if (id === s.id) setId(undefined) } }) }}><Trash2 className="h-3.5 w-3.5" /></IconButton>
                  </li>
                ))}</ul>
              ) : <p className="text-xs text-muted">None yet: build one and press Save.</p>}
            </Card>
            <Card title="Examples">
              <ul className="space-y-1">{cat.data.presets.map((p) => (
                <li key={p.name}><button type="button" className="w-full rounded px-1.5 py-1 text-left text-[13px] hover:bg-raised" onClick={() => load(p)}>{p.name}</button></li>
              ))}</ul>
              <p className="mt-2 text-2xs text-faint">Examples of popular setups, not recommendations: backtest them and see.</p>
            </Card>
          </div>
        </div>
      )}
    </div>
  )
}
