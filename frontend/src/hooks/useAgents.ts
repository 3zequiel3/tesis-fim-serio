import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import axios from 'axios'
import { getAgents, getAgent, updateAgentConfig, triggerRescan } from '@/api/agents'
import type { AgentConfig, RescanConflictError } from '@/api/agents'

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
      qc.invalidateQueries({ queryKey: AGENTS_KEY })
      qc.invalidateQueries({ queryKey: ['agents', id] })
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
  return useMutation<RescanResult, Error, { id: string; force: boolean }>({
    mutationFn: async ({ id, force }) => {
      try {
        await triggerRescan(id, force)
        return { success: true }
      } catch (err) {
        if (axios.isAxiosError(err) && err.response?.status === 409) {
          const body = err.response.data as RescanConflictError
          return { success: false, conflictCount: body.count }
        }
        throw err
      }
    },
    onSuccess: (_result, { id }) => {
      qc.invalidateQueries({ queryKey: AGENTS_KEY })
      qc.invalidateQueries({ queryKey: ['agents', id] })
    },
  })
}
