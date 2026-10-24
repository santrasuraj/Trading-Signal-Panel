/// <reference types="vitest/config" />
import { defineConfig, type PluginOption } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'node:path'

// Dev:  the React app runs on 127.0.0.1:5173 and forwards /api to the FastAPI backend (default :8600,
//       override with QD_API=http://127.0.0.1:8611).
// Mock: `npm run dev:mock` serves /api from src/api/mock (fixtures generated from data/results by
//       `npm run fixtures`). The mock is a dev-server middleware only: nothing of it reaches `vite build`.
// Prod: FastAPI serves the built app from web/ui/dist on the same origin.
export default defineConfig(async ({ mode, command }) => {
  const plugins: PluginOption[] = [react()]
  const useMock = command === 'serve' && mode === 'mock'
  if (useMock) {
    const { mockApiPlugin } = await import('./src/api/mock/server')
    plugins.push(mockApiPlugin())
  }
  const api = process.env.QD_API ?? 'http://127.0.0.1:8600'
  return {
    plugins,
    resolve: { alias: { '@': path.resolve(__dirname, 'src') } },
    server: {
      host: '127.0.0.1',
      port: 5173,
      proxy: useMock ? undefined : { '/api': api },
    },
    build: {
      chunkSizeWarningLimit: 600,
      rollupOptions: {
        output: {
          manualChunks: {
            react: ['react', 'react-dom', 'react-router-dom'],
            query: ['@tanstack/react-query', '@tanstack/react-table'],
            charts: ['lightweight-charts'],
          },
        },
      },
    },
    test: {
      environment: 'node',
      include: ['src/**/*.test.ts'],
    },
  }
})
