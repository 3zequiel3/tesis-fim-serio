import { useState } from 'react'
import { toast } from 'sonner'
import { useRules, useRulesetVersion, useCreateRule, useUpdateRule, useDeleteRule } from '@/hooks/useRules'
import { Can } from '@/components/ui/Can'
import { readApiError, apiErrorMessage } from '@/api/errors'
import { RuleForm } from '@/components/ui/RuleForm'
import { Modal } from '@/components/ui/Modal'
import { Button } from '@/components/ui/Button'
import { DataState } from '@/components/ui/DataState'
import { ResponsiveTable, type Column } from '@/components/ui/ResponsiveTable'
import { getSeverityMeta } from '@/utils/severity'
import type { Rule, CreateRulePayload, UpdateRulePayload } from '@/api/rules'

// ─── Helpers ──────────────────────────────────────────────────────────────────

const ACTION_LABELS: Record<string, string> = {
  auto_restore: 'Auto-restaurar',
  quarantine: 'Cuarentena',
  manual_review: 'Revisión manual',
  alert_only: 'Solo alerta',
}

// ─── Componente ───────────────────────────────────────────────────────────────

export function Rules() {
  const { data: rules, isLoading, error, refetch } = useRules()
  const { data: rulesetVersion } = useRulesetVersion()
  const createMutation = useCreateRule()
  const updateMutation = useUpdateRule()
  const deleteMutation = useDeleteRule()

  // Estado del modal/form
  const [formMode, setFormMode] = useState<'create' | 'edit' | null>(null)
  const [editingRule, setEditingRule] = useState<Rule | null>(null)
  // D91/RN-185: a `pattern_*` rejection of the backend, shown next to the field.
  const [patternServerError, setPatternServerError] = useState<string | null>(null)

  // Estado delete confirm inline
  const [deletingId, setDeletingId] = useState<number | null>(null)

  // "Sync pending" — IDs de reglas mutadas cuyo sync aún no fue confirmado por heartbeat
  // RN-87: tras cualquier mutación el backend incrementa ruleset_version.
  const [syncPendingIds, setSyncPendingIds] = useState<Set<number>>(new Set())

  function openCreate() {
    setEditingRule(null)
    setPatternServerError(null)
    setFormMode('create')
  }

  function openEdit(rule: Rule) {
    setEditingRule(rule)
    setPatternServerError(null)
    setFormMode('edit')
  }

  function closeForm() {
    setFormMode(null)
    setEditingRule(null)
    setPatternServerError(null)
  }

  // A `pattern_*` code belongs to the field; anything else is a toast.
  function handleSaveError(err: unknown, verb: string) {
    const { code, message } = readApiError(err)
    if (code?.startsWith('pattern_') && message) {
      setPatternServerError(message)
      return
    }
    toast.error(`Error al ${verb} regla: ${apiErrorMessage(err, 'intentá de nuevo')}`)
  }

  function handleFormSubmit(payload: CreateRulePayload | UpdateRulePayload) {
    setPatternServerError(null)
    if (formMode === 'create') {
      createMutation.mutate(payload as CreateRulePayload, {
        onSuccess: () => {
          toast.success('Regla creada')
          closeForm()
        },
        onError: (err) => handleSaveError(err, 'crear'),
      })
    } else if (formMode === 'edit' && editingRule) {
      updateMutation.mutate(
        { id: editingRule.id, payload },
        {
          onSuccess: () => {
            toast.success('Regla actualizada')
            setSyncPendingIds((prev) => new Set([...prev, editingRule.id]))
            closeForm()
          },
          onError: (err) => handleSaveError(err, 'actualizar'),
        },
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
        toast.error(`Error al eliminar regla: ${apiErrorMessage(err, 'intentá de nuevo')}`)
        setDeletingId(null)
      },
    })
  }

  const isMutating = createMutation.isPending || updateMutation.isPending

  const columns: Column<Rule>[] = [
    {
      key: 'pattern',
      header: 'Patrón',
      primary: true,
      cell: (rule) => <span className="font-mono text-text [overflow-wrap:anywhere]">{rule.pattern}</span>,
    },
    {
      key: 'severity',
      header: 'Severidad',
      cell: (rule) => (
        <span className={`font-semibold ${getSeverityMeta(rule.severity).textClass}`}>{rule.severity}</span>
      ),
    },
    {
      key: 'action',
      header: 'Acción',
      cell: (rule) => <span className="text-text">{ACTION_LABELS[rule.action] ?? rule.action}</span>,
    },
    {
      key: 'sync',
      header: 'Sincronización',
      cell: (rule) =>
        syncPendingIds.has(rule.id) ? (
          <span className="inline-flex items-center rounded-control bg-warning-bg px-2 py-0.5 text-xs font-semibold text-warning-fg">
            sincronización pendiente
          </span>
        ) : (
          <span className="inline-flex items-center rounded-control bg-success-bg px-2 py-0.5 text-xs font-semibold text-success-fg">
            sincronizado
          </span>
        ),
    },
    {
      key: 'actions',
      header: 'Acciones',
      hideHeader: true,
      cell: (rule) => (
        <Can>
          {deletingId === rule.id ? (
            <div className="flex items-center gap-2 text-xs">
              <span className="text-text-muted">¿Eliminar?</span>
              <Button variant="danger" size="sm" onClick={() => handleDelete(rule.id)} disabled={deleteMutation.isPending}>
                Confirmar
              </Button>
              <Button size="sm" onClick={() => setDeletingId(null)}>
                Cancelar
              </Button>
            </div>
          ) : (
            <div className="flex items-center gap-2 sm:justify-end">
              <Button size="sm" onClick={() => openEdit(rule)}>
                Editar
              </Button>
              <Button variant="ghost" size="sm" onClick={() => setDeletingId(rule.id)}>
                Eliminar
              </Button>
            </div>
          )}
        </Can>
      ),
    },
  ]

  return (
    <div className="space-y-4">
      {/* Encabezado */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-text">Reglas de monitoreo</h1>
          {rulesetVersion !== undefined && (
            <p className="mt-0.5 text-xs text-text-muted">
              ruleset_version actual: <span className="font-mono text-text">{rulesetVersion}</span>
            </p>
          )}
        </div>
        <Can>
          <Button variant="primary" onClick={openCreate}>
            Nueva regla
          </Button>
        </Can>
      </div>

      {/* Leyenda: acción por defecto sin regla que matchee (RN-06) */}
      <p className="text-text-muted">
        Si ningún patrón matchea un archivo, se aplica la acción por defecto:{' '}
        <span className="font-semibold text-text">Solo alerta (alert_only)</span>.
      </p>

      {/* Modal create/edit */}
      {formMode && (
        <Modal
          title={formMode === 'create' ? 'Nueva regla' : 'Editar regla'}
          onClose={closeForm}
          busy={isMutating}
        >
          <RuleForm
            rule={editingRule ?? undefined}
            onSubmit={handleFormSubmit}
            onCancel={closeForm}
            isLoading={isMutating}
            patternServerError={patternServerError}
          />
        </Modal>
      )}

      <DataState
        isLoading={isLoading}
        error={error}
        onRetry={() => void refetch()}
        resource="las reglas"
        loadingLabel="Cargando reglas..."
        isEmpty={!rules || rules.length === 0}
        emptyTitle="No hay reglas configuradas."
        emptyHint="Sin reglas, todo cambio genera solo una alerta."
        emptyAction={
          <Can>
            <Button variant="primary" onClick={openCreate}>
              Crear la primera regla
            </Button>
          </Can>
        }
      >
        <ResponsiveTable caption="Reglas" columns={columns} rows={rules ?? []} getRowKey={(r) => r.id} />
      </DataState>
    </div>
  )
}
