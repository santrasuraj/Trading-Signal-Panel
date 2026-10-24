import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { CheckCircle2, Info, X, XCircle } from 'lucide-react'
import { cn } from '@/lib/csv'

type ToastTone = 'good' | 'bad' | 'info'
interface ToastItem { id: number; tone: ToastTone; title: ReactNode; detail?: ReactNode }
const Ctx = createContext<(t: Omit<ToastItem, 'id'>) => void>(() => {})

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([])
  const n = useRef(0)
  const push = useCallback((t: Omit<ToastItem, 'id'>) => {
    const id = ++n.current
    setItems((xs) => [...xs.slice(-3), { ...t, id }])
    setTimeout(() => setItems((xs) => xs.filter((x) => x.id !== id)), t.tone === 'bad' ? 9000 : 5000)
  }, [])
  const value = useMemo(() => push, [push])
  return (
    <Ctx.Provider value={value}>
      {children}
      {createPortal(
        <div className="pointer-events-none fixed bottom-10 right-4 z-[60] flex w-[360px] max-w-[calc(100vw-32px)] flex-col gap-2 max-md:bottom-20" aria-live="polite">
          {items.map((t) => (
            <div key={t.id} className="animate-in pointer-events-auto flex items-start gap-2.5 rounded-lg bg-panel px-3.5 py-3 shadow-pop">
              {t.tone === 'good' ? <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-profit" /> : t.tone === 'bad' ? <XCircle className="mt-0.5 h-4 w-4 shrink-0 text-loss" /> : <Info className="mt-0.5 h-4 w-4 shrink-0 text-info" />}
              <div className="min-w-0 flex-1">
                <div className="text-[13px] font-medium text-fg">{t.title}</div>
                {t.detail && <div className={cn('mt-0.5 text-xs text-muted')}>{t.detail}</div>}
              </div>
              <button type="button" aria-label="Dismiss" className="focus-ring -m-1 rounded p-1.5 text-faint hover:bg-raised hover:text-fg" onClick={() => setItems((xs) => xs.filter((x) => x.id !== t.id))}>
                <X className="h-3.5 w-3.5" />
              </button>
            </div>
          ))}
        </div>,
        document.body,
      )}
    </Ctx.Provider>
  )
}

export const useToast = () => useContext(Ctx)
