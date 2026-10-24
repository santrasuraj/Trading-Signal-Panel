// Theme, colour-blind mode, density and number style. Stored per viewer in localStorage; applied as attributes on
// <html> (the inline script in index.html applies them before first paint). Charts read `version` to re-theme.

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { readLocal, writeLocal } from './useLocalStorage'

export type ThemePref = 'system' | 'dark' | 'light'
export type Density = 'comfortable' | 'compact'

interface ThemeState {
  pref: ThemePref
  resolved: 'dark' | 'light'
  cvd: boolean
  density: Density
  compactMoney: boolean
  version: number
  setPref: (p: ThemePref) => void
  toggle: () => void
  setCvd: (on: boolean) => void
  setDensity: (d: Density) => void
  setCompactMoney: (on: boolean) => void
}

const Ctx = createContext<ThemeState | null>(null)

function systemDark(): boolean {
  try {
    return !window.matchMedia('(prefers-color-scheme: light)').matches
  } catch {
    return true
  }
}

function readRaw(key: string, fallback: string): string {
  try {
    return window.localStorage.getItem(key) ?? fallback
  } catch {
    return fallback
  }
}
function writeRaw(key: string, v: string) {
  try {
    window.localStorage.setItem(key, v)
  } catch {
    /* ignore */
  }
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [pref, setPrefState] = useState<ThemePref>(() => (readRaw('qd.theme', 'system') as ThemePref))
  const [sysDark, setSysDark] = useState(systemDark)
  const [cvd, setCvdState] = useState(() => readRaw('qd.cvd', 'off') === 'on')
  const [density, setDensityState] = useState<Density>(() => (readRaw('qd.density', 'comfortable') === 'compact' ? 'compact' : 'comfortable'))
  const [compactMoney, setCompactMoneyState] = useState(() => readLocal('qd.compactMoney', true))
  const [version, setVersion] = useState(0)

  useEffect(() => {
    const mq = window.matchMedia('(prefers-color-scheme: light)')
    const on = () => setSysDark(!mq.matches)
    mq.addEventListener('change', on)
    return () => mq.removeEventListener('change', on)
  }, [])

  const resolved: 'dark' | 'light' = pref === 'system' ? (sysDark ? 'dark' : 'light') : pref

  useEffect(() => {
    const d = document.documentElement
    d.classList.remove('dark', 'light')
    d.classList.add(resolved)
    d.dataset.cvd = cvd ? 'on' : 'off'
    d.dataset.density = density
    setVersion((v) => v + 1)
  }, [resolved, cvd, density])

  const setPref = useCallback((p: ThemePref) => {
    writeRaw('qd.theme', p)
    setPrefState(p)
  }, [])
  const toggle = useCallback(() => setPref(resolved === 'dark' ? 'light' : 'dark'), [resolved, setPref])
  const setCvd = useCallback((on: boolean) => {
    writeRaw('qd.cvd', on ? 'on' : 'off')
    setCvdState(on)
  }, [])
  const setDensity = useCallback((d: Density) => {
    writeRaw('qd.density', d)
    setDensityState(d)
  }, [])
  const setCompactMoney = useCallback((on: boolean) => {
    writeLocal('qd.compactMoney', on)
    setCompactMoneyState(on)
  }, [])

  const value = useMemo(
    () => ({ pref, resolved, cvd, density, compactMoney, version, setPref, toggle, setCvd, setDensity, setCompactMoney }),
    [pref, resolved, cvd, density, compactMoney, version, setPref, toggle, setCvd, setDensity, setCompactMoney],
  )
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useTheme(): ThemeState {
  const v = useContext(Ctx)
  if (!v) throw new Error('useTheme outside ThemeProvider')
  return v
}
