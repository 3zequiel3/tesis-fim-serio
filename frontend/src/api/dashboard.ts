import { apiClient } from '@/api/client'
import type { AgentStatus } from '@/api/agents'
import type { EventStatus } from '@/api/events'

// ─── Tipos ────────────────────────────────────────────────────────────────────

export interface DashboardSummary {
  eventsByStatus: Record<EventStatus, number>
  pendingCriticalHigh: number
  agentsByStatus: Record<AgentStatus, number>
  health: {
    postgres: string
    valkey: string
    n8n: string
    agents: string
  }
}

// ─── Funciones API ────────────────────────────────────────────────────────────

export async function getDashboardSummary(): Promise<DashboardSummary> {
  // Obtener datos de 3 endpoints en paralelo
  const [eventsRes, agentsRes, healthRes] = await Promise.all([
    apiClient.get<{ total: number; items: Array<{ status: EventStatus; severity?: string }> }>('/events', {
      params: { page_size: 100 },
    }),
    apiClient.get<Array<{ status: AgentStatus }>>('/agents'),
    apiClient.get<{ postgres: string; valkey: string; n8n: string; agents: string }>('/health/components'),
  ])

  // Contar eventos por estado — usamos un segundo call con page_size pequeño para obtener contadores
  // El backend retorna el total, pero no agrega por status directamente.
  // Hacemos calls por cada status relevante para obtener los totales.
  const statuses: EventStatus[] = ['pending', 'approved', 'rejected', 'auto_restored', 'quarantined', 'alert_only']

  const countResults = await Promise.all(
    statuses.map((s) =>
      apiClient
        .get<{ total: number }>('/events', { params: { status: s, page_size: 1 } })
        .then((r) => ({ status: s, count: r.data.total }))
    )
  )

  const eventsByStatus = statuses.reduce(
    (acc, s) => {
      acc[s] = countResults.find((r) => r.status === s)?.count ?? 0
      return acc
    },
    {} as Record<EventStatus, number>
  )

  // Pending críticos y altos — calls adicionales
  const [criticalPending, highPending] = await Promise.all([
    apiClient
      .get<{ total: number }>('/events', { params: { status: 'pending', severity: 'critical', page_size: 1 } })
      .then((r) => r.data.total)
      .catch(() => 0),
    apiClient
      .get<{ total: number }>('/events', { params: { status: 'pending', severity: 'high', page_size: 1 } })
      .then((r) => r.data.total)
      .catch(() => 0),
  ])

  // Contar agentes por status
  const agentStatuses: AgentStatus[] = ['online', 'offline', 'draining', 'dead']
  const agentsByStatus = agentStatuses.reduce(
    (acc, s) => {
      acc[s] = agentsRes.data.filter((a) => a.status === s).length
      return acc
    },
    {} as Record<AgentStatus, number>
  )

  return {
    eventsByStatus,
    pendingCriticalHigh: criticalPending + highPending,
    agentsByStatus,
    health: healthRes.data,
  }
}
