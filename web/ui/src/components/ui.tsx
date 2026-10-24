// UI primitives: Card, Button, Tabs, Segmented, Chip, Popover, Drawer, Dialog, Switch, Field, Kbd, Tip.
// Borders over shadows, 6 px control radius, 8 px card radius, colour only for meaning (spec 4.4).

import {
  forwardRef, isValidElement, useEffect, useId, useLayoutEffect, useRef, useState, type ButtonHTMLAttributes, type ReactNode, type Ref,
} from 'react'
import { createPortal } from 'react-dom'
import { Link } from 'react-router-dom'
import { ChevronDown, X } from 'lucide-react'
import { cn } from '@/lib/csv'

// ------------------------------------------------------------------ Card
export function Card({
  title, subtitle, right, children, className, bodyClass, flush, id,
}: {
  title?: ReactNode; subtitle?: ReactNode; right?: ReactNode; children: ReactNode; className?: string; bodyClass?: string; flush?: boolean; id?: string
}) {
  return (
    <section id={id} className={cn('card min-w-0', className)}>
      {(title || right) && (
        // The title block has a real basis (14rem), so on a narrow card the right-hand controls wrap onto their own
        // line instead of squeezing the title and subtitle into a one-word-per-line column.
        <header className="flex min-h-[44px] flex-wrap items-center gap-x-3 gap-y-1.5 border-b border-line px-4 py-2">
          <div className="min-w-0 flex-[1_1_14rem]">
            {/* wraps instead of truncating: on a phone "Breadth · % of stocks above their 5…" lost what it measures */}
            {title && <h2 className="break-words text-sm font-semibold text-fg">{title}</h2>}
            {/* up to 2 lines (never a 1-line cut that drops the meaning); the full text is in the tooltip */}
            {subtitle && <div className="text-xs text-muted sm:line-clamp-2" title={textOf(subtitle).trim() || undefined}>{subtitle}</div>}
          </div>
          {right && <div className="ml-auto flex shrink-0 flex-wrap items-center gap-2">{right}</div>}
        </header>
      )}
      <div className={cn(!flush && 'card-pad', bodyClass)}>{children}</div>
    </section>
  )
}

// ------------------------------------------------------------------ Button
type Variant = 'primary' | 'secondary' | 'ghost' | 'danger' | 'subtle'
const VARIANT: Record<Variant, string> = {
  primary: 'bg-accent-strong text-white hover:brightness-110 border border-transparent',
  secondary: 'bg-raised text-fg border border-line hover:border-line-strong',
  subtle: 'bg-transparent text-fg border border-line hover:bg-raised',
  ghost: 'bg-transparent text-muted hover:text-fg hover:bg-raised border border-transparent',
  danger: 'bg-loss/90 text-white hover:bg-loss border border-transparent',
}
export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant; size?: 'xs' | 'sm' | 'md'; icon?: ReactNode; iconRight?: ReactNode; loading?: boolean
}
export const Button = forwardRef(function Button(
  { variant = 'secondary', size = 'md', icon, iconRight, loading, className, children, disabled, type = 'button', ...rest }: ButtonProps,
  ref: Ref<HTMLButtonElement>,
) {
  return (
    <button
      ref={ref}
      type={type}
      disabled={disabled || loading}
      className={cn(
        'focus-ring inline-flex shrink-0 select-none items-center justify-center gap-1.5 whitespace-nowrap rounded-md font-medium transition-[background,border,color,filter] duration-100 disabled:cursor-not-allowed disabled:opacity-50',
        size === 'xs' ? 'h-6 px-2 text-2xs' : size === 'sm' ? 'h-7 px-2.5 text-xs' : 'h-8 px-3 text-[13px]',
        VARIANT[variant],
        className,
      )}
      {...rest}
    >
      {loading ? <Spinner className="h-3.5 w-3.5" /> : icon}
      {children}
      {iconRight}
    </button>
  )
})

export function IconButton({ label, className, children, size = 'md', ...rest }: ButtonHTMLAttributes<HTMLButtonElement> & { label: string; size?: 'sm' | 'md' }) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      className={cn(
        'focus-ring inline-flex shrink-0 items-center justify-center rounded-md text-muted transition-colors duration-100 hover:bg-raised hover:text-fg disabled:opacity-40',
        size === 'sm' ? 'h-7 w-7' : 'h-8 w-8',
        className,
      )}
      {...rest}
    >
      {children}
    </button>
  )
}

