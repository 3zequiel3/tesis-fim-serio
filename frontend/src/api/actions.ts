import { apiClient } from '@/api/client'

// ─── Tipos derivados del contrato backend-approve-reject (C13) ───────────────

export type RejectAction = 'restore' | 'quarantine'

export type BulkFailReason =
  | 'conflict'
  | 'absent_confirmation_required'
  | 'not_found'
  | 'forbidden'
  | string

export interface BulkItem {
  event_id: number
  version: number
  confirm_absent?: boolean
}

export interface BulkRejectItem {
  event_id: number
  version: number
}

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

export async function bulkApprove(items: BulkItem[]): Promise<BulkResult> {
  const { data } = await apiClient.post<BulkResult>('/actions/bulk-approve', { items })
  return data
}

export async function bulkReject(items: BulkRejectItem[], action: RejectAction): Promise<BulkResult> {
  const { data } = await apiClient.post<BulkResult>('/actions/bulk-reject', { items, action })
  return data
}
