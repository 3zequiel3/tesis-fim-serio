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

export interface EventListItem {
  id: number
  path: string
  hash_detected: string | null
  status: EventStatus
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
