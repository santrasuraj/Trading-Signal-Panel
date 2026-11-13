// Intraday backtest `/intraday-backtest`: an opening-range breakout, VWAP reclaim or gap fade / go with your settings
// on the stored 5-minute bars, sized by risk with MIS charges (ibt_svc.py). Short history: read the t-statistic.

import { useMutation } from '@tanstack/react-query'
import { Download, FlaskConical } from 'lucide-react'
import { fetchJson, isFailure } from '@/api/client'
import { LinesChart } from '@/components/charts/LinesChart'
import { KpiStrip, KpiTile, PageHeader } from '@/components/domain'
import { Banner } from '@/components/feedback'
import { Button, Card, Field } from '@/components/ui'
import { downloadCsv } from '@/lib/exporting'
import { money, num, pct } from '@/lib/format'
import { useLocalStorage } from '@/lib/useLocalStorage'
import { cn } from '@/lib/csv'

interface Spec { template: 'orb' | 'vwap' | 'gap'; direction: 'long' | 'short' | 'both'; or_minutes: 15 | 30 | 60; stop: 'range' | 'atr'; atr_frac: number; target_r: number | null; cutoff_min: number; gap_pct: number; mode: 'fade' | 'go'; max_trades: number; risk_pct: number }
interface M { days: number; trades: number; trades_per_day?: number; return_pct?: number; after_tax_return_pct?: number; sharpe?: number | null; max_dd_pct?: number; win_rate?: number | null; avg_trade_pct?: number | null; profit_factor?: number | null; avg_day_pct?: number; t_stat?: number | null; significant?: boolean }
interface Res { metrics: M; exits: Record<string, number>; by_hour: { hour: string; trades: number; pnl: number }[]; curve: { date: string; equity: number }[]; trades: { date: string; symbol: string; side: string; entry: string; entry_px: number; exit_px: number; reason: string; qty: number; pnl: number }[]; note: string }

const DEFAULT: Spec = { template: 'orb', direction: 'both', or_minutes: 15, stop: 'range', atr_frac: 0.5, target_r: 2, cutoff_min: 780, gap_pct: 2, mode: 'fade', max_trades: 3, risk_pct: 0.5 }
const hhmm = (m: number) => `${String(Math.floor(m / 60)).padStart(2, '0')}:${String(m % 60).padStart(2, '0')}`

