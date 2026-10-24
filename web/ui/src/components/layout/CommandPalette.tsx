// Ctrl/Cmd K palette (cmdk): symbols, strategies, pages and actions.
//
// Matching is our own (paletteScore): an exact symbol or word scores 1, a word prefix 0.9, a substring 0.6, a
// keyword 0.4, anything else 0 (hidden). cmdk's loose fuzzy match let "IGIL" select the page "Signals". cmdk 1.1
// also never reorders groups (its group sort looks groups up by id, but data-value holds the heading), so the
// groups are rendered best match first here; the first visible item is the one Enter opens.

import { useMemo, useState, type ReactNode } from 'react'
import { Command } from 'cmdk'
import { useNavigate } from 'react-router-dom'
import { CandlestickChart, Keyboard, LogIn, Moon, RefreshCw, RotateCw, Search, Trophy } from 'lucide-react'
import { useStrategies, useSymbols } from '@/api/hooks'
import { NAV, SETTINGS_NAV } from '@/app/nav'
import { useUi } from '@/app/uiState'
import { useTheme } from '@/lib/theme'
import { StatusDot } from '../badges'
import { Kbd } from '../ui'
import { useRunScan } from './ScanButton'

/** 0..1 relevance of one palette item for the typed search (0 hides it). */
export function paletteScore(value: string, search: string, keywords?: string[]): number {
  const q = search.trim().toLowerCase()
  if (!q) return 1
  const v = value.toLowerCase()
  const words = v.split(/[\s/·()-]+/).filter(Boolean)
  if (words.includes(q)) return 1
  if (words.some((w) => w.startsWith(q))) return 0.9
  if (v.includes(q)) return 0.6
  const kw = (keywords ?? []).join(' ').toLowerCase()
  if (kw && kw.split(/\s+/).some((w) => w.startsWith(q))) return 0.4
  const terms = q.split(/\s+/).filter(Boolean)
  if (terms.length > 1 && terms.every((t) => words.some((w) => w.startsWith(t)) || kw.includes(t))) return 0.5
  return 0
}

function Item({ children, onSelect, value, keywords, icon, hint }: { children: ReactNode; onSelect: () => void; value: string; keywords?: string[]; icon?: ReactNode; hint?: ReactNode }) {
  return (
    <Command.Item value={value} keywords={keywords} onSelect={onSelect} className="mx-1 flex cursor-pointer items-center gap-3 rounded-md px-2.5 py-2 text-[13px] text-fg">
      <span className="text-muted">{icon}</span>
      <span className="flex min-w-0 flex-1 items-center gap-2">{children}</span>
      {hint && <span className="min-w-0 max-w-[38%] shrink truncate text-right text-2xs text-faint" title={typeof hint === 'string' ? hint : undefined}>{hint}</span>}
    </Command.Item>
  )
}

type Entry = { key: string; value: string; keywords?: string[]; node: ReactNode }

