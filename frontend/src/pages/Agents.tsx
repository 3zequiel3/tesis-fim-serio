import { useState } from 'react'
import { toast } from 'sonner'
import { apiErrorMessage, readApiError } from '@/api/errors'
import { useAgents, useUpdateAgentConfig, useRescanAgent } from '@/hooks/useAgents'
import { AgentCard } from '@/components/ui/AgentCard'
import { RescanConfirmModal } from '@/components/ui/RescanConfirmModal'
import { DataState } from '@/components/ui/DataState'
import type { ConfigSaveError } from '@/components/ui/AgentCard'

export function Agents() {
  const { data: agents, isLoading, error, refetch } = useAgents()
  const updateConfig = useUpdateAgentConfig()
  const rescan = useRescanAgent()

  // Estado del modal de confirmación de rescan
  const [rescanModal, setRescanModal] = useState<{
    agentId: string
    pendingCount: number
    paths: string[]
  } | null>(null)

  // IDs que están actualmente en rescan
  const [rescanningId, setRescanningId] = useState<string | null>(null)
  const [savingConfigId, setSavingConfigId] = useState<string | null>(null)
  // Rejection of the last watch_paths save, shown next to the entry it names (D91/RN-185).
  const [configError, setConfigError] = useState<{ agentId: string; error: ConfigSaveError } | null>(null)

  // US-22: `paths` son los watch_paths seleccionados en AgentCard para este
  // rescan (por defecto, todos). Antes de ejecutar, se intenta sin forzar —
  // el backend devuelve 409 con la cantidad de eventos `pending` bajo esos
  // paths si los hay, y recién ahí se muestra el diálogo de confirmación
  // (RescanConfirmModal) antes de proceder con force=true.
  function handleRescan(agentId: string, paths: string[]) {
    setRescanningId(agentId)
    rescan.mutate(
      { id: agentId, force: false, paths },
      {
        onSuccess: (result) => {
          if (result.success) {
            toast.success('Rescan iniciado')
            setRescanningId(null)
          } else {
            // 409 — mostrar modal de confirmación antes de forzar
            setRescanModal({ agentId, pendingCount: result.conflictCount ?? 0, paths })
            setRescanningId(null)
          }
        },
        onError: (err) => {
          toast.error(`Error al iniciar rescan: ${apiErrorMessage(err, 'no se pudo iniciar')}`)
          setRescanningId(null)
        },
      }
    )
  }

  function handleForceRescan() {
    if (!rescanModal) return
    const { agentId, paths } = rescanModal
    setRescanningId(agentId)
    rescan.mutate(
      { id: agentId, force: true, paths },
      {
        onSuccess: () => {
          toast.success('Rescan forzado iniciado')
          setRescanModal(null)
          setRescanningId(null)
        },
        onError: (err) => {
          toast.error(`Error al forzar rescan: ${apiErrorMessage(err, 'no se pudo forzar')}`)
          setRescanModal(null)
          setRescanningId(null)
        },
      }
    )
  }

  // Resolves false on failure so the editor stays open with the error (D91/RN-185).
  function handleConfigSave(agentId: string, paths: string[]): Promise<boolean> {
    setSavingConfigId(agentId)
    setConfigError(null)
    return new Promise((resolve) => {
      updateConfig.mutate(
        { id: agentId, config: { watch_paths: paths } },
        {
          onSuccess: () => {
            toast.success('Configuración guardada')
            setSavingConfigId(null)
            resolve(true)
          },
          onError: (err) => {
            const { message, data } = readApiError(err)
            const text = message || 'no se pudo guardar'
            setConfigError({
              agentId,
              error: { message: text, index: typeof data.index === 'number' ? data.index : undefined },
            })
            toast.error(`Error al guardar configuración: ${text}`)
            setSavingConfigId(null)
            resolve(false)
          },
        },
      )
    })
  }

  return (
    <div className="space-y-4">
      {/* Encabezado */}
      <div className="flex items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold text-text">Agentes FIM</h1>
        {agents && (
          <span className="text-xs text-text-muted">
            {agents.length} agente{agents.length !== 1 ? 's' : ''} registrado{agents.length !== 1 ? 's' : ''}
          </span>
        )}
      </div>

      {/* Modal de confirmación rescan */}
      {rescanModal && (
        <RescanConfirmModal
          pendingCount={rescanModal.pendingCount}
          paths={rescanModal.paths}
          onConfirm={handleForceRescan}
          onCancel={() => setRescanModal(null)}
          isLoading={rescan.isPending && rescanningId === rescanModal.agentId}
        />
      )}

      <DataState
        isLoading={isLoading}
        error={error}
        onRetry={() => void refetch()}
        resource="los agentes"
        loadingLabel="Cargando agentes..."
        isEmpty={!agents || agents.length === 0}
        emptyTitle="No hay agentes registrados."
        emptyHint="Instalá el agente en un host Linux y registralo para empezar a vigilar archivos."
      >
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2 xl:grid-cols-3">
          {agents?.map((agent) => (
            <AgentCard
              key={agent.agent_id}
              agent={agent}
              onConfigSave={handleConfigSave}
              configError={configError?.agentId === agent.agent_id ? configError.error : null}
              onRescan={handleRescan}
              isSavingConfig={savingConfigId === agent.agent_id}
              isRescanning={rescanningId === agent.agent_id}
            />
          ))}
        </div>
      </DataState>
    </div>
  )
}
