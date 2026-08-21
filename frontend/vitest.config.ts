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
    //
    // D39/RN-133 (D-5 regla 3 del design de timestamps-timezone-aware):
    // jsdom hereda la zona del PROCESO. Fijarla acá — no por archivo — a
    // America/Argentina/Buenos_Aires, una zona con desfase NO nulo y además
    // la del operador real: un test de formateo corrido bajo una zona en
    // UTC no distingue el código correcto del roto, que es exactamente el
    // punto ciego que dejó pasar el defecto original en producción.
    env: {
      TZ: 'America/Argentina/Buenos_Aires',
    },
  },
  resolve: {
    alias: {
      '@/': path.resolve(__dirname, 'src') + '/',
    },
  },
})
