// Big money footprints (Chart page): NSE's public disclosures about who owns, pledges, buys and sells this stock -
// promoter pledges, SEBI SAST filings (anyone crossing 5% / moving 2%), the F&O ban list and delivery volume with its
// tested record (scanner/big_money.py). Every filing links to NSE. Bulk / block deals, insider trades and the
// quarterly shareholding are in the side panel's Big investors box.

import { ExternalLink, RefreshCw } from 'lucide-react'
import { isFailure } from '@/api/client'
import type { BigMoney, BmTested } from '@/api/outlook'
import { useBigMoneyRefresh } from '@/api/outlook'
import { useToast } from '@/components/toast'
import { Button, Card, Tip } from '@/components/ui'
import { cn } from '@/lib/csv'
import { DASH, date, dateTimeIST, num, pct, qty } from '@/lib/format'

const TESTED: Record<string, { label: string; cls: string }> = {
  edge: { label: 'tested: edge after costs', cls: 'text-profit' },
  edge_before_costs: { label: 'tested: edge before costs only', cls: 'text-warn' },
  no_edge: { label: 'tested: no edge', cls: 'text-muted' },
  opposite: { label: 'tested: worked in reverse', cls: 'text-loss' },
  too_few: { label: 'too few cases', cls: 'text-faint' },
}

function Tested({ t, what }: { t: BmTested | null; what: string }) {
  if (!t) return <span className="text-2xs text-faint">untested</span>
  const x = TESTED[t.verdict] ?? TESTED.no_edge
  return (
    <Tip text={<>{qty(t.n)} {what} in 8 years of the point-in-time top 500: 10 days later {pct(t.excess_pct, { dp: 2 })} vs the average stock ({pct(t.after_cost_pct, { dp: 2 })} after costs), t {num(t.t, 1)}.</>}>
      <span className={cn('text-2xs underline decoration-dotted', x.cls)}>{x.label}</span>
    </Tip>
  )
}

