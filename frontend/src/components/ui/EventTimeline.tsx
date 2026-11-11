import { Link } from 'react-router-dom'
import type { EventDetail } from '@/api/events'
import { StatusBadge } from '@/components/ui/StatusBadge'
import { formatAbsolute } from '@/utils/timeDisplay'

interface EventTimelineProps {
  event: EventDetail
}

// Marker color per state, from the same solid tokens the dashboard bar uses.
const MARKER: Record<string, string> = {
  pending: 'bg-status-pending',
  approved: 'bg-status-approved',
  rejected: 'bg-status-rejected',
  superseded: 'bg-status-superseded',
  auto_restored: 'bg-status-auto_restored',
  quarantined: 'bg-status-quarantined',
  alert_only: 'bg-status-alert_only',
}

/**
 * Muestra la cadena temporal del evento.
 * Para C18, muestra el padre como link clickeable y el estado actual.
 * La cadena completa (US-10) vive en su propia vista (@/pages/EventChain),
 * accesible desde el link "Ver cadena completa" que agrega EventDetail.tsx
 * cuando el evento pertenece a una cadena de más de un elemento.
 */
export function EventTimeline({ event }: EventTimelineProps) {
  return (
    <div className="space-y-3">
      <h3 className="font-semibold text-text">Cadena de eventos</h3>
      <ol className="relative ml-2 space-y-4 border-l border-line-strong">
        {/* Evento padre, si existe */}
        {event.parent_event_id != null && (
          <li className="ml-4">
            <span className="absolute -left-1.5 size-3 rounded-full border border-line-strong bg-surface-raised" />
            <p className="text-text-muted">
              Evento anterior:{' '}
              <Link
                to={`/events/${event.parent_event_id}`}
                className="font-semibold text-accent underline"
                aria-label={`Ver evento padre #${event.parent_event_id}`}
              >
                #{event.parent_event_id}
              </Link>
            </p>
          </li>
        )}

        {/* Evento actual */}
        <li className="ml-4">
          <span
            className={`absolute -left-1.5 size-3 rounded-full ${MARKER[event.status] ?? 'bg-status-superseded'}`}
          />
          <div className="space-y-1">
            <p className="flex items-center gap-2 font-semibold text-text">
              #{event.id} <StatusBadge status={event.status} />
            </p>
            <p className="text-text-muted">Detectado: {formatAbsolute(event.detected_at)}</p>
            {event.resolved_at && (
              <p className="text-text-muted">Resuelto: {formatAbsolute(event.resolved_at)}</p>
            )}
          </div>
        </li>
      </ol>
    </div>
  )
}
