// Labels and colours of the options verdict (scanner/option_verdict.py), shared by the chart badge and the panel.

import type { OvKind } from '@/api/outlook'

export const VERDICT_STYLE: Record<OvKind, { label: string; cls: string }> = {
  BUY_CALL: { label: 'BUY CALL', cls: 'border-profit bg-profit/15 text-profit' },
  BUY_PUT: { label: 'BUY PUT', cls: 'border-loss bg-loss/15 text-loss' },
  NO_TRADE: { label: 'NO TRADE', cls: 'border-line-strong bg-raised text-fg' },
  NO_DATA: { label: 'NO VERDICT', cls: 'border-warn/50 bg-warn/10 text-warn' },
}
