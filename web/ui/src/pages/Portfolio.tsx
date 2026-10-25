// Portfolio `/portfolio` (spec 3.7): holdings health, P&L, alerts, sector weights, editor drawer, Fyers import.

import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { AlertOctagon, AlertTriangle, CheckCircle2, Download, Pencil, Plus, RotateCw, Trash2 } from 'lucide-react'
import { useHoldings, useImportFyers, useSaveHoldings, useStatus, useSymbols } from '@/api/hooks'
import { isFailure } from '@/api/client'
import type { HoldingInput, HoldingRow, HoldingsResponse } from '@/api/types'
import { LevelPill, ResultsChip } from '@/components/badges'
import { WeightBars } from '@/components/charts/svg'
import { DataTable, SymbolCell, type Col } from '@/components/DataTable'
import { AsOfLine, KpiStrip, KpiTile, PageHeader } from '@/components/domain'
import { Banner, EmptyState, ErrorState, RefreshFailed, SkeletonKpis, SkeletonRows } from '@/components/feedback'
import { useRunScan } from '@/components/layout/ScanButton'
import { Money, Pct, Price, Qty } from '@/components/num'
import { Button, Card, Dialog, Drawer, IconButton, Segmented } from '@/components/ui'
import { useToast } from '@/components/toast'
import { cn } from '@/lib/csv'
import { date, daysBetween, pct, todayIST } from '@/lib/format'

const distPct = (target: number | null, price: number | null) => (target != null && price ? (target / price - 1) * 100 : null)

function columns(): Col<HoldingRow>[] {
  const today = todayIST()
  return [
    { id: 'sym', header: 'Symbol', value: (r) => r.symbol, cell: (r) => <SymbolCell symbol={r.symbol} company={r.company} />, sticky: true, minWidth: 160, mobile: 'primary', search: (r) => `${r.symbol} ${r.company ?? ''}`, csvExtra: { label: 'Company', value: (r) => r.company } },
    { id: 'lvl', header: 'Level', value: (r) => ['danger', 'watch', 'unknown', 'ok', 'good'].indexOf(r.level), cell: (r) => <LevelPill level={r.level} />, mobile: 'secondary', label: 'Level' },
    { id: 'qty', header: 'Qty', align: 'right', value: (r) => r.qty, cell: (r) => <Qty v={r.qty} /> },
    { id: 'avg', header: 'Avg ₹', align: 'right', value: (r) => r.buy_price, cell: (r) => <Price v={r.buy_price} /> },
    { id: 'ltp', header: 'LTP ₹', align: 'right', value: (r) => r.price, cell: (r) => <Price v={r.price} />, mobile: 'value' },
    { id: 'day', header: 'Day', title: "Change on the last scan's price day", align: 'right', value: (r) => r.change_pct, cell: (r) => <Pct v={r.change_pct} dp={2} /> },
    { id: 'pnl', header: 'P&L ₹', align: 'right', value: (r) => r.pnl_amount, cell: (r) => <Money v={r.pnl_amount} signed color />, mobile: 'secondary', label: 'P&L' },
    { id: 'pnlp', header: 'P&L %', align: 'right', value: (r) => r.pnl_pct, cell: (r) => <Pct v={r.pnl_pct} />, mobile: 'change' },
    { id: 'stop', header: 'Stop ₹ (dist)', align: 'right', value: (r) => r.stop_price, cell: (r) => <span className="num"><Price v={r.stop_price} /> <span className="text-2xs text-faint">{pct(distPct(r.stop_price, r.price))}</span></span> },
    { id: 'tgt', header: 'Target ₹ (dist)', align: 'right', value: (r) => r.target_price, cell: (r) => <span className="num"><Price v={r.target_price} /> <span className="text-2xs text-faint">{pct(distPct(r.target_price, r.price))}</span></span> },
    { id: 'mom', header: 'Mom #', title: 'Momentum rank in the universe', align: 'right', value: (r) => r.momentum_rank, cell: (r) => <span className="num">{r.momentum_rank ?? '—'}</span> },
    { id: 'rs', header: 'RS', align: 'right', value: (r) => r.rs, cell: (r) => <span className="num">{r.rs ?? '—'}</span> },
    { id: 'res', header: 'Results', value: (r) => r.results_on, cell: (r) => <ResultsChip on={r.results_on} inDays={r.results_on ? daysBetween(today, r.results_on) : null} compact /> },
    { id: 'models', header: 'In models', value: (r) => r.in_models.join(' '), cell: (r) => <span className="text-xs text-muted">{r.in_models.join(', ') || '—'}</span>, defaultHidden: true },
  ]
}

