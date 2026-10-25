// Screener `/screener` (spec 3.5): presets, filters in the URL, one DataTable with sparklines, CSV, column chooser.

import { useMemo } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useScreener, useSparklines } from '@/api/hooks'
import { isFailure } from '@/api/client'
import type { ScreenerPreset, ScreenerRow } from '@/api/types'
import { ResultsChip } from '@/components/badges'
import { Sparkline } from '@/components/charts/svg'
import { DataTable, SymbolCell, type Col } from '@/components/DataTable'
import { PageHeader } from '@/components/domain'
import { ErrorState, FeatureUnavailable, RefreshFailed, Skeleton, SkeletonRows } from '@/components/feedback'
import { Pct, Price } from '@/components/num'
import { Card, Chip, MenuCheck, Popover, Segmented, SelectButton, Switch } from '@/components/ui'
import { daysBetween, date, num, todayIST } from '@/lib/format'

const PRESETS: { id: ScreenerPreset; label: string; help: string }[] = [
  { id: 'momentum', label: 'Momentum', help: 'NSE momentum score (risk-adjusted 6 and 12-month return), above the 200-DMA' },
  { id: 'rs', label: 'Rel. strength', help: 'Relative strength 1-99 vs the whole list' },
  { id: 'near_high', label: 'Near 52w high', help: 'Closest to the 52-week high, in an uptrend' },
  { id: 'low_vol', label: 'Low vol', help: 'Steadiest stocks among the 150 most traded' },
  { id: 'volume', label: 'Vol spike', help: 'Volume at least 3× its 20-day average' },
  { id: 'uptrend', label: '>200-DMA', help: 'Above the 200-DMA with the 50-DMA above the 200-DMA' },
  { id: 'all', label: 'All', help: 'Every liquid stock' },
]

// the column that explains why a stock is in each preset is shown by default for that preset
const PRESET_COLUMN: Partial<Record<ScreenerPreset, string>> = { volume: 'vr', near_high: 'hi', low_vol: 'vol' }

