import { useCallback, useEffect, useRef, useState } from 'react'

/** Read a JSON value from localStorage; any failure (private mode, bad JSON) falls back to the default. */
export function readLocal<T>(key: string, fallback: T): T {
  try {
    const raw = window.localStorage.getItem(key)
    return raw == null ? fallback : (JSON.parse(raw) as T)
  } catch {
    return fallback
  }
}

export function writeLocal<T>(key: string, value: T): void {
  try {
    window.localStorage.setItem(key, JSON.stringify(value))
  } catch {
    /* storage unavailable: the preference just doesn't persist */
  }
}

// 'storage' events only reach OTHER tabs; this one keeps every hook on the same key in sync inside this tab
// (e.g. the Long-term and Swing tables share one column choice).
const LOCAL_EVENT = 'qd-local'

/** useState persisted to localStorage (per-viewer conveniences only: theme, column choices, dismissed banners). */
export function useLocalStorage<T>(key: string, fallback: T): [T, (v: T | ((p: T) => T)) => void] {
  const [value, setValue] = useState<T>(() => readLocal(key, fallback))
  const current = useRef(value)
  current.current = value
  useEffect(() => {
    const onStorage = (e: StorageEvent) => {
      if (e.key === key) setValue(readLocal(key, fallback))
    }
    const onLocal = (e: Event) => {
      const d = (e as CustomEvent<{ key: string; value: T }>).detail
      if (d?.key === key && d.value !== current.current) setValue(d.value)
    }
    window.addEventListener('storage', onStorage)
    window.addEventListener(LOCAL_EVENT, onLocal)
    return () => {
      window.removeEventListener('storage', onStorage)
      window.removeEventListener(LOCAL_EVENT, onLocal)
    }
    // fallback is intentionally not a dependency (callers pass literals)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key])
  const set = useCallback(
    (v: T | ((p: T) => T)) => {
      const next = typeof v === 'function' ? (v as (p: T) => T)(current.current) : v
      current.current = next
      writeLocal(key, next)
      setValue(next)
      window.dispatchEvent(new CustomEvent(LOCAL_EVENT, { detail: { key, value: next } }))
    },
    [key],
  )
  return [value, set]
}
