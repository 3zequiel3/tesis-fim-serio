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
  path: string
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

// El detalle del evento tiene los mismos campos que el listado
export type EventDetail = EventListItem

export interface EventListResponse {
  total: number
  page: number
  page_size: number
  items: EventListItem[]
}

export interface EventFilters {
  status?: string[]
  path_prefix?: string
  date_from?: string
  date_to?: string
  include_superseded?: boolean
  page?: number
  page_size?: number
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
      if (p.path_prefix) sp.set('path_prefix', p.path_prefix)
      if (p.date_from) sp.set('date_from', p.date_from)
      if (p.date_to) sp.set('date_to', p.date_to)
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
