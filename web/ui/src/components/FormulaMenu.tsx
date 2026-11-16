// Your own indicators as formulas (chart toolbar): write, check and save a formula such as
// (close - sma(close, 50)) / atr(14); show it on the price chart or in its own pane. Saved formulas are also scan
// fields ("Your formulas"). scanner/formula.py: a small safe language, not code.

import { useState } from 'react'
import { useMutation, useQueries, useQuery, useQueryClient } from '@tanstack/react-query'
import { Sigma, Trash2 } from 'lucide-react'
import { fetchJson, isFailure } from '@/api/client'
import { LinesChart } from '@/components/charts/LinesChart'
import { Button, IconButton, Popover } from '@/components/ui'
import type { PatternDrawing } from '@/lib/patternDrawing'
import { useLocalStorage } from '@/lib/useLocalStorage'
import { num } from '@/lib/format'

export interface Formula { id: string; name: string; expr: string; pane: 'price' | 'own' }
interface FormulasResponse { formulas: Formula[]; functions: { name: string; help: string }[]; fields: string[] }
interface Series { symbol: string; t: string[]; v: (number | null)[] }

export function useFormulas() {
  return useQuery({ queryKey: ['formulas'], queryFn: () => fetchJson<FormulasResponse>('/api/formulas'), staleTime: Infinity })
}

/** The shown formulas' values on this symbol: price-pane ones as drawings, own-pane ones for a separate chart. */
export function useFormulaSeries(symbol: string, range: string, enabled: boolean) {
  const f = useFormulas()
  const [shown] = useLocalStorage<string[]>('qd.chart.formulas', [])
  const list = (f.data?.formulas ?? []).filter((x) => shown.includes(x.id))
  const qs = useQueries({ queries: list.map((x) => ({
    queryKey: ['formula-series', symbol, x.expr, range], enabled, staleTime: 5 * 60_000, retry: false,
    queryFn: () => fetchJson<Series>(`/api/formula-series/${encodeURIComponent(symbol)}?range=${range}&expr=${encodeURIComponent(x.expr)}`),
  })) })
  const price: PatternDrawing[] = []
  const own: { f: Formula; s: Series }[] = []
  list.forEach((x, i) => {
    const s = qs[i]?.data
    if (!s || s.symbol !== symbol.toUpperCase()) return
    if (x.pane === 'price') {
      const pts = s.t.map((t, k) => ({ t, v: s.v[k] })).filter((p): p is { t: string; v: number } => p.v != null)
      if (pts.length > 1) price.push({ key: `f:${x.id}`, name: x.name, tone: 'info', status: 'confirmed', lines: [{ id: `f:${x.id}`, role: 'line', points: pts, tone: 'info', style: 'solid', width: 2, labels: [], axisLabel: x.name.slice(0, 12) }] })
    } else own.push({ f: x, s })
  })
  return { price, own }
}

export function FormulaPanes({ own }: { own: { f: Formula; s: { t: string[]; v: (number | null)[] } }[] }) {
  if (!own.length) return null
  return (
    <>{own.map(({ f, s }) => (
      <div key={f.id} className="border-t border-line">
        <div className="px-3 pt-1.5 text-2xs text-muted"><b className="text-fg">{f.name}</b> · <code>{f.expr}</code></div>
        <LinesChart t={s.t} height={140} lines={[{ id: f.id, label: f.name, v: s.v, color: 'accent', format: (v) => num(v, 2), refLines: [{ price: 0 }] }]} />
      </div>))}</>
  )
}

