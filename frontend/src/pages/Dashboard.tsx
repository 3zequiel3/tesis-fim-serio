import { Link } from 'react-router-dom'
import { useDashboard } from '@/hooks/useDashboard'
import { DataState } from '@/components/ui/DataState'
import { PathLabel } from '@/components/ui/PathLabel'
import { StatusBadge } from '@/components/ui/StatusBadge'
import { getSeverityMeta } from '@/utils/severity'
import { formatAbsolute } from '@/utils/timeDisplay'
import type { EventStatus } from '@/api/events'
import type { AgentStatus } from '@/api/agents'

// ─── Helpers ──────────────────────────────────────────────────────────────────

// C1/RN-71: minúsculas snake_case en toda la UI, con excepción única para
// botones de acción — una etiqueta de contador no lo es. La etiqueta ES el
// valor canónico, igual que en la tabla de eventos.

const AGENT_STATUS_LABELS: Record<AgentStatus, string> = {
  online: 'Online',
  offline: 'Offline',
  draining: 'Draining',
  dead: 'Dead',
  revoked: 'Revoked',
}

const AGENT_STATUS_TONE: Record<AgentStatus, string> = {
  online: 'text-success-fg',
  offline: 'text-neutral-fg',
  draining: 'text-warning-fg',
  dead: 'text-danger-fg',
  revoked: 'text-danger-fg',
}

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

// `superseded` está excluido del listado por default (RN-22/RN-98): sin
// `include_superseded=true` el enlace llevaría a una lista vacía.
function eventsLink(status: EventStatus): string {
  return status === 'superseded'
    ? `/events?status=${status}&include_superseded=true`
    : `/events?status=${status}`
}

// ─── Sub-componentes ──────────────────────────────────────────────────────────

function Metric({
  label,
  value,
  tone,
  emphasis,
  to,
}: {
  label: string
  value: number
  tone?: string
  emphasis?: boolean
  /** Destino opcional: sin él el indicador queda inerte (agentes sin lista prefiltrada). */
  to?: string
}) {
  const className = `flex items-baseline justify-between gap-3 rounded-panel border px-4 py-3 ${
    emphasis ? 'border-danger-line bg-danger-bg' : 'border-line bg-surface-raised'
  }`
  const content = (
    <>
      <span className={emphasis ? 'text-danger-fg' : 'text-text-muted'}>{label}</span>
      <span className={`text-xl font-semibold tabular-nums ${tone ?? 'text-text'}`}>{value}</span>
    </>
  )
  if (to) {
    return (
      <Link to={to} className={`${className} hover:border-line-strong`}>
        {content}
      </Link>
    )
  }
  return <div className={className}>{content}</div>
}

/**
 * Proportional bar of events by state (design D-1): each segment is a link to
 * the filtered list and carries its state color; the legend below spells the
 * numbers out, so the bar never relies on color alone.
 */
// Tailwind only generates utilities for class names it can read literally.
const SEGMENT_BG: Record<EventStatus, string> = {
  pending: 'bg-status-pending',
  approved: 'bg-status-approved',
  rejected: 'bg-status-rejected',
  superseded: 'bg-status-superseded',
  auto_restored: 'bg-status-auto_restored',
  quarantined: 'bg-status-quarantined',
  alert_only: 'bg-status-alert_only',
}

function StatusBar({ counts }: { counts: Record<EventStatus, number> }) {
  const total = EVENT_STATUSES.reduce((sum, s) => sum + (counts[s] ?? 0), 0)
  if (total === 0) {
    return <p className="rounded-panel border border-dashed border-line-strong px-4 py-6 text-center text-text-muted">Todavía no hay eventos registrados.</p>
  }
  return (
    <div
      role="group"
      aria-label="Proporción de eventos por estado"
      className="flex h-4 w-full overflow-hidden rounded-control border border-line bg-surface"
    >
      {EVENT_STATUSES.filter((s) => (counts[s] ?? 0) > 0).map((s) => (
        <Link
          key={s}
          to={eventsLink(s)}
          title={`${s}: ${counts[s]}`}
          aria-label={`Ver eventos ${s}`}
          style={{ width: `${((counts[s] ?? 0) / total) * 100}%` }}
          className={`min-w-1 ${SEGMENT_BG[s]} border-r border-surface last:border-r-0 hover:opacity-80`}
        />
      ))}
    </div>
  )
}

