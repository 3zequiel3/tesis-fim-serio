import { useDashboard } from '@/hooks/useDashboard'
import type { EventStatus } from '@/api/events'
import type { AgentStatus } from '@/api/agents'

// ─── Helpers ──────────────────────────────────────────────────────────────────

const EVENT_STATUS_LABELS: Record<EventStatus, string> = {
  pending: 'Pending',
  approved: 'Approved',
  rejected: 'Rejected',
  superseded: 'Superseded',
  auto_restored: 'Auto-restored',
  quarantined: 'Quarantined',
  alert_only: 'Alert only',
}

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
}

const AGENT_STATUS_COLORS: Record<AgentStatus, string> = {
  online: 'text-green-400',
  offline: 'text-gray-500',
  draining: 'text-yellow-400',
  dead: 'text-red-400',
}

// ─── Sub-componentes ──────────────────────────────────────────────────────────

function StatCard({
  label,
  value,
  colorClass,
  emphasis,
}: {
  label: string
  value: number
  colorClass?: string
  emphasis?: boolean
}) {
  return (
    <div
      className={`bg-gray-800 border rounded-lg p-4 flex flex-col gap-1 ${
        emphasis
          ? 'border-red-600 bg-red-950/30'
          : 'border-gray-700'
      }`}
    >
      <span className={`text-2xl font-bold tabular-nums ${colorClass ?? 'text-white'}`}>
        {value}
      </span>
      <span className={`text-xs ${emphasis ? 'text-red-300' : 'text-gray-400'}`}>{label}</span>
    </div>
  )
}

// ─── Página ───────────────────────────────────────────────────────────────────

const EVENT_STATUSES: EventStatus[] = [
  'pending',
  'approved',
  'rejected',
  'auto_restored',
  'quarantined',
  'alert_only',
]

const AGENT_STATUSES: AgentStatus[] = ['online', 'offline', 'draining', 'dead']

export function Dashboard() {
  const { data, isLoading, dataUpdatedAt } = useDashboard()

  const lastUpdate = dataUpdatedAt
    ? new Date(dataUpdatedAt).toLocaleTimeString('es-AR', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
    : null

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
              />
              <StatCard
                label="Pending critical + high"
                value={data?.pendingCriticalHigh ?? 0}
                colorClass="text-red-400"
                emphasis={(data?.pendingCriticalHigh ?? 0) > 0}
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
                  label={EVENT_STATUS_LABELS[s]}
                  value={data?.eventsByStatus[s] ?? 0}
                  colorClass={EVENT_STATUS_COLORS[s]}
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
