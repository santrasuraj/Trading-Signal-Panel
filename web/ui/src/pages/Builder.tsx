// Strategy builder `/builder`: write a strategy in plain English (Claude turns it into rules; it never says whether it
// works) or build it from the rule editor, then test it like the built-in strategies (8 years of the survivorship-free
// top 500, costs, slippage, tax, the same "working" test), optimise its exits with a walk-forward, and save it.

import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { FlaskConical, Plus, Save, Sparkles, Trash2, Wand2 } from 'lucide-react'
import { fetchJson, isFailure } from '@/api/client'
import { useAiConfigured, useScanCatalog, type ScanRule } from '@/api/scans'
import { LinesChart } from '@/components/charts/LinesChart'
import { KpiStrip, KpiTile, PageHeader } from '@/components/domain'
import { ErrorState, Skeleton } from '@/components/feedback'
import { Pct } from '@/components/num'
import { useToast } from '@/components/toast'
import { Button, Card, IconButton, Segmented } from '@/components/ui'
import { cn } from '@/lib/csv'
import { num } from '@/lib/format'
import { RuleRow } from './Scans'

interface Spec {
  name: string; entry: { match: 'all' | 'any'; rules: ScanRule[] }
  exit: { stop_pct: number | null; target_pct: number | null; trail_pct: number | null; max_days: number | null; match: 'all' | 'any'; rules: ScanRule[] }
  max_positions: number; priority: string | null
}
interface TestResult {
  spec: Spec; text: { entry: string; exit: string; sizing: string }; status: string; status_reason: string
  metrics: Record<string, unknown>; split: { in_sample_cagr_pct: number | null; out_of_sample_cagr_pct: number | null; cut: string }
  yearly: Record<string, number>; trades: number; curve: [string, number][]; elapsed_s: number
}
interface OptResult {
  combos: number; first_unseen_year: number; walk_forward_cagr_pct: number | null; hindsight_best_cagr_pct: number | null
  your_settings_cagr_pct: number | null; hindsight_best: Record<string, number | null>; picks: { year: number; settings: Record<string, number | null> }[]
  deflated_sharpe: { deflated_pct?: number; sharpe_ann?: number; trials?: number } | null; curve: [string, number][]; note: string
}
interface Job { id: string; state: 'running' | 'done' | 'error'; done: number; total: number; error: string | null; result?: OptResult | null }
interface SavedSpec extends Spec { id: string; saved: string; last_test: { status: string; status_reason: string } | null }

const BLANK: Spec = { name: 'My strategy', entry: { match: 'all', rules: [{ left: 'close', op: '>', right: { field: 'high_52w_prev', mult: 1 } }] },
  exit: { stop_pct: 8, target_pct: null, trail_pct: 15, max_days: null, match: 'any', rules: [] }, max_positions: 10, priority: 'rs_rating' }
const post = <T,>(p: string, b: unknown) => fetchJson<T>(p, { method: 'POST', body: JSON.stringify(b) })
const STATUS: Record<string, string> = { working: 'WORKING', mixed: 'MIXED', not_working: 'NOT WORKING', unknown: 'UNKNOWN', too_new: 'TOO NEW' }
const fmtSet = (s: Record<string, number | null>) => `stop ${s.stop_pct ?? '—'}% · target ${s.target_pct ?? 'none'}${s.target_pct ? '%' : ''} · ${s.max_days ? `${s.max_days} days` : 'no time limit'}`

function NumIn({ label, v, on, step = 1 }: { label: string; v: number | null; on: (x: number | null) => void; step?: number }) {
  return <label className="text-2xs text-muted">{label}<input aria-label={label} inputMode="decimal" step={step} value={v ?? ''} placeholder="none"
    onChange={(e) => on(e.target.value === '' ? null : Number(e.target.value))} className="input num mt-0.5 block h-8 w-24 px-2 text-right" /></label>
}

