import { Link, useSearchParams } from 'react-router-dom'
import { useAlerts } from '@/hooks/useAlerts'
import { DataState } from '@/components/ui/DataState'
import { PathLabel } from '@/components/ui/PathLabel'
import { Button } from '@/components/ui/Button'
import { inputClassName } from '@/components/ui/Field'
import { ResponsiveTable, type Column } from '@/components/ui/ResponsiveTable'
import { formatAbsolute } from '@/utils/timeDisplay'
import { getSeverityMeta } from '@/utils/severity'
import { getRuleActionLabel } from '@/utils/ruleAction'
import { getAlertDeliveryMeta } from '@/utils/alertDelivery'
import { CanonicalLabel } from '@/components/ui/CanonicalLabel'
import type { Alert, AlertFilters, AlertStatus, AlertSeverity } from '@/api/alerts'

// ─── URL param helpers ────────────────────────────────────────────────────────

function parseAlertFilters(sp: URLSearchParams): AlertFilters {
  const rawPage = Number(sp.get('page'))
  return {
    status: (sp.get('status') as AlertStatus) || undefined,
    severity: (sp.get('severity') as AlertSeverity) || undefined,
    // Same sanitizing as the events list (M7): the URL is untrusted.
    page: Number.isInteger(rawPage) && rawPage >= 1 ? rawPage : 1,
    size: 50,
  }
}

function serializeAlertFilters(f: AlertFilters): URLSearchParams {
  const sp = new URLSearchParams()
  if (f.status) sp.set('status', f.status)
  if (f.severity) sp.set('severity', f.severity)
  if (f.page && f.page > 1) sp.set('page', String(f.page))
  return sp
}

/**
 * Cuánto pasó entre que la alerta se creó y se entregó, redondeado a algo
 * que se lea de un vistazo. Devuelve «—» mientras no haya entrega.
 */
