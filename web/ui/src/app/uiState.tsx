import { createContext, useContext, useMemo, useState, type ReactNode } from 'react'

interface UiState {
  palette: boolean
  setPalette: (o: boolean) => void
  help: boolean
  setHelp: (o: boolean) => void
  fyersLogin: boolean
  setFyersLogin: (o: boolean) => void
}
const Ctx = createContext<UiState | null>(null)

export function UiStateProvider({ children }: { children: ReactNode }) {
  const [palette, setPalette] = useState(false)
  const [help, setHelp] = useState(false)
  const [fyersLogin, setFyersLogin] = useState(false)
  const v = useMemo(() => ({ palette, setPalette, help, setHelp, fyersLogin, setFyersLogin }), [palette, help, fyersLogin])
  return <Ctx.Provider value={v}>{children}</Ctx.Provider>
}

export function useUi(): UiState {
  const v = useContext(Ctx)
  if (!v) throw new Error('useUi outside UiStateProvider')
  return v
}
