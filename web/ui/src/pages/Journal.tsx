// Trade journal `/journal`: every trade (real fills, practice account, replays) with your notes, and what works for
// you: by setup, mistake, hour, weekday, holding time, plus how far trades went against / for you (MAE / MFE).
// web/api/services/journal_svc.py

import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { NotebookPen, Star } from 'lucide-react'
import { fetchJson, isFailure } from '@/api/client'
import { KpiStrip, KpiTile, PageHeader } from '@/components/domain'
import { EmptyState, ErrorState, SkeletonKpis } from '@/components/feedback'
import { Button, Card, Drawer, Segmented } from '@/components/ui'
import { money, num, pct } from '@/lib/format'
import { cn } from '@/lib/csv'

type Source = 'all' | 'real' | 'practice' | 'replay'
interface JTrade {
  id: string; source: 'real' | 'practice' | 'replay'; symbol: string; side: 'LONG' | 'SHORT'; qty: number; entry: number; exit: number
  opened: string | null; closed: string | null; pnl: number; charges: number | null; reason: string; tf: string | null
  hold_days: number | null; ret_pct: number | null; mae_pct: number | null; mfe_pct: number | null
  setup: string; tags: string[]; mistakes: string[]; notes: string; rating: number | null; has_image: boolean
}
interface Summary { key?: string; trades: number; win_rate?: number; total?: number; avg_win?: number | null; avg_loss?: number | null; expectancy?: number; profit_factor?: number | null; best?: number; worst?: number }
interface JStats {
  overall: Summary; by_source: Summary[]; by_setup: Summary[]; by_tag: Summary[]; by_mistake: Summary[]; by_hour: Summary[]; by_weekday: Summary[]; by_hold: Summary[]; by_side: Summary[]
  excursion: { winners_mae_pct: number | null; losers_mae_pct: number | null; winners_worst_mae_pct: number | null; kept_of_best_pct: number | null; with_bars: number }
}
interface JournalResponse { trades: JTrade[]; stats: JStats; setups: string[]; tags: string[]; mistakes: string[]; counts: Record<string, number>; note: string }

const when = (s: string | null) => (s ? s.replace('T', ' ').slice(0, 16) : '—')

function Breakdown({ title, rows, subtitle }: { title: string; rows: Summary[]; subtitle?: string }) {
  if (!rows.length) return null
  const max = Math.max(...rows.map((r) => Math.abs(r.total ?? 0)), 1)
  return (
    <Card flush title={title} subtitle={subtitle}>
      <table className="w-full text-[13px]">
        <thead className="text-2xs text-muted"><tr className="text-left"><th className="px-4 py-1.5" /><th className="px-2 text-right">Trades</th><th className="px-2 text-right">Win %</th><th className="px-2 text-right">Avg trade</th><th className="px-4">Total</th></tr></thead>
        <tbody className="divide-y divide-line">{rows.map((r) => (
          <tr key={r.key}>
            <td className="max-w-[180px] truncate px-4 py-1.5">{r.key}</td>
            <td className="num px-2 text-right">{r.trades}</td>
            <td className="num px-2 text-right">{r.win_rate != null ? `${r.win_rate.toFixed(0)}%` : '—'}</td>
            <td className={cn('num px-2 text-right', (r.expectancy ?? 0) >= 0 ? 'text-profit' : 'text-loss')}>{money(r.expectancy, { signed: true })}</td>
            <td className="px-4"><div className="flex items-center gap-2"><div className="h-1.5 w-20 overflow-hidden rounded bg-raised"><div className={cn('h-full', (r.total ?? 0) >= 0 ? 'bg-profit' : 'bg-loss')} style={{ width: `${(Math.abs(r.total ?? 0) / max) * 100}%` }} /></div><span className={cn('num', (r.total ?? 0) >= 0 ? 'text-profit' : 'text-loss')}>{money(r.total, { signed: true })}</span></div></td>
          </tr>))}</tbody>
      </table>
    </Card>
  )
}

async function shrink(file: File): Promise<string> {
  const url = URL.createObjectURL(file)
  try {
    const img = await new Promise<HTMLImageElement>((ok, bad) => { const i = new Image(); i.onload = () => ok(i); i.onerror = bad; i.src = url })
    const k = Math.min(1, 1200 / Math.max(img.width, img.height))
    const c = document.createElement('canvas')
    c.width = Math.round(img.width * k); c.height = Math.round(img.height * k)
    c.getContext('2d')!.drawImage(img, 0, 0, c.width, c.height)
    return c.toDataURL('image/jpeg', 0.75)
  } finally { URL.revokeObjectURL(url) }
}

