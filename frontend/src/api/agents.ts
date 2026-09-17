import { apiClient } from '@/api/client'

// ─── Tipos ────────────────────────────────────────────────────────────────────

export type AgentStatus = 'online' | 'offline' | 'draining' | 'dead' | 'revoked'

export interface Agent {
  agent_id: string
  status: AgentStatus
  watch_paths: string[]
  queue_pressure: number | null   // 0..1 float
  // US-21: cantidad de eventos en la cola local del agente, reportada en el
  // heartbeat. null/undefined cuando el agente nunca reportó — distinto de 0
  // (mismo criterio que discarded_events).
  queue_size?: number | null
  last_heartbeat: string | null   // ISO8601
  ruleset_version_applied: number | null
  // D36/RN-130 (C41): mapa {watch_path: clasificación} del preflight de
  // escritura del agente (writable | read_only_mount | permission_denied |
  // missing), reportado en cada heartbeat. null cuando el agente nunca
  // reportó (agente viejo, o sin heartbeat aún) — distinto de {} (que se
  // leería como "todos los paths escribibles").
  watch_path_status?: Record<string, string> | null
  // D37/RN-131 (C42): contador acumulativo de eventos que el agente
  // descartó localmente desde su arranque (techo de reintentos agotado o
  // event_nack terminal). null/undefined cuando el agente nunca reportó
  // heartbeat con esta clave — distinto de 0 (ver frontend/src/utils/discardedEvents.ts).
  discarded_events?: number | null
  // D69/RN-163: contador acumulativo de eventos descartados por caer fuera
  // de los watch_paths (marca de fanotify de filesystem completo en modo
  // FID). null/undefined cuando el agente nunca reportó — distinto de 0
  // (ver frontend/src/utils/outOfScopeDrops.ts). A diferencia de
  // discarded_events, un positivo acá es **esperado**: es evidencia de que
  // el filtro de scope está funcionando, no una detección perdida.
  out_of_scope_drops?: number | null
  // D72/RN-166: booleano calculado por el agente (umbral de 80% sobre
  // queue_pressure), reportado en cada heartbeat. null/ausente cuando el
  // agente nunca reportó la clave — el umbral lo decide el agente, no el
  // cliente.
  queue_pressure_high?: boolean | null
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
 *
 * US-22: `paths` acota el rescan a paths específicos del agente. Ausente o
 * vacío conserva el comportamiento previo (todos los watch_paths).
 */
export async function triggerRescan(id: string, force: boolean, paths?: string[]): Promise<void> {
  await apiClient.post(`/agents/${id}/rescan`, { force, paths })
}
