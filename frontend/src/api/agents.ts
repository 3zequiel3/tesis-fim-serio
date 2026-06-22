import { apiClient } from '@/api/client'

// ─── Tipos ────────────────────────────────────────────────────────────────────

export type AgentStatus = 'online' | 'offline' | 'draining' | 'dead'

export interface Agent {
  id: string
  hostname: string
  status: AgentStatus
  watch_paths: string[]
  queue_pressure: number   // 0..1 float
  last_seen: string        // ISO8601
  ruleset_version_applied: number | null
}

export interface AgentConfig {
  watch_paths: string[]
}

export interface RescanConflictError {
  code: 'pending_events_exist'
  count: number
}

// ─── Funciones API ────────────────────────────────────────────────────────────

export async function getAgents(): Promise<Agent[]> {
  const { data } = await apiClient.get<{ items: Agent[]; total: number }>('/agents')
  return data.items
}

export async function getAgent(id: string): Promise<Agent> {
  const { data } = await apiClient.get<Agent>(`/agents/${id}`)
  return data
}

export async function updateAgentConfig(id: string, config: AgentConfig): Promise<Agent> {
  const { data } = await apiClient.post<Agent>(`/agents/${id}/config`, config)
  return data
}

/**
 * Dispara rescan de un agente.
 * Si force=false y hay pending events, el backend retorna 409 con
 * { code: "pending_events_exist", count: N }.
 * El caller debe manejar el AxiosError 409 y leer error.response.data.
 */
export async function triggerRescan(id: string, force: boolean): Promise<void> {
  await apiClient.post(`/agents/${id}/rescan`, null, {
    params: { force },
  })
}