export function Spinner({ className }: { className?: string }) {
  return (
    <svg className={cn('animate-spin', className ?? 'h-4 w-4')} viewBox="0 0 24 24" fill="none" aria-hidden>
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeOpacity="0.25" strokeWidth="3" />
      <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
    </svg>
  )
}

// ------------------------------------------------------------------ Tabs (underline) and Segmented (pills)
export interface TabItem<T extends string> { id: T; label: ReactNode; count?: number | string | null; disabled?: boolean; badge?: ReactNode; to?: string }
export function Tabs<T extends string>({ items, value, onChange, className, size = 'md' }: {
  items: TabItem<T>[]; value: T; onChange?: (v: T) => void; className?: string; size?: 'sm' | 'md'
}) {
  return (
    <div role="tablist" className={cn('scroll-x no-scrollbar -mb-px flex items-end gap-1', className)}>
      {items.map((it) => {
        const active = it.id === value
        const cls = cn(
          'focus-ring relative inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap border-b-2 px-2 font-medium transition-colors duration-100 sm:px-2.5',
          size === 'sm' ? 'h-8 text-xs' : 'h-10 text-[13px]',
          active ? 'border-accent text-fg' : 'border-transparent text-muted hover:text-fg',
          it.disabled && 'pointer-events-none opacity-50',
        )
        const inner = (
          <>
            {it.label}
            {it.count != null && (
              <span className={cn('num rounded px-1 text-2xs', active ? 'bg-accent/15 text-accent' : 'bg-raised text-muted')}>{it.count}</span>
            )}
            {it.badge}
          </>
        )
        return it.to ? (
          <Link key={it.id} to={it.to} role="tab" aria-selected={active} className={cls} onClick={() => onChange?.(it.id)}>
            {inner}
          </Link>
        ) : (
          <button key={it.id} type="button" role="tab" aria-selected={active} disabled={it.disabled} className={cls} onClick={() => onChange?.(it.id)}>
            {inner}
          </button>
        )
      })}
    </div>
  )
}

export function Segmented<T extends string>({ items, value, onChange, size = 'sm', className, ariaLabel }: {
  items: { id: T; label: ReactNode; disabled?: boolean; title?: string }[]; value: T; onChange: (v: T) => void; size?: 'xs' | 'sm'; className?: string; ariaLabel?: string
}) {
  return (
    // Fixed outer heights that match the other controls: sm = 32 px (Button md, IconButton, SelectButton, .input),
    // xs = 28 px (Button sm) for card headers.
    <div role="radiogroup" aria-label={ariaLabel} className={cn('inline-flex shrink-0 items-stretch rounded-md border border-line bg-raised p-0.5', size === 'xs' ? 'h-7' : 'h-8', className)}>
      {items.map((it) => {
        const on = it.id === value
        return (
          <button
            key={it.id}
            type="button"
            role="radio"
            aria-checked={on}
            title={it.title}
            disabled={it.disabled}
            onClick={() => onChange(it.id)}
            className={cn(
              'focus-ring num inline-flex shrink-0 items-center gap-1 whitespace-nowrap rounded-[5px] font-medium transition-colors duration-100 disabled:cursor-not-allowed disabled:opacity-40',
              size === 'xs' ? 'px-2 text-2xs' : 'px-2.5 text-xs',
              on ? 'bg-panel text-fg shadow-[0_0_0_1px_rgb(var(--line-strong))]' : 'text-muted hover:text-fg',
            )}
          >
            {it.label}
          </button>
        )
      })}
    </div>
  )
}

// ------------------------------------------------------------------ Chip
export function Chip({ children, className, title, icon }: { children: ReactNode; className?: string; title?: string; icon?: ReactNode }) {
  return (
    <span title={title} className={cn('inline-flex h-5 shrink-0 items-center gap-1 whitespace-nowrap rounded-full px-2 text-2xs font-medium leading-none', className ?? 'bg-raised text-muted')}>
      {icon}
      {children}
    </span>
  )
}

export function Kbd({ children }: { children: ReactNode }) {
  return <kbd className="inline-flex h-5 min-w-[20px] items-center justify-center rounded border border-line bg-raised px-1 font-sans text-2xs font-medium text-muted">{children}</kbd>
}

/** Space kept clear at the top of the viewport for the sticky top bar (h-12 + the 2 px progress bar). */
export const TOP_BAR_H = 50

