import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { RouterProvider } from 'react-router-dom'
import '@fontsource-variable/inter'
import '@fontsource/jetbrains-mono/400.css'
import './index.css'
import { shouldRetry } from '@/api/hooks'
import { router } from '@/app/router'
import { UiStateProvider } from '@/app/uiState'
import { ToastProvider } from '@/components/toast'
import { ThemeProvider } from '@/lib/theme'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: shouldRetry,
      retryDelay: (n) => Math.min(8000, 800 * 2 ** n),
      refetchOnWindowFocus: false,
      staleTime: Infinity,
    },
  },
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <ToastProvider>
          <UiStateProvider>
            <RouterProvider router={router} future={{ v7_startTransition: true }} />
          </UiStateProvider>
        </ToastProvider>
      </ThemeProvider>
    </QueryClientProvider>
  </StrictMode>,
)