function formatDeliveryLag(createdAt: string | null | undefined, deliveredAt: string | null | undefined): string {
  if (!createdAt || !deliveredAt) return '—'
  const ms = new Date(deliveredAt).getTime() - new Date(createdAt).getTime()
  if (!Number.isFinite(ms) || ms < 0) return '—'
  if (ms < 1000) return `${ms} ms`
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)} s`
  return `${Math.round(ms / 60_000)} min`
}

const STATUS_OPTIONS: AlertStatus[] = ['pending', 'delivered', 'failed']
const SEVERITY_OPTIONS: AlertSeverity[] = ['critical', 'high', 'medium', 'low']

const COLUMNS: Column<Alert>[] = [
  { key: 'id', header: 'ID', cell: (a) => <span className="tabular-nums text-text-muted">{a.id}</span> },
  {
    key: 'path',
    header: 'Ruta',
    primary: true,
    cell: (a) => (
      // US-19: la alerta es navegable hacia el detalle del evento asociado.
      <Link to={`/events/${a.event_id}`} className="hover:underline">
        {a.path ? <PathLabel path={a.path} /> : '—'}
      </Link>
    ),
  },
  {
    key: 'severity',
    header: 'Severidad',
    cell: (a) => {
      const meta = getSeverityMeta(a.severity)
      return <CanonicalLabel name={meta.label} value={a.severity} className={`font-semibold ${meta.textClass}`} />
    },
  },
  {
    key: 'action',
    header: 'Acción',
    cell: (a) =>
      a.action_taken ? (
        <CanonicalLabel name={getRuleActionLabel(a.action_taken)} value={a.action_taken} className="text-xs text-text-muted" />
      ) : (
        <span className="text-xs text-text-muted">—</span>
      ),
  },
  {
    key: 'status',
    header: 'Estado',
    cell: (a) => {
      const meta = getAlertDeliveryMeta(a.status)
      return (
        <span className="inline-flex flex-wrap items-baseline gap-x-1.5">
          <CanonicalLabel name={meta.label} value={a.status} className={`font-semibold ${meta.toneClass}`} />
          {/* El canal era una columna propia repitiendo «n8n» en cada fila.
              Sólo informa junto a la entrega, y sólo cuando hubo una. */}
          {a.channel && <span className="font-mono text-[0.6875rem] text-text-muted">por {a.channel}</span>}
        </span>
      )
    },
  },
  {
    key: 'created',
    header: 'Creada',
    // Misma razón que en la tabla de eventos: la fecha es el dato, el
    // relativo sería una comodidad que la tapa.
    cell: (a) => <span className="text-xs tabular-nums text-text-muted">{formatAbsolute(a.created_at)}</span>,
  },
  {
    // La fecha de entrega repetía la de creación segundo a segundo en cada
    // fila: cincuenta timbres idénticos y ningún dato. Lo que informa es
    // cuánto tardó, así que la columna muestra la demora y deja la marca
    // absoluta en el tooltip.
    key: 'delivered',
    header: 'Demora',
    cell: (a) => (
      <span className="text-xs text-text-muted" title={formatAbsolute(a.delivered_at, { nullLabel: 'sin entregar' })}>
        {formatDeliveryLag(a.created_at, a.delivered_at)}
      </span>
    ),
  },
]

// ─── Página ───────────────────────────────────────────────────────────────────

export function Alerts() {
  const [searchParams, setSearchParams] = useSearchParams()
  const filters = parseAlertFilters(searchParams)

  const { data, isLoading, isFetching, error, refetch } = useAlerts(filters)

  function updateFilter(updates: Partial<AlertFilters>) {
    setSearchParams(serializeAlertFilters({ ...filters, ...updates, page: 1 }))
  }

  function handlePageChange(newPage: number) {
    setSearchParams(serializeAlertFilters({ ...filters, page: newPage }))
  }

  const total = data?.total ?? 0
  const size = filters.size ?? 50
  const currentPage = filters.page ?? 1
  const totalPages = Math.max(1, Math.ceil(total / size))

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold text-text">Alertas</h1>
        <div className="flex items-center gap-3">
          {isFetching && !isLoading && <span className="text-xs text-text-muted">Actualizando...</span>}
          <Link to="/alerts/failed" className="font-semibold text-accent underline">
            Ver alertas fallidas
          </Link>
        </div>
      </div>

      <div className="flex flex-wrap gap-4 rounded-panel border border-line bg-surface-raised p-4">
        <div>
          <label htmlFor="alert-status" className="mb-1 block text-xs font-semibold text-text-muted">
            Estado
          </label>
          <select
            id="alert-status"
            value={filters.status ?? ''}
            onChange={(e) => updateFilter({ status: (e.target.value as AlertStatus) || undefined })}
            className={inputClassName}
          >
            <option value="">Todos</option>
            {STATUS_OPTIONS.map((s) => (
              <option key={s} value={s}>
                {getAlertDeliveryMeta(s).label ?? s} ({s})
              </option>
            ))}
          </select>
        </div>
        <div>
          <label htmlFor="alert-severity" className="mb-1 block text-xs font-semibold text-text-muted">
            Severidad
          </label>
          <select
            id="alert-severity"
            value={filters.severity ?? ''}
            onChange={(e) => updateFilter({ severity: (e.target.value as AlertSeverity) || undefined })}
            className={inputClassName}
          >
            <option value="">Todas</option>
            {SEVERITY_OPTIONS.map((s) => (
              <option key={s} value={s}>
                {getSeverityMeta(s).label ?? s} ({s})
              </option>
            ))}
          </select>
        </div>
      </div>

      <DataState
        isLoading={isLoading}
        error={error}
        onRetry={() => void refetch()}
        resource="las alertas"
        loadingLabel="Cargando alertas..."
        isEmpty={!data || data.items.length === 0}
        emptyTitle="No hay alertas con los filtros seleccionados."
        emptyHint="Cuando un cambio dispare una alerta, la vas a ver acá."
      >
        <ResponsiveTable
          caption="Alertas"
          columns={COLUMNS}
          rows={data?.items ?? []}
          getRowKey={(a) => a.id}
          rowClassName={(a) => `border-l-4 ${getSeverityMeta(a.severity).bandClass}`}
        />
      </DataState>

      {!isLoading && !error && total > 0 && (
        <div className="flex flex-wrap items-center justify-between gap-3 text-text-muted">
          <span>
            {(currentPage - 1) * size + 1}–{Math.min(currentPage * size, total)} de {total}
          </span>
          <div className="flex items-center gap-2">
            <Button onClick={() => handlePageChange(currentPage - 1)} disabled={currentPage <= 1}>
              Anterior
            </Button>
            <span className="tabular-nums">
              Página {currentPage} de {totalPages}
            </span>
            <Button onClick={() => handlePageChange(currentPage + 1)} disabled={currentPage >= totalPages}>
              Siguiente
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}