function Editor({ t, d, onClose }: { t: JTrade; d: JournalResponse; onClose: () => void }) {
  const qc = useQueryClient()
  const [setup, setSetup] = useState(t.setup)
  const [tags, setTags] = useState(t.tags.join(', '))
  const [mistakes, setMistakes] = useState<string[]>(t.mistakes)
  const [notes, setNotes] = useState(t.notes)
  const [rating, setRating] = useState<number>(t.rating ?? 0)
  const [image, setImage] = useState<string | null | undefined>(undefined)
  const img = useQuery({ queryKey: ['journal-image', t.id], queryFn: () => fetchJson<{ image: string | null }>(`/api/journal/${t.id}/image`), enabled: t.has_image })
  const save = useMutation({
    mutationFn: () => fetchJson(`/api/journal/${t.id}`, { method: 'PUT', body: JSON.stringify({ setup, tags: tags.split(',').map((x) => x.trim()).filter(Boolean).slice(0, 12), mistakes, notes, rating, ...(image !== undefined ? { image } : {}) }) }),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ['journal'] }); void qc.invalidateQueries({ queryKey: ['journal-image', t.id] }); onClose() },
  })
  const shown = image !== undefined ? image : img.data?.image
  return (
    <Drawer open onClose={onClose} title={`${t.symbol} · ${t.side === 'LONG' ? 'long' : 'short'} ${t.qty} · ${t.source}`} subtitle={`${when(t.opened)} → ${when(t.closed)} · ${money(t.pnl, { signed: true })}`}
      footer={<><Button variant="ghost" onClick={onClose}>Cancel</Button><Button variant="primary" loading={save.isPending} onClick={() => save.mutate()}>Save</Button></>}>
      <div className="space-y-3 text-[13px]">
        <label className="block text-xs text-muted">Setup<input list="journal-setups" className="input mt-1 block h-9 w-full px-2" value={setup} maxLength={60} placeholder="e.g. Breakout, Pullback to 20-day" onChange={(e) => setSetup(e.target.value)} /></label>
        <datalist id="journal-setups">{d.setups.map((s) => <option key={s} value={s} />)}</datalist>
        <label className="block text-xs text-muted">Tags (comma-separated)<input className="input mt-1 block h-9 w-full px-2" value={tags} placeholder="e.g. results week, gap" onChange={(e) => setTags(e.target.value)} /></label>
        <div>
          <div className="text-xs text-muted">Mistakes</div>
          <div className="mt-1 flex flex-wrap gap-1.5">{d.mistakes.map((m) => (
            <button key={m} type="button" onClick={() => setMistakes((xs) => (xs.includes(m) ? xs.filter((x) => x !== m) : [...xs, m]))}
              className={cn('rounded border px-2 py-0.5 text-xs', mistakes.includes(m) ? 'border-loss bg-loss/10 text-loss' : 'border-line text-muted')}>{m}</button>))}</div>
        </div>
        <div className="flex items-center gap-1 text-xs text-muted">How well did you follow your plan?
          {[1, 2, 3, 4, 5].map((k) => <button key={k} type="button" aria-label={`${k} stars`} onClick={() => setRating(k === rating ? 0 : k)}><Star className={cn('h-4 w-4', k <= rating ? 'fill-warn text-warn' : 'text-faint')} /></button>)}</div>
        <label className="block text-xs text-muted">Notes<textarea className="input mt-1 block h-28 w-full p-2" value={notes} maxLength={4000} placeholder="Why you took it, what you saw, what you'd do differently" onChange={(e) => setNotes(e.target.value)} /></label>
        <div className="text-xs text-muted">Chart screenshot
          <input type="file" accept="image/*" className="mt-1 block text-xs" onChange={async (e) => { const f = e.target.files?.[0]; if (f) setImage(await shrink(f)) }} />
          {shown && <div className="mt-2"><img src={shown} alt="Chart screenshot" className="max-h-64 rounded border border-line" /><button type="button" className="link mt-1 text-2xs" onClick={() => setImage(null)}>Remove</button></div>}
        </div>
        {save.error && <p className="text-xs text-loss">{isFailure(save.error) ? save.error.message : 'Not saved.'}</p>}
      </div>
    </Drawer>
  )
}

