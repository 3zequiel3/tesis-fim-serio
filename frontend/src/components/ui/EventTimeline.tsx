import { Link } from 'react-router-dom'
import type { EventDetail } from '@/api/events'

interface EventTimelineProps {
  event: EventDetail
}

/**
 * Muestra la cadena temporal del evento.
 * Para C18, muestra el padre como link clickeable y el estado actual.
 * Una cadena completa requeriría múltiples llamadas API (fuera del alcance de C18).
 */
export function EventTimeline({ event }: EventTimelineProps) {
  return (
    <div className="space-y-2">
      <h3 className="text-sm font-semibold text-gray-300">Cadena de eventos</h3>
      <ol className="relative border-l border-gray-600 ml-2 space-y-3">
        {/* Evento padre, si existe */}
        {event.parent_event_id != null && (
          <li className="ml-4">
            <span className="absolute -left-1.5 w-3 h-3 rounded-full bg-gray-500 border border-gray-600" />
            <p className="text-xs text-gray-400">
              Evento anterior:{' '}
              <Link
                to={`/events/${event.parent_event_id}`}
                className="text-blue-400 hover:text-blue-300 underline"
              >
                #{event.parent_event_id}
              </Link>
            </p>
          </li>
        )}

        {/* Evento actual */}
        <li className="ml-4">
          <span
            className={`absolute -left-1.5 w-3 h-3 rounded-full border ${
              event.status === 'superseded'
                ? 'bg-gray-600 border-gray-500'
                : event.status === 'pending'
                  ? 'bg-yellow-500 border-yellow-400'
                  : event.status === 'approved'
                    ? 'bg-green-500 border-green-400'
                    : event.status === 'rejected'
                      ? 'bg-red-500 border-red-400'
                      : 'bg-blue-500 border-blue-400'
            }`}
          />
          <div className="text-xs space-y-0.5">
            <p className="font-medium text-gray-200">
              #{event.id}{' '}
              <StatusBadge status={event.status} />
            </p>
            <p className="text-gray-400">
              Detectado: {new Date(event.detected_at).toLocaleString('es-AR')}
            </p>
            {event.resolved_at && (
              <p className="text-gray-400">
                Resuelto: {new Date(event.resolved_at).toLocaleString('es-AR')}
              </p>
            )}
          </div>
        </li>
      </ol>
    </div>
  )
}

function StatusBadge({ status }: { status: string }) {
  const classes: Record<string, string> = {
    pending: 'bg-yellow-900 text-yellow-300',
    approved: 'bg-green-900 text-green-300',
    rejected: 'bg-red-900 text-red-300',
    superseded: 'bg-gray-700 text-gray-400',
    auto_restored: 'bg-blue-900 text-blue-300',
    quarantined: 'bg-orange-900 text-orange-300',
    alert_only: 'bg-purple-900 text-purple-300',
  }
  const cls = classes[status] ?? 'bg-gray-700 text-gray-300'
  return (
    <span className={`inline-block px-1.5 py-0.5 rounded text-xs font-mono ${cls}`}>
      {status}
    </span>
  )
}
