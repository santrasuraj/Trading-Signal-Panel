import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'node:path'

// Dev: the React app runs on :5173 and forwards /api to the FastAPI backend on :8600.
// Prod: FastAPI serves the built app from web/ui/dist on the same origin.
export default defineConfig({
  plugins: [react()],
  resolve: { alias: { '@': path.resolve(__dirname, 'src') } },
  server: {
    host: '127.0.0.1',
    port: 5173,
    proxy: { '/api': 'http://127.0.0.1:8600' },
  },
  build: { chunkSizeWarningLimit: 900 },
})
