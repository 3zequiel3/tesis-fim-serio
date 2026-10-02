import { apiClient } from '@/api/client'

// ─── Tipos derivados del contrato backend-approve-reject (C13) ───────────────

export type RejectAction = 'restore' | 'quarantine'

export type BulkFailReason =
  | 'conflict'
  | 'absent_confirmation_required'
  | 'not_found'
  | 'forbidden'
  | string

export interface BulkFailedItem {
  event_id: number
  reason: BulkFailReason
}

export interface BulkResult {
  succeeded: number[]
  failed: BulkFailedItem[]
}

// D83/RN-177: cómo se libera una cuarentena. `restore_original` APRUEBA el
// contenido cuarentenado; `restore_baseline` vuelve a la versión aprobada;
// `discard` sólo elimina el artefacto.
export type ReleaseMode = 'restore_original' | 'restore_baseline' | 'discard'

// ─── Parámetros de las acciones individuales ─────────────────────────────────

export interface ApproveParams {
  event_id: number
  version: number
  confirm_absent?: boolean
}

export interface RejectParams {
  event_id: number
  version: number
  action: RejectAction
}

// US-12 (D-8): cuerpo de POST /actions/reject — baseline_absent señala una
// condición de carrera entre el baseline_status leído al abrir el modal y el
// estado real al confirmar (ver useEventActions.ts).
export interface RejectResponse {
  event_id: number
  status: string
  baseline_absent: boolean
}

export interface ReleaseQuarantineParams {
  event_id: number
  mode: ReleaseMode
  reason: string
}

// Cuerpo 202 de POST /events/{id}/quarantine/release: la liberación es
// asíncrona, el resultado llega por command_ack (ack_status / quarantine_state).
export interface ReleaseQuarantineResponse {
  event_id: number
  command_id: string
  mode: ReleaseMode
  ack_status: string
}

// ─── Funciones API ────────────────────────────────────────────────────────────

export async function approve(params: ApproveParams): Promise<void> {
  await apiClient.post('/actions/approve', params)
}

export async function reject(params: RejectParams): Promise<RejectResponse> {
  const { data } = await apiClient.post<RejectResponse>('/actions/reject', params)
  return data
}

export async function bulkApprove(eventIds: number[]): Promise<BulkResult> {
  const { data } = await apiClient.post<BulkResult>('/actions/bulk-approve', { event_ids: eventIds })
  return data
}

export async function bulkReject(eventIds: number[], action: RejectAction): Promise<BulkResult> {
  const { data } = await apiClient.post<BulkResult>('/actions/bulk-reject', { event_ids: eventIds, action })
  return data
}

export async function releaseQuarantine(
  eventId: number,
  body: { mode: ReleaseMode; reason: string },
): Promise<ReleaseQuarantineResponse> {
  const { data } = await apiClient.post<ReleaseQuarantineResponse>(
    `/events/${eventId}/quarantine/release`,
    body,
  )
  return data
}
