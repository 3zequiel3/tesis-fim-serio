import { Link } from 'react-router-dom'
import { ArrowRight, BellRing, ListChecks, Server } from 'lucide-react'
import { useDashboard } from '@/hooks/useDashboard'
import { DataState } from '@/components/ui/DataState'
import { PathLabel } from '@/components/ui/PathLabel'
import { StatusBadge } from '@/components/ui/StatusBadge'
import { getSeverityMeta } from '@/utils/severity'
import { formatAbsolute } from '@/utils/timeDisplay'
import type { EventStatus } from '@/api/events'
import type { AgentStatus } from '@/api/agents'

// ─── Helpers ──────────────────────────────────────────────────────────────────

// US-04, criterio 2: «los valores de estado se muestran siempre en minúsculas
// (snake_case), alineados al léxico canónico C1». El criterio exige que el
// valor canónico esté a la vista; no exige que sea lo único a la vista, y
// RN-71 acota su alcance a persistencia, APIs, streams, logs y documentación
// técnica — no a la etiqueta que lee un operador. Cada fila muestra entonces
// el nombre en español y, junto a él, el valor canónico en monoespaciada: el
// humano lee el nombre, el criterio conserva el identificador.

const EVENT_STATUS_LABELS: Record<EventStatus, string> = {
  pending: 'Pendientes',
  approved: 'Aprobados',
  rejected: 'Rechazados',
  auto_restored: 'Restaurados',
  quarantined: 'En cuarentena',
  alert_only: 'Solo alerta',
  superseded: 'Reemplazados',
}

const AGENT_STATUS_LABELS: Record<AgentStatus, string> = {
  online: 'En línea',
  offline: 'Sin conexión',
  draining: 'Drenando',
  dead: 'Caído',
  revoked: 'Revocado',
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

// `superseded` está excluido del listado por default (RN-22/RN-98): sin
// `include_superseded=true` el enlace llevaría a una lista vacía.
function eventsLink(status: EventStatus): string {
  return status === 'superseded'
    ? `/events?status=${status}&include_superseded=true`
    : `/events?status=${status}`
}

function plural(n: number, one: string, many: string): string {
  return n === 1 ? one : many
}

// ─── Sub-componentes ──────────────────────────────────────────────────────────

/**
 * El parte: una sola frase que responde la única pregunta que el operador trae
 * a esta pantalla — ¿algo necesita mi decisión ahora? El resto de la página es
 * el respaldo de esa frase.
 */
function Verdict({
  pending,
  criticalHigh,
}: {
  pending: number
  criticalHigh: number
}) {
  if (criticalHigh > 0) {
    return (
      <p className="text-2xl font-semibold text-danger-fg sm:text-3xl">
        {criticalHigh} {plural(criticalHigh, 'evento crítico o alto espera', 'eventos críticos o altos esperan')} tu
        decisión
      </p>
    )
  }
  if (pending > 0) {
    return (
      <p className="text-2xl font-semibold text-text sm:text-3xl">
        {pending} {plural(pending, 'evento espera', 'eventos esperan')} tu decisión
      </p>
    )
  }
  return <p className="text-2xl font-semibold text-text sm:text-3xl">Nada espera tu decisión</p>
}

function QuickAction({
  to,
  icon: Icon,
  children,
  primary,
}: {
  to: string
  icon: typeof ArrowRight
  children: string
  primary?: boolean
}) {
  const tone = primary
    ? 'border-accent bg-accent text-on-accent hover:bg-accent-hover'
    : 'border-line bg-surface text-text hover:border-line-strong hover:bg-surface-hover'
  return (
    <Link
      to={to}
      className={`inline-flex items-center gap-2 rounded-control border px-3 py-2 text-sm font-medium ${tone}`}
    >
      <Icon aria-hidden="true" className="size-4 shrink-0" />
      {children}
    </Link>
  )
}

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
 * Lectura de eventos por estado: una fila por estado canónico, con una barra
 * proporcional al total. La jerarquía sale del dato y no de una tarjeta
 * elegida a mano — un estado en cero se apaga solo y el que manda se impone.
 */
function StatusReadout({ counts }: { counts: Record<EventStatus, number> }) {
  const total = EVENT_STATUSES.reduce((sum, s) => sum + (counts[s] ?? 0), 0)
  const peak = EVENT_STATUSES.reduce((max, s) => Math.max(max, counts[s] ?? 0), 0)

  return (
    <div className="overflow-hidden rounded-panel border border-line bg-surface-raised">
      {total === 0 && (
        <p className="border-b border-line px-4 py-3 text-text-muted">
          Todavía no hay eventos registrados. Van a aparecer acá apenas un agente reporte el primero.
        </p>
      )}
      <ul className="divide-y divide-line">
        {EVENT_STATUSES.map((s) => {
          const count = counts[s] ?? 0
          const width = peak > 0 ? (count / peak) * 100 : 0
          return (
            <li key={s}>
              <Link
                to={eventsLink(s)}
                className="grid grid-cols-[minmax(0,11rem)_1fr_auto] items-center gap-3 px-4 py-2.5 hover:bg-surface-hover sm:grid-cols-[minmax(0,15rem)_1fr_auto]"
              >
                <span className="flex min-w-0 flex-wrap items-baseline gap-x-2">
                  <span className={count > 0 ? 'text-text' : 'text-text-muted'}>
                    {EVENT_STATUS_LABELS[s]}
                  </span>
                  <span className="font-mono text-xs text-text-muted">{s}</span>
                </span>
                {/* Un estado en cero no dibuja riel: seis rieles vacíos son
                    ruido y le roban la única barra que sí dice algo. */}
                <span aria-hidden="true" className="h-1.5">
                  {count > 0 && (
                    <span
                      className={`block h-full rounded-full ${SEGMENT_BG[s]}`}
                      style={{ width: `${Math.max(width, 2)}%` }}
                    />
                  )}
                </span>
                <span
                  className={`w-12 text-right text-base font-semibold tabular-nums ${
                    count > 0 ? 'text-text' : 'text-text-muted'
                  }`}
                >
                  {count}
                </span>
              </Link>
            </li>
          )
        })}
      </ul>
    </div>
  )
}

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="space-y-3">
      <h2 className="text-lg font-semibold text-text">{title}</h2>
      {children}
    </section>
  )
}

