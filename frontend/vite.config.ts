import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

const backend = `http://127.0.0.1:${process.env.TWIN_PORT ?? '8765'}`

export default defineConfig({
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    port: 5173,
    strictPort: true,
    proxy: { '/api': { target: backend, changeOrigin: false } },
  },
  // three.js + three-vrm（約760KB）はアバター表示時だけ遅延読み込みするため、警告の上限を上げる
  build: { outDir: 'dist', sourcemap: false, chunkSizeWarningLimit: 800 },
  test: {
    environment: 'jsdom',
    setupFiles: ['src/test/setup.ts'],
  },
})