export function CommandPalette() {
  const { palette, setPalette, setHelp, setFyersLogin } = useUi()
  const nav = useNavigate()
  const { toggle } = useTheme()
  const { run } = useRunScan()
  const symbols = useSymbols()
  const strategies = useStrategies()
  const [search, setSearch] = useState('')
  const open = (o: boolean) => { setPalette(o); if (!o) setSearch('') }
  const go = (to: string) => { open(false); nav(to) }
  const act = (f: () => void) => { open(false); f() }

  const groups = useMemo(() => {
    const pages: Entry[] = [...NAV, SETTINGS_NAV].map((n) => {
      const Icon = n.icon
      const value = `page ${n.label}`
      return { key: n.id, value, node: <Item key={n.id} value={value} onSelect={() => go(n.to)} icon={<Icon className="h-4 w-4" />} hint={n.keys}>{n.label}</Item> }
    })
    const strats: Entry[] = (strategies.data?.strategies ?? []).map((s) => {
      const value = `strategy ${s.name} ${s.key}`
      const keywords = [s.horizon, s.evidence]
      return { key: s.key, value, keywords, node: (
        <Item key={s.key} value={value} keywords={keywords} onSelect={() => go(`/strategies/${s.key}`)} icon={<Trophy className="h-4 w-4" />} hint={s.horizon === 'longterm' ? 'Long-term' : s.horizon === 'swing' ? 'Swing' : 'Intraday'}>
          <StatusDot status={s.status} />
          <span className="truncate">{s.name}</span>
        </Item>
      ) }
    })
    const actions: Entry[] = [
      { key: 'full', value: 'action run full scan', node: <Item key="full" value="action run full scan" onSelect={() => act(() => run(true))} icon={<RefreshCw className="h-4 w-4" />}>Run full scan</Item> },
      { key: 'recheck', value: 'action re-check without download', node: <Item key="recheck" value="action re-check without download" onSelect={() => act(() => run(false))} icon={<RotateCw className="h-4 w-4" />}>Re-check without download</Item> },
      { key: 'login', value: 'action log in to fyers login', node: <Item key="login" value="action log in to fyers login" onSelect={() => act(() => setFyersLogin(true))} icon={<LogIn className="h-4 w-4" />}>Log in to Fyers</Item> },
      { key: 'theme', value: 'action toggle theme dark light', node: <Item key="theme" value="action toggle theme dark light" onSelect={() => act(toggle)} icon={<Moon className="h-4 w-4" />} hint="Shift T">Toggle dark / light</Item> },
      { key: 'help', value: 'action keyboard shortcuts help', node: <Item key="help" value="action keyboard shortcuts help" onSelect={() => act(() => setHelp(true))} icon={<Keyboard className="h-4 w-4" />} hint="?">Keyboard shortcuts</Item> },
    ]
    const syms: Entry[] = (symbols.data?.symbols ?? []).map((s) => {
      const value = `${s.symbol} ${s.company ?? ''}`
      const keywords = [s.industry ?? '']
      return { key: s.symbol, value, keywords, node: (
        <Item key={s.symbol} value={value} keywords={keywords} onSelect={() => go(`/chart/${s.symbol}`)} icon={<CandlestickChart className="h-4 w-4" />} hint={s.kind === 'stock' ? s.industry : s.kind.toUpperCase()}>
          <span className="font-semibold">{s.symbol}</span>
          <span className="truncate text-muted">{s.company}</span>
        </Item>
      ) }
    })
    return [
      { heading: 'Pages', items: pages }, { heading: 'Strategies', items: strats },
      { heading: 'Actions', items: actions }, { heading: 'Symbols', items: syms },
    ]
    // go/act/run close over stable setters; rebuilding on every render would re-render ~600 items per keystroke
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [strategies.data, symbols.data])

  // best match first (stable: the default order while nothing is typed)
  const ordered = useMemo(() => {
    if (!search.trim()) return groups
    const best = (g: (typeof groups)[number]) => g.items.reduce((m, e) => Math.max(m, paletteScore(e.value, search, e.keywords)), 0)
    return groups.map((g, i) => ({ g, i, b: best(g) })).sort((a, b) => b.b - a.b || a.i - b.i).map((x) => x.g)
  }, [groups, search])

  return (
    <Command.Dialog
      open={palette}
      onOpenChange={open}
      label="Command palette"
      filter={paletteScore}
      overlayClassName="fixed inset-0 z-50 bg-black/55"
      contentClassName="fixed left-1/2 top-[12vh] z-50 w-[640px] max-w-[calc(100vw-24px)] -translate-x-1/2 overflow-hidden rounded-xl bg-panel shadow-pop"
    >
      <div className="flex items-center gap-2.5 border-b border-line px-3.5">
        <Search className="h-4 w-4 text-faint" />
        <Command.Input autoFocus value={search} onValueChange={setSearch} placeholder="Search stocks, strategies, pages, actions…" className="h-12 flex-1 bg-transparent text-[14px] text-fg outline-none placeholder:text-faint" />
        <Kbd>Esc</Kbd>
      </div>
      <Command.List className="py-1.5">
        <Command.Empty>No match. Try a symbol like IGIL or a page like “signals”.</Command.Empty>
        {ordered.filter((g) => g.items.length > 0).map((g) => (
          <Command.Group key={g.heading} heading={g.heading}>
            {g.items.map((e) => e.node)}
          </Command.Group>
        ))}
      </Command.List>
    </Command.Dialog>
  )
}
