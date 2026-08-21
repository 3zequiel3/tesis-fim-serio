import { Link } from 'react-router-dom'
import { useDashboard } from '@/hooks/useDashboard'
import { QueryErrorState } from '@/components/ui/QueryErrorState'
import { formatAbsolute } from '@/utils/timeDisplay'
import type { EventStatus } from '@/api/events'
import type { AgentStatus } from '@/api/agents'

// ─── Helpers ──────────────────────────────────────────────────────────────────

// C1/RN-71: minúsculas snake_case en toda la UI, con excepción única para
// botones de acción — una etiqueta de tarjeta no lo es. Reemplaza
// EVENT_STATUS_LABELS (que rotulaba `Pending`, `Auto-restored`, `Alert only`
// mientras la tabla de eventos ya renderiza el valor canónico) por el valor
// canónico mismo, para que las dos pantallas nombren el mismo estado igual.

const EVENT_STATUS_COLORS: Record<EventStatus, string> = {
  pending: 'text-yellow-400',
  approved: 'text-green-400',
  rejected: 'text-red-400',
  superseded: 'text-gray-500',
  auto_restored: 'text-blue-400',
  quarantined: 'text-orange-400',
  alert_only: 'text-purple-400',
}

const AGENT_STATUS_LABELS: Record<AgentStatus, string> = {
  online: 'Online',
  offline: 'Offline',
  draining: 'Draining',
  dead: 'Dead',
  revoked: 'Revoked',
}

const AGENT_STATUS_COLORS: Record<AgentStatus, string> = {
  online: 'text-green-400',
  offline: 'text-gray-500',
  draining: 'text-yellow-400',
  dead: 'text-red-400',
  revoked: 'text-red-500',
}

// ─── Sub-componentes ──────────────────────────────────────────────────────────

function StatCard({
  label,
  value,
  colorClass,
  emphasis,
  to,
}: {
  label: string
  value: number
  colorClass?: string
  emphasis?: boolean
  /** Destino opcional (5.1 del design): sin él la tarjeta queda inerte, como
   * agentes e infraestructura, que no tienen lista prefiltrada a la que ir. */
  to?: string
}) {
  const className = `bg-gray-800 border rounded-lg p-4 flex flex-col gap-1 ${
    emphasis ? 'border-red-600 bg-red-950/30' : 'border-gray-700'
  }`

  const content = (
    <>
      <span className={`text-2xl font-bold tabular-nums ${colorClass ?? 'text-white'}`}>
        {value}
      </span>
      <span className={`text-xs ${emphasis ? 'text-red-300' : 'text-gray-400'}`}>{label}</span>
    </>
  )

  if (to) {
    return (
      <Link to={to} className={`${className} hover:border-gray-500 transition-colors focus:outline-none focus:ring-2 focus:ring-primary`}>
        {content}
      </Link>
    )
  }

  return <div className={className}>{content}</div>
}

// ─── Página ───────────────────────────────────────────────────────────────────

const EVENT_STATUSES: EventStatus[] = [
  'pending',
  'approved',
  'rejected',
  'auto_restored',
  'quarantined',
  'alert_only',
  'superseded',
]

const AGENT_STATUSES: AgentStatus[] = ['online', 'offline', 'draining', 'dead', 'revoked']

export function Dashboard() {
  const { data, isLoading, isError, refetch, dataUpdatedAt } = useDashboard()

  // D39/RN-133: pasa por el helper compartido como el resto de la consola —
  // ningún componente formatea un instante por su cuenta (frontend-time-display).
  const lastUpdate = dataUpdatedAt ? formatAbsolute(dataUpdatedAt) : null

  return (
    <div className="space-y-6">
      {/* Encabezado */}
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold text-white">Dashboard</h1>
        {lastUpdate && (
          <span className="text-xs text-gray-500">
            Actualizado {lastUpdate} · polling cada 30s
          </span>
        )}
      </div>

      {isLoading ? (
        <div className="py-12 text-center text-gray-500">Cargando dashboard...</div>
      ) : isError ? (
        <QueryErrorState resource="el dashboard" onRetry={() => refetch()} />
      ) : (
        <>
          {/* Sección: Pending crítico/alto — énfasis visual diferenciado */}
          <section>
            <h2 className="text-sm font-medium text-gray-400 mb-3 uppercase tracking-wider">
              Pending criticos y altos
            </h2>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <StatCard
                label="Pending (todos)"
                value={data?.eventsByStatus.pending ?? 0}
                colorClass="text-yellow-400"
                to="/events?status=pending"
              />
              <StatCard
                label="Pending critical + high"
                value={data?.pendingCriticalHigh ?? 0}
                colorClass="text-red-400"
                emphasis={(data?.pendingCriticalHigh ?? 0) > 0}
                to="/events?status=pending&severity=critical&severity=high"
              />
            </div>
          </section>

          {/* Sección: Eventos por estado */}
          <section>
            <h2 className="text-sm font-medium text-gray-400 mb-3 uppercase tracking-wider">
              Eventos por estado
            </h2>
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
              {EVENT_STATUSES.map((s) => (
                <StatCard
                  key={s}
                  label={s}
                  value={data?.eventsByStatus[s] ?? 0}
                  colorClass={EVENT_STATUS_COLORS[s]}
                  // `superseded` está excluido del listado por default (RN-22/RN-98):
                  // sin `include_superseded=true` el enlace llevaría a una lista
                  // vacía (:5.4).
                  to={
                    s === 'superseded'
                      ? `/events?status=${s}&include_superseded=true`
                      : `/events?status=${s}`
                  }
                />
              ))}
            </div>
          </section>

          {/* Sección: Agentes por estado */}
          <section>
            <h2 className="text-sm font-medium text-gray-400 mb-3 uppercase tracking-wider">
              Agentes
            </h2>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              {AGENT_STATUSES.map((s) => (
                <StatCard
                  key={s}
                  label={AGENT_STATUS_LABELS[s]}
                  value={data?.agentsByStatus[s] ?? 0}
                  colorClass={AGENT_STATUS_COLORS[s]}
                />
              ))}
            </div>
          </section>

          {/* Sección: Estado de infraestructura */}
          <section>
            <h2 className="text-sm font-medium text-gray-400 mb-3 uppercase tracking-wider">
              Infraestructura
            </h2>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              {data?.health &&
                Object.entries(data.health).map(([name, status]) => (
                  <div
                    key={name}
                    className="bg-gray-800 border border-gray-700 rounded-lg p-3 flex items-center gap-2"
                  >
                    <span
                      className={`w-2 h-2 rounded-full shrink-0 ${
                        status === 'ok' ? 'bg-green-500' : 'bg-red-500'
                      }`}
                    />
                    <div>
                      <p className="text-xs font-medium text-gray-200 capitalize">{name}</p>
                      <p
                        className={`text-xs ${
                          status === 'ok' ? 'text-green-400' : 'text-red-400'
                        }`}
                      >
                        {status}
                      </p>
                    </div>
                  </div>
                ))}
            </div>
          </section>
        </>
      )}
    </div>
  )
}
