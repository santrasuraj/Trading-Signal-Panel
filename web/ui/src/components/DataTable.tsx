// One DataTable for the whole app (spec 4.5), on TanStack Table 8:
// sticky header, sticky first column, numeric columns right-aligned with tabular numbers, 3-state sort (Shift for
// multi-sort, nulls always last), hover + selected row, j/k/Enter keyboard, '/' focuses the filter box, column
// chooser persisted per table id, client-side CSV export of raw values, optional pagination, and a list layout on
// phones (line 1 symbol · value · change, line 2 muted secondary fields).

import { useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import {
  flexRender, getCoreRowModel, getFilteredRowModel, getPaginationRowModel, getSortedRowModel, useReactTable,
  type ColumnDef, type Header, type Row, type SortingState, type VisibilityState,
} from '@tanstack/react-table'
import { ArrowDown, ArrowUp, ChevronLeft, ChevronRight, Columns3, Download, Search } from 'lucide-react'
import { cn, downloadText, toCsv } from '@/lib/csv'
import { useLocalStorage } from '@/lib/useLocalStorage'
import { typingTarget, useIsMobile } from '@/lib/useMedia'
import { useWidth } from '@/lib/useWidth'
import { IconButton, MenuCheck, Popover, TOP_BAR_H } from './ui'
import { EmptyState } from './feedback'

export interface Col<T> {
  id: string
  header: ReactNode
  /** CSV header / column chooser label when header is not a plain string. */
  label?: string
  title?: string
  value: (r: T) => string | number | boolean | null | undefined
  cell?: (r: T) => ReactNode
  align?: 'left' | 'right' | 'center'
  width?: number
  minWidth?: number
  sticky?: boolean
  defaultHidden?: boolean
  /** Low-priority column: hidden by default while the table's box is narrower than this many px (the column
   *  chooser can still show it). Keeps the columns that matter on screen in split windows and on laptops. */
  hideBelow?: number
  sortable?: boolean
  /** Phone list layout role. */
  mobile?: 'primary' | 'value' | 'change' | 'secondary'
  /** Cell for the phone list layout when the table cell is too wide for it (e.g. a value with a range bar). */
  mobileCell?: (r: T) => ReactNode
  className?: string
  /** Text the filter box searches for this column (default: String(value)), e.g. symbol + company. */
  search?: (r: T) => string | null | undefined
  /** An extra CSV column written right after this one (e.g. the company behind a symbol cell). */
  csvExtra?: { label: string; value: (r: T) => unknown }
}

export interface DataTableProps<T> {
  id: string
  data: T[]
  columns: Col<T>[]
  rowKey: (r: T) => string
  onRowClick?: (r: T) => void
  initialSort?: SortingState
  filterable?: boolean
  filterPlaceholder?: string
  toolbar?: ReactNode
  toolbarRight?: ReactNode
  exportName?: string
  columnChooser?: boolean
  pageSize?: number
  rowClassName?: (r: T) => string | undefined
  empty?: ReactNode
  maxHeight?: number | string
  keyboard?: boolean
  footer?: ReactNode
  className?: string
  /** Disable sorting entirely (server order matters, e.g. evidence order). */
  sortable?: boolean
  onSortingChange?: (s: SortingState) => void
  sorting?: SortingState
  hideHeaderOnMobile?: boolean
  /** table-layout: fixed with each column's `width`: stacked tables with the same columns line up exactly. */
  fixedLayout?: boolean
}

const norm = (v: unknown) => (v === null || (typeof v === 'number' && !Number.isFinite(v)) ? undefined : v)

/** A column is shown unless the viewer hid it, or (no choice stored) it is hidden by default or low-priority for a
 *  box this narrow. */
function colVisible<T>(c: Col<T>, hidden: Record<string, boolean>, boxW: number): boolean {
  if (hidden[c.id] != null) return !hidden[c.id]
  return !(c.defaultHidden || (c.hideBelow != null && boxW > 0 && boxW < c.hideBelow))
}

/** The column chooser on its own, for pages that stack several tables with one shared column choice (same `id`
 *  as the DataTables); `boxWidth` is the tables' width, for low-priority columns. */
export function ColumnChooser<T>({ id, columns, boxWidth = 0 }: { id: string; columns: Col<T>[]; boxWidth?: number }) {
  const [hidden, setHidden] = useLocalStorage<Record<string, boolean>>(`qd.cols.${id}`, {})
  const isMobile = useIsMobile()
  if (isMobile) return null
  return (
    <Popover align="right" trigger={({ toggle }) => <IconButton label="Columns" onClick={toggle} className="border border-line bg-raised"><Columns3 className="h-4 w-4" /></IconButton>}>
      <div className="max-h-[320px] overflow-auto py-1">
        <div className="eyebrow px-2.5 pb-1 pt-1">Columns</div>
        {columns.filter((c) => !c.sticky).map((c) => (
          <MenuCheck key={c.id} checked={colVisible(c, hidden, boxWidth)} onChange={(on) => setHidden((h) => ({ ...h, [c.id]: !on }))}>
            {c.label ?? (typeof c.header === 'string' ? c.header : c.id)}
          </MenuCheck>
        ))}
      </div>
    </Popover>
  )
}

export function DataTable<T>(p: DataTableProps<T>) {
  const isMobile = useIsMobile()
  const [innerSorting, setInnerSorting] = useState<SortingState>(p.initialSort ?? [])
  const sorting = p.sorting ?? innerSorting
  const [filter, setFilter] = useState('')
  const [hidden, setHidden] = useLocalStorage<Record<string, boolean>>(`qd.cols.${p.id}`, {})
  const [selected, setSelected] = useState<number>(-1)
  const filterRef = useRef<HTMLInputElement>(null)
  const bodyRef = useRef<HTMLTableSectionElement>(null)
  const scrollRef = useRef<HTMLDivElement>(null)
  const tableRef = useRef<HTMLTableElement>(null)
  const floatRef = useRef<HTMLDivElement>(null)
  const [rootRef, boxW] = useWidth<HTMLDivElement>()

  const visibility: VisibilityState = useMemo(() => {
    const v: VisibilityState = {}
    for (const c of p.columns) v[c.id] = colVisible(c, hidden, boxW)
    return v
  }, [p.columns, hidden, boxW])

  const defs: ColumnDef<T>[] = useMemo(
    () =>
      p.columns.map((c) => ({
        id: c.id,
        accessorFn: (r: T) => norm(c.value(r)),
        header: () => c.header,
        cell: (ctx) => (c.cell ? c.cell(ctx.row.original) : (ctx.getValue() as ReactNode) ?? null),
        enableSorting: p.sortable !== false && c.sortable !== false,
        sortUndefined: 'last',
        sortDescFirst: c.align === 'right',
        meta: c,
      })),
    [p.columns, p.sortable],
  )

  const table = useReactTable({
    data: p.data,
    columns: defs,
    state: { sorting, globalFilter: filter, columnVisibility: visibility },
    onSortingChange: (u) => {
      const next = typeof u === 'function' ? u(sorting) : u
      if (p.onSortingChange) p.onSortingChange(next)
      else setInnerSorting(next)
    },
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    getPaginationRowModel: p.pageSize ? getPaginationRowModel() : undefined,
    initialState: p.pageSize ? { pagination: { pageIndex: 0, pageSize: p.pageSize } } : undefined,
    enableMultiSort: true,
    isMultiSortEvent: (e) => (e as MouseEvent).shiftKey,
    globalFilterFn: (row, _id, value: string) => {
      const q = value.trim().toLowerCase()
      if (!q) return true
      return p.columns.some((c) => {
        const v = c.search ? c.search(row.original) : c.value(row.original)
        return v != null && String(v).toLowerCase().includes(q)
      })
    },
    getRowId: (r) => p.rowKey(r),
  })

  const rows = table.getRowModel().rows

  // Floating header. The real <thead> is sticky only inside the horizontal scroll box (overflow-x makes that box the
  // sticky container), so on a long page the column names scrolled away. While the table's top is under the top bar,
  // a copy of the header row (same column widths, same sort buttons, horizontal scroll kept in step) sticks below it.
  const floatable = !p.maxHeight && !isMobile && rows.length > 0
  const [float, setFloat] = useState<{ cols: number[]; width: number } | null>(null)
  useEffect(() => {
    if (!floatable) { setFloat(null); return }
    let raf = 0
    const check = () => {
      raf = 0
      const t = tableRef.current
      if (!t) return
      const r = t.getBoundingClientRect()
      const head = t.tHead?.getBoundingClientRect().height ?? 32
      if (!(r.top < TOP_BAR_H && r.bottom > TOP_BAR_H + head * 2)) { setFloat((f) => (f ? null : f)); return }
      const cells = t.tHead?.rows[0]?.cells
      const cols = cells ? Array.from(cells, (c) => c.getBoundingClientRect().width) : []
      setFloat((f) => (f && f.width === r.width && f.cols.length === cols.length && f.cols.every((x, i) => x === cols[i]) ? f : { cols, width: r.width }))
    }
    const on = () => { if (!raf) raf = requestAnimationFrame(check) }
    check()
    window.addEventListener('scroll', on, { passive: true })
    window.addEventListener('resize', on)
    return () => {
      window.removeEventListener('scroll', on)
      window.removeEventListener('resize', on)
      if (raf) cancelAnimationFrame(raf)
    }
  }, [floatable, rows, visibility])
  useLayoutEffect(() => {
    if (float && floatRef.current && scrollRef.current) floatRef.current.scrollLeft = scrollRef.current.scrollLeft
  }, [float])

  // keyboard: j/k move, Enter opens, '/' focuses the filter
  useEffect(() => {
    if (!p.keyboard) return
    const onKey = (e: KeyboardEvent) => {
      if (e.ctrlKey || e.metaKey || e.altKey) return
      if (e.key === '/' && !typingTarget(e) && p.filterable) {
        e.preventDefault()
        filterRef.current?.focus()
        return
      }
      if (typingTarget(e)) {
        if (e.key === 'Escape' && document.activeElement === filterRef.current) filterRef.current?.blur()
        return
      }
      if (e.key === 'j' || e.key === 'k') {
        e.preventDefault()
        setSelected((s) => {
          const n = e.key === 'j' ? Math.min(rows.length - 1, s + 1) : Math.max(0, s - 1)
          bodyRef.current?.querySelector<HTMLElement>(`[data-ri="${n}"]`)?.scrollIntoView({ block: 'nearest' })
          return n
        })
      } else if (e.key === 'Enter' && selected >= 0 && rows[selected] && p.onRowClick) {
        p.onRowClick(rows[selected].original)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [p.keyboard, p.filterable, p.onRowClick, rows, selected])

  function exportCsv() {
    const sortedRows = table.getPrePaginationRowModel().rows
    // visible columns that carry a value (sparklines / action buttons have none), plus their CSV extras
    const cols = p.columns.filter((c) => visibility[c.id] !== false && sortedRows.some((r) => c.value(r.original) != null))
    const out: { label: string; value: (r: T) => unknown }[] = cols.flatMap((c) => [
      { label: c.label ?? (typeof c.header === 'string' ? c.header : c.id), value: c.value },
      ...(c.csvExtra ? [c.csvExtra] : []),
    ])
    downloadText(`${p.exportName ?? p.id}.csv`, toCsv(out.map((c) => c.label), sortedRows.map((r) => out.map((c) => c.value(r.original)))))
  }

  const showToolbar = p.filterable || p.toolbar || p.toolbarRight || p.exportName || p.columnChooser
  const toolbar = showToolbar && (
    <div className="flex flex-wrap items-center gap-2 border-b border-line px-3 py-2">
      {p.filterable && (
        <label className="relative flex min-w-[160px] max-w-[260px] flex-1 items-center">
          <Search className="pointer-events-none absolute left-2.5 h-3.5 w-3.5 text-faint" />
          <input
            ref={filterRef}
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder={p.filterPlaceholder ?? 'Filter…'}
            aria-label="Filter rows"
            className="input h-8 w-full pl-8 text-xs"
          />
          {p.keyboard && !filter && <span className="pointer-events-none absolute right-2 text-2xs text-faint">/</span>}
        </label>
      )}
      {p.toolbar}
      <div className="ml-auto flex items-center gap-1">
        {filter.trim() && <span className="num px-1 text-xs text-muted" aria-live="polite">{table.getPrePaginationRowModel().rows.length} of {p.data.length}</span>}
        {p.toolbarRight}
        {p.columnChooser && !isMobile && (
          <Popover align="right" trigger={({ toggle }) => <IconButton label="Columns" onClick={toggle}><Columns3 className="h-4 w-4" /></IconButton>}>
            <div className="max-h-[320px] overflow-auto py-1">
              <div className="eyebrow px-2.5 pb-1 pt-1">Columns</div>
              {p.columns.filter((c) => !c.sticky).map((c) => (
                <MenuCheck key={c.id} checked={visibility[c.id] !== false} onChange={(on) => setHidden((h) => ({ ...h, [c.id]: !on }))}>
                  {c.label ?? (typeof c.header === 'string' ? c.header : c.id)}
                </MenuCheck>
              ))}
            </div>
          </Popover>
        )}
        {p.exportName && (
          <IconButton label="Export CSV" onClick={exportCsv}><Download className="h-4 w-4" /></IconButton>
        )}
      </div>
    </div>
  )

  const pager = p.pageSize && table.getPageCount() > 1 && (
    <div className="flex items-center justify-end gap-2 border-t border-line px-3 py-1.5 text-xs text-muted">
      <span className="num">
        {table.getState().pagination.pageIndex * p.pageSize + 1}–{Math.min(rows.length + table.getState().pagination.pageIndex * p.pageSize, table.getPrePaginationRowModel().rows.length)} of {table.getPrePaginationRowModel().rows.length}
      </span>
      <IconButton size="sm" label="Previous page" disabled={!table.getCanPreviousPage()} onClick={() => table.previousPage()}><ChevronLeft className="h-4 w-4" /></IconButton>
      <IconButton size="sm" label="Next page" disabled={!table.getCanNextPage()} onClick={() => table.nextPage()}><ChevronRight className="h-4 w-4" /></IconButton>
    </div>
  )

  if (rows.length === 0) {
    // An empty table keeps its filter box (the filter may be what emptied it) and any page controls, but not a row
    // holding only an Export / Columns icon: there is nothing to export or show.
    return (
      <div ref={rootRef} className={cn('min-w-0', p.className)}>
        {(p.filterable || p.toolbar || p.toolbarRight) && toolbar}
        {p.empty ?? <EmptyState title={filter ? 'No rows match the filter' : 'Nothing to show'} compact />}
      </div>
    )
  }

  if (isMobile) return <div ref={rootRef} className={cn('min-w-0', p.className)}>{toolbar}<MobileList rows={rows} cols={p.columns} onRowClick={p.onRowClick} rowClassName={p.rowClassName} />{pager}{p.footer}</div>

  const headCell = (h: Header<T, unknown>, clone: boolean) => {
    const c = h.column.columnDef.meta as Col<T>
    const sorted = h.column.getIsSorted()
    const canSort = h.column.getCanSort()
    return (
      <th
        key={h.id}
        scope="col"
        title={c.title}
        aria-sort={clone ? undefined : sorted === 'asc' ? 'ascending' : sorted === 'desc' ? 'descending' : 'none'}
        style={clone ? undefined : { width: c.width, minWidth: c.minWidth ?? c.width }}
        className={cn(
          'h-8 whitespace-nowrap border-b border-line bg-raised px-3 text-2xs font-semibold uppercase tracking-[0.04em] text-muted',
          !clone && 'sticky top-0 z-10',
          c.align === 'right' ? 'text-right' : c.align === 'center' ? 'text-center' : 'text-left',
          c.sticky && 'qd-sticky sticky left-0 z-20',
        )}
      >
        {canSort ? (
          <button
            type="button"
            tabIndex={clone ? -1 : undefined}
            onClick={h.column.getToggleSortingHandler()}
            className={cn('focus-ring inline-flex items-center gap-1 rounded-sm uppercase hover:text-fg', c.align === 'right' && 'flex-row-reverse', sorted && 'text-fg')}
          >
            {flexRender(h.column.columnDef.header, h.getContext())}
            <span className={cn('inline-flex w-3', !sorted && 'opacity-0')}>
              {sorted === 'desc' ? <ArrowDown className="h-3 w-3" /> : <ArrowUp className="h-3 w-3" />}
            </span>
          </button>
        ) : (
          flexRender(h.column.columnDef.header, h.getContext())
        )}
      </th>
    )
  }

  return (
    // qd-hscroll / qd-x / qd-edge-r / qd-sticky: CSS scroll cues (index.css): a fade over the cut right edge while
    // more columns are off to the right, and a shadow on the sticky column once scrolled.
    <div ref={rootRef} className={cn('qd-hscroll min-w-0', p.className)}>
      {toolbar}
      {float && (
        <div className="sticky z-[25] h-0" style={{ top: TOP_BAR_H }} aria-hidden>
          <div className="relative shadow-[0_3px_6px_-3px_rgb(0_0_0/0.2)]">
            <div ref={floatRef} className="overflow-hidden">
              <table className="border-separate border-spacing-0 text-[13px]" style={{ width: float.width, tableLayout: 'fixed' }}>
                <colgroup>{float.cols.map((w, i) => <col key={i} style={{ width: w }} />)}</colgroup>
                <thead>{table.getHeaderGroups().map((hg) => <tr key={hg.id}>{hg.headers.map((h) => headCell(h, true))}</tr>)}</thead>
              </table>
            </div>
            <div className="qd-edge-r pointer-events-none absolute inset-y-0 right-0 w-8 bg-gradient-to-l from-raised" />
          </div>
        </div>
      )}
      <div className="relative">
        <div
          ref={scrollRef}
          className="scroll-x qd-x relative"
          style={p.maxHeight ? { maxHeight: p.maxHeight, overflowY: 'auto' } : undefined}
          onScroll={(e) => { if (floatRef.current) floatRef.current.scrollLeft = e.currentTarget.scrollLeft }}
        >
        <table ref={tableRef} className={cn('w-full border-separate border-spacing-0 text-[13px]', p.fixedLayout && 'table-fixed')}>
          <thead>
            {table.getHeaderGroups().map((hg) => <tr key={hg.id}>{hg.headers.map((h) => headCell(h, false))}</tr>)}
          </thead>
          <tbody ref={bodyRef}>
            {rows.map((row, i) => {
              const sel = i === selected
              return (
                <tr
                  key={row.id}
                  data-ri={i}
                  onClick={p.onRowClick ? () => { setSelected(i); p.onRowClick!(row.original) } : undefined}
                  className={cn('group scroll-mt-[90px]', p.onRowClick && 'cursor-pointer', p.rowClassName?.(row.original))}
                >
                  {row.getVisibleCells().map((cell, ci) => {
                    const c = cell.column.columnDef.meta as Col<T>
                    return (
                      <td
                        key={cell.id}
                        className={cn(
                          'h-row whitespace-nowrap border-b border-line/70 px-3 py-1 align-middle transition-colors duration-75',
                          c.align === 'right' ? 'num text-right' : c.align === 'center' ? 'text-center' : 'text-left',
                          c.sticky ? 'qd-sticky sticky left-0 z-[1] bg-panel' : '',
                          sel ? 'bg-accent/[0.08]' : 'group-hover:bg-raised',
                          c.sticky && sel && 'bg-[rgb(var(--panel))]',
                          ci === 0 && sel && 'shadow-[inset_2px_0_0_rgb(var(--accent))]',
                          c.className,
                        )}
                      >
                        {flexRender(cell.column.columnDef.cell, cell.getContext())}
                      </td>
                    )
                  })}
                </tr>
              )
            })}
          </tbody>
        </table>
        </div>
        <div className="qd-edge-r pointer-events-none absolute inset-y-0 right-0 z-[15] w-8 bg-gradient-to-l from-panel" />
      </div>
      {pager}
      {p.footer}
    </div>
  )
}

function MobileList<T>({ rows, cols, onRowClick, rowClassName }: { rows: Row<T>[]; cols: Col<T>[]; onRowClick?: (r: T) => void; rowClassName?: (r: T) => string | undefined }) {
  const primary = cols.find((c) => c.mobile === 'primary') ?? cols[0]
  const value = cols.find((c) => c.mobile === 'value')
  const change = cols.find((c) => c.mobile === 'change')
  const secondary = cols.filter((c) => c.mobile === 'secondary').slice(0, 4)
  const render = (c: Col<T>, r: T) => (c.mobileCell ? c.mobileCell(r) : c.cell ? c.cell(r) : String(c.value(r) ?? '—'))
  return (
    <ul className="divide-y divide-line">
      {rows.map((row) => {
        const r = row.original
        return (
          <li key={row.id}>
            <button
              type="button"
              disabled={!onRowClick}
              onClick={() => onRowClick?.(r)}
              className={cn('flex w-full flex-col gap-0.5 px-4 py-2.5 text-left active:bg-raised', rowClassName?.(r))}
            >
              <div className="flex w-full items-center gap-2">
                {/* wraps rather than truncating: a long name ("Media Entertainment & Publication", "Intraday
                    momentum (morning predicts close)") is the row's identity; stock cells truncate the company themselves */}
                <div className="min-w-0 flex-1 overflow-hidden break-words">{render(primary, r)}</div>
                {value && <div className="num text-[13px]">{render(value, r)}</div>}
                {change && <div className="num w-[72px] text-right text-[13px]">{render(change, r)}</div>}
              </div>
              {secondary.length > 0 && (
                <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5 text-xs text-muted">
                  {secondary.map((c) => (
                    <span key={c.id} className="inline-flex items-center gap-1">
                      <span className="text-faint">{c.label ?? (typeof c.header === 'string' ? c.header : '')}</span>
                      <span className="num text-muted">{render(c, r)}</span>
                    </span>
                  ))}
                </div>
              )}
            </button>
          </li>
        )
      })}
    </ul>
  )
}

/** Symbol + company cell used by every stock table. */
export function SymbolCell({ symbol, company, extra }: { symbol: string; company?: string | null; extra?: ReactNode }) {
  return (
    <div className="flex min-w-0 flex-col leading-tight">
      <span className="flex items-center gap-1.5">
        <span className="font-semibold text-fg">{symbol}</span>
        {extra}
      </span>
      {company && <span className="max-w-[220px] truncate text-2xs text-muted [[data-density=compact]_&]:hidden" title={company}>{company}</span>}
    </div>
  )
}