export function BigMoneyCard({ symbol, b, kind }: { symbol: string; b: BigMoney; kind: string }) {
  const refresh = useBigMoneyRefresh(symbol)
  const toast = useToast()
  const p = b.pledge
  const d = b.delivery
  const busy = refresh.isPending || b.refreshing
  return (
    <Card
      title="Big money footprints"
      subtitle={`NSE's public disclosures: pledges, 5%+ holders' filings, F&O ban, delivery${b.refreshed_at ? ` · fetched ${dateTimeIST(b.refreshed_at)}` : ''}`}
      right={kind === 'stock' && (
        <Button size="sm" icon={<RefreshCw className="h-3.5 w-3.5" />} loading={busy} title="Fetch this stock's pledge data, the acquisition filings and the F&O ban list from NSE"
          onClick={() => refresh.mutate(undefined, { onError: (e) => toast({ tone: 'bad', title: isFailure(e) ? e.message : 'Could not start the refresh' }) })}>
          {busy ? 'Fetching…' : 'Refresh from NSE'}
        </Button>
      )}
    >
      <div className="space-y-4">
        <div className="grid gap-4 md:grid-cols-3">
          <div>
            <div className="eyebrow mb-1">Promoter pledge</div>
            {p ? (
              <div className="space-y-0.5 text-xs">
                <div className="flex justify-between"><span className="text-muted">Promoter holding</span><span className="num">{num(p.promoter_pct, 2)}%</span></div>
                <div className="flex justify-between"><span className="text-muted">Pledged by promoters</span>
                  <span className={cn('num font-semibold', (p.promoter_pledged_pct ?? 0) >= 25 ? 'text-loss' : (p.promoter_pledged_pct ?? 0) >= 10 ? 'text-warn' : 'text-fg')}>{num(p.promoter_pledged_pct, 2)}% of theirs</span></div>
                <div className="flex justify-between"><span className="text-muted">… of the company</span><span className="num">{num(p.promoter_pledged_total_pct, 2)}%</span></div>
                <div className="flex justify-between"><Tip text="Every pledged share in the depository system, by any holder - often brokers' margin pledges, not a risk by itself"><span className="text-muted underline decoration-dotted">All pledged shares (demat)</span></Tip><span className="num">{num(p.depository_pledged_pct, 2)}%</span></div>
                <div className="text-2xs text-faint">Quarter {date(p.quarter)} · <a href={p.source} target="_blank" rel="noreferrer" className="link">NSE pledge data</a></div>
              </div>
            ) : <p className="text-xs text-muted">{b.pledge_checked ? 'NSE has no pledge record for this company.' : kind === 'stock' ? 'Not fetched yet: Refresh from NSE.' : 'Companies only.'}</p>}
          </div>
          <div>
            <div className="eyebrow mb-1">Delivery (shares taken home)</div>
            {d ? (
              <div className="space-y-0.5 text-xs">
                <div className="flex justify-between"><span className="text-muted">Delivered today</span><span className="num">{num(d.deliv_pct, 1)}% <span className="text-faint">(20-day avg {num(d.deliv_pct_avg20, 1)}%)</span></span></div>
                <div className="flex justify-between"><span className="text-muted">Delivery vs usual</span><span className="num">{num(d.deliv_ratio, 2)}×</span></div>
                <div className="flex justify-between"><span className="text-muted">Today</span><span className={cn('font-medium', d.state === 'accumulation' ? 'text-profit' : d.state === 'distribution' ? 'text-loss' : 'text-muted')}>{d.state === 'normal' ? 'no spike' : `${d.state} spike`}</span></div>
                {d.events.length > 0 && (
                  <ul className="mt-1 space-y-0.5 text-2xs">
                    {d.events.slice(0, 4).map((e) => <li key={e.date} className="flex justify-between gap-2"><span className="num text-muted">{date(e.date, { year: false })}</span><span className={e.kind === 'accumulation' ? 'text-profit' : 'text-loss'}>{e.kind} · {num(e.ratio, 1)}× · {pct(e.chg_pct, { dp: 1 })}</span></li>)}
                  </ul>
                )}
                <div className="flex flex-wrap gap-x-3 pt-0.5"><span className="text-2xs text-faint">Accumulation:</span><Tested t={d.tested_accumulation} what="spikes on up days" /><span className="text-2xs text-faint">Distribution:</span><Tested t={d.tested_distribution} what="spikes on down days" /></div>
              </div>
            ) : <p className="text-xs text-muted">No delivery data (NSE reports it for stocks only).</p>}
          </div>
          <div>
            <div className="eyebrow mb-1">F&O ban list</div>
            {b.ban ? (
              <div className="text-xs">
                <div className={cn('font-medium', b.ban.in_ban ? 'text-warn' : 'text-muted')}>{b.ban.in_ban ? `${symbol} is in the ban period` : `${symbol} is not in the ban`}</div>
                <div className="text-2xs text-muted">Trade date {date(b.ban.trade_date)}: {b.ban.symbols.length ? b.ban.symbols.join(', ') : 'none'}. In the ban, open interest is above 95% of the market-wide limit: no new F&O positions until it falls under 80%.</div>
                <a href={b.ban.source} target="_blank" rel="noreferrer" className="link text-2xs">NSE ban file</a>
              </div>
            ) : <p className="text-xs text-muted">Not fetched yet.</p>}
          </div>
        </div>
        <div>
          <div className="eyebrow mb-1">5%+ holders: acquisitions and disposals (SEBI SAST Reg 29, last 12 months)</div>
          {b.filings.length ? (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[640px] text-xs">
                <thead><tr className="border-b border-line text-2xs text-muted">
                  {['Filed', 'Who', 'Side', '% of company', 'Holds after', 'How', 'Filing'].map((h, i) => <th key={h} className={cn('py-1 font-medium', i > 2 && i < 5 ? 'text-right' : 'text-left')}>{h}</th>)}
                </tr></thead>
                <tbody>{b.filings.map((f, i) => (
                  <tr key={`${f.filed}${f.acquirer}${i}`} className="border-b border-line/50 last:border-0">
                    <td className="num whitespace-nowrap py-1 text-muted">{date(f.filed?.slice(0, 10), { year: false })}</td>
                    <td className="max-w-[260px] truncate py-1" title={f.acquirer}>{f.acquirer}{f.promoter && <span className="ml-1 rounded border border-line px-1 text-2xs text-muted">promoter</span>}</td>
                    <td className={cn('py-1 font-semibold', f.side === 'BUY' ? 'text-profit' : 'text-loss')}>{f.side}</td>
                    <td className="num py-1 text-right">{num(f.pct, 2)}%</td>
                    <td className="num py-1 text-right">{num(f.after_pct, 2)}%</td>
                    <td className="max-w-[180px] truncate py-1 pl-3 text-muted" title={`${f.mode ?? ''} · ${f.security ?? ''} · ${f.period ?? ''}`}>{f.mode ?? DASH}</td>
                    <td className="py-1">{f.link ? <a href={f.link} target="_blank" rel="noreferrer" className="link inline-flex items-center gap-0.5">NSE <ExternalLink className="h-3 w-3" /></a> : DASH}</td>
                  </tr>
                ))}</tbody>
              </table>
              {b.filings_note && <p className="mt-1 text-2xs text-muted">{b.filings_note}</p>}
            </div>
          ) : <p className="text-xs text-muted">{b.refreshed_at ? 'No 5%+ holder filed a purchase or sale in the last 12 months.' : 'Not fetched yet: Refresh from NSE (the scan also fetches them every evening).'}</p>}
        </div>
        <p className="text-2xs text-muted">{b.note} Bulk and block deals, insider trades and the quarterly shareholding (FII, mutual funds, named 1%+ holders) are in the side panel's Big investors box.</p>
      </div>
    </Card>
  )
}
