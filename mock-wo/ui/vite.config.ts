/// <reference types="vitest/config" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The bundle is served by mock-wo's operator app (:8091) from app/ui_dist.
// Everything, fonts included, is emitted into that directory: no CDN, no
// runtime external fetch (operator-dashboard-spec §10, D6).
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: '../app/ui_dist',
    emptyOutDir: true,
    assetsInlineLimit: 0,
  },
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://127.0.0.1:8091',
      '/media': 'http://127.0.0.1:8091',
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    css: false,
  },
})
