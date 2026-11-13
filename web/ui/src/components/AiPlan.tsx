// AI trade plan (Signals page, Intraday tab): Claude reads one symbol's levels, the latest 5-minute bars and today's
// signals and writes an IF-THEN plan - key levels, up to two setups with entry zone, conditions, stop and two targets
// (web/api/services/ai_svc.plan, structured JSON). The Anthropic key lives only in .env on this PC; the plan is shown
// as text elements, never as HTML.

import { useEffect } from 'react'
import { Sparkles, X } from 'lucide-react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { fetchJson } from '@/api/client'
import { ErrorState } from '@/components/feedback'
import { Price } from '@/components/num'
import { Button, Card, IconButton } from '@/components/ui'
import { cn } from '@/lib/csv'
import { dateTimeIST, qty } from '@/lib/format'

interface AiStatus { configured: boolean; model: string; running: boolean; note: string }
interface PlanLevel { price: number; label: string; kind: 'support' | 'resistance' | 'liquidity' | 'pivot' }
interface PlanSetup {
  name: string; side: 'LONG' | 'SHORT'; entry_low: number; entry_high: number; conditions: string[]; stop: number
  target_1: number; target_2: number; invalidation: string
}
interface PlanBody { bias: 'long' | 'short' | 'neutral'; summary: string; levels: PlanLevel[]; setups: PlanSetup[]; no_trade_if: string; risk_note: string }
interface AiPlanResponse {
  symbol: string; plan: PlanBody | null; refused: boolean; stop_reason: string | null; model: string; session: string | null
  bars_source: string | null; generated_at: string; cached: boolean; input_tokens: number | null; output_tokens: number | null; note: string
}

const BIAS = { long: ['Bias: long', 'text-profit'], short: ['Bias: short', 'text-loss'], neutral: ['Bias: neutral', 'text-muted'] } as const
const KIND = { support: 'text-profit', resistance: 'text-loss', liquidity: 'text-warn', pivot: 'text-muted' } as const

function Setup({ s }: { s: PlanSetup }) {
  const risk = Math.abs((s.entry_low + s.entry_high) / 2 - s.stop)
  return (
    <div className="rounded-md border border-line p-3">
      <div className="flex flex-wrap items-baseline gap-2">
        <span className={cn('text-2xs font-bold tracking-[0.04em]', s.side === 'LONG' ? 'text-profit' : 'text-loss')}>{s.side}</span>
        <span className="text-[13px] font-semibold">{s.name}</span>
      </div>
      <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-xs sm:grid-cols-4">
        <div><dt className="text-faint">Entry zone</dt><dd><Price v={s.entry_low} /> – <Price v={s.entry_high} /></dd></div>
        <div><dt className="text-faint">Stop</dt><dd className="text-loss"><Price v={s.stop} /></dd></div>
        <div><dt className="text-faint">Target 1</dt><dd className="text-profit"><Price v={s.target_1} /></dd></div>
        <div><dt className="text-faint">Target 2</dt><dd className="text-profit"><Price v={s.target_2} /></dd></div>
      </dl>
      {risk > 0 && <p className="mt-1 text-2xs text-faint">Risk ≈ ₹{risk.toFixed(2)} a share from the middle of the zone.</p>}
      <p className="mt-2 text-2xs font-medium text-muted">Wait for</p>
      <ul className="ml-4 list-disc space-y-0.5 text-xs">{s.conditions.map((c, i) => <li key={i}>{c}</li>)}</ul>
      <p className="mt-2 text-xs"><span className="text-muted">Cancelled if: </span>{s.invalidation}</p>
    </div>
  )
}

export function AiPlan({ symbol, onClose }: { symbol: string; onClose: () => void }) {
  const st = useQuery({ queryKey: ['ai', 'status'], queryFn: () => fetchJson<AiStatus>('/api/ai/status'), staleTime: 30_000 })
  const run = useMutation({
    mutationFn: (s: string) => fetchJson<AiPlanResponse>('/api/ai/plan', { method: 'POST', body: JSON.stringify({ symbol: s }) }),
  })
  const { mutate, reset } = run
  const configured = st.data?.configured
  useEffect(() => { reset(); if (configured) mutate(symbol) }, [symbol, configured, mutate, reset])
  const a = run.data?.symbol === symbol ? run.data : undefined
  const p = a?.plan
  return (
    <Card
      title={<span className="inline-flex items-center gap-1.5"><Sparkles className="h-4 w-4 text-violet" />AI trade plan · {symbol}</span>}
      subtitle={configured ? `Claude (${st.data?.model}) reads ${symbol}'s levels, the latest 5-minute bars and today's signals, and writes IF-THEN setups` : 'Claude reads the chart and writes an IF-THEN plan'}
      right={<IconButton label="Close the AI plan" size="sm" onClick={onClose}><X className="h-4 w-4" /></IconButton>}
    >
      {!st.data ? null : !configured ? (
        <div className="space-y-1 text-xs text-muted">
          <p>To switch it on, add your Anthropic API key to the <code>.env</code> file next to <code>config.yaml</code> on this PC:</p>
          <pre className="rounded bg-raised px-2 py-1 text-2xs">ANTHROPIC_API_KEY=sk-ant-api03-…</pre>
          <p>Create the key at console.anthropic.com → API keys. Never paste a key into a chat or a web page. Each plan costs roughly ₹5-10 on your Anthropic account.</p>
        </div>
      ) : run.isPending ? (
        <p className="text-xs text-muted">Claude is reading {symbol}'s chart… (up to a minute)</p>
      ) : run.error ? (
        <ErrorState compact error={run.error} onRetry={() => mutate(symbol)} />
      ) : a ? (
        <div className="space-y-3">
          {a.refused ? <p className="text-xs text-warn">Claude declined to plan this one.</p> : !p ? <p className="text-xs text-muted">No readable plan came back. Try again.</p> : (
            <>
              <p className="text-[13px]"><span className={cn('mr-2 font-semibold', BIAS[p.bias][1])}>{BIAS[p.bias][0]}</span>{p.summary}</p>
              {p.levels.length > 0 && (
                <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs">
                  {p.levels.map((l, i) => (
                    <span key={i}><span className={cn('font-medium', KIND[l.kind])}>{l.label}</span> <Price v={l.price} /></span>
                  ))}
                </div>
              )}
              {p.setups.length > 0 ? <div className="grid gap-2 lg:grid-cols-2">{p.setups.map((s, i) => <Setup key={i} s={s} />)}</div>
                : <p className="text-xs text-muted">No clean setup right now.</p>}
              <p className="text-xs"><span className="text-muted">No trade if: </span>{p.no_trade_if}</p>
              <p className="text-xs text-warn">{p.risk_note}</p>
            </>
          )}
          <div className="flex flex-wrap items-center gap-2">
            <Button size="sm" icon={<Sparkles className="h-3.5 w-3.5" />} onClick={() => mutate(symbol)}>Plan again</Button>
            <span className="text-2xs text-faint">
              {a.model} · bars of {a.session ?? '—'} ({a.bars_source ?? 'none'}) · {dateTimeIST(a.generated_at)}{a.cached ? ' · from the 5-minute cache (not billed again)' : ''}
              {a.input_tokens != null && ` · ${qty(a.input_tokens)} in / ${qty(a.output_tokens)} out tokens`}
            </span>
          </div>
          <p className="text-2xs text-muted">{a.note}</p>
        </div>
      ) : null}
    </Card>
  )
}
