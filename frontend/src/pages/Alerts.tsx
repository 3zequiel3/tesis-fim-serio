import { useSearchParams } from 'react-router-dom'
import { useAlerts } from '@/hooks/useAlerts'
import type { AlertFilters, AlertStatus, AlertSeverity } from '@/api/alerts'

// ─── URL param helpers ────────────────────────────────────────────────────────

function parseAlertFilters(sp: URLSearchParams): AlertFilters {
  return {
    status: (sp.get('status') as AlertStatus) || undefined,
    severity: (sp.get('severity') as AlertSeverity) || undefined,
    page: sp.get('page') ? Number(sp.get('page')) : 1,
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

// ─── Helpers visuales ────────────────────────────────────────────────────────

const SEVERITY_COLORS: Record<string, string> = {
  critical: 'text-red-400',
  high: 'text-orange-400',
  medium: 'text-yellow-400',
  low: 'text-blue-400',
}

const STATUS_COLORS: Record<string, string> = {
  pending: 'text-yellow-400',
  delivered: 'text-green-400',
  failed: 'text-red-400',
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleString('es-AR', {
    day: '2-digit',
    month: '2-digit',
    year: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

// ─── Página ───────────────────────────────────────────────────────────────────

const STATUS_OPTIONS: AlertStatus[] = ['pending', 'delivered', 'failed']
const SEVERITY_OPTIONS: AlertSeverity[] = ['critical', 'high', 'medium', 'low']

export function Alerts() {
  const [searchParams, setSearchParams] = useSearchParams()
  const filters = parseAlertFilters(searchParams)

  const { data, isLoading, isFetching } = useAlerts(filters)

  function updateFilter(updates: Partial<AlertFilters>) {
    const newFilters = { ...filters, ...updates, page: 1 }
    setSearchParams(serializeAlertFilters(newFilters))
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
      {/* Encabezado */}
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold text-white">Alertas</h1>
        {isFetching && !isLoading && (
          <span className="text-xs text-gray-500">Actualizando...</span>
        )}
      </div>

      {/* Filtros */}
      <div className="bg-gray-800 border border-gray-700 rounded p-4 flex flex-wrap gap-4">
        <div>
          <label className="block text-xs text-gray-400 mb-1">Estado</label>
          <select
            value={filters.status ?? ''}
            onChange={(e) =>
              updateFilter({ status: (e.target.value as AlertStatus) || undefined })
            }
            className="px-3 py-1.5 bg-gray-900 border border-gray-600 rounded text-sm text-gray-200 focus:outline-none focus:border-primary"
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
          <label className="block text-xs text-gray-400 mb-1">Severidad</label>
          <select
            value={filters.severity ?? ''}
            onChange={(e) =>
              updateFilter({ severity: (e.target.value as AlertSeverity) || undefined })
            }
            className="px-3 py-1.5 bg-gray-900 border border-gray-600 rounded text-sm text-gray-200 focus:outline-none focus:border-primary"
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

      {/* Tabla */}
      {isLoading ? (
        <div className="py-12 text-center text-gray-500">Cargando alertas...</div>
      ) : !data || data.items.length === 0 ? (
        <div className="py-12 text-center text-gray-500">
          <p className="text-sm">No hay alertas con los filtros seleccionados.</p>
        </div>
      ) : (
        <div className="bg-gray-800 border border-gray-700 rounded overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-700 text-xs text-gray-400">
                <th className="text-left px-4 py-2.5">ID</th>
                <th className="text-left px-4 py-2.5">Severidad</th>
                <th className="text-left px-4 py-2.5">Estado</th>
                <th className="text-left px-4 py-2.5">Canal</th>
                <th className="text-left px-4 py-2.5">Creada</th>
                <th className="text-left px-4 py-2.5">Entregada</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-700">
              {data.items.map((alert) => (
                <tr key={alert.id} className="hover:bg-gray-750">
                  <td className="px-4 py-2.5 text-gray-400 tabular-nums">{alert.id}</td>
                  <td className={`px-4 py-2.5 font-medium ${SEVERITY_COLORS[alert.severity] ?? 'text-gray-300'}`}>
                    {alert.severity}
                  </td>
                  <td className={`px-4 py-2.5 font-medium ${STATUS_COLORS[alert.status] ?? 'text-gray-300'}`}>
                    {alert.status}
                  </td>
                  <td className="px-4 py-2.5 text-gray-400 font-mono text-xs">{alert.channel}</td>
                  <td className="px-4 py-2.5 text-gray-400 text-xs">{formatDate(alert.created_at)}</td>
                  <td className="px-4 py-2.5 text-gray-400 text-xs">
                    {alert.delivered_at ? formatDate(alert.delivered_at) : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Paginación */}
      {!isLoading && total > 0 && (
        <div className="flex items-center justify-between text-sm text-gray-400">
          <span>
            {(currentPage - 1) * size + 1}–{Math.min(currentPage * size, total)} de {total}
          </span>
          <div className="flex items-center gap-2">
            <button
              onClick={() => handlePageChange(currentPage - 1)}
              disabled={currentPage <= 1}
              className="px-3 py-1.5 bg-gray-800 border border-gray-700 rounded hover:bg-gray-700 disabled:opacity-40 disabled:cursor-not-allowed"
            >
              Anterior
            </button>
            <span className="tabular-nums">
              Página {currentPage} de {totalPages}
            </span>
            <button
              onClick={() => handlePageChange(currentPage + 1)}
              disabled={currentPage >= totalPages}
              className="px-3 py-1.5 bg-gray-800 border border-gray-700 rounded hover:bg-gray-700 disabled:opacity-40 disabled:cursor-not-allowed"
            >
              Siguiente
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
