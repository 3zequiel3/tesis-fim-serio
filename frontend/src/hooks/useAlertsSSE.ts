import { useEffect } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { useAuthStore } from '@/stores/auth.store'
import { fetchStreamTicket } from '@/api/alerts'

const INITIAL_BACKOFF_MS = 1_000
const MAX_BACKOFF_MS = 30_000

const FAILED_ALERTS_COUNT_QUERY_KEY = ['alerts', 'failed', 'count']

/**
 * Abre una conexión SSE a GET /alerts/stream?ticket=<ticket>.
 *
 * EventSource no admite headers custom, así que la autenticación no puede ir
 * por Authorization: Bearer. Antes de cada conexión y de cada reconexión, el
 * hook pide un ticket nuevo con POST /alerts/stream-ticket a través del
 * cliente HTTP autenticado (JWT en header, con el refresh automático del
 * interceptor) — el ticket es de un solo uso (D64/RN-158), así que no puede
 * reutilizarse entre intentos. La URL del stream nunca contiene el access
 * token.
 *
 * La reconexión nativa de EventSource reutilizaría la MISMA URL — con un
 * ticket ya consumido, el primer reintento siempre fallaría con 401 — así
 * que el hook gestiona el ciclo completo a mano: ante cualquier error cierra
 * la conexión de inmediato (impidiendo el reintento nativo) y reabre con un
 * ticket nuevo tras un backoff exponencial (1s inicial, duplicando hasta un
 * máximo de 30s, reiniciado al abrir con éxito), pasando el último id
 * recibido en el query param `last_event_id` para no perder alertas
 * (D-EV-6). Si la obtención del ticket falla por sesión inválida (401 tras
 * el intento de refresh) o falta de permisos (403), el hook deja de
 * reintentar.
 *
 * Cada alerta nueva dispara un toast e invalida las queries `['alerts']`,
 * `['dashboard']` y `['alerts', 'failed', 'count']`; una reapertura exitosa
 * (no la primera) invalida las mismas queries para reflejar cambios
 * ocurridos durante el corte.
 *
 * La conexión depende de si hay sesión (Boolean(accessToken)), no del valor
 * puntual del access token: una rotación del token no reabre el stream — el
 * ticket sólo se valida al abrir la conexión.
 */
export function useAlertsSSE() {
  const accessToken = useAuthStore((s) => s.accessToken)
  const isAuthenticated = Boolean(accessToken)
  const queryClient = useQueryClient()

  useEffect(() => {
    if (!isAuthenticated) return

    let cancelled = false
    let source: EventSource | null = null
    let retryTimer: ReturnType<typeof setTimeout> | null = null
    let backoffMs = INITIAL_BACKOFF_MS
    let hasOpenedOnce = false
    let lastEventId: string | null = null

    const apiUrl = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

    function invalidateAlertQueries() {
      queryClient.invalidateQueries({ queryKey: ['alerts'] })
      queryClient.invalidateQueries({ queryKey: ['dashboard'] })
      queryClient.invalidateQueries({ queryKey: FAILED_ALERTS_COUNT_QUERY_KEY })
    }

    function scheduleReconnect() {
      if (cancelled) return
      retryTimer = setTimeout(() => {
        retryTimer = null
        void connect()
      }, backoffMs)
      backoffMs = Math.min(backoffMs * 2, MAX_BACKOFF_MS)
    }

    async function connect() {
      if (cancelled) return

      let ticket: string
      try {
        const data = await fetchStreamTicket()
        ticket = data.ticket
      } catch (err) {
        if (cancelled) return
        const status = (err as { response?: { status?: number } } | undefined)?.response
          ?.status
        if (status === 401 || status === 403) {
          // Sesión inválida (401 tras refresh) o sin permisos (403): dejar de
          // reintentar (D64/RN-158).
          return
        }
        // Error de red o 5xx al pedir el ticket: backoff, igual que un error
        // de la conexión SSE.
        scheduleReconnect()
        return
      }

      if (cancelled) return

      let url = `${apiUrl}/alerts/stream?ticket=${encodeURIComponent(ticket)}`
      if (lastEventId !== null) {
        url += `&last_event_id=${encodeURIComponent(lastEventId)}`
      }

      const es = new EventSource(url)
      source = es

      es.addEventListener('alert', (e: MessageEvent) => {
        let alert: { id?: number; event_id?: number; severity?: string } = {}
        try {
          alert = JSON.parse(e.data) as typeof alert
          const severity = alert.severity ?? 'nueva'
          const eventRef = alert.event_id ? ` — evento #${alert.event_id}` : ''
          toast.warning(`Alerta ${severity}${eventRef}`)
        } catch {
          // Ignorar errores de parseo
        }

        // El id del propio frame SSE (String(alert.id), ver
        // _alert_to_dict/_alert_sse_generator en el backend) es equivalente a
        // e.lastEventId — se prefiere el del payload para no depender de que
        // el entorno de test reproduzca la semántica exacta de EventSource.
        if (typeof alert.id === 'number') {
          lastEventId = String(alert.id)
        } else if (typeof e.lastEventId === 'string' && e.lastEventId !== '') {
          lastEventId = e.lastEventId
        }

        invalidateAlertQueries()
      })

      es.onopen = () => {
        backoffMs = INITIAL_BACKOFF_MS
        if (hasOpenedOnce) {
          // Reapertura tras un corte: no hay cursor inicial de replay para el
          // toast puntual de lo que pasó durante el corte (D64/RN-158), pero
          // listados, dashboard y banner sí reflejan el estado real.
          invalidateAlertQueries()
        }
        hasOpenedOnce = true
      }

      es.onerror = () => {
        // Reutilizar la reconexión nativa de EventSource reenviaría la MISMA
        // URL, con un ticket ya consumido ⇒ 401 garantizado. Cerramos de
        // inmediato e impedimos el reintento nativo; reabrimos a mano con un
        // ticket nuevo tras el backoff.
        es.close()
        if (source === es) source = null
        scheduleReconnect()
      }
    }

    void connect()

    return () => {
      cancelled = true
      if (retryTimer !== null) {
        clearTimeout(retryTimer)
        retryTimer = null
      }
      if (source !== null) {
        source.close()
        source = null
      }
    }
  }, [isAuthenticated, queryClient])
}
