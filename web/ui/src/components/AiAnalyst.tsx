// AI analyst (Chart page): Claude reads this page's data for the symbol (setup and base rates, levels, signals with
// their tested records, the options verdict, F&O positioning, NSE disclosures) and explains it in plain English
// (web/api/services/ai_svc.py). The Anthropic key lives only in .env on this PC - there is deliberately no key box
// here. The answer is rendered as text elements (never as HTML).

import { useState, type ReactNode } from 'react'
import { Sparkles } from 'lucide-react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { fetchJson } from '@/api/client'
import { ErrorState } from '@/components/feedback'
import { Button, Card } from '@/components/ui'
import { dateTimeIST, qty } from '@/lib/format'

interface AiStatus { configured: boolean; model: string; running: boolean; note: string }
interface AiAnalysis {
  symbol: string; question: string | null; answer: string | null; refused: boolean; stop_reason: string | null; model: string
  data_date: string | null; generated_at: string; cached: boolean; input_tokens: number | null; output_tokens: number | null
  cache_read_tokens: number | null; note: string
}

/** **bold** spans inside one line. */
function inline(s: string): ReactNode[] {
  return s.split(/(\*\*[^*]+\*\*)/g).filter(Boolean).map((part, i) =>
    part.startsWith('**') && part.endsWith('**') ? <strong key={i}>{part.slice(2, -2)}</strong> : <span key={i}>{part}</span>)
}

/** A small Markdown subset: headings, bold, bullet and numbered lists, paragraphs. */
function Markdown({ text }: { text: string }) {
  const out: ReactNode[] = []
  let list: ReactNode[] = []
  const flush = () => { if (list.length) { out.push(<ul key={`l${out.length}`} className="ml-4 list-disc space-y-0.5">{list}</ul>); list = [] } }
  text.split(/\r?\n/).forEach((raw, i) => {
    const line = raw.trimEnd()
    const bullet = /^\s*(?:[-*•]|\d+[.)])\s+(.*)$/.exec(line)
    if (bullet) { list.push(<li key={i}>{inline(bullet[1])}</li>); return }
    flush()
    if (!line.trim()) return
    const h = /^#{1,4}\s+(.*)$/.exec(line)
    if (h) out.push(<h3 key={i} className="mt-2 text-[13px] font-semibold">{inline(h[1])}</h3>)
    else out.push(<p key={i}>{inline(line)}</p>)
  })
  flush()
  return <div className="space-y-1.5 text-[13px] leading-relaxed">{out}</div>
}

export function AiAnalyst({ symbol }: { symbol: string }) {
  const st = useQuery({ queryKey: ['ai', 'status'], queryFn: () => fetchJson<AiStatus>('/api/ai/status'), staleTime: 30_000 })
  const [q, setQ] = useState('')
  const run = useMutation({
    mutationFn: (question: string | null) => fetchJson<AiAnalysis>('/api/ai/analyze', { method: 'POST', body: JSON.stringify({ symbol, question }) }),
  })
  const a = run.data?.symbol === symbol ? run.data : undefined
  const ask = (question: string | null) => run.mutate(question)
  return (
    <Card title={<span className="inline-flex items-center gap-1.5"><Sparkles className="h-4 w-4 text-violet" />AI analyst</span>}
      subtitle={st.data?.configured ? `Claude (${st.data.model}) reads this page's data for ${symbol} and explains it - no news, no guesses` : 'Claude explains this page in plain English'}>
      {!st.data ? null : !st.data.configured ? (
        <div className="space-y-1 text-xs text-muted">
          <p>To switch it on, add your Anthropic API key to the <code>.env</code> file next to <code>config.yaml</code> on this PC:</p>
          <pre className="rounded bg-raised px-2 py-1 text-2xs">ANTHROPIC_API_KEY=sk-ant-api03-…</pre>
          <p>Create the key at console.anthropic.com → API keys. Never paste a key into a chat or a web page (this page has no key box on purpose). No restart needed. Each analysis costs roughly ₹5-10 on your Anthropic account.</p>
        </div>
      ) : (
        <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <Button size="sm" variant="primary" icon={<Sparkles className="h-3.5 w-3.5" />} loading={run.isPending} onClick={() => ask(null)}>
              {run.isPending ? 'Claude is reading the data… (up to a minute)' : `Explain ${symbol}`}
            </Button>
            <form className="flex min-w-[240px] flex-1 gap-2" onSubmit={(e) => { e.preventDefault(); if (q.trim()) ask(q.trim()) }}>
              <input value={q} onChange={(e) => setQ(e.target.value)} maxLength={1000} placeholder="Or ask about this stock, e.g. where is the support if it falls?"
                className="focus-ring h-8 min-w-0 flex-1 rounded-md border border-line bg-panel px-2 text-[13px]" aria-label="Question for the AI analyst" />
              <Button size="sm" type="submit" disabled={!q.trim() || run.isPending}>Ask</Button>
            </form>
          </div>
          {run.error && <ErrorState compact error={run.error} />}
          {a && (
            <div className="rounded-md border border-line p-3">
              {a.question && <p className="mb-2 text-xs text-muted">Q: {a.question}</p>}
              {a.refused ? <p className="text-xs text-warn">Claude declined to answer this one. Try asking it differently.</p> : a.answer ? <Markdown text={a.answer} /> : <p className="text-xs text-muted">No answer came back.</p>}
              <p className="mt-2 text-2xs text-faint">
                {a.model} · data to {a.data_date} · {dateTimeIST(a.generated_at)}{a.cached ? ' · from the 15-minute cache (not billed again)' : ''}
                {a.input_tokens != null && ` · ${qty(a.input_tokens)} in / ${qty(a.output_tokens)} out tokens`}
              </p>
              <p className="mt-1 text-2xs text-muted">{a.note}</p>
            </div>
          )}
        </div>
      )}
    </Card>
  )
}