export default function Journal() {
  const [source, setSource] = useState<Source>('all')
  const q = useQuery({ queryKey: ['journal', source], queryFn: () => fetchJson<JournalResponse>(`/api/journal?source=${source}`), staleTime: 30_000 })
  const [edit, setEdit] = useState<string | null>(null)
  const d = q.data
  const s = d?.stats
  const editing = useMemo(() => d?.trades.find((t) => t.id === edit) ?? null, [d, edit])
  const o = s?.overall
  return (
    <div>
      <PageHeader title="Trade journal" subtitle={d ? `${d.counts.real} real · ${d.counts.practice} practice · ${d.counts.replay} replay trades` : 'Every trade, your notes, and what works for you'}
        right={<Segmented<Source> ariaLabel="Source" value={source} onChange={setSource} items={[{ id: 'all', label: 'All' }, { id: 'real', label: 'Real' }, { id: 'practice', label: 'Practice' }, { id: 'replay', label: 'Replay' }]} />} />
      {q.error ? <ErrorState error={q.error} onRetry={() => q.refetch()} /> : !d || !s || !o ? <SkeletonKpis n={6} /> : !o.trades ? (
        <EmptyState icon={<NotebookPen />} title="No trades yet" action={<span className="flex gap-3"><Link className="text-accent" to="/replay">Practise on Replay</Link><Link className="text-accent" to="/sim">Open the practice account</Link></span>}>
          Trades appear here from your real FYERS fills (recorded by Quant Desk), the practice account and finished replays.
        </EmptyState>
      ) : (
        <>
          <KpiStrip>
            <KpiTile label="Trades" value={o.trades} sub={`win rate ${o.win_rate?.toFixed(0)}%`} />
            <KpiTile label="Total after charges" value={money(o.total, { signed: true })} tone={(o.total ?? 0) >= 0 ? 'text-profit' : 'text-loss'} />
            <KpiTile label="Average trade" value={money(o.expectancy, { signed: true })} sub="expectancy" tone={(o.expectancy ?? 0) >= 0 ? 'text-profit' : 'text-loss'} />
            <KpiTile label="Average win / loss" value={<span className="text-base">{money(o.avg_win)} / {money(o.avg_loss)}</span>} />
            <KpiTile label="Profit factor" value={o.profit_factor != null ? o.profit_factor.toFixed(2) : '—'} sub="won ÷ lost" />
            <KpiTile label="Winners dipped" value={s.excursion.winners_mae_pct != null ? pct(s.excursion.winners_mae_pct) : '—'} sub={s.excursion.winners_worst_mae_pct != null ? `worst ${pct(s.excursion.winners_worst_mae_pct)}: room your stop needs` : 'needs price bars'} />
            <KpiTile label="Kept of the best move" value={s.excursion.kept_of_best_pct != null ? `${s.excursion.kept_of_best_pct.toFixed(0)}%` : '—'} sub="winners: result ÷ best price" />
          </KpiStrip>
          <div className="mt-3 grid gap-3 xl:grid-cols-2">
            <Breakdown title="By setup" subtitle="Tag each trade's setup to see which ones pay" rows={s.by_setup} />
            <Breakdown title="What your mistakes cost" rows={s.by_mistake} />
            <Breakdown title="By hour of entry" rows={s.by_hour} />
            <Breakdown title="By weekday" rows={s.by_weekday} />
            <Breakdown title="By holding time" rows={s.by_hold} />
            <Breakdown title="By source" rows={s.by_source} />
          </div>
          <Card flush className="mt-3" title="Trades" subtitle="Click a trade to add its setup, mistakes, notes and a screenshot">
            <div className="overflow-x-auto"><table className="w-full text-[13px]">
              <thead className="text-2xs text-muted"><tr className="text-left"><th className="px-4 py-1.5">Closed</th><th className="px-2">Stock</th><th className="px-2">Source</th><th className="px-2 text-right">Qty</th><th className="px-2 text-right">Entry → exit</th><th className="px-2 text-right">P&L</th><th className="px-2 text-right">Against / for</th><th className="px-4">Setup · notes</th></tr></thead>
              <tbody className="divide-y divide-line">{d.trades.map((t) => (
                <tr key={t.id} className="cursor-pointer hover:bg-raised/60" onClick={() => setEdit(t.id)}>
                  <td className="num px-4 py-1.5 text-muted">{when(t.closed)}</td>
                  <td className="px-2 font-semibold">{t.symbol} <span className="text-2xs font-normal text-muted">{t.side === 'SHORT' ? 'short' : ''}</span></td>
                  <td className="px-2 text-muted">{t.source}{t.tf ? ` ${t.tf}` : ''}</td>
                  <td className="num px-2 text-right">{t.qty}</td>
                  <td className="num px-2 text-right">{num(t.entry, 2)} → {num(t.exit, 2)}</td>
                  <td className={cn('num px-2 text-right', t.pnl >= 0 ? 'text-profit' : 'text-loss')}>{money(t.pnl, { signed: true })}</td>
                  <td className="num px-2 text-right text-2xs">{t.mae_pct != null ? <><span className="text-loss">{pct(t.mae_pct)}</span> / <span className="text-profit">{pct(t.mfe_pct)}</span></> : '—'}</td>
                  <td className="max-w-[280px] truncate px-4 text-muted">{t.setup && <b className="text-fg">{t.setup}</b>}{t.mistakes.length > 0 && <span className="ml-1 text-loss">· {t.mistakes.length} mistake{t.mistakes.length > 1 ? 's' : ''}</span>}{t.notes && ` · ${t.notes}`}{!t.setup && !t.notes && !t.mistakes.length && <span className="text-faint">add notes</span>}</td>
                </tr>))}</tbody>
            </table></div>
          </Card>
          <p className="mt-3 text-2xs text-faint">{d.note} Against / for: how far the price went against the trade and in its favour while it was open (daily bars, or 5-minute bars for a same-day trade).</p>
        </>
      )}
      {editing && d && <Editor t={editing} d={d} onClose={() => setEdit(null)} />}
    </div>
  )
}
