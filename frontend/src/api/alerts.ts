import { apiClient } from '@/api/client'

// ─── Tipos ────────────────────────────────────────────────────────────────────

export type AlertStatus = 'pending' | 'delivered' | 'failed'
export type AlertSeverity = 'critical' | 'high' | 'medium' | 'low'

export interface Alert {
  id: number
  event_id: number
  severity: AlertSeverity
  status: AlertStatus
  channel: string
  created_at: string
  delivered_at: string | null
  failed_at: string | null
  // US-19: path del archivo y tipo de acción tomada sobre el evento asociado
  // (derivados server-side con un join a `events`; null si el evento no tiene
  // acción tomada todavía, p. ej. status=pending).
  path: string | null
  action_taken: string | null
}

export interface AlertFilters {
  status?: AlertStatus
  severity?: AlertSeverity
  page?: number
  size?: number
}

export interface AlertListResponse {
  total: number
  page: number
  size: number
  items: Alert[]
}

// ─── Funciones API ────────────────────────────────────────────────────────────

export async function getAlerts(filters: AlertFilters = {}): Promise<AlertListResponse> {
  const { data } = await apiClient.get<AlertListResponse>('/alerts', {
    params: filters,
  })
  return data
}

export async function getFailedAlerts(): Promise<Alert[]> {
  const { data } = await apiClient.get<{ items: Alert[]; total: number }>('/alerts/failed')
  return data.items
}

export async function retryAlert(id: number): Promise<void> {
  await apiClient.post(`/alerts/${id}/retry`)
}

export async function discardAlert(id: number): Promise<void> {
  await apiClient.delete(`/alerts/${id}`)
}

export interface StreamTicket {
  ticket: string
  expires_in: number
}

/**
 * Pide un ticket SSE de un solo uso para GET /alerts/stream (D64/RN-158).
 * Va por el cliente HTTP autenticado (JWT en Authorization, con el refresh
 * automático del interceptor) — nunca por la URL del stream, que no admite
 * headers (EventSource).
 */
export async function fetchStreamTicket(): Promise<StreamTicket> {
  const { data } = await apiClient.post<StreamTicket>('/alerts/stream-ticket')
  return data
}