function AlertsList({ rows }: { rows: HoldingRow[] }) {
  const items = rows.filter((r) => r.alerts.length).sort((a, b) => ['danger', 'watch', 'unknown', 'good', 'ok'].indexOf(a.level) - ['danger', 'watch', 'unknown', 'good', 'ok'].indexOf(b.level))
  if (!items.length) return null
  return (
    <Card title="Alerts" subtitle="From the last scan (rows edited since are re-checked on its prices); colour by level" flush>
      <ul className="divide-y divide-line">
        {items.map((r) => {
          const Icon = r.level === 'danger' ? AlertOctagon : r.level === 'good' ? CheckCircle2 : AlertTriangle
          const cls = r.level === 'danger' ? 'text-loss' : r.level === 'good' ? 'text-profit' : r.level === 'watch' ? 'text-warn' : 'text-muted'
          return (
            <li key={r.symbol} className="flex items-start gap-3 px-4 py-2.5 text-[13px]">
              <Icon className={cn('mt-0.5 h-4 w-4 shrink-0', cls)} />
              <span className="w-24 shrink-0 font-semibold">{r.symbol}</span>
              <span className="text-muted">{r.alerts.join(' · ')}</span>
            </li>
          )
        })}
      </ul>
    </Card>
  )
}

type Draft = { symbol: string; qty: string; buy_price: string; buy_date: string; stop_loss_pct: string; target_pct: string }
const toDraft = (h: HoldingInput): Draft => ({
  symbol: h.symbol, qty: h.qty?.toString() ?? '', buy_price: h.buy_price?.toString() ?? '', buy_date: h.buy_date ?? '',
  stop_loss_pct: h.stop_loss_pct?.toString() ?? '', target_pct: h.target_pct?.toString() ?? '',
})
const numOrNull = (s: string) => (s.trim() === '' ? null : Number(s))
const fromDraft = (d: Draft): HoldingInput => ({
  symbol: d.symbol.trim().toUpperCase(), qty: numOrNull(d.qty), buy_price: numOrNull(d.buy_price), buy_date: d.buy_date || null,
  stop_loss_pct: numOrNull(d.stop_loss_pct), target_pct: numOrNull(d.target_pct),
})

