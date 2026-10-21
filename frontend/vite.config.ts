import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

// In development, Vite serves the UI on :5173 and forwards /api to the Python backend on :8000.
// In production the backend serves the built files from dist/ itself (one process, one URL).
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: { '/api': 'http://127.0.0.1:8000' } },
  build: { outDir: 'dist', sourcemap: false },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    css: false,
  },
})
