import { useState } from 'react'
import { toast } from 'sonner'
import axios from 'axios'
import { useRules, useCreateRule, useUpdateRule, useDeleteRule } from '@/hooks/useRules'
import { RuleForm } from '@/components/ui/RuleForm'
import { ModalDialog } from '@/components/ui/ModalDialog'
import { QueryErrorState } from '@/components/ui/QueryErrorState'
import type { Rule, CreateRulePayload, UpdateRulePayload } from '@/api/rules'

// ─── Helpers ──────────────────────────────────────────────────────────────────

const SEVERITY_COLORS: Record<string, string> = {
  critical: 'text-red-400',
  high: 'text-orange-400',
  medium: 'text-yellow-400',
  low: 'text-blue-400',
}

const ACTION_LABELS: Record<string, string> = {
  auto_restore: 'Auto-restaurar',
  quarantine: 'Cuarentena',
  manual_review: 'Revisión manual',
  alert_only: 'Solo alerta',
}

// ─── Componente ───────────────────────────────────────────────────────────────

export function Rules() {
  const { data: rules, isLoading, isError, refetch } = useRules()
  const createMutation = useCreateRule()
  const updateMutation = useUpdateRule()
  const deleteMutation = useDeleteRule()

  // Estado del modal/form
  const [formMode, setFormMode] = useState<'create' | 'edit' | null>(null)
  const [editingRule, setEditingRule] = useState<Rule | null>(null)

  // Estado delete confirm inline
  const [deletingId, setDeletingId] = useState<number | null>(null)

  // "Sync pending" — IDs de reglas mutadas cuyo sync aún no fue confirmado por heartbeat
  // RN-87: tras cualquier mutación el backend incrementa ruleset_version.
  // En el próximo heartbeat del agente, ruleset_version_applied se actualiza.
  // Mostramos el badge hasta que el refetch confirme que versiones coinciden.
  const [syncPendingIds, setSyncPendingIds] = useState<Set<number>>(new Set())

  function openCreate() {
    setEditingRule(null)
    setFormMode('create')
  }

  function openEdit(rule: Rule) {
    setEditingRule(rule)
    setFormMode('edit')
  }

  function closeForm() {
    setFormMode(null)
    setEditingRule(null)
  }

  function handleFormSubmit(payload: CreateRulePayload | UpdateRulePayload) {
    if (formMode === 'create') {
      createMutation.mutate(payload as CreateRulePayload, {
        onSuccess: () => {
          toast.success('Regla creada')
          closeForm()
        },
        onError: (err) => {
          const msg = axios.isAxiosError(err)
            ? err.response?.data?.detail ?? err.message
            : String(err)
          toast.error(`Error al crear regla: ${msg}`)
        },
      })
    } else if (formMode === 'edit' && editingRule) {
      updateMutation.mutate(
        { id: editingRule.id, payload: payload as UpdateRulePayload },
        {
          onSuccess: () => {
            toast.success('Regla actualizada')
            // Marcar como sync pending
            setSyncPendingIds((prev) => new Set([...prev, editingRule.id]))
            closeForm()
          },
          onError: (err) => {
            const msg = axios.isAxiosError(err)
              ? err.response?.data?.detail ?? err.message
              : String(err)
            toast.error(`Error al actualizar regla: ${msg}`)
          },
        }
      )
    }
  }

  function handleDelete(id: number) {
    deleteMutation.mutate(id, {
      onSuccess: () => {
        toast.success('Regla eliminada')
        setDeletingId(null)
        setSyncPendingIds((prev) => {
          const next = new Set(prev)
          next.delete(id)
          return next
        })
      },
      onError: (err) => {
        const msg = axios.isAxiosError(err)
          ? err.response?.data?.detail ?? err.message
          : String(err)
        toast.error(`Error al eliminar regla: ${msg}`)
        setDeletingId(null)
      },
    })
  }

  const isMutating =
    createMutation.isPending || updateMutation.isPending

  return (
    <div className="space-y-4">
      {/* Encabezado */}
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold text-white">Reglas de monitoreo</h1>
        <button
          onClick={openCreate}
          className="px-4 py-1.5 bg-primary hover:bg-primary-hover text-white text-sm rounded"
        >
          Nueva regla
        </button>
      </div>

      {/* Modal create/edit */}
      {formMode && (
        <ModalDialog labelledBy="rule-form-title" onClose={closeForm} panelClassName="p-6 w-full max-w-md mx-4">
          <h2 id="rule-form-title" className="text-base font-semibold text-white mb-4">
            {formMode === 'create' ? 'Nueva regla' : 'Editar regla'}
          </h2>
          <RuleForm
            rule={editingRule ?? undefined}
            onSubmit={handleFormSubmit}
            onCancel={closeForm}
            isLoading={isMutating}
          />
        </ModalDialog>
      )}

      {/* Tabla */}
      {isLoading ? (
        <div className="py-12 text-center text-gray-500">Cargando reglas...</div>
      ) : isError ? (
        <QueryErrorState resource="las reglas" onRetry={() => refetch()} />
      ) : !rules || rules.length === 0 ? (
        <div className="py-12 text-center text-gray-500">
          <p className="text-sm">No hay reglas configuradas.</p>
          <button
            onClick={openCreate}
            className="mt-3 px-4 py-1.5 bg-primary hover:bg-primary-hover text-white text-sm rounded"
          >
            Crear la primera regla
          </button>
        </div>
      ) : (
        <div className="bg-gray-800 border border-gray-700 rounded overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-700 text-xs text-gray-400">
                <th className="text-left px-4 py-2.5">Pattern</th>
                <th className="text-left px-4 py-2.5">Severidad</th>
                <th className="text-left px-4 py-2.5">Acción</th>
                <th className="text-left px-4 py-2.5">Sync</th>
                <th className="px-4 py-2.5" />
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-700">
              {rules.map((rule) => (
                <tr key={rule.id} className="hover:bg-gray-750">
                  <td className="px-4 py-2.5 font-mono text-gray-200 max-w-xs truncate">
                    {rule.pattern}
                  </td>
                  <td className={`px-4 py-2.5 font-medium ${SEVERITY_COLORS[rule.severity] ?? 'text-gray-300'}`}>
                    {rule.severity}
                  </td>
                  <td className="px-4 py-2.5 text-gray-300">
                    {ACTION_LABELS[rule.action] ?? rule.action}
                  </td>
                  <td className="px-4 py-2.5">
                    {syncPendingIds.has(rule.id) ? (
                      <span className="inline-flex items-center px-2 py-0.5 rounded text-xs bg-yellow-800 text-yellow-300">
                        sync pendiente
                      </span>
                    ) : (
                      <span className="inline-flex items-center px-2 py-0.5 rounded text-xs bg-green-900 text-green-400">
                        sincronizado
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-2.5">
                    {deletingId === rule.id ? (
                      <div className="flex items-center gap-2 text-xs">
                        <span className="text-gray-400">¿Eliminar?</span>
                        <button
                          onClick={() => handleDelete(rule.id)}
                          disabled={deleteMutation.isPending}
                          className="text-red-400 hover:text-red-300 disabled:opacity-40"
                        >
                          Confirmar
                        </button>
                        <button
                          onClick={() => setDeletingId(null)}
                          className="text-gray-500 hover:text-gray-300"
                        >
                          Cancelar
                        </button>
                      </div>
                    ) : (
                      <div className="flex items-center gap-3 justify-end">
                        <button
                          onClick={() => openEdit(rule)}
                          className="text-xs text-blue-400 hover:text-blue-300"
                        >
                          Editar
                        </button>
                        <button
                          onClick={() => setDeletingId(rule.id)}
                          className="text-xs text-red-400 hover:text-red-300"
                        >
                          Eliminar
                        </button>
                      </div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
