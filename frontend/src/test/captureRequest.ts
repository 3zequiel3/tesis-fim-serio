import type { AxiosAdapter, InternalAxiosRequestConfig } from 'axios'
import { apiClient } from '@/api/client'

// D-5 del design de frontend-severity-triage: el problema original no era
// la profundidad del mock — `vi.mock('@/api/client')` ya captura el objeto
// del cuerpo — sino que ningún artefacto del lado del frontend sabía qué
// acepta el backend. Este helper NO reemplaza ese mock por uno más
// "profundo": instala un adaptador sobre el cliente axios REAL
// (`apiClient.defaults.adapter`, API pública de axios) para que la llamada
// de API se ejecute de punta a punta sin mockear `@/api/client`, y la
// captura ocurra DESPUÉS de `transformRequest` — lo capturado es el cuerpo
// serializado que saldría al cable, no el objeto de JavaScript que lo
// precede. No se usa msw (D-5): sería una dependencia nueva y un service
// worker en jsdom para obtener exactamente este mismo dato.

export interface RequestCapture {
  /** Todas las configs de petición capturadas, en orden de emisión. */
  requests: InternalAxiosRequestConfig[]
  /** La última config capturada, o undefined si ninguna petición pasó. */
  last(): InternalAxiosRequestConfig | undefined
  /** Restaura el adapter original. Llamar SIEMPRE en `afterEach`: `apiClient.defaults`
   * es estado global del módulo, y si se filtra el síntoma es ruidoso (todas
   * las peticiones subsiguientes quedan capturadas) pero igual hay que cerrarlo. */
  restore(): void
}

/**
 * Instala el adaptador de captura. Responde cada petición con un 200 vacío
 * sin tocar la red — el interés del helper es la petición SALIENTE, nunca
 * la respuesta.
 */
export function installRequestCapture(): RequestCapture {
  const requests: InternalAxiosRequestConfig[] = []
  const originalAdapter = apiClient.defaults.adapter

  const captureAdapter: AxiosAdapter = async (config) => {
    requests.push(config)
    return {
      data: {},
      status: 200,
      statusText: 'OK',
      headers: {},
      config,
    }
  }

  apiClient.defaults.adapter = captureAdapter

  return {
    requests,
    last: () => requests[requests.length - 1],
    restore: () => {
      apiClient.defaults.adapter = originalAdapter
    },
  }
}
