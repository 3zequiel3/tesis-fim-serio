import { useState, useEffect, useRef } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useEvents } from '@/hooks/useEvents'
import { EventsTable } from '@/components/ui/EventsTable'
import { BulkActionBar } from '@/components/ui/BulkActionBar'
import { parseEventFilters, serializeEventFilters } from '@/utils/eventFilters'
import type { EventFilters } from '@/api/events'

const ALL_STATUSES = [
  'pending',
  'approved',
  'rejected',
  'auto_restored',
  'quarantined',
  'alert_only',
] as const

export function Events() {
  const [searchParams, setSearchParams] = useSearchParams()
  const filters = parseEventFilters(searchParams)
  const [selected, setSelected] = useState<Set<number>>(new Set())

  // Limpiar selección cuando cambian los filtros o la página
  useEffect(() => {
    setSelected(new Set())
  }, [searchParams.toString()])

  const { data, isLoading, isFetching } = useEvents(filters)

  // Debounce para path_prefix
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const [pathInput, setPathInput] = useState(filters.path_prefix ?? '')

  function updateFilter(updates: Partial<EventFilters>) {
    const newFilters: EventFilters = { ...filters, ...updates, page: 1 }
    setSearchParams(serializeEventFilters(newFilters))
  }

  function handlePathChange(value: string) {
    setPathInput(value)
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => {
      updateFilter({ path_prefix: value || undefined })
    }, 300)
  }

  function handleStatusToggle(status: string) {
    const current = filters.status ?? []
    const next = current.includes(status)
      ? current.filter((s) => s !== status)
      : [...current, status]
    updateFilter({ status: next.length > 0 ? next : undefined })
  }

  function handlePageChange(newPage: number) {
    const newFilters = { ...filters, page: newPage }
    setSearchParams(serializeEventFilters(newFilters))
  }

  const total = data?.total ?? 0
  const pageSize = filters.page_size ?? 50
  const currentPage = filters.page ?? 1
  const totalPages = Math.max(1, Math.ceil(total / pageSize))
  const showSuperseded = !!filters.include_superseded

  return (
    <div className="space-y-4">
      {/* Encabezado */}
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold text-white">Eventos</h1>
        {isFetching && !isLoading && (
          <span className="text-xs text-gray-500">Actualizando...</span>
        )}
      </div>

      {/* Panel de filtros */}
      <div className="bg-gray-800 border border-gray-700 rounded p-4 space-y-3">
        {/* Filtro por estado */}
        <div>
          <p className="text-xs text-gray-400 mb-1.5">Estado</p>
          <div className="flex flex-wrap gap-2">
            {ALL_STATUSES.map((s) => (
              <label key={s} className="flex items-center gap-1.5 text-sm text-gray-300 cursor-pointer">
                <input
                  type="checkbox"
                  checked={(filters.status ?? []).includes(s)}
                  onChange={() => handleStatusToggle(s)}
                  className="rounded"
                />
                <span className="font-mono text-xs">{s}</span>
              </label>
            ))}
            {showSuperseded && (
              <label className="flex items-center gap-1.5 text-sm text-gray-300 cursor-pointer">
                <input
                  type="checkbox"
                  checked={(filters.status ?? []).includes('superseded')}
                  onChange={() => handleStatusToggle('superseded')}
                  className="rounded"
                />
                <span className="font-mono text-xs">superseded</span>
              </label>
            )}
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          {/* Filtro por path */}
          <div>
            <label className="block text-xs text-gray-400 mb-1">Prefijo de path</label>
            <input
              type="text"
              value={pathInput}
              onChange={(e) => handlePathChange(e.target.value)}
              placeholder="/etc/..."
              className="w-full px-3 py-1.5 bg-gray-900 border border-gray-600 rounded text-sm text-gray-200 placeholder-gray-600 focus:outline-none focus:border-primary"
            />
          </div>

          {/* Fecha desde */}
          <div>
            <label className="block text-xs text-gray-400 mb-1">Desde</label>
            <input
              type="datetime-local"
              value={filters.date_from ?? ''}
              onChange={(e) => updateFilter({ date_from: e.target.value || undefined })}
              className="w-full px-3 py-1.5 bg-gray-900 border border-gray-600 rounded text-sm text-gray-200 focus:outline-none focus:border-primary"
            />
          </div>

          {/* Fecha hasta */}
          <div>
            <label className="block text-xs text-gray-400 mb-1">Hasta</label>
            <input
              type="datetime-local"
              value={filters.date_to ?? ''}
              onChange={(e) => updateFilter({ date_to: e.target.value || undefined })}
              className="w-full px-3 py-1.5 bg-gray-900 border border-gray-600 rounded text-sm text-gray-200 focus:outline-none focus:border-primary"
            />
          </div>
        </div>

        {/* Toggle superseded */}
        <label className="flex items-center gap-2 text-sm text-gray-300 cursor-pointer">
          <input
            type="checkbox"
            checked={showSuperseded}
            onChange={(e) =>
              updateFilter({ include_superseded: e.target.checked || undefined })
            }
            className="rounded"
          />
          Mostrar eventos superseded
        </label>
      </div>

      {/* BulkActionBar (se muestra solo si hay selección) */}
      {selected.size > 0 && (
        <BulkActionBar
          selected={selected}
          items={data?.items ?? []}
          filters={filters}
          onClearSelection={() => setSelected(new Set())}
        />
      )}

      {/* Tabla de eventos */}
      {isLoading ? (
        <div className="py-12 text-center text-gray-500">Cargando eventos...</div>
      ) : (
        <EventsTable
          items={data?.items ?? []}
          selected={selected}
          onSelectionChange={setSelected}
        />
      )}

      {/* Paginación */}
      {!isLoading && total > 0 && (
        <div className="flex items-center justify-between text-sm text-gray-400">
          <span>
            Mostrando {(currentPage - 1) * pageSize + 1}–{Math.min(currentPage * pageSize, total)} de {total} eventos
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
