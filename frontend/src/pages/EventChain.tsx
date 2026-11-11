import { Link } from 'react-router-dom'
import { Unlink } from 'lucide-react'
import { useEventChain } from '@/hooks/useEventChain'
import { useEventId } from '@/hooks/useEventId'
import { readApiError } from '@/api/errors'
import { DataState } from '@/components/ui/DataState'
import { EventNotFound } from '@/components/ui/EventNotFound'
import { PathLabel } from '@/components/ui/PathLabel'
import { StatusBadge } from '@/components/ui/StatusBadge'
import { formatAbsolute } from '@/utils/timeDisplay'

/**
 * US-10: cadena de eventos de un mismo path, orden cronológico ascendente.
 * Cada evento es navegable hacia su detalle (criterio 3); los `superseded`
 * llevan ícono de cadena rota y referencia a su `parent_event_id`
 * (criterio 4).
 */
export function EventChain() {
  const eventId = useEventId()
  const { data: chain, isLoading, error, refetch } = useEventChain(eventId)

  // D93/RN-187: an invalid id or a 404 is «not found»; any other error is an
  // error state with retry, never an endless «Cargando...».
  if (eventId === null || (error != null && readApiError(error).status === 404)) {
    return <EventNotFound eventId={eventId} />
  }

  return (
    <div className="mx-auto max-w-3xl space-y-4">
      <div className="flex items-center gap-2">
        <Link to={`/events/${eventId}`} className="text-text-muted hover:text-text">
          Evento #{eventId}
        </Link>
        <span className="text-text-muted">/</span>
        <span className="text-text">Cadena</span>
      </div>

      <DataState
        isLoading={isLoading}
        error={error}
        onRetry={() => void refetch()}
        resource="la cadena de eventos"
        loadingLabel="Cargando cadena de eventos..."
      >
        {chain && (
          <>
            <h1 className="text-xl font-semibold text-text [overflow-wrap:anywhere]">
              Cadena de eventos — {chain.path ?? '(sin path)'}
            </h1>

            <ol className="mt-4 space-y-2">
              {chain.items.map((item) => (
                <li
                  key={item.id}
                  data-testid="chain-item"
                  className={`flex flex-wrap items-center justify-between gap-3 rounded-panel border bg-surface-raised p-3 ${
                    item.id === eventId ? 'border-accent' : 'border-line'
                  }`}
                >
                  <div className="flex flex-wrap items-center gap-2">
                    {item.status === 'superseded' && (
                      <span
                        data-testid="broken-chain-icon"
                        title="Evento superseded — reemplazado por uno más reciente"
                        aria-label="cadena rota"
                        className="text-text-muted"
                      >
                        <Unlink aria-hidden="true" size={16} />
                      </span>
                    )}
                    <span className="font-mono font-semibold text-text">#{item.id}</span>
                    <StatusBadge status={item.status} />
                    {item.parent_event_id != null && (
                      <span className="text-xs text-text-muted">padre: #{item.parent_event_id}</span>
                    )}
                  </div>
                  <div className="flex items-center gap-3">
                    <span className="text-xs text-text-muted">{formatAbsolute(item.created_at)}</span>
                    <Link to={`/events/${item.id}`} className="text-xs font-semibold text-accent underline">
                      Ver #{item.id}
                    </Link>
                  </div>
                </li>
              ))}
            </ol>
            {chain.items.length === 0 && <PathLabel path={chain.path} />}
          </>
        )}
      </DataState>
    </div>
  )
}