/**
 * Hover/focus tooltip for short help text (not for table cells inside scroll containers: use title there).
 * Rendered in a portal with fixed positioning, measured on open: kept 8 px inside the viewport horizontally and
 * flipped to the other side when it would land under the top bar (or off the bottom), so it is never clipped by a
 * card, main's overflow clip or the screen edge.
 */
export function Tip({ text, children, className, side = 'top' }: { text: ReactNode; children: ReactNode; className?: string; side?: 'top' | 'bottom' }) {
  const anchor = useRef<HTMLSpanElement>(null)
  const tip = useRef<HTMLSpanElement>(null)
  const [open, setOpen] = useState(false)
  const [pos, setPos] = useState<{ left: number; top: number } | null>(null)
  useLayoutEffect(() => {
    if (!open) { setPos(null); return }
    const a = anchor.current?.getBoundingClientRect()
    const t = tip.current
    if (!a || !t) return
    const w = t.offsetWidth
    const h = t.offsetHeight
    const vw = document.documentElement.clientWidth
    const left = Math.max(8, Math.min(a.left + a.width / 2 - w / 2, vw - 8 - w))
    const above = a.top - 6 - h
    const below = a.bottom + 6
    const fitsAbove = above >= TOP_BAR_H + 6
    const fitsBelow = below + h <= window.innerHeight - 8
    const top = side === 'top' ? (fitsAbove || !fitsBelow ? above : below) : (fitsBelow || !fitsAbove ? below : above)
    setPos({ left, top })
  }, [open, side, text])
  useEffect(() => {
    if (!open) return
    const close = () => setOpen(false)
    window.addEventListener('scroll', close, { passive: true, capture: true })
    return () => window.removeEventListener('scroll', close, { capture: true })
  }, [open])
  return (
    <span
      ref={anchor}
      className={cn('relative inline-flex', className)}
      tabIndex={-1}
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
      onFocus={() => setOpen(true)}
      onBlur={() => setOpen(false)}
    >
      {children}
      {open && createPortal(
        <span
          ref={tip}
          role="tooltip"
          style={pos ? { left: pos.left, top: pos.top } : { left: 0, top: 0, visibility: 'hidden' }}
          className="pointer-events-none fixed z-[60] block w-max max-w-[min(280px,calc(100vw-16px))] rounded-md bg-raised px-2.5 py-1.5 text-xs font-normal normal-case tracking-normal text-fg shadow-pop"
        >
          {text}
        </span>,
        document.body,
      )}
    </span>
  )
}

// ------------------------------------------------------------------ Popover / menu
// Open overlays (popovers, dialogs, drawers) in opening order: only the topmost one closes on Escape,
// e.g. the Fyers-import Dialog inside the holdings Drawer closes without discarding the Drawer's edits.
const overlayStack: number[] = []
let overlaySeq = 0

export function Popover({ trigger, children, align = 'left', className, open: openProp, onOpenChange, width }: {
  trigger: (p: { open: boolean; toggle: () => void; id: string }) => ReactNode; children: ReactNode | ((close: () => void) => ReactNode);
  align?: 'left' | 'right'; className?: string; open?: boolean; onOpenChange?: (o: boolean) => void; width?: number
}) {
  const [inner, setInner] = useState(false)
  const open = openProp ?? inner
  const set = (o: boolean) => { setInner(o); onOpenChange?.(o) }
  const ref = useRef<HTMLDivElement>(null)
  const panelRef = useRef<HTMLDivElement>(null)
  const [dx, setDx] = useState(0)
  const id = useId()
  useEffect(() => {
    if (!open) return
    const sid = ++overlaySeq
    overlayStack.push(sid)
    const onDown = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) set(false) }
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape' && overlayStack[overlayStack.length - 1] === sid) set(false) }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
      const i = overlayStack.indexOf(sid)
      if (i >= 0) overlayStack.splice(i, 1)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])
  // Keep the panel inside the viewport (phones: a right-aligned 360 px panel would run off the left edge).
  useLayoutEffect(() => {
    const el = panelRef.current
    if (!open || !el) { if (dx !== 0) setDx(0); return }
    const r = el.getBoundingClientRect()
    const vw = document.documentElement.clientWidth
    const left = r.left - dx
    const right = r.right - dx
    const next = left < 8 ? 8 - left : right > vw - 8 ? Math.max(8 - left, vw - 8 - right) : 0
    if (next !== dx) setDx(next)
  }, [open, dx])
  const close = () => set(false)
  return (
    <div ref={ref} className="relative inline-flex">
      {trigger({ open, toggle: () => set(!open), id })}
      {open && (
        <div
          id={id}
          ref={panelRef}
          style={{ ...(width ? { width } : {}), maxWidth: 'calc(100vw - 16px)', translate: dx ? `${dx}px 0` : undefined }}
          className={cn('animate-in absolute top-full z-40 mt-1.5 min-w-[200px] rounded-lg bg-panel p-1 shadow-pop', align === 'right' ? 'right-0' : 'left-0', className)}
        >
          {typeof children === 'function' ? children(close) : children}
        </div>
      )}
    </div>
  )
}

