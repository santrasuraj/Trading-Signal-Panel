// Loading / empty / error / unavailable states and banners (spec 4.8). Never a blank card.

import { useState, type ReactNode } from 'react'
import { AlertOctagon, AlertTriangle, ChevronDown, Info, PackageOpen, RefreshCw, WifiOff, X } from 'lucide-react'
import { isFailure } from '@/api/client'
import { cn } from '@/lib/csv'
import { Button } from './ui'

export function Skeleton({ className, style }: { className?: string; style?: React.CSSProperties }) {
  return <div className={cn('skeleton', className)} style={style} aria-hidden />
}

export function SkeletonRows({ rows = 8, cols = 6 }: { rows?: number; cols?: number }) {
  return (
    <div className="divide-y divide-line" aria-busy="true" aria-label="Loading">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="flex h-row items-center gap-4 px-4">
          {Array.from({ length: cols }).map((__, j) => (
            <Skeleton key={j} className={cn('h-3', j === 0 ? 'w-32' : 'ml-auto w-14')} />
          ))}
        </div>
      ))}
    </div>
  )
}

export function SkeletonKpis({ n = 6 }: { n?: number }) {
  return (
    <div className="grid gap-px overflow-hidden rounded-lg border border-line bg-line" style={{ gridTemplateColumns: `repeat(auto-fit, minmax(140px, 1fr))` }}>
      {Array.from({ length: n }).map((_, i) => (
        <div key={i} className="h-[72px] bg-panel p-3">
          <Skeleton className="h-2.5 w-16" />
          <Skeleton className="mt-3 h-5 w-20" />
        </div>
      ))}
    </div>
  )
}

export function SkeletonChart({ height = 280 }: { height?: number }) {
  return (
    <div className="relative" style={{ height }} aria-busy="true">
      <div className="absolute inset-0 grid grid-rows-5">
        {Array.from({ length: 5 }).map((_, i) => <div key={i} className="border-b border-line/60" />)}
      </div>
      <Skeleton className="absolute bottom-3 left-3 right-14 top-6 opacity-40" />
    </div>
  )
}

export function EmptyState({ title, children, icon, action, compact }: { title: ReactNode; children?: ReactNode; icon?: ReactNode; action?: ReactNode; compact?: boolean }) {
  return (
    <div className={cn('flex flex-col items-center justify-center text-center', compact ? 'gap-1.5 px-4 py-6' : 'gap-2 px-6 py-12')}>
      <div className="text-faint">{icon ?? <PackageOpen className="h-6 w-6" strokeWidth={1.5} />}</div>
      <div className="text-[13px] font-medium text-fg">{title}</div>
      {children && <div className="max-w-[56ch] text-xs text-muted">{children}</div>}
      {action && <div className="mt-2">{action}</div>}
    </div>
  )
}

/** Inline error card: icon, message, hint, retry, collapsible code/details. */
export function ErrorState({ error, onRetry, compact }: { error: unknown; onRetry?: () => void; compact?: boolean }) {
  const [open, setOpen] = useState(false)
  if (isFailure(error) && error.code === 'FEATURE_UNAVAILABLE') {
    return <FeatureUnavailable title={error.message} hint={error.hint} />
  }
  const f = isFailure(error) ? error : null
  const msg = f?.message ?? (error instanceof Error ? error.message : 'Something went wrong.')
  const offline = f?.code === 'OFFLINE'
  return (
    <div role="alert" className={cn('flex flex-col items-start gap-2', compact ? 'p-3' : 'p-5')}>
      <div className="flex items-start gap-2.5">
        {offline ? <WifiOff className="mt-0.5 h-4 w-4 shrink-0 text-loss" /> : <AlertOctagon className="mt-0.5 h-4 w-4 shrink-0 text-loss" />}
        <div>
          <div className="text-[13px] font-medium text-fg">{msg}</div>
          {f?.hint && <div className="mt-0.5 text-xs text-muted">{f.hint}</div>}
        </div>
      </div>
      <div className="flex items-center gap-2 pl-6">
        {onRetry && <Button size="sm" icon={<RefreshCw className="h-3.5 w-3.5" />} onClick={onRetry}>Retry</Button>}
        {f && (
          <button type="button" onClick={() => setOpen(!open)} className="focus-ring inline-flex items-center gap-1 rounded text-2xs text-faint hover:text-muted">
            Details <ChevronDown className={cn('h-3 w-3 transition-transform', open && 'rotate-180')} />
          </button>
        )}
      </div>
      {open && f && (
        <pre className="ml-6 max-w-full overflow-auto rounded-md border border-line bg-raised p-2 font-mono text-2xs text-muted">
          {JSON.stringify({ code: f.code, status: f.status, details: f.details }, null, 2)}
        </pre>
      )}
    </div>
  )
}

