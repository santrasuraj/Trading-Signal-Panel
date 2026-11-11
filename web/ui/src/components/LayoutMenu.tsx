// Saved chart layouts (chart toolbar): name the current indicators, chart type, timeframe and options, then apply
// them to any stock in one click (web/api/services/layouts_svc.py, kept on this PC).

import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { LayoutTemplate, Trash2 } from 'lucide-react'
import { fetchJson } from '@/api/client'
import { Button, IconButton, Popover } from '@/components/ui'

export interface ChartLayoutT { name: string; ind: string[]; log: boolean; lines: boolean; ctype: string; tf: string; range: string; levels: string[] }

export function LayoutMenu({ current, apply }: { current: Omit<ChartLayoutT, 'name'>; apply: (l: ChartLayoutT) => void }) {
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['chart-layouts'], queryFn: () => fetchJson<{ layouts: ChartLayoutT[] }>('/api/chart-layouts'), staleTime: Infinity })
  const put = useMutation({ mutationFn: (layouts: ChartLayoutT[]) => fetchJson<{ layouts: ChartLayoutT[] }>('/api/chart-layouts', { method: 'PUT', body: JSON.stringify({ layouts }) }),
    onSuccess: (d) => qc.setQueryData(['chart-layouts'], d) })
  const [name, setName] = useState('')
  const items = q.data?.layouts ?? []
  return (
    <Popover align="right" width={280} trigger={({ toggle, open }) => (
      <Button icon={<LayoutTemplate className="h-3.5 w-3.5" />} onClick={toggle} aria-expanded={open} title="Saved chart layouts: indicators, chart type, timeframe" className="max-sm:px-2.5">
        <span className="max-sm:hidden">Layouts</span>
      </Button>)}>
      {(close) => (
        <div className="space-y-2 p-2.5">
          {items.length === 0 ? <p className="text-xs text-muted">No saved layouts yet. Set the chart up, name it and save.</p> : (
            <ul className="space-y-0.5">{items.map((l) => (
              <li key={l.name} className="flex items-center gap-1.5 rounded px-1 py-0.5 text-xs hover:bg-raised">
                <button type="button" className="min-w-0 flex-1 truncate text-left" onClick={() => { apply(l); close() }} title={`${l.ind.length} indicators · ${l.ctype} · ${l.tf}`}>{l.name} <span className="text-muted">· {l.tf} · {l.ind.length} indicators</span></button>
                <IconButton label={`Delete layout ${l.name}`} onClick={() => put.mutate(items.filter((x) => x.name !== l.name))}><Trash2 className="h-3.5 w-3.5" /></IconButton>
              </li>))}</ul>)}
          <div className="flex gap-1.5 border-t border-line pt-2">
            <input aria-label="Layout name" className="input h-8 min-w-0 flex-1 px-2 text-xs" placeholder="Name this layout" value={name} maxLength={40} onChange={(e) => setName(e.target.value)} />
            <Button size="sm" disabled={!name.trim()} loading={put.isPending}
              onClick={() => { const n = name.trim(); put.mutate([...items.filter((x) => x.name.toLowerCase() !== n.toLowerCase()), { ...current, name: n }]); setName('') }}>Save</Button>
          </div>
        </div>
      )}
    </Popover>
  )
}