export function MenuItem({ children, onClick, icon, hint, disabled, active }: {
  children: ReactNode; onClick?: () => void; icon?: ReactNode; hint?: ReactNode; disabled?: boolean; active?: boolean
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className={cn(
        'focus-ring flex w-full items-center gap-2.5 rounded-md px-2.5 py-1.5 text-left text-[13px] text-fg hover:bg-raised disabled:cursor-not-allowed disabled:opacity-50',
        active && 'bg-raised',
      )}
    >
      {icon && <span className="text-muted">{icon}</span>}
      <span className="min-w-0 flex-1">{children}</span>
      {hint && <span className="shrink-0 text-2xs text-faint">{hint}</span>}
    </button>
  )
}

/** Plain text of a small ReactNode (strings, numbers, nested elements' children): for aria-label. */
export function textOf(n: ReactNode): string {
  if (n == null || typeof n === 'boolean') return ''
  if (typeof n === 'string' || typeof n === 'number') return String(n)
  if (Array.isArray(n)) return n.map(textOf).join('')
  if (isValidElement(n)) return textOf((n.props as { children?: ReactNode }).children)
  return ''
}

export function MenuCheck({ checked, onChange, children, disabled }: { checked: boolean; onChange: (v: boolean) => void; children: ReactNode; disabled?: boolean }) {
  return (
    <label className={cn('flex cursor-pointer items-center gap-2.5 rounded-md px-2.5 py-1.5 text-[13px] hover:bg-raised', disabled && 'pointer-events-none opacity-50')}>
      <input type="checkbox" aria-label={textOf(children).trim() || undefined} className="h-3.5 w-3.5 accent-[rgb(var(--accent))]" checked={checked} disabled={disabled} onChange={(e) => onChange(e.target.checked)} />
      <span className="min-w-0 flex-1">{children}</span>
    </label>
  )
}

export function SelectButton({ label, value, open, onClick }: { label: string; value?: ReactNode; open: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-expanded={open}
      className={cn('focus-ring inline-flex h-8 items-center gap-1.5 rounded-md border bg-raised px-2.5 text-[13px] transition-colors', open ? 'border-line-strong' : 'border-line hover:border-line-strong')}
    >
      <span className="text-muted">{label}</span>
      {value != null && <span className="font-medium text-fg">{value}</span>}
      <ChevronDown className="h-3.5 w-3.5 text-faint" />
    </button>
  )
}

// ------------------------------------------------------------------ Drawer and Dialog
// The body scroll lock is ref-counted so nested overlays never leave the page unscrollable.
let lockDepth = 0
let savedOverflow = ''
function useLockScroll(on: boolean, onClose: () => void) {
  const closeRef = useRef(onClose)
  useEffect(() => { closeRef.current = onClose })
  useEffect(() => {
    if (!on) return
    const id = ++overlaySeq
    overlayStack.push(id)
    if (lockDepth++ === 0) { savedOverflow = document.body.style.overflow; document.body.style.overflow = 'hidden' }
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape' && overlayStack[overlayStack.length - 1] === id) closeRef.current() }
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('keydown', onKey)
      const i = overlayStack.indexOf(id)
      if (i >= 0) overlayStack.splice(i, 1)
      if (--lockDepth === 0) document.body.style.overflow = savedOverflow
    }
  }, [on])
}

