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

// D-5 del design de frontend-severity-triage: `action` va DENTRO de cada
// ítem, espejando `BulkRejectItem` del backend (schemas.py:57-61), donde es
// obligatoria y sin default. El backend rechaza con 422 el cuerpo con la
// acción al nivel superior — con el campo en el tipo, omitirlo deja de
// compilar.
export interface BulkRejectItem {
  event_id: number
  version: number
  action: RejectAction
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

export async function bulkReject(items: BulkRejectItem[]): Promise<BulkResult> {
  const { data } = await apiClient.post<BulkResult>('/actions/bulk-reject', { items })
  return data
}
