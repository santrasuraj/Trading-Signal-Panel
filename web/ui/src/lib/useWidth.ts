import { useCallback, useRef, useState } from 'react'

/** Width of an element's content box in px, kept current with a ResizeObserver (0 until measured). */
export function useWidth<E extends HTMLElement>(): [(el: E | null) => void, number] {
  const [w, setW] = useState(0)
  const ro = useRef<ResizeObserver | null>(null)
  const ref = useCallback((el: E | null) => {
    ro.current?.disconnect()
    ro.current = null
    if (!el) return
    setW(Math.round(el.clientWidth))
    if (typeof ResizeObserver === 'undefined') return
    ro.current = new ResizeObserver(([e]) => setW(Math.round(e.contentRect.width)))
    ro.current.observe(el)
  }, [])
  return [ref, w]
}