export function FeatureUnavailable({ title, hint, children }: { title: ReactNode; hint?: ReactNode; children?: ReactNode }) {
  return (
    <div className="flex items-start gap-3 p-5">
      <Info className="mt-0.5 h-4 w-4 shrink-0 text-muted" />
      <div className="text-[13px]">
        <div className="font-medium text-fg">{title}</div>
        {hint && <div className="mt-0.5 text-xs text-muted">{hint}</div>}
        {children}
      </div>
    </div>
  )
}

type BannerTone = 'danger' | 'warn' | 'info'
export function Banner({ tone, children, onDismiss, action, icon }: { tone: BannerTone; children: ReactNode; onDismiss?: () => void; action?: ReactNode; icon?: ReactNode }) {
  const cls = tone === 'danger' ? 'border-loss/40 tint-loss' : tone === 'warn' ? 'border-warn/40 tint-warn' : 'border-info/30 tint-info'
  const ic = icon ?? (tone === 'danger' ? <AlertOctagon className="h-4 w-4 text-loss" /> : tone === 'warn' ? <AlertTriangle className="h-4 w-4 text-warn" /> : <Info className="h-4 w-4 text-info" />)
  return (
    <div role={tone === 'danger' ? 'alert' : 'status'} className={cn('flex items-center gap-3 rounded-lg border px-3.5 py-2 text-[13px]', cls)}>
      <span className="shrink-0">{ic}</span>
      <div className="min-w-0 flex-1 text-fg">{children}</div>
      {action}
      {onDismiss && (
        <button type="button" aria-label="Dismiss" onClick={onDismiss} className="focus-ring -mr-1 rounded p-1 text-muted hover:text-fg">
          <X className="h-3.5 w-3.5" />
        </button>
      )}
    </div>
  )
}

/** A refetch failed but the previous data is still on screen (TanStack keeps it): say so instead of showing old
 *  results as if they were the new scan's. Render as `{q.error && q.data && <RefreshFailed ... />}`. */
export function RefreshFailed({ error, onRetry }: { error: unknown; onRetry: () => void }) {
  if (!error) return null
  return (
    <Banner tone="warn" action={<Button size="sm" icon={<RefreshCw className="h-3.5 w-3.5" />} onClick={onRetry}>Retry</Button>}>
      Could not load the latest results: showing the previous data.{isFailure(error) ? ` ${error.message}` : ''}
    </Banner>
  )
}

/** Query wrapper: skeleton on first load, error card on failure, children with data otherwise. */
export function QueryView<T>({ q, skeleton, children, compact }: {
  q: { data: T | undefined; error: unknown; isLoading: boolean; refetch: () => unknown }; skeleton?: ReactNode; children: (d: T) => ReactNode; compact?: boolean
}) {
  if (q.data !== undefined) return <>{children(q.data)}</>
  if (q.error) return <ErrorState error={q.error} onRetry={() => void q.refetch()} compact={compact} />
  return <>{skeleton ?? <SkeletonRows />}</>
}