function columns(spark: Record<string, (number | null)[]> | undefined, preset: ScreenerPreset): Col<ScreenerRow>[] {
  const today = todayIST()
  const show = PRESET_COLUMN[preset]
  return [
    { id: 'rank', header: '#', align: 'right', value: (r) => r.momentum_rank, cell: (r) => <span className="num text-muted">{r.momentum_rank ?? '—'}</span>, width: 48, title: 'Momentum rank' },
    {
      id: 'sym', header: 'Symbol', label: 'Symbol', value: (r) => r.symbol, sticky: true, minWidth: 180, mobile: 'primary',
      search: (r) => `${r.symbol} ${r.company ?? ''}`, csvExtra: { label: 'Company', value: (r) => r.company },
      cell: (r) => <SymbolCell symbol={r.symbol} company={r.company} extra={<>{r.you_hold && <Chip className="tint-accent h-4 px-1.5 text-[10px] text-accent">held</Chip>}{r.in_models.length > 0 && <span className="h-1.5 w-1.5 rounded-full bg-accent" title={`In model: ${r.in_models.join(', ')}`} />}</>} />,
    },
    { id: 'ind', header: 'Sector', value: (r) => r.industry, cell: (r) => <span className="block max-w-[150px] truncate text-muted 2xl:max-w-[240px]" title={r.industry ?? ''}>{r.industry ?? '—'}</span>, hideBelow: 960 },
    { id: 'price', header: 'Price ₹', align: 'right', value: (r) => r.price, cell: (r) => <Price v={r.price} />, mobile: 'value' },
    { id: 'd1', header: '1D', align: 'right', value: (r) => r.change_pct, cell: (r) => <Pct v={r.change_pct} dp={2} />, mobile: 'change' },
    { id: 'w1', header: '1W', align: 'right', value: (r) => r.ret_1w_pct, cell: (r) => <Pct v={r.ret_1w_pct} />, defaultHidden: true },
    { id: 'm1', header: '1M', align: 'right', value: (r) => r.ret_1m_pct, cell: (r) => <Pct v={r.ret_1m_pct} />, hideBelow: 1400 },
    { id: 'm3', header: '3M', align: 'right', value: (r) => r.ret_3m_pct, cell: (r) => <Pct v={r.ret_3m_pct} /> },
    { id: 'm6', header: '6M', align: 'right', value: (r) => r.ret_6m_pct, cell: (r) => <Pct v={r.ret_6m_pct} />, mobile: 'secondary', label: '6M' },
    { id: 'm12', header: '12M', align: 'right', value: (r) => r.ret_12m_pct, cell: (r) => <Pct v={r.ret_12m_pct} />, mobile: 'secondary', label: '12M' },
    { id: 'rs', header: 'RS', title: 'Relative strength 1-99', align: 'right', value: (r) => r.rs, cell: (r) => <span className="num">{num(r.rs, 0)}</span>, mobile: 'secondary', label: 'RS' },
    { id: 'score', header: 'Score', title: 'NSE momentum score', align: 'right', value: (r) => r.momentum_score, cell: (r) => <span className="num">{num(r.momentum_score, 2)}</span>, hideBelow: 1300 },
    { id: 'vol', header: 'Vol %', title: 'Annualised volatility (1 year)', align: 'right', value: (r) => r.vol_ann_pct, cell: (r) => <span className="num">{num(r.vol_ann_pct, 1)}</span>, hideBelow: preset === 'low_vol' ? undefined : 1400 },
    { id: 'hi', header: '52wH', title: 'Distance from the 52-week high', align: 'right', value: (r) => r.pct_from_52w_high, cell: (r) => <Pct v={r.pct_from_52w_high} color={false} />, hideBelow: preset === 'near_high' ? undefined : 1400 },
    { id: 'vr', header: 'Vol ×', title: 'Volume vs its 20-day average', align: 'right', value: (r) => r.vol_ratio, cell: (r) => <span className="num">{num(r.vol_ratio, 1)}×</span>, defaultHidden: show !== 'vr' },
    { id: 'rsi', header: 'RSI', align: 'right', value: (r) => r.rsi14, cell: (r) => <span className="num">{num(r.rsi14, 0)}</span>, defaultHidden: true },
    { id: 'turn', header: 'Turnover', title: '20-day average traded value, ₹ crore', align: 'right', value: (r) => r.turnover_cr, cell: (r) => <span className="num">{num(r.turnover_cr, 0)}</span>, defaultHidden: true },
    { id: 'atr', header: 'ATR %', align: 'right', value: (r) => r.atr_pct, cell: (r) => <span className="num">{num(r.atr_pct, 1)}</span>, defaultHidden: true },
    { id: 'deliv', header: 'Deliv %', align: 'right', value: (r) => r.deliv_pct, cell: (r) => <span className="num">{num(r.deliv_pct, 0)}</span>, defaultHidden: true },
    { id: 'spark', header: '60D', value: () => null, sortable: false, cell: (r) => <Sparkline values={spark?.[r.symbol] ?? []} width={80} height={22} /> },
    { id: 'res', header: 'Results', value: (r) => r.results_on, cell: (r) => <ResultsChip on={r.results_on} inDays={r.results_on ? daysBetween(today, r.results_on) : null} compact /> },
    { id: 'models', header: 'In models', value: (r) => r.in_models.join(' '), cell: (r) => <span className="flex gap-1">{r.in_models.slice(0, 2).map((m) => <Chip key={m}>{m}</Chip>)}{r.in_models.length > 2 && <Chip>+{r.in_models.length - 2}</Chip>}</span>, defaultHidden: true },
  ]
}

