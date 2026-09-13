import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'node:path'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { '@': path.resolve(import.meta.dirname, '../src') } },
  server: {
    proxy: {
      '/auth/refresh': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        configure: (proxy) => {
          proxy.on('proxyReq', (proxyRequest) => proxyRequest.setHeader('origin', 'http://localhost'))
        },
      },
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        rewrite: (requestPath) => requestPath.replace(/^\/api/, ''),
        configure: (proxy) => {
          // The production nginx keeps the browser same-origin. The local
          // E2E proxy mirrors that topology and forwards an allowed origin.
          proxy.on('proxyReq', (proxyRequest) => proxyRequest.setHeader('origin', 'http://localhost'))
        },
      },
    },
  },
})
