import { createRequire } from 'node:module'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

const require = createRequire(import.meta.url)
const pkg = require('./package.json')

// Served from the Pi at the site root (PWA), not file:// — so base '/'.
export default defineConfig({
  base: '/',
  define: { __APP_VERSION__: JSON.stringify(pkg.version) },
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    strictPort: true,
    // Dev: Vite (:5173) proxies the API to the local server (:4901) so the
    // app always talks to a same-origin `/api` — matching production.
    proxy: { '/api': 'http://localhost:4901' }
  },
  build: { outDir: 'dist' }
})