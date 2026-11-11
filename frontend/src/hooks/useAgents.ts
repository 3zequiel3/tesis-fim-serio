import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { readApiError } from '@/api/errors'
import { getAgents, getAgent, updateAgentConfig, triggerRescan } from '@/api/agents'
import type { AgentConfig } from '@/api/agents'

const AGENTS_KEY = ['agents'] as const

export function useAgents() {
  return useQuery({
    queryKey: AGENTS_KEY,
    queryFn: getAgents,
  })
}

export function useAgent(id: string) {
  return useQuery({
    queryKey: ['agents', id],
    queryFn: () => getAgent(id),
    enabled: !!id,
  })
}

export function useUpdateAgentConfig() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, config }: { id: string; config: AgentConfig }) =>
      updateAgentConfig(id, config),
    onSuccess: (_data, { id }) => {
      void qc.invalidateQueries({ queryKey: AGENTS_KEY })
      void qc.invalidateQueries({ queryKey: ['agents', id] })
    },
  })
}

export interface RescanResult {
  success: boolean
  conflictCount?: number
}

/**
 * Mutación de rescan con manejo del 409.
 * onSuccess recibe { success: true } si 200
 * onSuccess recibe { success: false, conflictCount: N } si 409
 * En ambos casos onSuccess se llama — el 409 NO es un error de mutación.
 */
export function useRescanAgent() {
  const qc = useQueryClient()
  return useMutation<RescanResult, Error, { id: string; force: boolean; paths?: string[] }>({
    mutationFn: async ({ id, force, paths }) => {
      try {
        await triggerRescan(id, force, paths)
        return { success: true }
      } catch (err) {
        // D90/RN-184: the count lives in `detail.count`, next to `detail.code`.
        const { status, code, data } = readApiError(err)
        if (status === 409 && code === 'pending_events_exist') {
          return { success: false, conflictCount: typeof data.count === 'number' ? data.count : 0 }
        }
        throw err
      }
    },
    onSuccess: (_result, { id }) => {
      void qc.invalidateQueries({ queryKey: AGENTS_KEY })
      void qc.invalidateQueries({ queryKey: ['agents', id] })
    },
  })
}