function Editor({ open, onClose, h, loggedIn }: { open: boolean; onClose: () => void; h: HoldingsResponse; loggedIn: boolean }) {
  const [rows, setRows] = useState<Draft[]>(() => h.inputs.map(toDraft))
  const syms = useSymbols()
  const known = useMemo(() => new Set(syms.data?.symbols.map((s) => s.symbol) ?? []), [syms.data])
  const save = useSaveHoldings()
  const imp = useImportFyers()
  const toast = useToast()
  const [preview, setPreview] = useState<HoldingInput[] | null>(null)
  const [mode, setMode] = useState<'replace' | 'merge'>('merge')
  const today = todayIST()
  // A row the user just added and hasn't typed in yet shows no errors (no red 'Required' before typing) and is
  // left out when saving.
  const isBlank = (r: Draft) => !r.symbol.trim() && !r.qty.trim() && !r.buy_price.trim() && !r.buy_date && !r.stop_loss_pct.trim() && !r.target_pct.trim()
  const errors = rows.map((r) => {
    const e: Partial<Record<keyof Draft, string>> = {}
    if (isBlank(r)) return e
    const s = r.symbol.trim().toUpperCase()
    if (!s) e.symbol = 'Required'
    else if (known.size && !known.has(s)) e.symbol = 'Unknown symbol'
    const n = (v: string) => Number(v.trim())
    if (r.qty.trim() && (!Number.isInteger(n(r.qty)) || n(r.qty) <= 0)) e.qty = 'Whole shares, > 0'
    if (r.buy_price.trim() && (Number.isNaN(n(r.buy_price)) || n(r.buy_price) <= 0)) e.buy_price = 'Must be > 0'
    if (r.buy_date && r.buy_date > today) e.buy_date = 'In the future'
    if (r.stop_loss_pct.trim() && (Number.isNaN(n(r.stop_loss_pct)) || n(r.stop_loss_pct) < 0 || n(r.stop_loss_pct) > 100)) e.stop_loss_pct = '0 to 100'
    if (r.target_pct.trim() && (Number.isNaN(n(r.target_pct)) || n(r.target_pct) < 0)) e.target_pct = 'Must be ≥ 0'
    return e
  })
  const blocking = errors.some((e) => e.qty || e.buy_price || e.buy_date || e.stop_loss_pct || e.target_pct || e.symbol === 'Required')
  const upd = (i: number, k: keyof Draft, v: string) => setRows((rs) => rs.map((r, j) => (j === i ? { ...r, [k]: v } : r)))

  const doImport = () => imp.mutate(undefined, { onSuccess: (r) => setPreview(r.rows) })
  const applyImport = () => {
    if (!preview) return
    if (mode === 'replace') setRows(preview.map(toDraft))
    else {
      const bySym = new Map(rows.map((r) => [r.symbol.toUpperCase(), r]))
      for (const p of preview) bySym.set(p.symbol, { ...(bySym.get(p.symbol) ?? toDraft(p)), qty: p.qty?.toString() ?? '', buy_price: p.buy_price?.toString() ?? '' })
      setRows([...bySym.values()])
    }
    setPreview(null)
  }
  const doSave = () =>
    save.mutate(rows.filter((r) => !isBlank(r)).map(fromDraft), {
      onSuccess: (r) => {
        toast({ tone: r.rejected.length ? 'bad' : 'good', title: `Saved ${r.saved} holding${r.saved === 1 ? '' : 's'}`, detail: [r.rejected.length ? `${r.rejected.length} rejected: ${r.rejected.map((x) => `${x.symbol} (${x.reason})`).join(', ')}` : '', r.unknown_symbols.length ? `Not in the scan universe: ${r.unknown_symbols.join(', ')}` : '', 'Alerts update after a re-check.'].filter(Boolean).join(' ') })
        onClose()
      },
    })

  const cell = 'input h-8 w-full px-2 text-[13px]'
  return (
    <Drawer
      open={open}
      onClose={onClose}
      title="Edit holdings"
      subtitle="Saved to holdings.csv in this checkout. Stops and targets default to the config values when blank."
      width={720}
      footer={
        <>
          <Button variant="ghost" icon={<Download className="h-4 w-4" />} disabled={!loggedIn} title={loggedIn ? 'Preview your Fyers holdings' : 'Log in to Fyers first'} loading={imp.isPending} onClick={doImport} className="mr-auto">Import from Fyers</Button>
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button variant="primary" loading={save.isPending} disabled={blocking} onClick={doSave}>Save</Button>
        </>
      }
    >
      {!loggedIn && <p className="mb-3 text-xs text-muted">Import from Fyers needs today's Fyers login (top bar › Fyers).</p>}
      {(imp.error || save.error) && <div className="mb-3"><Banner tone="danger">{isFailure(imp.error ?? save.error) ? (imp.error ?? save.error as Error).message : 'Request failed'}{isFailure(imp.error) && imp.error.hint ? ` ${imp.error.hint}` : ''}</Banner></div>}
      <datalist id="qd-symbols">{syms.data?.symbols.filter((s) => s.kind !== 'index').map((s) => <option key={s.symbol} value={s.symbol}>{s.company ?? ''}</option>)}</datalist>
      <div className="scroll-x">
        <table className="w-full min-w-[620px] border-separate border-spacing-y-1 text-[13px]">
          <thead>
            <tr className="text-left text-2xs font-semibold uppercase tracking-[0.04em] text-muted">
              <th className="pr-2">Symbol</th><th className="pr-2 text-right">Qty</th><th className="pr-2 text-right">Buy ₹</th>
              <th className="pl-3 pr-2" title="Needed to adjust for splits/bonuses after you bought">Buy date</th><th className="pr-2 text-right">Stop %</th><th className="pr-2 text-right">Target %</th><th />
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i} className="align-top">
                <td className="pr-2"><input list="qd-symbols" aria-label="Symbol" className={cn(cell, 'w-[120px] uppercase', errors[i].symbol && 'border-loss/70')} value={r.symbol} onChange={(e) => upd(i, 'symbol', e.target.value.toUpperCase())} />{errors[i].symbol && <div className={cn('mt-0.5 text-2xs', errors[i].symbol === 'Required' ? 'text-loss' : 'text-warn')}>{errors[i].symbol}</div>}</td>
                <td className="pr-2"><input inputMode="numeric" aria-label="Quantity" className={cn(cell, 'num w-[80px] text-right', errors[i].qty && 'border-loss/70')} value={r.qty} onChange={(e) => upd(i, 'qty', e.target.value)} />{errors[i].qty && <div className="mt-0.5 text-2xs text-loss">{errors[i].qty}</div>}</td>
                <td className="pr-2"><input inputMode="decimal" aria-label="Buy price" className={cn(cell, 'num w-[96px] text-right', errors[i].buy_price && 'border-loss/70')} value={r.buy_price} onChange={(e) => upd(i, 'buy_price', e.target.value)} />{errors[i].buy_price && <div className="mt-0.5 text-2xs text-loss">{errors[i].buy_price}</div>}</td>
                <td className="pl-3 pr-2"><input type="date" max={today} aria-label="Buy date" className={cn(cell, 'num w-[140px]', errors[i].buy_date && 'border-loss/70')} value={r.buy_date} onChange={(e) => upd(i, 'buy_date', e.target.value)} />{errors[i].buy_date && <div className="mt-0.5 text-2xs text-loss">{errors[i].buy_date}</div>}</td>
                <td className="pr-2"><input inputMode="decimal" aria-label="Stop-loss percent" placeholder={String(h.defaults.stop_loss_pct)} className={cn(cell, 'num w-[64px] text-right', errors[i].stop_loss_pct && 'border-loss/70')} value={r.stop_loss_pct} onChange={(e) => upd(i, 'stop_loss_pct', e.target.value)} />{errors[i].stop_loss_pct && <div className="mt-0.5 text-2xs text-loss">{errors[i].stop_loss_pct}</div>}</td>
                <td className="pr-2"><input inputMode="decimal" aria-label="Target percent" placeholder={String(h.defaults.target_pct)} className={cn(cell, 'num w-[64px] text-right', errors[i].target_pct && 'border-loss/70')} value={r.target_pct} onChange={(e) => upd(i, 'target_pct', e.target.value)} />{errors[i].target_pct && <div className="mt-0.5 text-2xs text-loss">{errors[i].target_pct}</div>}</td>
                <td><IconButton size="sm" label="Remove row" onClick={() => setRows((rs) => rs.filter((_, j) => j !== i))}><Trash2 className="h-3.5 w-3.5" /></IconButton></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <Button size="sm" className="mt-2" icon={<Plus className="h-3.5 w-3.5" />} onClick={() => setRows((rs) => [...rs, { symbol: '', qty: '', buy_price: '', buy_date: '', stop_loss_pct: '', target_pct: '' }])}>Add row</Button>
      <p className="mt-4 text-2xs text-faint">The buy date lets the scan adjust your buy price for splits and bonuses that happened after you bought.</p>

      <Dialog open={preview != null} onClose={() => setPreview(null)} title={`Fyers holdings (${preview?.length ?? 0})`} footer={<><Button variant="ghost" onClick={() => setPreview(null)}>Cancel</Button><Button variant="primary" onClick={applyImport}>Use these rows</Button></>}>
        <div className="space-y-3 text-[13px]">
          <Segmented ariaLabel="Import mode" value={mode} onChange={setMode} items={[{ id: 'merge', label: 'Merge (update qty and price, keep the rest)' }, { id: 'replace', label: 'Replace all' }]} />
          <p className="text-xs text-muted">Fyers cost prices are already split/bonus adjusted; the buy date is unknown. Nothing is saved until you press Save.</p>
          <ul className="max-h-[260px] divide-y divide-line overflow-auto rounded-md border border-line">
            {preview?.map((p) => <li key={p.symbol} className="num flex justify-between px-3 py-1.5"><span className="font-semibold">{p.symbol}</span><span className="text-muted">{p.qty} @ {p.buy_price}</span></li>)}
          </ul>
        </div>
      </Dialog>
    </Drawer>
  )
}