export function FormulaMenu({ symbol }: { symbol: string }) {
  const qc = useQueryClient()
  const f = useFormulas()
  const [shown, setShown] = useLocalStorage<string[]>('qd.chart.formulas', [])
  const [draft, setDraft] = useState<Formula>({ id: '', name: '', expr: '', pane: 'own' })
  const [preview, setPreview] = useState<string | null>(null)
  const save = useMutation({
    mutationFn: (list: Formula[]) => fetchJson<{ formulas: Formula[] }>('/api/formulas', { method: 'PUT', body: JSON.stringify({ formulas: list }) }),
    onSuccess: (d) => { qc.setQueryData(['formulas'], (old: FormulasResponse | undefined) => old ? { ...old, formulas: d.formulas } : old); void qc.invalidateQueries({ queryKey: ['formula-series'] }) },
  })
  const check = useMutation({
    mutationFn: (expr: string) => fetchJson<{ last: { t: string; v: number }[] }>('/api/formulas/check', { method: 'POST', body: JSON.stringify({ expr, symbol }) }),
    onSuccess: (d) => setPreview(d.last.length ? `${symbol} now: ${num(d.last[d.last.length - 1].v, 3)}` : 'No values yet (not enough history).'),
    onError: (e) => setPreview(isFailure(e) ? e.message : 'Not a valid formula.'),
  })
  const items = f.data?.formulas ?? []
  const add = () => {
    const name = draft.name.trim() || draft.expr.trim().slice(0, 30)
    save.mutate([...items.filter((x) => x.id !== draft.id), { ...draft, id: draft.id || '', name }], {
      onSuccess: (d) => { const made = d.formulas.find((x) => x.name === name); if (made && !shown.includes(made.id)) setShown([...shown, made.id]); setDraft({ id: '', name: '', expr: '', pane: 'own' }); setPreview(null) },
      onError: (e) => setPreview(isFailure(e) ? e.message : 'Not saved.'),
    })
  }
  return (
    <Popover align="right" width={360} trigger={({ toggle, open }) => (
      <Button icon={<Sigma className="h-3.5 w-3.5" />} onClick={toggle} aria-expanded={open} title="Your own indicators as formulas" className="max-sm:px-2.5">
        <span className="max-sm:hidden">Formulas</span>{shown.length ? ` · ${shown.filter((id) => items.some((x) => x.id === id)).length}` : ''}
      </Button>)}>
      {() => (
        <div className="space-y-2 p-2.5 text-xs">
          {items.length > 0 && <ul className="space-y-0.5">{items.map((x) => (
            <li key={x.id} className="flex items-center gap-1.5 rounded px-1 py-0.5 hover:bg-raised">
              <input type="checkbox" aria-label={`Show ${x.name}`} checked={shown.includes(x.id)} onChange={(e) => setShown(e.target.checked ? [...shown, x.id] : shown.filter((i) => i !== x.id))} />
              <button type="button" className="min-w-0 flex-1 truncate text-left" title={x.expr} onClick={() => { setDraft(x); setPreview(null) }}>{x.name} <span className="text-muted">· {x.pane === 'price' ? 'on the price' : 'own pane'}</span></button>
              <IconButton label={`Delete ${x.name}`} onClick={() => save.mutate(items.filter((y) => y.id !== x.id))}><Trash2 className="h-3.5 w-3.5" /></IconButton>
            </li>))}</ul>}
          <div className="space-y-1.5 border-t border-line pt-2">
            <input aria-label="Formula name" className="input h-8 w-full px-2" placeholder="Name, e.g. Distance from 50-day in ATRs" maxLength={40} value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
            <textarea aria-label="Formula" className="input h-16 w-full p-2 font-mono text-[12px]" placeholder="(close - sma(close, 50)) / atr(14)" maxLength={300} value={draft.expr} onChange={(e) => { setDraft({ ...draft, expr: e.target.value }); setPreview(null) }} />
            <div className="flex items-center gap-2">
              <select aria-label="Where to draw it" className="input h-8 px-1" value={draft.pane} onChange={(e) => setDraft({ ...draft, pane: e.target.value as Formula['pane'] })}>
                <option value="own">Own pane</option><option value="price">On the price</option></select>
              <Button size="sm" variant="ghost" disabled={!draft.expr.trim()} loading={check.isPending} onClick={() => check.mutate(draft.expr)}>Check</Button>
              <Button size="sm" variant="primary" disabled={!draft.expr.trim()} loading={save.isPending} onClick={add}>{draft.id ? 'Update' : 'Save'}</Button>
            </div>
            {preview && <p className="text-2xs text-muted">{preview}</p>}
          </div>
          <details className="text-2xs text-muted"><summary className="cursor-pointer">Functions and fields</summary>
            <p className="mt-1">Fields: open, high, low, close, volume. Operators + − × ÷ and ** with a number.</p>
            <ul className="mt-1 space-y-0.5">{(f.data?.functions ?? []).map((x) => <li key={x.name}><code>{x.name}</code>: {x.help}</li>)}</ul>
            <p className="mt-1">Saved formulas are also scan fields under "Your formulas".</p>
          </details>
        </div>
      )}
    </Popover>
  )
}
