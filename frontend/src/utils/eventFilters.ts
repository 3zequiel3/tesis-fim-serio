import type { EventFilters } from '@/api/events'

const DEFAULT_PAGE = 1
const DEFAULT_PAGE_SIZE = 50

/**
 * Parsea los filtros de eventos desde URLSearchParams.
 * Defaults: page=1, page_size=50, include_superseded=false.
 */
export function parseEventFilters(sp: URLSearchParams): EventFilters {
  const statusValues = sp.getAll('status')
  const severityValues = sp.getAll('severity')
  return {
    status: statusValues.length > 0 ? statusValues : undefined,
    // Mismo patrón que status: array si hay valores, undefined si está
    // vacío. El undefined mantiene la URL limpia y evita que el query key
    // de TanStack cambie por un array vacío (D-4).
    severity: severityValues.length > 0 ? severityValues : undefined,
    path_prefix: sp.get('path_prefix') ?? undefined,
    date_from: sp.get('date_from') ?? undefined,
    date_to: sp.get('date_to') ?? undefined,
    include_superseded: sp.get('include_superseded') === 'true' ? true : undefined,
    page: sp.get('page') ? Number(sp.get('page')) : DEFAULT_PAGE,
    page_size: DEFAULT_PAGE_SIZE,
  }
}

/**
 * Serializa los filtros de eventos a URLSearchParams.
 * Omite valores default para URLs limpias.
 */
export function serializeEventFilters(f: EventFilters): URLSearchParams {
  const sp = new URLSearchParams()
  if (f.status && f.status.length > 0) {
    f.status.forEach((s) => sp.append('status', s))
  }
  if (f.severity && f.severity.length > 0) {
    f.severity.forEach((s) => sp.append('severity', s))
  }
  if (f.path_prefix) sp.set('path_prefix', f.path_prefix)
  if (f.date_from) sp.set('date_from', f.date_from)
  if (f.date_to) sp.set('date_to', f.date_to)
  if (f.include_superseded) sp.set('include_superseded', 'true')
  if (f.page && f.page > DEFAULT_PAGE) sp.set('page', String(f.page))
  // page_size se omite: siempre DEFAULT_PAGE_SIZE, el backend usa su default
  return sp
}
