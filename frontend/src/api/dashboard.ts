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
  // Agentes e infraestructura en paralelo
  const [agentsRes, healthRes] = await Promise.all([
    apiClient.get<{ items: Array<{ status: AgentStatus }>; total: number }>('/agents'),
    apiClient.get<{ postgres: string; valkey: string; n8n: string; agents: { status: string; items: unknown[] }; checked_at: string }>('/health/components'),
  ])

  // Contar eventos por estado: el backend no agrega por status, se usa el
  // total de una request page_size=1 por cada status relevante.
  const statuses: EventStatus[] = ['pending', 'approved', 'rejected', 'auto_restored', 'quarantined', 'alert_only', 'superseded']

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

  // KPI real de pendings criticos/altos: una sola request con el filtro
  // severity persistido en el evento (D34/RN-128). El parametro es repetible,
  // igual que status.
  const pendingCriticalHigh = await apiClient
    .get<{ total: number }>('/events', {
      params: new URLSearchParams([
        ['status', 'pending'],
        ['severity', 'critical'],
        ['severity', 'high'],
        ['page_size', '1'],
      ]),
    })
    .then((r) => r.data.total)

  // Contar agentes por status
  const agentItems = agentsRes.data.items
  const agentStatuses: AgentStatus[] = ['online', 'offline', 'draining', 'dead', 'revoked']
  const agentsByStatus = agentStatuses.reduce(
    (acc, s) => {
      acc[s] = agentItems.filter((a) => a.status === s).length
      return acc
    },
    {} as Record<AgentStatus, number>
  )

  const h = healthRes.data
  return {
    eventsByStatus,
    pendingCriticalHigh,
    agentsByStatus,
    health: {
      postgres: h.postgres,
      valkey: h.valkey,
      n8n: h.n8n,
      agents: h.agents.status,
    },
  }
}
