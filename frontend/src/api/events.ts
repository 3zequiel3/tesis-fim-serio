import { apiClient } from '@/api/client'

// ─── Tipos derivados del contrato backend-events-api (C11) ───────────────────

export type EventStatus =
  | 'pending'
  | 'approved'
  | 'rejected'
  | 'superseded'
  | 'auto_restored'
  | 'quarantined'
  | 'alert_only'

// Estado de EJECUCIÓN del comando asociado al evento (D30/RN-124, C36).
// Indicador secundario, distinto de EventStatus — NO forma parte de la
// máquina de estados del evento (RN-72). Ausente cuando no hay comando
// confirmable asociado.
export type CommandAckStatus = 'pending' | 'acked' | 'failed' | 'timeout'

// Severidad persistida del evento (D34/RN-128, C38): calculada al ingerir
// con la logica compartida de D-C15-01 (severidad maxima de las reglas que
// matchean el path; sin matches -> low).
export type EventSeverity = 'critical' | 'high' | 'medium' | 'low'

export interface EventListItem {
  id: number
  // D51/RN-145: vocabulario canonico que el agente ya emite (file_created,
  // file_modified, file_deleted, file_absent, detection_gap), snake_case
  // (RN-71). Discriminador que la tabla y el detalle usan para renderizar un
  // evento sin ruta — no el nulo de `path` (D-10 del design).
  event_type: string
  // D51/RN-145: nulo para eventos que no hablan de ningun archivo concreto,
  // como detection_gap (D50/RN-144, brecha de cobertura del kernel).
  path: string | null
  // Contrato C11/C38: EventOut.hash_detected es str no-nullable — el backend
  // nunca envía null (a lo sumo cadena vacía para eventos sin hash). El flujo
  // de archivo ausente (confirm_absent/baseline_absent) va por el 422 del
  // backend, no por este campo.
  hash_detected: string
  status: EventStatus
  severity: EventSeverity
  parent_event_id: number | null
  version: number
  process_pid: number | null
  process_uid: number | null
  process_exe: string | null
  detected_at: string   // ISO8601
  received_at: string
  created_at: string
  resolved_at: string | null
  resolved_by: number | null
  ack_status?: CommandAckStatus | null
  // D33/RN-127 (C39): symlink-as-object. is_symlink distingue un evento sobre
  // un symlink (nunca se sigue el link) de uno sobre un archivo regular;
  // symlink_target es el string crudo de os.readlink, sin normalizar.
  is_symlink: boolean
  symlink_target: string | null
  // D35/RN-129 (C40): true cuando la acción automática (auto_restore/quarantine)
  // falló en el agente. Ortogonal al status — un pending con action_failed=true
  // significa que el archivo sigue adulterado y la remediación ya falló.
  action_failed: boolean
  // D36/RN-130 (C41): causa del fallo de la acción automática — distingue
  // barrera de despliegue (read_only_mount, permission_denied) de problema
  // de datos (no_baseline_content, no_baseline_metadata, ...). Ausente
  // cuando action_failed es false.
  action_error?: string | null
}

// US-09: el diff se entrega solo en el detalle. Es un patch unificado acotado,
// no las versiones completas del archivo.
export type EventDetail = EventListItem & {
  hash_expected: string | null
  diff_text: string | null
}

export interface EventListResponse {
  total: number
  page: number
  page_size: number
  items: EventListItem[]
}

export interface EventFilters {
  status?: string[]
  // Filtro repetible por severidad (D34/RN-128), simétrico con `status`.
  // `string[]` y no `EventSeverity[]` a propósito (D-4 del design de
  // frontend-severity-triage): la URL es entrada no confiable, y un tipo
  // estricto acá daría una garantía falsa sobre un valor que viene de una
  // query string. El backend valida contra su enum y responde 422.
  severity?: string[]
  path_prefix?: string
  date_from?: string
  date_to?: string
  include_superseded?: boolean
  page?: number
  page_size?: number
}

// D39/RN-133 (D-4 del design de timestamps-timezone-aware): los filtros de
// fecha de <input type="datetime-local"> son hora de pared del navegador,
// sin desfase. La conversión a UTC ocurre ACÁ, al construir la petición
// HTTP — no al escribir la URL (eventFilters.ts no se toca, D-4). La URL
// sigue llevando la hora local que el operador tipeó, legible y estable
// para links compartidos; este es el único punto de conversión y por lo
// tanto el único lugar donde va el test (frontend-events spec).
//
// `new Date(local)` interpreta un string sin desfase como hora LOCAL — la
// misma regla de ECMAScript que causa el defecto en el sentido inverso
// (parsear un instante UTC sin desfase como si fuera local) es, usada acá
// a propósito, la conversión correcta: el valor de un datetime-local YA es
// hora de pared local, y ese es exactamente el significado que se le da.
function localFilterToUtcInstant(local: string): string | undefined {
  const parsed = new Date(local)
  if (Number.isNaN(parsed.getTime())) return undefined
  return parsed.toISOString()
}

// ─── Funciones API ────────────────────────────────────────────────────────────

export async function getEvents(filters: EventFilters = {}): Promise<EventListResponse> {
  const { data } = await apiClient.get<EventListResponse>('/events', {
    params: filters,
    paramsSerializer: (p: EventFilters) => {
      const sp = new URLSearchParams()
      if (p.status && p.status.length > 0) {
        p.status.forEach((s) => sp.append('status', s))
      }
      // Repetible, no comma-joined ni bracket notation: el backend declara
      // `Annotated[list[RuleSeverity], Query(alias="severity")]` (router.py:73)
      // y sólo acepta la forma repetida — verificado en vivo (D-4).
      if (p.severity && p.severity.length > 0) {
        p.severity.forEach((s) => sp.append('severity', s))
      }
      if (p.path_prefix) sp.set('path_prefix', p.path_prefix)
      const dateFrom = p.date_from ? localFilterToUtcInstant(p.date_from) : undefined
      const dateTo = p.date_to ? localFilterToUtcInstant(p.date_to) : undefined
      if (dateFrom) sp.set('date_from', dateFrom)
      if (dateTo) sp.set('date_to', dateTo)
      if (p.include_superseded) sp.set('include_superseded', 'true')
      if (p.page && p.page > 1) sp.set('page', String(p.page))
      if (p.page_size) sp.set('page_size', String(p.page_size))
      return sp.toString()
    },
  })
  return data
}

export async function getEvent(id: number): Promise<EventDetail> {
  const { data } = await apiClient.get<EventDetail>(`/events/${id}`)
  return data
}
