// Scan control: split button (Full scan / Re-check without download) with a progress ring while running.

import { ChevronDown, Download, RefreshCw, RotateCw } from 'lucide-react'
import { useStartScan, useStatus } from '@/api/hooks'
import { isFailure } from '@/api/client'
import { cn } from '@/lib/csv'
import { duration, num, relative, timeIST } from '@/lib/format'
import { MenuItem, Popover } from '../ui'
import { useToast } from '../toast'

/** Known progress, or null while the scan has not reported any (starting, or 0% outside the download phase). */
export function knownPct(pct: number | null | undefined, message: string | null | undefined): number | null {
  if (pct == null) return null
  return pct > 0 || /^Downloading/.test(message ?? '') ? pct : null
}

/** Progress bar that runs indeterminate while the scan reports no percentage. */
export function ProgressBar({ pct, message }: { pct: number | null | undefined; message: string | null | undefined }) {
  const p = knownPct(pct, message)
  return (
    <div className="relative h-1.5 overflow-hidden rounded-full bg-raised" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={p ?? undefined} aria-label="Scan progress">
      {p == null
        ? <div className="qd-progress absolute inset-0 rounded-full" />
        : <div className="h-full rounded-full bg-accent transition-[width] duration-500" style={{ width: `${Math.max(3, p)}%` }} />}
    </div>
  )
}

function Ring({ pct }: { pct: number | null }) {
  const r = 7, c = 2 * Math.PI * r
  const p = pct == null ? 0.25 : Math.max(0.03, pct / 100)
  return (
    <svg viewBox="0 0 18 18" className={cn('h-4 w-4 -rotate-90', pct == null && 'animate-spin')} aria-hidden>
      <circle cx="9" cy="9" r={r} fill="none" stroke="currentColor" strokeOpacity="0.25" strokeWidth="2.5" />
      <circle cx="9" cy="9" r={r} fill="none" stroke="currentColor" strokeWidth="2.5" strokeDasharray={`${p * c} ${c}`} strokeLinecap="round" />
    </svg>
  )
}

export function useRunScan() {
  const start = useStartScan()
  const toast = useToast()
  return {
    run: (update: boolean) =>
      start.mutate(update, {
        onSuccess: () => toast({ tone: 'info', title: update ? 'Scan started' : 'Re-check started', detail: update ? 'Downloading the latest prices, then testing every strategy.' : 'No download: re-tests every strategy and re-checks holdings on stored prices (~2 min).' }),
        onError: (e) => toast({ tone: 'bad', title: isFailure(e) && e.code === 'SCAN_BUSY' ? 'A scan is already running' : 'Could not start the scan', detail: isFailure(e) ? e.hint ?? e.message : String(e) }),
      }),
    pending: start.isPending,
  }
}

export function ScanButton({ compact }: { compact?: boolean }) {
  const { data } = useStatus()
  const { run, pending } = useRunScan()
  const scan = data?.scan
  const running = !!scan && (scan.running || scan.state === 'starting')
  const offline = !data
  const shown = running ? knownPct(scan?.progress_pct, scan?.message) : null
  return (
    <Popover
      align="right"
      width={300}
      trigger={({ toggle, open }) => (
        <div className="flex h-8 items-stretch overflow-hidden rounded-md border border-line bg-raised">
          <button
            type="button"
            disabled={pending || offline}
            onClick={toggle}
            title={running ? scan?.message ?? 'Scan running' : 'Scan options: full scan (download + test) or re-check without download'}
            className={cn('focus-ring inline-flex items-center gap-1.5 px-2.5 text-[13px] font-medium text-fg hover:bg-panel disabled:cursor-default', running && 'text-accent', offline && 'opacity-50')}
          >
            {running ? <Ring pct={shown} /> : <RefreshCw className="h-3.5 w-3.5" />}
            {!compact && (running ? <span className="num">{shown != null ? `${num(shown, 0)}%` : scan?.state === 'starting' ? 'Starting' : 'Running'}</span> : 'Scan')}
          </button>
          {!compact && (
            <button type="button" aria-label="Scan options" aria-expanded={open} onClick={toggle} className="focus-ring border-l border-line px-1.5 text-muted hover:bg-panel hover:text-fg">
              <ChevronDown className="h-3.5 w-3.5" />
            </button>
          )}
        </div>
      )}
    >
      {(close) => (
        <div className="p-1">
          {running ? (
            <div className="space-y-2 p-2.5">
              <div className="flex items-center justify-between text-xs">
                <span className="font-medium text-fg">{scan?.state === 'starting' ? 'Starting scan' : 'Scan running'}</span>
                <span className="num text-muted">{shown != null ? `${num(shown, 0)}%` : ''}</span>
              </div>
              <ProgressBar pct={scan?.progress_pct} message={scan?.message} />
              <div className="text-xs text-muted">{scan?.message ?? '…'}</div>
              <div className="text-2xs text-faint">Started {timeIST(scan?.started_at)}{scan?.by ? ` by ${scan.by}` : ''}. Pages stay usable; everything refreshes when it finishes.</div>
            </div>
          ) : (
            <>
              <MenuItem icon={<Download className="h-4 w-4" />} hint="~4 min" onClick={() => { close(); run(true) }}>
                <div>Full scan</div>
                <div className="text-2xs text-muted">Download prices, re-test every strategy</div>
              </MenuItem>
              <MenuItem icon={<RotateCw className="h-4 w-4" />} hint="~2 min" onClick={() => { close(); run(false) }}>
                <div>Re-check without download</div>
                <div className="text-2xs text-muted">Re-test strategies, signals and holdings on stored prices</div>
              </MenuItem>
              {data?.latest && (
                <div className="mt-1 border-t border-line px-2.5 pb-1.5 pt-2 text-2xs text-faint">
                  Last scan {timeIST(data.latest.generated_at)} ({relative(data.latest.generated_at)}), took {duration(data.latest.elapsed_s)}.
                  Scheduled scans run at 15:40 and 19:15 on weekdays.
                </div>
              )}
            </>
          )}
        </div>
      )}
    </Popover>
  )
}
