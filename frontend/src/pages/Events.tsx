import { useCallback, useEffect, useMemo, useRef, useState, type Dispatch, type SetStateAction } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useEvents } from '@/hooks/useEvents'
import { useCan } from '@/hooks/useCan'
import { Can } from '@/components/ui/Can'
import { EventsTable } from '@/components/ui/EventsTable'
import { BulkActionBar } from '@/components/ui/BulkActionBar'
import { DataState } from '@/components/ui/DataState'
import { Pagination } from '@/components/ui/Pagination'
import { StatusBadge } from '@/components/ui/StatusBadge'
import { inputClassName } from '@/components/ui/Field'
import { Button } from '@/components/ui/Button'
import { useMediaQuery } from '@/hooks/useMediaQuery'
import { SlidersHorizontal } from 'lucide-react'
import { parseEventFilters, serializeEventFilters } from '@/utils/eventFilters'
import type { EventFilters } from '@/api/events'
import { CanonicalLabel } from '@/components/ui/CanonicalLabel'
import { getSeverityMeta } from '@/utils/severity'
import { getQuarantineStateMeta } from '@/utils/quarantineState'

// US-07 C1, W1, D-2 del design: los siete estados canónicos (RN-71), siempre
// visibles y en este orden. `superseded` NO depende del toggle "Mostrar
// superseded" para aparecer en el selector — sólo el toggle decide si el
// listado los incluye (ver handleStatusToggle y el onChange del toggle).
const ALL_STATUSES = [
  'pending',
  'approved',
  'rejected',
  'auto_restored',
  'quarantined',
  'alert_only',
  'superseded',
] as const

// Orden de precedencia descendente (critical > high > medium > low): el
// orden en que el operador los busca, no el alfabético (:4.5).
const ALL_SEVERITIES = ['critical', 'high', 'medium', 'low'] as const

// D82/RN-176: resultado físico de la cuarentena. `none` no se ofrece: es la
// ausencia de filtro, no algo que el operador busque.
const ALL_QUARANTINE_STATES = ['quarantined', 'released', 'discarded'] as const

