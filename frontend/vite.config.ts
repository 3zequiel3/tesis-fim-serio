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
  build: {
    rollupOptions: {
      output: {
        // Design D-12: the entry chunk keeps only the application shell. Framework
        // and data libraries (stable between releases, so cacheable) get their own
        // chunks; pages load on demand through React.lazy.
        manualChunks(id: string) {
          if (!id.includes('node_modules')) return undefined
          if (/node_modules\/(\.pnpm\/)?(react|react-dom|scheduler)[@/]/.test(id)) return 'vendor-react'
          if (/node_modules\/(\.pnpm\/)?(react-router|react-router-dom|@remix-run)/.test(id)) return 'vendor-router'
          if (/node_modules\/(\.pnpm\/)?(@tanstack|axios|zustand|sonner)/.test(id)) return 'vendor-data'
          return undefined
        },
      },
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