export function Drawer({ open, onClose, title, subtitle, children, footer, width = 560 }: {
  open: boolean; onClose: () => void; title: ReactNode; subtitle?: ReactNode; children: ReactNode; footer?: ReactNode; width?: number
}) {
  useLockScroll(open, onClose)
  if (!open) return null
  return createPortal(
    <div className="fixed inset-0 z-50 flex justify-end">
      <div className="absolute inset-0 bg-black/50" onClick={onClose} aria-hidden />
      <aside role="dialog" aria-modal="true" className="animate-drawer relative flex h-full w-full flex-col border-l border-line bg-panel" style={{ maxWidth: width }}>
        <header className="flex items-start gap-3 border-b border-line px-5 py-3.5">
          <div className="min-w-0 flex-1">
            <h2 className="text-base font-semibold">{title}</h2>
            {subtitle && <p className="mt-0.5 text-xs text-muted">{subtitle}</p>}
          </div>
          <IconButton label="Close" onClick={onClose}><X className="h-4 w-4" /></IconButton>
        </header>
        <div className="min-h-0 flex-1 overflow-auto px-5 py-4">{children}</div>
        {footer && <footer className="flex flex-wrap items-center justify-end gap-2 border-t border-line px-5 py-3">{footer}</footer>}
      </aside>
    </div>,
    document.body,
  )
}

export function Dialog({ open, onClose, title, children, footer, width = 520 }: {
  open: boolean; onClose: () => void; title: ReactNode; children: ReactNode; footer?: ReactNode; width?: number
}) {
  useLockScroll(open, onClose)
  if (!open) return null
  return createPortal(
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-auto p-4 pt-[10vh]">
      <div className="fixed inset-0 bg-black/55" onClick={onClose} aria-hidden />
      <div role="dialog" aria-modal="true" className="animate-in relative w-full rounded-xl bg-panel shadow-pop" style={{ maxWidth: width }}>
        <header className="flex items-center gap-3 border-b border-line px-5 py-3.5">
          <h2 className="min-w-0 flex-1 text-base font-semibold">{title}</h2>
          <IconButton label="Close" onClick={onClose}><X className="h-4 w-4" /></IconButton>
        </header>
        <div className="max-h-[70vh] overflow-auto px-5 py-4">{children}</div>
        {footer && <footer className="flex flex-wrap items-center justify-end gap-2 border-t border-line px-5 py-3">{footer}</footer>}
      </div>
    </div>,
    document.body,
  )
}

// ------------------------------------------------------------------ form bits
export function Switch({ checked, onChange, label, disabled, ariaLabel }: { checked: boolean; onChange: (v: boolean) => void; label?: ReactNode; disabled?: boolean; ariaLabel?: string }) {
  return (
    <label className={cn('inline-flex cursor-pointer select-none items-center gap-2 text-[13px]', disabled && 'pointer-events-none opacity-50')}>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        aria-label={ariaLabel ?? (textOf(label).trim() || undefined)}
        onClick={() => onChange(!checked)}
        className={cn('focus-ring relative h-[18px] w-8 shrink-0 rounded-full border transition-colors duration-100', checked ? 'border-accent bg-accent' : 'border-faint/50 bg-line-strong')}
      >
        {/* left-[1px] is required: a <button> centres its content, so without a left offset the knob's static position
            is the middle of the track and the translate starts from there (off looked on; on hung outside). Inner
            track is 30 x 16 px; the 14 px knob sits 1 px from either end. */}
        <span className={cn('absolute left-[1px] top-[1px] h-3.5 w-3.5 rounded-full bg-white shadow-[0_1px_2px_rgb(0_0_0/0.3)] transition-transform duration-100', checked ? 'translate-x-[14px]' : 'translate-x-0')} />
      </button>
      {label && <span className="text-fg">{label}</span>}
    </label>
  )
}

export function Field({ label, hint, error, children, className }: { label: ReactNode; hint?: ReactNode; error?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <label className={cn('flex flex-col gap-1', className)}>
      <span className="text-xs font-medium text-muted">{label}</span>
      {children}
      {error ? <span className="text-2xs text-loss">{error}</span> : hint ? <span className="text-2xs text-faint">{hint}</span> : null}
    </label>
  )
}

/** Key/value row for detail panels. */
export function KV({ k, v, className, title }: { k: ReactNode; v: ReactNode; className?: string; title?: string }) {
  return (
    <div className={cn('flex items-baseline justify-between gap-4 py-1.5', className)} title={title}>
      <span className="text-xs text-muted">{k}</span>
      <span className="num text-right text-[13px] text-fg">{v}</span>
    </div>
  )
}

export function SectionTitle({ children, right, className }: { children: ReactNode; right?: ReactNode; className?: string }) {
  return (
    <div className={cn('flex items-center justify-between gap-3', className)}>
      <h3 className="eyebrow">{children}</h3>
      {right}
    </div>
  )
}
