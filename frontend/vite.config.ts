import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The Python engine runs on :8000; the dev server proxies /api to it.
const ENGINE = process.env.OPTICORE_ENGINE_URL ?? 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: { '/api': { target: ENGINE, changeOrigin: true } },
  },
  preview: {
    port: 4173,
    proxy: { '/api': { target: ENGINE, changeOrigin: true } },
  },
  build: {
    chunkSizeWarningLimit: 6000,
  },
  test: {
    environment: 'jsdom',
    include: ['src/**/*.test.ts', 'src/**/*.test.tsx'],
  },
} as Parameters<typeof defineConfig>[0])
