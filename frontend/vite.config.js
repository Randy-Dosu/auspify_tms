import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Vite config for the React frontend.
// The API is reached through a relative `/api` path, which Vite proxies to
// Flask in development. That keeps the browser on a single origin, so no
// CORS preflight is needed and the deployed preview host works unchanged.
// Build output. `dist` is the normal default; hosted preview sandboxes wipe
// folders named dist/build/out between snapshots, so VITE_OUT_DIR can point the
// build (and `vite preview`) at a durable directory such as `preview-dist`.
const OUT_DIR = process.env.VITE_OUT_DIR || 'dist'

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: OUT_DIR,
    emptyOutDir: true,
  },
  server: {
    host: '0.0.0.0', // listen on all interfaces (required for previews)
    port: 5173,
    strictPort: true,
    // Accept any host header so the sandbox preview domain works.
    allowedHosts: true,
    proxy: {
      '/api': {
        target: process.env.VITE_PROXY_TARGET || 'http://127.0.0.1:5000',
        changeOrigin: true,
      },
    },
  },
  // `npm run preview` serves the production build with the same /api proxy, so
  // the built bundle can be exercised exactly like the dev server.
  preview: {
    host: '0.0.0.0',
    port: 4173,
    strictPort: true,
    allowedHosts: true,
    proxy: {
      '/api': {
        target: process.env.VITE_PROXY_TARGET || 'http://127.0.0.1:5000',
        changeOrigin: true,
      },
    },
  },
  // UI tests run in jsdom (no browser needed).
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: './src/test/setup.js',
    css: false,
  },
})
