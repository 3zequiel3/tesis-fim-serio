import { useEffect } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { useAuthStore } from '@/stores/auth.store'

/**
 * Abre una conexión SSE a GET /alerts/stream?token=<accessToken>.
 * Por cada alerta recibida dispara un toast e invalida las queries de
 * alertas, dashboard y contador de fallidas (C38) — antes solo el toast,
 * y las vistas quedaban desactualizadas hasta el próximo polling.
 * EventSource reconecta automáticamente y envía Last-Event-ID (D-EV-6).
 * El token va en query param porque EventSource no admite headers custom (contrato C16).
 */
export function useAlertsSSE() {
  const accessToken = useAuthStore((s) => s.accessToken)
  const queryClient = useQueryClient()

  useEffect(() => {
    if (!accessToken) return

    const apiUrl = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'
    const url = `${apiUrl}/alerts/stream?token=${encodeURIComponent(accessToken)}`
    const es = new EventSource(url)

    es.addEventListener('alert', (e: MessageEvent) => {
      try {
        const alert = JSON.parse(e.data) as {
          event_id?: number
          severity?: string
          message?: string
        }
        const severity = alert.severity ?? 'nueva'
        const eventRef = alert.event_id ? ` — evento #${alert.event_id}` : ''
        toast.warning(`Alerta ${severity}${eventRef}`)
      } catch {
        // Ignorar errores de parseo
      }
      // Refrescar las vistas que muestran alertas (invalidar cubre también
      // ['alerts', 'failed'] por prefijo de query key).
      queryClient.invalidateQueries({ queryKey: ['alerts'] })
      queryClient.invalidateQueries({ queryKey: ['dashboard'] })
      queryClient.invalidateQueries({ queryKey: ['alerts-failed-count'] })
    })

    es.onerror = () => {
      // Corte transitorio de red: readyState = CONNECTING y EventSource
      // reconecta solo — no se requiere acción.
      //
      // Respuesta no-200 (p. ej. 401 por access token vencido en el query
      // param): el browser cierra la conexión de forma DEFINITIVA
      // (readyState = CLOSED) y no reintenta. Sin manejo, el feed moría en
      // silencio o quedaba atado a un token muerto. Cerramos limpio e
      // intentamos un refresh: si funciona, accessToken cambia y este effect
      // recrea la conexión con el token nuevo; si falla, no hay loop porque
      // la conexión ya quedó cerrada.
      if (es.readyState === EventSource.CLOSED) {
        es.close()
        void useAuthStore
          .getState()
          .refreshToken()
          .catch(() => undefined)
      }
    }

    return () => {
      es.close()
    }
  }, [accessToken, queryClient])
}
