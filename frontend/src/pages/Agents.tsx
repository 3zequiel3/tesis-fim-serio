import { useState } from 'react'
import { toast } from 'sonner'
import axios from 'axios'
import { useAgents, useUpdateAgentConfig, useRescanAgent } from '@/hooks/useAgents'
import { AgentCard } from '@/components/ui/AgentCard'
import { RescanConfirmModal } from '@/components/ui/RescanConfirmModal'
import { QueryErrorState } from '@/components/ui/QueryErrorState'

export function Agents() {
  const { data: agents, isLoading, isError, refetch } = useAgents()
  const updateConfig = useUpdateAgentConfig()
  const rescan = useRescanAgent()

  // Estado del modal de confirmación de rescan
  const [rescanModal, setRescanModal] = useState<{
    agentId: string
    pendingCount: number
  } | null>(null)

  // IDs que están actualmente en rescan
  const [rescanningId, setRescanningId] = useState<string | null>(null)
  const [savingConfigId, setSavingConfigId] = useState<string | null>(null)

  async function handleRescan(agentId: string) {
    setRescanningId(agentId)
    rescan.mutate(
      { id: agentId, force: false },
      {
        onSuccess: (result) => {
          if (result.success) {
            toast.success('Rescan iniciado')
            setRescanningId(null)
          } else {
            // 409 — mostrar modal
            setRescanModal({ agentId, pendingCount: result.conflictCount ?? 0 })
            setRescanningId(null)
          }
        },
        onError: (err) => {
          const msg = axios.isAxiosError(err)
            ? err.response?.data?.detail ?? err.message
            : String(err)
          toast.error(`Error al iniciar rescan: ${msg}`)
          setRescanningId(null)
        },
      }
    )
  }

  function handleForceRescan() {
    if (!rescanModal) return
    const { agentId } = rescanModal
    setRescanningId(agentId)
    rescan.mutate(
      { id: agentId, force: true },
      {
        onSuccess: () => {
          toast.success('Rescan forzado iniciado')
          setRescanModal(null)
          setRescanningId(null)
        },
        onError: (err) => {
          const msg = axios.isAxiosError(err)
            ? err.response?.data?.detail ?? err.message
            : String(err)
          toast.error(`Error al forzar rescan: ${msg}`)
          setRescanModal(null)
          setRescanningId(null)
        },
      }
    )
  }

  function handleConfigSave(agentId: string, paths: string[]) {
    setSavingConfigId(agentId)
    updateConfig.mutate(
      { id: agentId, config: { watch_paths: paths } },
      {
        onSuccess: () => {
          toast.success('Configuración guardada')
          setSavingConfigId(null)
        },
        onError: (err) => {
          const msg = axios.isAxiosError(err)
            ? err.response?.data?.detail ?? err.message
            : String(err)
          toast.error(`Error al guardar configuración: ${msg}`)
          setSavingConfigId(null)
        },
      }
    )
  }

  return (
    <div className="space-y-4">
      {/* Encabezado */}
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold text-white">Agentes FIM</h1>
        {agents && (
          <span className="text-xs text-gray-500">
            {agents.length} agente{agents.length !== 1 ? 's' : ''} registrado{agents.length !== 1 ? 's' : ''}
          </span>
        )}
      </div>

      {/* Modal de confirmación rescan */}
      {rescanModal && (
        <RescanConfirmModal
          pendingCount={rescanModal.pendingCount}
          onConfirm={handleForceRescan}
          onCancel={() => setRescanModal(null)}
          isLoading={rescan.isPending && rescanningId === rescanModal.agentId}
        />
      )}

      {/* Lista de agentes */}
      {isLoading ? (
        <div className="py-12 text-center text-gray-500">Cargando agentes...</div>
      ) : isError ? (
        <QueryErrorState resource="los agentes" onRetry={() => refetch()} />
      ) : !agents || agents.length === 0 ? (
        <div className="py-12 text-center text-gray-500">
          <p className="text-sm">No hay agentes registrados.</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {agents.map((agent) => (
            <AgentCard
              key={agent.agent_id}
              agent={agent}
              onConfigSave={handleConfigSave}
              onRescan={handleRescan}
              isSavingConfig={savingConfigId === agent.agent_id}
              isRescanning={rescanningId === agent.agent_id}
            />
          ))}
        </div>
      )}
    </div>
  )
}