// ─── Página ───────────────────────────────────────────────────────────────────

export function Dashboard() {
  const { data, isLoading, error, refetch, dataUpdatedAt } = useDashboard()

  // D39/RN-133: pasa por el helper compartido como el resto de la consola —
  // ningún componente formatea un instante por su cuenta (frontend-time-display).
  const lastUpdate = dataUpdatedAt ? formatAbsolute(dataUpdatedAt) : null

  return (
    <div className="space-y-8">
      {/* Encabezado */}
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h1 className="text-2xl font-semibold text-text">Dashboard</h1>
        {lastUpdate && (
          <span className="text-xs text-text-muted">Actualizado {lastUpdate} · polling cada 30s</span>
        )}
      </div>

      <DataState
        isLoading={isLoading}
        error={error}
        onRetry={() => void refetch()}
        resource="el dashboard"
        loadingLabel="Cargando dashboard..."
      >
        {/* Sección: lo que el operador tiene que mirar */}
        <section className="space-y-3">
          <h2 className="text-lg font-semibold text-text">Pending criticos y altos</h2>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <Metric
              label="Pending (todos)"
              value={data?.eventsByStatus.pending ?? 0}
              to="/events?status=pending"
            />
            <Metric
              label="Pending critical + high"
              value={data?.pendingCriticalHigh ?? 0}
              tone={(data?.pendingCriticalHigh ?? 0) > 0 ? 'text-danger-fg' : undefined}
              emphasis={(data?.pendingCriticalHigh ?? 0) > 0}
              to="/events?status=pending&severity=critical&severity=high"
            />
          </div>
          {(data?.pendingCriticalHighItems.length ?? 0) > 0 && (
            <ul aria-label="Pendientes críticos y altos más recientes" className="divide-y divide-line rounded-panel border border-line bg-surface-raised">
              {data?.pendingCriticalHighItems.map((item) => (
                <li key={item.id}>
                  <Link
                    to={`/events/${item.id}`}
                    className={`flex flex-wrap items-center gap-x-3 gap-y-1 border-l-4 px-4 py-2 hover:bg-surface-hover ${getSeverityMeta(item.severity).bandClass}`}
                  >
                    <span className="min-w-0 flex-1">
                      <PathLabel path={item.path} />
                    </span>
                    <span className={`font-mono text-xs font-semibold ${getSeverityMeta(item.severity).textClass}`}>{item.severity}</span>
                    <StatusBadge status={item.status} />
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </section>

        {/* Sección: Eventos por estado */}
        <section className="space-y-3">
          <h2 className="text-lg font-semibold text-text">Eventos por estado</h2>
          <StatusBar counts={data?.eventsByStatus ?? ({} as Record<EventStatus, number>)} />
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
            {EVENT_STATUSES.map((s) => (
              <Metric
                key={s}
                label={s}
                value={data?.eventsByStatus[s] ?? 0}
                to={eventsLink(s)}
              />
            ))}
          </div>
        </section>

        {/* Sección: Agentes por estado */}
        <section className="space-y-3">
          <h2 className="text-lg font-semibold text-text">Agentes</h2>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5">
            {AGENT_STATUSES.map((s) => (
              <Metric
                key={s}
                label={AGENT_STATUS_LABELS[s]}
                value={data?.agentsByStatus[s] ?? 0}
                tone={AGENT_STATUS_TONE[s]}
              />
            ))}
          </div>
        </section>

        {/* Sección: Estado de infraestructura */}
        <section className="space-y-3">
          <h2 className="text-lg font-semibold text-text">Infraestructura</h2>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            {data?.health &&
              Object.entries(data.health).map(([name, status]) => (
                <div
                  key={name}
                  className="flex items-center gap-2 rounded-panel border border-line bg-surface-raised p-3"
                >
                  <span
                    aria-hidden="true"
                    className={`size-2 shrink-0 rounded-full ${status === 'ok' ? 'bg-status-approved' : 'bg-status-rejected'}`}
                  />
                  <div>
                    <p className="font-semibold capitalize text-text">{name}</p>
                    <p className={status === 'ok' ? 'text-success-fg' : 'text-danger-fg'}>{status}</p>
                  </div>
                </div>
              ))}
          </div>
        </section>
      </DataState>
    </div>
  )
}
