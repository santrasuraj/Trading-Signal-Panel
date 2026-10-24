// Number cells: always tabular, signed values coloured AND signed, missing values as a faint dash.

import type { ReactNode } from 'react'
import { cn } from '@/lib/csv'
import { DASH, money, moneyCompact, ok, pct, price, pts, qty, ratio, toneClass } from '@/lib/format'
import { useTheme } from '@/lib/theme'

function Missing() {
  return <span className="text-faint">{DASH}</span>
}

export function Pct({ v, dp, signed = true, color = true, className }: { v: number | null | undefined; dp?: number; signed?: boolean; color?: boolean; className?: string }) {
  if (!ok(v)) return <Missing />
  return <span className={cn('num', color && signed && toneClass(v), className)}>{pct(v, { dp, signed })}</span>
}

export function Pts({ v, color = true, className, suffix }: { v: number | null | undefined; color?: boolean; className?: string; suffix?: ReactNode }) {
  if (!ok(v)) return <Missing />
  return <span className={cn('num', color && toneClass(v), className)}>{pts(v)}{suffix}</span>
}

export function Price({ v, className }: { v: number | null | undefined; className?: string }) {
  if (!ok(v)) return <Missing />
  return <span className={cn('num', className)}>{price(v)}</span>
}

export function Qty({ v, className }: { v: number | null | undefined; className?: string }) {
  if (!ok(v)) return <Missing />
  return <span className={cn('num', className)}>{qty(v)}</span>
}

export function Money({ v, signed, color, dp, compact, className }: {
  v: number | null | undefined; signed?: boolean; color?: boolean; dp?: 0 | 2; compact?: boolean; className?: string
}) {
  const { compactMoney } = useTheme()
  if (!ok(v)) return <Missing />
  const text = compact && compactMoney ? moneyCompact(v, { signed }) : money(v, { dp, signed })
  return <span title={compact && compactMoney ? money(v, { signed }) : undefined} className={cn('num', color && toneClass(v), className)}>{text}</span>
}

export function Ratio({ v, className }: { v: number | null | undefined; className?: string }) {
  if (!ok(v)) return <Missing />
  return <span className={cn('num', className)}>{ratio(v)}</span>
}

/** Risk metric (max drawdown, volatility): neutral colour, always shows the sign. */
export function Risk({ v, dp = 1, className }: { v: number | null | undefined; dp?: number; className?: string }) {
  if (!ok(v)) return <Missing />
  return <span className={cn('num text-fg', className)}>{pct(v, { dp })}</span>
}

export { Missing }