export default function Screener() {
  const [sp, setSp] = useSearchParams()
  const preset = (sp.get('preset') as ScreenerPreset | null) ?? 'momentum'
  const industries = sp.get('industry')?.split(',').filter(Boolean) ?? []
  const inModels = sp.get('models') === '1'
  const resultsSoon = sp.get('results') === '1'
  const set = (k: string, v: string | null) => setSp((p) => { const n = new URLSearchParams(p); if (v) n.set(k, v); else n.delete(k); return n }, { replace: true })
  const q = useScreener({ preset, industry: industries.join(',') || undefined, in_models: inModels || undefined, results_within: resultsSoon ? 7 : undefined })
  const syms = useMemo(() => q.data?.rows.map((r) => r.symbol) ?? [], [q.data])
  const spark = useSparklines(syms)
  const nav = useNavigate()
  const cols = useMemo(() => columns(spark.data?.series, preset), [spark.data, preset])
  // every industry of the liquid list comes with the response (no second preset=all download just for the menu)
  const industryList = useMemo(() => q.data?.industries ?? [...new Set((q.data?.rows ?? []).map((r) => r.industry).filter(Boolean) as string[])].sort(), [q.data])
  const unavailable = isFailure(q.error) && q.error.code === 'FEATURE_UNAVAILABLE'

  return (
    <div>
      <PageHeader
        title="Screener"
        subtitle={q.data ? <>{q.data.total} stocks · prices {date(q.data.source_date)} · liquid stocks of the scan universe</> : <Skeleton className="h-3 w-56" />}
        right={<Segmented<ScreenerPreset> ariaLabel="Preset" value={preset} onChange={(v) => set('preset', v === 'momentum' ? null : v)} items={PRESETS.map((p) => ({ id: p.id, label: p.label, title: p.help }))} className="scroll-x no-scrollbar max-w-full" />}
      />
      {q.error && q.data && !unavailable && <div className="mb-3"><RefreshFailed error={q.error} onRetry={() => void q.refetch()} /></div>}
      <Card flush>
        {unavailable ? (
          <FeatureUnavailable title="The screener appears after the next scan." hint="It reads screener.parquet, which the scan writes with the same prices as the orders (including a live candle). Run a scan from the top bar." />
        ) : q.error && !q.data ? (
          <ErrorState error={q.error} onRetry={() => void q.refetch()} />
        ) : !q.data ? (
          <SkeletonRows rows={12} cols={9} />
        ) : (
          <DataTable
            id="screener"
            data={q.data.rows}
            columns={cols}
            rowKey={(r) => r.symbol}
            onRowClick={(r) => nav(`/chart/${r.symbol}`)}
            filterable
            filterPlaceholder="Filter symbol, company, sector…"
            columnChooser
            exportName={`screener-${preset}`}
            keyboard
            toolbar={
              <>
                <Popover trigger={({ toggle, open }) => <SelectButton label="Industry" value={industries.length ? industries.length : 'All'} open={open} onClick={toggle} />} width={280}>
                  <div className="max-h-[320px] overflow-auto py-1">
                    {industryList.map((i) => (
                      <MenuCheck key={i} checked={industries.includes(i)} onChange={(on) => set('industry', (on ? [...industries, i] : industries.filter((x) => x !== i)).join(',') || null)}>{i}</MenuCheck>
                    ))}
                    {industries.length > 0 && <button type="button" className="w-full px-2.5 py-1.5 text-left text-xs text-accent hover:underline" onClick={() => set('industry', null)}>Clear</button>}
                  </div>
                </Popover>
                <Switch checked={inModels} onChange={(v) => set('models', v ? '1' : null)} label={<span className="text-xs">In a model</span>} />
                <Switch checked={resultsSoon} onChange={(v) => set('results', v ? '1' : null)} label={<span className="text-xs">Results ≤ 7 d</span>} />
              </>
            }
          />
        )}
      </Card>
      <p className="mt-2 text-2xs text-faint">Rankings use the last scan's prices{q.data?.as_of.live ? ", including today's still-forming (provisional) candle" : ' (official closes)'}. Click a row for the chart; j/k to move, Enter to open, / to filter.</p>
    </div>
  )
}
