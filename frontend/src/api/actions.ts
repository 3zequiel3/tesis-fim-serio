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

// ─── Funciones API ────────────────────────────────────────────────────────────

export async function approve(params: ApproveParams): Promise<void> {
  await apiClient.post('/actions/approve', params)
}

export async function reject(params: RejectParams): Promise<void> {
  await apiClient.post('/actions/reject', params)
}

export async function bulkApprove(eventIds: number[]): Promise<BulkResult> {
  const { data } = await apiClient.post<BulkResult>('/actions/bulk-approve', { event_ids: eventIds })
  return data
}

export async function bulkReject(eventIds: number[], action: RejectAction): Promise<BulkResult> {
  const { data } = await apiClient.post<BulkResult>('/actions/bulk-reject', { event_ids: eventIds, action })
  return data
}