export default function Builder() {
  const cat = useScanCatalog()
  const ai = useAiConfigured()
  const qc = useQueryClient()
  const toast = useToast()
  const [spec, setSpec] = useState<Spec>(BLANK)
  const [sid, setSid] = useState<string | undefined>()
  const [text, setText] = useState('')
  const [jobId, setJobId] = useState<string | null>(null)
  const fail = (title: string) => (e: unknown) => toast({ tone: 'bad', title, detail: isFailure(e) ? `${e.message}${e.hint ? ` ${e.hint}` : ''}` : undefined })
  const fromText = useMutation({ mutationFn: (t: string) => post<{ spec: Spec; text: TestResult['text']; explanation: string; unsupported: string }>('/api/builder/from-text', { text: t }) })
  const testM = useMutation({ mutationFn: (s: Spec) => post<TestResult>('/api/builder/test', s) })
  const optM = useMutation({ mutationFn: (s: Spec) => post<Job>('/api/builder/optimise', s), onSuccess: (j) => setJobId(j.id) })
  const job = useQuery({ queryKey: ['builder-job', jobId], queryFn: () => fetchJson<Job>(`/api/builder/optimise/${jobId}`), enabled: !!jobId,
    refetchInterval: (q) => (q.state.data?.state === 'running' ? 2_000 : false) })
  const saved = useQuery({ queryKey: ['builder-saved'], queryFn: () => fetchJson<{ strategies: SavedSpec[] }>('/api/builder/saved') })
  const saveM = useMutation({ mutationFn: (v: { spec: Spec; id?: string; result?: TestResult }) => post<SavedSpec>('/api/builder/saved', { spec: v.spec, id: v.id, result: v.result }),
    onSuccess: (s) => { setSid(s.id); void qc.invalidateQueries({ queryKey: ['builder-saved'] }); toast({ tone: 'good', title: `Saved: ${s.name}` }) } })
  const delM = useMutation({ mutationFn: (id: string) => fetchJson(`/api/builder/saved/${id}`, { method: 'DELETE' }), onSuccess: () => void qc.invalidateQueries({ queryKey: ['builder-saved'] }) })
  useEffect(() => { setJobId(null); testM.reset() }, [spec]) // eslint-disable-line react-hooks/exhaustive-deps
  if (cat.error) return <ErrorState error={cat.error} />
  if (!cat.data) return <Skeleton className="h-40 w-full" />
  const fields = cat.data.fields
  const ex = spec.exit
  const setEx = (k: keyof Spec['exit'], v: unknown) => setSpec((s) => ({ ...s, exit: { ...s.exit, [k]: v } }))
  const rules = (which: 'entry' | 'exit') => (which === 'entry' ? spec.entry.rules : spec.exit.rules)
  const setRules = (which: 'entry' | 'exit', rs: ScanRule[]) => setSpec((s) => (which === 'entry' ? { ...s, entry: { ...s.entry, rules: rs } } : { ...s, exit: { ...s.exit, rules: rs } }))
  const r = testM.data
  const opt = job.data?.result
  const m = (r?.metrics ?? {}) as Record<string, number | null | undefined>
  const ruleBlock = (which: 'entry' | 'exit') => (
    <div className="space-y-1.5">
      {rules(which).map((x, i) => <RuleRow key={i} r={x} i={i} fields={fields} ops={cat.data!.ops}
        onChange={(y) => setRules(which, rules(which).map((z, j) => (j === i ? y : z)))} onRemove={() => setRules(which, rules(which).filter((_, j) => j !== i))} />)}
      <Button size="xs" variant="ghost" icon={<Plus className="h-3.5 w-3.5" />} disabled={rules(which).length >= cat.data!.max_rules}
        onClick={() => setRules(which, [...rules(which), { left: 'rsi14', op: '>', right: { value: 50 } }])}>Add {which} rule</Button>
    </div>
  )
  return (
    <div className="space-y-3">
      <PageHeader title="Strategy builder" subtitle="Describe a strategy or build it from rules, then test it exactly like the built-in ones: 8 years of the survivorship-free top 500, real costs and tax, the same 'working' test." />
      <div className="grid gap-3 xl:grid-cols-[minmax(0,1fr)_280px]">
        <div className="min-w-0 space-y-3">
          <Card title={<span className="flex items-center gap-1.5"><Sparkles className="h-4 w-4 text-accent" />Describe it</span>} subtitle="Claude turns your words into rules (it never says whether they work: the backtest does).">
            <textarea aria-label="Strategy in plain English" value={text} onChange={(e) => setText(e.target.value)} rows={3} maxLength={1500}
              placeholder="e.g. Buy stocks breaking a 52-week high on twice the normal volume, strongest first, 10 at a time; stop 8%, trail 15%."
              className="input w-full p-2 text-[13px]" />
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <Button size="sm" variant="primary" icon={<Wand2 className="h-3.5 w-3.5" />} disabled={!text.trim() || !ai.data?.configured} loading={fromText.isPending}
                onClick={() => fromText.mutate(text, { onSuccess: (d) => { setSpec(d.spec); setSid(undefined) }, onError: fail('Not translated') })}>Turn into rules</Button>
              {!ai.data?.configured && <span className="text-2xs text-warn">Needs ANTHROPIC_API_KEY in .env (the rule editor below works without it).</span>}
            </div>
            {fromText.data && <p className="mt-2 text-xs text-muted">{fromText.data.explanation}{fromText.data.unsupported && <span className="text-warn"> Left out: {fromText.data.unsupported}</span>}</p>}
          </Card>
          <Card title="Rules">
            <input aria-label="Strategy name" value={spec.name} maxLength={60} onChange={(e) => setSpec({ ...spec, name: e.target.value })} className="input mb-3 h-8 w-72 px-2 text-[13px] font-medium" />
            <div className="space-y-4">
              <section>
                <div className="mb-1.5 flex items-center gap-2"><h3 className="eyebrow">Buy when</h3>
                  <Segmented<'all' | 'any'> size="xs" ariaLabel="Entry match" value={spec.entry.match} onChange={(v) => setSpec({ ...spec, entry: { ...spec.entry, match: v } })} items={[{ id: 'all', label: 'All rules' }, { id: 'any', label: 'Any rule' }]} /></div>
                {ruleBlock('entry')}
              </section>
              <section>
                <h3 className="eyebrow mb-1.5">Sell when</h3>
                <div className="flex flex-wrap gap-2">
                  <NumIn label="Stop-loss %" v={ex.stop_pct} on={(x) => setEx('stop_pct', x)} />
                  <NumIn label="Target %" v={ex.target_pct} on={(x) => setEx('target_pct', x)} />
                  <NumIn label="Trailing stop %" v={ex.trail_pct} on={(x) => setEx('trail_pct', x)} />
                  <NumIn label="Max days held" v={ex.max_days} on={(x) => setEx('max_days', x)} />
                </div>
                <div className="mt-2">{ruleBlock('exit')}</div>
              </section>
              <section className="flex flex-wrap items-end gap-3">
                <NumIn label="Positions at once" v={spec.max_positions} on={(x) => setSpec({ ...spec, max_positions: Math.max(1, Math.min(50, Math.round(x ?? 10))) })} />
                <label className="text-2xs text-muted">Buy first<select aria-label="Ranking" value={spec.priority ?? ''} onChange={(e) => setSpec({ ...spec, priority: e.target.value || null })} className="input mt-0.5 block h-8 px-2 text-[13px]">
                  <option value="">No ranking</option>{fields.map((f) => <option key={f.key} value={f.key}>Highest {f.label}</option>)}</select></label>
              </section>
            </div>
            <div className="mt-3 flex flex-wrap gap-2">
              <Button size="sm" variant="primary" icon={<FlaskConical className="h-3.5 w-3.5" />} disabled={!spec.entry.rules.length} loading={testM.isPending} onClick={() => testM.mutate(spec, { onError: fail('Test failed') })}>Test 8 years</Button>
              <Button size="sm" disabled={!spec.entry.rules.length} loading={optM.isPending || job.data?.state === 'running'} onClick={() => optM.mutate(spec, { onError: fail('Not started') })}>Optimise exits (walk-forward)</Button>
              <Button size="sm" icon={<Save className="h-3.5 w-3.5" />} disabled={!spec.entry.rules.length} loading={saveM.isPending} onClick={() => saveM.mutate({ spec, id: sid, result: r }, { onError: fail('Not saved') })}>{sid ? 'Save' : 'Save as new'}</Button>
            </div>
            {testM.isPending && <p className="mt-2 text-2xs text-muted">Testing on 8 years: a few seconds (the first test loads the data, ~10 s more).</p>}
            {testM.error && <p className="mt-2 text-xs text-loss">{isFailure(testM.error) ? testM.error.message : 'Failed.'}</p>}
          </Card>
          {r && (
            <Card title={<span className="flex items-center gap-2">Test result <span className={cn('rounded px-1.5 py-0.5 text-xs font-bold', r.status === 'working' ? 'bg-profit text-white' : r.status === 'not_working' ? 'bg-loss text-white' : 'border border-line-strong bg-raised')}>{STATUS[r.status] ?? r.status}</span></span>}
              subtitle={`${r.text.entry} · sell: ${r.text.exit} · ${r.text.sizing}`}>
              <KpiStrip>
                <KpiTile label="CAGR" value={<Pct v={m.cagr_pct} dp={1} />} sub="after costs" />
                <KpiTile label="After tax" value={<Pct v={m.after_tax_cagr_pct} dp={1} />} />
                <KpiTile label="Worst drop" value={<Pct v={m.max_dd_pct} dp={1} />} />
                <KpiTile label="Trades" value={r.trades} sub={m.exposure_pct != null ? `${num(m.exposure_pct, 0)}% invested` : undefined} />
                <KpiTile label="First 70% of years" value={<Pct v={r.split.in_sample_cagr_pct} dp={1} />} sub="a year" />
                <KpiTile label="Last 30% (since cut)" value={<Pct v={r.split.out_of_sample_cagr_pct} dp={1} />} sub={`from ${r.split.cut}`} />
              </KpiStrip>
              <p className="mt-2 text-xs text-muted">{r.status_reason}</p>
              <div className="mt-3"><LinesChart t={r.curve.map((x) => x[0])} lines={[{ id: 's', label: spec.name, v: r.curve.map((x) => x[1]), color: 'accent', width: 2, format: (v: number) => `${((v - 1) * 100).toFixed(0)}%` }]} height={220} /></div>
              <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-xs">{Object.entries(r.yearly).map(([y, v]) => <span key={y}>{y} <Pct v={v} dp={1} /></span>)}</div>
            </Card>
          )}
          {job.data?.state === 'running' && <Card title="Optimising exits"><p className="text-xs text-muted">Simulation {job.data.done} of {job.data.total || 27}…</p></Card>}
          {job.data?.state === 'error' && <Card title="Optimisation failed"><p className="text-xs text-loss">{job.data.error}</p></Card>}
          {opt && (
            <Card title="Walk-forward of the exits" subtitle={`${opt.combos} exit settings; from ${opt.first_unseen_year}, each year uses the settings that did best on the years before it only`}>
              <KpiStrip>
                <KpiTile label="Walk-forward (unseen years)" value={<Pct v={opt.walk_forward_cagr_pct} dp={1} />} sub="what tuning would really have given" />
                <KpiTile label="Your settings, same years" value={<Pct v={opt.your_settings_cagr_pct} dp={1} />} />
                <KpiTile label="Hindsight best" value={<Pct v={opt.hindsight_best_cagr_pct} dp={1} />} sub={fmtSet(opt.hindsight_best)} />
                <KpiTile label="Deflated Sharpe" value={opt.deflated_sharpe?.deflated_pct != null ? `${num(opt.deflated_sharpe.deflated_pct, 0)}%` : '—'} sub="chance it's not luck" />
              </KpiStrip>
              <ul className="mt-2 space-y-0.5 text-xs text-muted">{opt.picks.map((p) => <li key={p.year}>{p.year}: {fmtSet(p.settings)}</li>)}</ul>
              <p className="mt-2 text-2xs text-faint">{opt.note}</p>
            </Card>
          )}
        </div>
        <Card title="Your strategies">
          {saved.data?.strategies.length ? (
            <ul className="space-y-1">{saved.data.strategies.map((s) => (
              <li key={s.id} className={cn('flex items-center gap-1 rounded px-1.5 py-1 text-[13px] hover:bg-raised', s.id === sid && 'bg-raised')}>
                <button type="button" className="min-w-0 flex-1 truncate text-left" title={s.name}
                  onClick={() => { setSpec({ name: s.name, entry: s.entry, exit: s.exit, max_positions: s.max_positions, priority: s.priority }); setSid(s.id) }}>{s.name}
                  {s.last_test && <span className="ml-1 text-2xs text-faint">{STATUS[s.last_test.status] ?? s.last_test.status}</span>}</button>
                <IconButton label={`Delete ${s.name}`} onClick={() => { if (window.confirm(`Delete "${s.name}"?`)) delM.mutate(s.id) }}><Trash2 className="h-3.5 w-3.5" /></IconButton>
              </li>
            ))}</ul>
          ) : <p className="text-xs text-muted">None yet: build one and press Save.</p>}
          <p className="mt-3 text-2xs text-faint">Long only, daily bars, equal money per position, the regime filter (no new buys while the Nifty is below its 200-day average) as for the built-in strategies.</p>
        </Card>
      </div>
    </div>
  )
}