export function Events() {
  const [searchParams, setSearchParams] = useSearchParams()
  const filters = parseEventFilters(searchParams)
  const canMutate = useCan()
  // ≤ 768 px: the filter panel is collapsed behind a toggle; on desktop it is always open.
  const isDesktop = useMediaQuery('(min-width: 769px)')
  const [filtersOpen, setFiltersOpen] = useState(false)

  const { data, isLoading, isFetching, error, refetch } = useEvents(filters)
  const items = useMemo(() => data?.items ?? [], [data])

  // Selection (M9): it belongs to the current filters/page, and it only keeps ids
  // that are in the list on screen, so a refresh can never leave stale ids behind.
  const selectionKey = searchParams.toString()
  const [selection, setSelection] = useState<{ key: string; ids: Set<number> }>({
    key: selectionKey,
    ids: new Set(),
  })
  const visibleIds = useMemo(() => new Set(items.map((item) => item.id)), [items])
  const selected = useMemo(
    () =>
      selection.key === selectionKey
        ? new Set([...selection.ids].filter((id) => visibleIds.has(id)))
        : new Set<number>(),
    [selection, selectionKey, visibleIds],
  )
  const setSelected: Dispatch<SetStateAction<Set<number>>> = useCallback(
    (action) => {
      setSelection((prev) => {
        const base =
          prev.key === selectionKey ? new Set([...prev.ids].filter((id) => visibleIds.has(id))) : new Set<number>()
        return { key: selectionKey, ids: typeof action === 'function' ? action(base) : action }
      })
    },
    [selectionKey, visibleIds],
  )

  // Debounce para path_prefix
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const urlPath = filters.path_prefix ?? ''
  const [pathInput, setPathInput] = useState(urlPath)
  // Back/forward or a shared link changed the URL: show it in the input. A value
  // this component committed itself is never written back: while the operator keeps
  // typing, a slow URL update must not overwrite what is already in the box.
  const [syncedUrlPath, setSyncedUrlPath] = useState(urlPath)
  const [committedPath, setCommittedPath] = useState(urlPath)
  if (syncedUrlPath !== urlPath) {
    setSyncedUrlPath(urlPath)
    if (urlPath !== committedPath) setPathInput(urlPath)
  }

  const cancelDebounce = useCallback(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = null
  }, [])
  useEffect(() => cancelDebounce, [cancelDebounce])

  // M9: always merge into the CURRENT params, never into the ones captured by the
  // render that scheduled the change. React Router applies a navigation in a
  // transition, so `searchParams` can lag behind a change that was just made (a
  // debounced path commit followed at once by a status toggle). `latestParams`
  // is updated synchronously on every change we make and re-synced from the URL
  // whenever it really changes (back/forward, a shared link).
  const latestParams = useRef(searchParams)
  useEffect(() => {
    latestParams.current = searchParams
  }, [searchParams])

  function applyFilters(compute: (current: EventFilters) => EventFilters) {
    const next = serializeEventFilters(compute(parseEventFilters(latestParams.current)))
    latestParams.current = next
    setSearchParams(next)
  }

  function updateFilter(updates: Partial<EventFilters>) {
    applyFilters((current) => ({ ...current, ...updates, page: 1 }))
  }

  function handlePathChange(value: string) {
    setPathInput(value)
    cancelDebounce()
    debounceRef.current = setTimeout(() => {
      debounceRef.current = null
      setCommittedPath(value)
      updateFilter({ path_prefix: value || undefined })
    }, 300)
  }

  function handleStatusToggle(status: string) {
    const current = filters.status ?? []
    const marking = !current.includes(status)
    const next = marking ? [...current, status] : current.filter((s) => s !== status)
    // D-2 del design: GET /events excluye superseded antes de aplicar status,
    // así que status=superseded sin include_superseded=true siempre devuelve
    // vacío. Marcarlo en el selector activa también el toggle; desmarcarlo
    // sólo lo quita del filtro de estado y deja el toggle como estaba (tiene
    // sentido propio: ver los reemplazados junto al resto sin filtrar).
    if (marking && status === 'superseded') {
      updateFilter({ status: next, include_superseded: true })
      return
    }
    updateFilter({ status: next.length > 0 ? next : undefined })
  }

  function handleSeverityToggle(severity: string) {
    const current = filters.severity ?? []
    const next = current.includes(severity)
      ? current.filter((s) => s !== severity)
      : [...current, severity]
    updateFilter({ severity: next.length > 0 ? next : undefined })
  }

  function handleQuarantineStateToggle(state: string) {
    const current = filters.quarantine_state ?? []
    const next = current.includes(state)
      ? current.filter((s) => s !== state)
      : [...current, state]
    updateFilter({ quarantine_state: next.length > 0 ? next : undefined })
  }

  function handlePageChange(newPage: number) {
    applyFilters((current) => ({ ...current, page: newPage }))
  }

  const total = data?.total ?? 0
  const pageSize = filters.page_size ?? 50
  const currentPage = filters.page ?? 1
  const totalPages = Math.max(1, Math.ceil(total / pageSize))
  const showSuperseded = !!filters.include_superseded

  const activeFilterCount =
    (filters.status?.length ?? 0) +
    (filters.severity?.length ?? 0) +
    (filters.quarantine_state?.length ?? 0) +
    (filters.path_prefix ? 1 : 0) +
    (filters.date_from ? 1 : 0) +
    (filters.date_to ? 1 : 0) +
    (filters.include_superseded ? 1 : 0)
  const showFilters = isDesktop || filtersOpen

  const checkLabel = 'flex cursor-pointer items-center gap-2 text-text'

  return (
    <div className="space-y-4">
      {/* Encabezado */}
      <div className="flex items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold text-text">Eventos</h1>
        {isFetching && !isLoading && <span className="text-xs text-text-muted">Actualizando...</span>}
      </div>

      {!isDesktop && (
        <Button
          aria-expanded={filtersOpen}
          aria-controls="events-filters"
          onClick={() => setFiltersOpen((open) => !open)}
          className="w-full justify-between"
        >
          <span className="inline-flex items-center gap-2">
            <SlidersHorizontal aria-hidden="true" size={16} />
            Filtros ({activeFilterCount})
          </span>
          <span className="text-xs font-normal text-text-muted">{filtersOpen ? 'Ocultar' : 'Mostrar'}</span>
        </Button>
      )}

      {/* Panel de filtros */}
      <div
        id="events-filters"
        hidden={!showFilters}
        className="space-y-3 rounded-panel border border-line bg-surface-raised p-4"
      >
        {/* Filtro por estado */}
        <fieldset>
          <legend className="mb-1.5 text-xs font-semibold text-text-muted">Estado</legend>
          <div className="flex flex-wrap gap-x-4 gap-y-2">
            {ALL_STATUSES.map((s) => (
              <label key={s} className={checkLabel}>
                <input
                  type="checkbox"
                  checked={(filters.status ?? []).includes(s)}
                  onChange={() => handleStatusToggle(s)}
                  className="size-4 accent-accent"
                />
                <StatusBadge status={s} />
              </label>
            ))}
          </div>
        </fieldset>

        {/* Severidad y cuarentena son listas cortas: conviven en una fila
            para que la tabla entre en pantalla sin desplazarse. */}
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        {/* Filtro por severidad (D34/RN-128) */}
        <fieldset>
          <legend className="mb-1.5 text-xs font-semibold text-text-muted">Severidad</legend>
          <div className="flex flex-wrap gap-x-4 gap-y-2">
            {ALL_SEVERITIES.map((s) => (
              <label key={s} className={checkLabel}>
                <input
                  type="checkbox"
                  checked={(filters.severity ?? []).includes(s)}
                  onChange={() => handleSeverityToggle(s)}
                  className="size-4 accent-accent"
                />
                <CanonicalLabel name={getSeverityMeta(s).label} value={s} className={`text-xs font-semibold ${getSeverityMeta(s).textClass}`} />
              </label>
            ))}
          </div>
        </fieldset>

        {/* Filtro por cuarentena (D82/RN-176) */}
        <fieldset>
          <legend className="mb-1.5 text-xs font-semibold text-text-muted">Cuarentena</legend>
          <div className="flex flex-wrap gap-x-4 gap-y-2">
            {ALL_QUARANTINE_STATES.map((s) => (
              <label key={s} className={checkLabel}>
                <input
                  type="checkbox"
                  checked={(filters.quarantine_state ?? []).includes(s)}
                  onChange={() => handleQuarantineStateToggle(s)}
                  // `quarantined` también es un estado del evento (selector de
                  // arriba): el nombre accesible los distingue. Lleva el texto
                  // visible completo porque WCAG 2.5.3 pide que el nombre
                  // accesible contenga lo que se lee en pantalla.
                  aria-label={`Cuarentena: ${getQuarantineStateMeta(s)?.name ?? s} ${s}`}
                  className="size-4 accent-accent"
                />
                <CanonicalLabel name={getQuarantineStateMeta(s)?.name} value={s} className="text-xs" />
              </label>
            ))}
          </div>
        </fieldset>
        </div>

        <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
          {/* Filtro por path */}
          <div>
            <label htmlFor="filter-path" className="mb-1 block text-xs font-semibold text-text-muted">
              Prefijo de ruta
            </label>
            <input
              id="filter-path"
              type="text"
              value={pathInput}
              onChange={(e) => handlePathChange(e.target.value)}
              placeholder="/etc/..."
              className={`${inputClassName} font-mono`}
            />
          </div>

          {/* Fecha desde */}
          <div>
            <label htmlFor="filter-from" className="mb-1 block text-xs font-semibold text-text-muted">
              Desde
            </label>
            <input
              id="filter-from"
              type="datetime-local"
              value={filters.date_from ?? ''}
              onChange={(e) => updateFilter({ date_from: e.target.value || undefined })}
              className={inputClassName}
            />
          </div>

          {/* Fecha hasta */}
          <div>
            <label htmlFor="filter-to" className="mb-1 block text-xs font-semibold text-text-muted">
              Hasta
            </label>
            <input
              id="filter-to"
              type="datetime-local"
              value={filters.date_to ?? ''}
              onChange={(e) => updateFilter({ date_to: e.target.value || undefined })}
              className={inputClassName}
            />
          </div>
        </div>

        {/* Toggle superseded */}
        <label className={checkLabel}>
          <input
            type="checkbox"
            checked={showSuperseded}
            onChange={(e) => {
              const on = e.target.checked
              // Apagar el toggle también quita superseded del filtro de
              // estado (D-2): dejarlo marcado con el toggle apagado volvería
              // a pedir status=superseded sin include_superseded, que el
              // backend siempre responde vacío. Encenderlo no marca
              // superseded en el selector — sólo reincorpora los eventos al
              // listado sin filtrar por ese estado.
              if (!on) {
                const next = (filters.status ?? []).filter((s) => s !== 'superseded')
                updateFilter({ status: next.length > 0 ? next : undefined, include_superseded: undefined })
                return
              }
              updateFilter({ include_superseded: true })
            }}
            className="size-4 accent-accent"
          />
          Mostrar eventos reemplazados (superseded)
        </label>
      </div>

      {/* Permanece montada después de la acción para conservar su resumen. */}
      <Can>
        <BulkActionBar
          selected={selected}
          items={items}
          filters={filters}
          onSelectionChange={setSelected}
        />
      </Can>

      {/* Tabla de eventos */}
      <DataState
        isLoading={isLoading}
        error={error}
        onRetry={() => void refetch()}
        resource="los eventos"
        loadingLabel="Cargando eventos..."
      >
        <EventsTable
          items={items}
          selected={selected}
          onSelectionChange={setSelected}
          selectable={canMutate}
        />
      </DataState>

      {/* Paginación (US-26: navegación numerada + "ir a página") */}
      {!isLoading && !error && total > 0 && (
        <div className="flex flex-wrap items-center justify-between gap-3 text-text-muted">
          <span>
            Mostrando {(currentPage - 1) * pageSize + 1}–{Math.min(currentPage * pageSize, total)} de {total} eventos
          </span>
          <Pagination currentPage={currentPage} totalPages={totalPages} onPageChange={handlePageChange} />
        </div>
      )}
    </div>
  )
}
