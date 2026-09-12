import { Link, useParams } from 'react-router-dom'
import { useEventChain } from '@/hooks/useEventChain'
import { formatAbsolute } from '@/utils/timeDisplay'

/**
 * US-10: cadena de eventos de un mismo path, orden cronológico ascendente.
 * Cada evento es navegable hacia su detalle (criterio 3); los `superseded`
 * llevan ícono de cadena rota y referencia a su `parent_event_id`
 * (criterio 4).
 */
export function EventChain() {
  const { id } = useParams<{ id: string }>()
  const eventId = id ? Number(id) : null

  const { data: chain, isLoading, error } = useEventChain(eventId)

  const is404 =
    error != null &&
    (error as { response?: { status?: number } })?.response?.status === 404

  if (is404) {
    return (
      <div className="max-w-2xl mx-auto py-16 text-center">
        <p className="text-2xl font-semibold text-gray-400">Evento no encontrado</p>
        <Link to="/events" className="mt-4 inline-block text-blue-400 hover:text-blue-300 text-sm">
          Volver a eventos
        </Link>
      </div>
    )
  }

  if (isLoading || !chain) {
    return <div className="py-16 text-center text-gray-500">Cargando cadena de eventos...</div>
  }

  return (
    <div className="max-w-3xl mx-auto py-6 px-4 space-y-4">
      <div className="flex items-center gap-2">
        <Link to={`/events/${eventId}`} className="text-gray-500 hover:text-gray-300 text-sm">
          Evento #{eventId}
        </Link>
        <span className="text-gray-600">/</span>
        <span className="text-gray-300 text-sm">Cadena</span>
      </div>

      <h1 className="text-lg font-semibold text-white break-all">
        Cadena de eventos — {chain.path ?? '(sin path)'}
      </h1>

      <ol className="space-y-2">
        {chain.items.map((item) => (
          <li
            key={item.id}
            data-testid="chain-item"
            className={`flex items-center justify-between gap-3 rounded border p-3 ${
              item.id === eventId
                ? 'bg-gray-800 border-blue-700'
                : 'bg-gray-800 border-gray-700'
            }`}
          >
            <div className="flex items-center gap-2 text-sm">
              {item.status === 'superseded' && (
                <span
                  data-testid="broken-chain-icon"
                  title="Evento superseded — reemplazado por uno más reciente"
                  aria-label="cadena rota"
                >
                  ⛓️‍💥
                </span>
              )}
              <span className="font-mono text-gray-200">#{item.id}</span>
              <StatusBadge status={item.status} />
              {item.parent_event_id != null && (
                <span className="text-xs text-gray-500">padre: #{item.parent_event_id}</span>
              )}
            </div>
            <div className="flex items-center gap-3">
              <span className="text-xs text-gray-500">{formatAbsolute(item.created_at)}</span>
              <Link
                to={`/events/${item.id}`}
                className="text-blue-400 hover:text-blue-300 underline text-xs"
              >
                Ver #{item.id}
              </Link>
            </div>
          </li>
        ))}
      </ol>
    </div>
  )
}

function StatusBadge({ status }: { status: string }) {
  const classes: Record<string, string> = {
    pending: 'bg-yellow-900 text-yellow-300 border-yellow-800',
    approved: 'bg-green-900 text-green-300 border-green-800',
    rejected: 'bg-red-900 text-red-300 border-red-800',
    superseded: 'bg-gray-700 text-gray-400 border-gray-600',
    auto_restored: 'bg-blue-900 text-blue-300 border-blue-800',
    quarantined: 'bg-orange-900 text-orange-300 border-orange-800',
    alert_only: 'bg-purple-900 text-purple-300 border-purple-800',
  }
  const cls = classes[status] ?? 'bg-gray-700 text-gray-300 border-gray-600'
  return (
    <span className={`px-1.5 py-0.5 rounded border text-xs font-mono ${cls}`}>{status}</span>
  )
}
