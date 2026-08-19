/// <reference types="vitest" />
import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import path from 'path'

export default defineConfig({
  // El plugin de React es necesario para transformar los .tsx de los tests de
  // componente (Fast Refresh queda inerte fuera de `vite dev`).
  plugins: [react()],
  test: {
    // jsdom sobre happy-dom: implementacion de referencia que usa la doc de
    // Testing Library, con soporte completo de eventos de puntero/teclado que
    // necesita user-event. La suite es chica, la diferencia de velocidad no pesa.
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    // Sin `globals: true`: los tests existentes importan describe/it/expect
    // explicitamente desde 'vitest' y esa convencion se mantiene.
  },
  resolve: {
    alias: {
      '@/': path.resolve(__dirname, 'src') + '/',
    },
  },
})
