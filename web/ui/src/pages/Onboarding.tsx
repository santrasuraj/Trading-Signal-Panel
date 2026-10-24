import { Download, LogIn } from 'lucide-react'
import { useStatus } from '@/api/hooks'
import { useUi } from '@/app/uiState'
import { useRunScan } from '@/components/layout/ScanButton'
import { Button } from '@/components/ui'
import { num } from '@/lib/format'

/** First run (no latest.json): one card, one action. */
export function Onboarding() {
  const { data: s } = useStatus()
  const { run, pending } = useRunScan()
  const { setFyersLogin } = useUi()
  const running = s?.scan.running || s?.scan.state === 'starting'
  return (
    <div className="mx-auto mt-[8vh] max-w-[560px]">
      <div className="card p-8">
        <div className="mb-5 grid h-10 w-10 place-items-center rounded-lg bg-accent-strong text-sm font-bold text-white">QD</div>
        <h1 className="text-xl font-semibold">No scan yet</h1>
        <p className="mt-2 text-[14px] leading-6 text-muted">
          The first scan downloads about 8 years of daily prices for the Nifty 500, repairs them with official NSE data, and backtests every strategy with realistic Indian costs.
          It takes about 4 minutes. Later scans take a minute or two.
        </p>
        {running ? (
          <div className="mt-6 space-y-2">
            <div className="flex justify-between text-xs"><span className="font-medium">{s?.scan.message ?? 'Starting…'}</span><span className="num text-muted">{s?.scan.progress_pct != null ? `${num(s.scan.progress_pct, 0)}%` : ''}</span></div>
            <div className="h-1.5 overflow-hidden rounded-full bg-raised"><div className="h-full rounded-full bg-accent transition-[width] duration-500" style={{ width: `${s?.scan.progress_pct ?? 4}%` }} /></div>
          </div>
        ) : (
          <div className="mt-6 flex flex-wrap gap-2">
            <Button variant="primary" icon={<Download className="h-4 w-4" />} loading={pending} onClick={() => run(true)}>Run first scan</Button>
            <Button icon={<LogIn className="h-4 w-4" />} onClick={() => setFyersLogin(true)}>Log in to Fyers for real-time prices</Button>
          </div>
        )}
        {s?.scan.state === 'failed' && <p className="mt-4 text-xs text-loss">Last attempt failed: {s.scan.message}</p>}
        <p className="mt-6 border-t border-line pt-4 text-2xs text-faint">Research tool, not investment advice. Nothing here places orders.</p>
      </div>
    </div>
  )
}