export default function IntradayBacktest() {
  const [spec, setSpec] = useLocalStorage<Spec>('qd.ibt.spec', DEFAULT)
  const set = <K extends keyof Spec>(k: K, v: Spec[K]) => setSpec({ ...spec, [k]: v })
  const run = useMutation({ mutationFn: () => fetchJson<Res>('/api/intraday-backtest', { method: 'POST', body: JSON.stringify(spec) }) })
  const r = run.data, m = r?.metrics
  return (
    <div>
      <PageHeader title="Intraday backtest" subtitle="Your settings on the stored 5-minute bars of the liquid F&O stocks, with MIS charges, slippage and the 15:00 / 15:15 square-off" />
      <Card className="mb-3" title="Setup">
        <div className="flex flex-wrap items-end gap-3">
          <Field label="Setup"><select className="input h-9 px-2" value={spec.template} onChange={(e) => set('template', e.target.value as Spec['template'])}>
            <option value="orb">Opening-range breakout</option><option value="vwap">VWAP reclaim</option><option value="gap">Gap fade / go</option></select></Field>
          {spec.template !== 'gap' && <Field label="Direction"><select className="input h-9 px-2" value={spec.direction} onChange={(e) => set('direction', e.target.value as Spec['direction'])}>
            <option value="both">Long and short</option><option value="long">Long only</option><option value="short">Short only</option></select></Field>}
          {spec.template === 'orb' && <>
            <Field label="Opening range"><select className="input h-9 px-2" value={spec.or_minutes} onChange={(e) => set('or_minutes', Number(e.target.value) as Spec['or_minutes'])}>{[15, 30, 60].map((n) => <option key={n} value={n}>First {n} minutes</option>)}</select></Field>
            <Field label="Stop"><select className="input h-9 px-2" value={spec.stop} onChange={(e) => set('stop', e.target.value as Spec['stop'])}><option value="range">Other side of the range</option><option value="atr">Fraction of daily ATR</option></select></Field>
            {spec.stop === 'atr' && <Field label="ATR fraction"><input className="input h-9 w-20 px-2 text-right" inputMode="decimal" value={spec.atr_frac} onChange={(e) => set('atr_frac', Number(e.target.value) || 0.5)} /></Field>}
          </>}
          {spec.template === 'gap' && <>
            <Field label="Gap at least %"><input className="input h-9 w-20 px-2 text-right" inputMode="decimal" value={spec.gap_pct} onChange={(e) => set('gap_pct', Number(e.target.value) || 2)} /></Field>
            <Field label="Trade"><select className="input h-9 px-2" value={spec.mode} onChange={(e) => set('mode', e.target.value as Spec['mode'])}><option value="fade">Fade (back to yesterday's close)</option><option value="go">Go (with the gap)</option></select></Field>
          </>}
          {!(spec.template === 'gap' && spec.mode === 'fade') && <Field label="Target" hint="R = the risk to the stop"><select className="input h-9 px-2" value={spec.target_r ?? ''} onChange={(e) => set('target_r', e.target.value === '' ? null : Number(e.target.value))}>
            <option value="">None (square-off)</option>{[1, 1.5, 2, 3].map((n) => <option key={n} value={n}>{n} R</option>)}</select></Field>}
          {spec.template !== 'gap' && <Field label="No new trades after"><select className="input h-9 px-2" value={spec.cutoff_min} onChange={(e) => set('cutoff_min', Number(e.target.value))}>{[600, 660, 720, 780, 840].map((n) => <option key={n} value={n}>{hhmm(n)}</option>)}</select></Field>}
          <Field label="Trades a day"><input className="input h-9 w-16 px-2 text-right" inputMode="numeric" value={spec.max_trades} onChange={(e) => set('max_trades', Math.max(1, Math.min(10, Number(e.target.value) || 3)))} /></Field>
          <Field label="Risk per trade %"><input className="input h-9 w-16 px-2 text-right" inputMode="decimal" value={spec.risk_pct} onChange={(e) => set('risk_pct', Number(e.target.value) || 0.5)} /></Field>
          <Button variant="primary" icon={<FlaskConical className="h-4 w-4" />} loading={run.isPending} onClick={() => run.mutate()}>Run</Button>
        </div>
        {run.isPending && <p className="mt-2 text-2xs text-muted">The first run builds every stored session (10-20 seconds); later runs are quicker.</p>}
        {run.error && <p className="mt-2 text-xs text-loss">{isFailure(run.error) ? `${run.error.message} ${run.error.hint ?? ''}` : 'Failed.'}</p>}
      </Card>
      {r && m && (
        <>
          <KpiStrip>
            <KpiTile label="Return after charges" value={pct(m.return_pct)} tone={(m.return_pct ?? 0) >= 0 ? 'text-profit' : 'text-loss'} sub={`after tax ${pct(m.after_tax_return_pct)}`} />
            <KpiTile label="Sessions · trades" value={`${m.days} · ${m.trades}`} sub={`${m.trades_per_day ?? '—'} a day`} />
            <KpiTile label="Win rate" value={m.win_rate != null ? `${m.win_rate.toFixed(0)}%` : '—'} sub={`profit factor ${m.profit_factor ?? '—'}`} />
            <KpiTile label="Average trade" value={pct(m.avg_trade_pct, { dp: 2 })} sub="after charges" />
            <KpiTile label="Deepest fall" value={pct(m.max_dd_pct)} tone="text-loss" />
            <KpiTile label="t-statistic" value={m.t_stat != null ? m.t_stat.toFixed(2) : '—'} sub={m.significant ? ((m.avg_day_pct ?? 0) > 0 ? 'an edge in this sample' : 'reliably losing') : 'not distinguishable from luck'} tone={m.significant ? ((m.avg_day_pct ?? 0) > 0 ? 'text-profit' : 'text-loss') : undefined} />
          </KpiStrip>
          {m.days < 120 && <div className="mt-3"><Banner tone="warn">{m.days} sessions is a short sample: a real edge needs more history. Keep the live service running and it grows each day.</Banner></div>}
          <div className="mt-3 grid gap-3 xl:grid-cols-3">
            <Card flush className="xl:col-span-2" title="Equity" subtitle={`Exits: ${Object.entries(r.exits).map(([k, v]) => `${v} ${k}`).join(' · ')}`}>
              <LinesChart t={r.curve.map((x) => x.date)} height={240} lines={[{ id: 'eq', label: 'Equity', v: r.curve.map((x) => x.equity), color: 'accent', width: 2, format: (v) => money(v) }]} />
            </Card>
            <Card flush title="By hour of entry">
              <table className="w-full text-[13px]"><tbody className="divide-y divide-line">{r.by_hour.map((h) => (
                <tr key={h.hour}><td className="px-4 py-1.5">{h.hour}</td><td className="num px-2 text-right text-muted">{h.trades}</td><td className={cn('num px-4 text-right', h.pnl >= 0 ? 'text-profit' : 'text-loss')}>{money(h.pnl, { signed: true })}</td></tr>))}</tbody></table>
            </Card>
          </div>
          <Card flush className="mt-3" title="Trades (latest 300)" right={<Button size="sm" variant="ghost" icon={<Download className="h-3.5 w-3.5" />} onClick={() => downloadCsv('intraday-backtest.csv', r.trades)}>CSV</Button>}>
            <div className="max-h-[420px] overflow-auto"><table className="w-full text-[13px]"><tbody className="divide-y divide-line">{r.trades.map((t, i) => (
              <tr key={i}><td className="num px-4 py-1 text-muted">{t.date} {t.entry}</td><td className="px-2 font-semibold">{t.symbol}</td><td className={cn('px-2', t.side === 'LONG' ? 'text-profit' : 'text-loss')}>{t.side}</td>
                <td className="num px-2 text-right">{num(t.entry_px, 2)} → {num(t.exit_px, 2)}</td><td className="px-2 text-muted">{t.reason}</td><td className={cn('num px-4 text-right', t.pnl >= 0 ? 'text-profit' : 'text-loss')}>{money(t.pnl, { signed: true })}</td></tr>))}</tbody></table></div>
          </Card>
          <p className="mt-3 text-2xs text-faint">{r.note}</p>
        </>
      )}
    </div>
  )
}