export default function Portfolio() {
  const q = useHoldings()
  const { data: st } = useStatus()
  const { run, pending } = useRunScan()
  const [edit, setEdit] = useState(false)
  const nav = useNavigate()
  const cols = useMemo(columns, [])
  const h = q.data
  const t = h?.totals
  const running = !!st?.scan.running
  return (
    <div>
      <PageHeader
        title="Portfolio"
        subtitle={<>Your own holdings (holdings.csv): stop-loss, target, trend and results alerts from each scan · {h?.as_of ? <AsOfLine a={h.as_of} /> : 'no scan yet'}</>}
        right={h && <Button variant="primary" icon={<Pencil className="h-3.5 w-3.5" />} onClick={() => setEdit(true)}>Edit holdings</Button>}
      />
      {q.error && !h ? <div className="card"><ErrorState error={q.error} onRetry={() => void q.refetch()} /></div> : !h || !t ? (
        <div className="space-y-3"><SkeletonKpis n={7} /><div className="card"><SkeletonRows /></div></div>
      ) : h.inputs.length === 0 && h.rows.length === 0 ? (
        <div className="card">
          <EmptyState title="Add your holdings to get stop-loss, target, trend and results alerts" action={<Button variant="primary" icon={<Plus className="h-4 w-4" />} onClick={() => setEdit(true)}>Add holdings</Button>}>
            Enter what you own (or import it from Fyers). Every scan checks each holding against its stop and target, the 50 and 200-day averages, momentum rank and upcoming results.
          </EmptyState>
        </div>
      ) : (
        <div className="space-y-3">
          {q.error && <RefreshFailed error={q.error} onRetry={() => void q.refetch()} />}
          <KpiStrip min={120}>
            <KpiTile label="Invested" value={<Money compact v={t.invested} />} />
            <KpiTile label="Value" value={<Money compact v={t.value} />} />
            <KpiTile label="P&L" value={<Money compact signed v={t.pnl} />} tone={t.pnl == null ? undefined : t.pnl >= 0 ? 'text-profit' : 'text-loss'} sub={<Pct v={t.pnl_pct} />} />
            <KpiTile label={h.as_of ? `Day (${date(h.as_of.data_date, { year: false })})` : 'Day'} title="Move of the last scan's price day (not necessarily today)" value={<Money compact signed v={t.day_pnl} />} tone={t.day_pnl == null ? undefined : t.day_pnl >= 0 ? 'text-profit' : 'text-loss'} />
            <KpiTile label="Holdings" value={t.count} />
            <KpiTile label="Danger" value={t.danger} tone={t.danger ? 'text-loss' : 'text-muted'} />
            <KpiTile label="Watch" value={t.watch} tone={t.watch ? 'text-warn' : 'text-muted'} />
          </KpiStrip>
          {h.health_stale && (
            <Banner tone="warn" action={<Button size="sm" icon={<RotateCw className="h-3.5 w-3.5" />} loading={pending || running} onClick={() => run(false)}>Re-check now · no download · ~2 min</Button>}>
              Holdings changed after the last scan, so these alerts are out of date.
            </Banner>
          )}
          <AlertsList rows={h.rows} />
          <div className="grid gap-3 2xl:grid-cols-4">
            <Card title="Holdings" flush className="2xl:col-span-3">
              <DataTable id="holdings" data={h.rows} columns={cols} rowKey={(r) => r.symbol} onRowClick={(r) => nav(`/chart/${r.symbol}`)} exportName="holdings" columnChooser keyboard
                rowClassName={(r) => (r.level === 'danger' ? 'bg-loss/[0.04]' : undefined)}
                empty={<EmptyState compact title="Health appears after the next scan or re-check" />} />
            </Card>
            <Card title="Weight by sector">
              {h.by_industry.length ? <WeightBars items={h.by_industry.map((b) => ({ label: b.industry, value: b.weight_pct }))} /> : <p className="text-xs text-muted">Appears once holdings have prices.</p>}
            </Card>
          </div>
        </div>
      )}
      {h && edit && <Editor open={edit} onClose={() => setEdit(false)} h={h} loggedIn={!!st?.fyers.logged_in_today} />}
    </div>
  )
}
