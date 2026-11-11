import { Link, useSearchParams } from 'react-router-dom'
import { useAlerts } from '@/hooks/useAlerts'
import { DataState } from '@/components/ui/DataState'
import { PathLabel } from '@/components/ui/PathLabel'
import { Button } from '@/components/ui/Button'
import { inputClassName } from '@/components/ui/Field'
import { ResponsiveTable, type Column } from '@/components/ui/ResponsiveTable'
import { formatAbsolute } from '@/utils/timeDisplay'
import { getSeverityMeta } from '@/utils/severity'
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

const STATUS_TONE: Record<string, string> = {
  pending: 'text-warning-fg',
  delivered: 'text-success-fg',
  failed: 'text-danger-fg',
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
    cell: (a) => (
      <span className={`font-semibold ${getSeverityMeta(a.severity).textClass}`}>{a.severity}</span>
    ),
  },
  { key: 'action', header: 'Acción', cell: (a) => <span className="font-mono text-xs text-text-muted">{a.action_taken ?? '—'}</span> },
  {
    key: 'status',
    header: 'Estado',
    cell: (a) => <span className={`font-semibold ${STATUS_TONE[a.status] ?? 'text-text'}`}>{a.status}</span>,
  },
  { key: 'channel', header: 'Canal', cell: (a) => <span className="font-mono text-xs text-text-muted">{a.channel ?? 'sin canal entregado'}</span> },
  { key: 'created', header: 'Creada', cell: (a) => <span className="text-xs text-text-muted">{formatAbsolute(a.created_at)}</span> },
  {
    key: 'delivered',
    header: 'Entregada',
    cell: (a) => <span className="text-xs text-text-muted">{formatAbsolute(a.delivered_at, { nullLabel: '—' })}</span>,
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
                {s}
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
                {s}
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
