import { useEffect } from 'react'
import { toast } from 'sonner'
import { useAuthStore } from '@/stores/auth.store'

/**
 * Abre una conexión SSE a GET /alerts/stream?token=<accessToken>.
 * Dispara un toast por cada alerta recibida.
 * EventSource reconecta automáticamente y envía Last-Event-ID (D-EV-6).
 * El token va en query param porque EventSource no admite headers custom (contrato C16).
 */
export function useAlertsSSE() {
  const accessToken = useAuthStore((s) => s.accessToken)

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
    })

    es.onerror = () => {
      // EventSource reconecta automáticamente — no se requiere acción
    }

    return () => {
      es.close()
    }
  }, [accessToken])
}