// ─── Página ───────────────────────────────────────────────────────────────────

export function Dashboard() {
  const { data, isLoading, error, refetch, dataUpdatedAt } = useDashboard()

  // D39/RN-133: pasa por el helper compartido como el resto de la consola —
  // ningún componente formatea un instante por su cuenta (frontend-time-display).
  const lastUpdate = dataUpdatedAt ? formatAbsolute(dataUpdatedAt) : null

  const pending = data?.eventsByStatus.pending ?? 0
  const criticalHigh = data?.pendingCriticalHigh ?? 0
  const totalEvents = data
    ? EVENT_STATUSES.reduce((sum, s) => sum + (data.eventsByStatus[s] ?? 0), 0)
    : 0
  const agentsDown = data ? (data.agentsByStatus.dead ?? 0) + (data.agentsByStatus.revoked ?? 0) : 0
  const servicesDown = data
    ? Object.values(data.health).filter((status) => status !== 'ok').length
    : 0

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
        {/* El parte y las acciones que se desprenden de él */}
        <section
          aria-label="Estado general"
          className={`rounded-panel border p-5 sm:p-6 ${
            criticalHigh > 0 ? 'border-danger-line bg-danger-bg' : 'border-line bg-surface-raised'
          }`}
        >
          <Verdict pending={pending} criticalHigh={criticalHigh} />
          <p className="mt-2 text-sm text-text-muted">
            {totalEvents} {plural(totalEvents, 'evento registrado', 'eventos registrados')}
            {agentsDown > 0 && ` · ${agentsDown} ${plural(agentsDown, 'agente caído', 'agentes caídos')}`}
            {servicesDown > 0 &&
              ` · ${servicesDown} ${plural(servicesDown, 'servicio degradado', 'servicios degradados')}`}
          </p>
          <div className="mt-5 flex flex-wrap gap-2">
            <QuickAction to="/events?status=pending" icon={ListChecks} primary>
              Revisar pendientes
            </QuickAction>
            <QuickAction to="/alerts/failed" icon={BellRing}>
              Alertas fallidas
            </QuickAction>
            <QuickAction to="/agents" icon={Server}>
              Agentes
            </QuickAction>
          </div>
        </section>

        {/* Sección: lo que el operador tiene que mirar */}
        <Panel title="Cola de decisión">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <Metric label="Pendientes (todos)" value={pending} to="/events?status=pending" />
            <Metric
              label="Pendientes críticos + altos"
              value={criticalHigh}
              tone={criticalHigh > 0 ? 'text-danger-fg' : undefined}
              emphasis={criticalHigh > 0}
              to="/events?status=pending&severity=critical&severity=high"
            />
          </div>
          {(data?.pendingCriticalHighItems.length ?? 0) > 0 && (
            <ul
              aria-label="Pendientes críticos y altos más recientes"
              className="divide-y divide-line rounded-panel border border-line bg-surface-raised"
            >
              {data?.pendingCriticalHighItems.map((item) => (
                <li key={item.id}>
                  <Link
                    to={`/events/${item.id}`}
                    className={`flex flex-wrap items-center gap-x-3 gap-y-1 border-l-4 px-4 py-2 hover:bg-surface-hover ${getSeverityMeta(item.severity).bandClass}`}
                  >
                    <span className="min-w-0 basis-full sm:basis-0 sm:flex-1">
                      <PathLabel path={item.path} />
                    </span>
                    <span
                      className={`font-mono text-xs font-semibold ${getSeverityMeta(item.severity).textClass}`}
                    >
                      {item.severity}
                    </span>
                    <StatusBadge status={item.status} />
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </Panel>

        {/* Sección: Eventos por estado */}
        <Panel title="Eventos por estado">
          <StatusReadout counts={data?.eventsByStatus ?? ({} as Record<EventStatus, number>)} />
        </Panel>

        {/* Sección: Agentes e infraestructura, el soporte del parte */}
        <div className="grid grid-cols-1 gap-8 lg:grid-cols-2">
          <Panel title="Agentes">
            <div className="overflow-hidden rounded-panel border border-line bg-surface-raised">
              <ul className="divide-y divide-line">
                {AGENT_STATUSES.map((s) => (
                  <li key={s}>
                    {/* La fila es un <div> y no el <li>: el contrato de los tests
                        busca la tarjeta con closest('div, a') desde la etiqueta. */}
                    <div className="flex items-baseline justify-between gap-3 px-4 py-2.5">
                      <span className="text-text-muted">{AGENT_STATUS_LABELS[s]}</span>
                      {/* El tono del estado sólo se aplica si hay agentes en él:
                          un cero en rojo se lee como alarma y no lo es. */}
                      <span
                        className={`text-base font-semibold tabular-nums ${
                          (data?.agentsByStatus[s] ?? 0) > 0 ? AGENT_STATUS_TONE[s] : 'text-text-muted'
                        }`}
                      >
                        {data?.agentsByStatus[s] ?? 0}
                      </span>
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          </Panel>

          <Panel title="Infraestructura">
            <div className="overflow-hidden rounded-panel border border-line bg-surface-raised">
              <ul className="divide-y divide-line">
                {data?.health &&
                  Object.entries(data.health).map(([name, status]) => (
                    <li key={name}>
                      {/* Ídem agentes: la fila es el <div> que los tests buscan. */}
                      <div className="flex items-baseline justify-between gap-3 px-4 py-2.5">
                        <span className="flex items-baseline gap-2">
                          <span
                            aria-hidden="true"
                            className={`size-2 shrink-0 rounded-full ${status === 'ok' ? 'bg-status-approved' : 'bg-status-rejected'}`}
                          />
                          <span className="font-mono text-sm text-text">{name}</span>
                        </span>
                        <span
                          className={`font-mono text-sm ${status === 'ok' ? 'text-success-fg' : 'text-danger-fg'}`}
                        >
                          {status}
                        </span>
                      </div>
                    </li>
                  ))}
              </ul>
            </div>
          </Panel>
        </div>
      </DataState>
    </div>
  )
}
