import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'path'

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
  ],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, 'src'),
    },
  },
  server: {
    proxy: {
      // Keep development aligned with nginx and the E2E proxy. The refresh
      // cookie is scoped to this exact same-origin path.
      '/auth/refresh': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})
