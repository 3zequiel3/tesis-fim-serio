import { useState } from 'react'
import type { Dispatch, SetStateAction } from 'react'
import { Modal } from '@/components/ui/Modal'
import { Button } from '@/components/ui/Button'
import type { EventListItem, EventFilters } from '@/api/events'
import type { BulkResult, RejectAction } from '@/api/actions'
import { useEventActions } from '@/hooks/useEventActions'
import { PathLabel } from '@/components/ui/PathLabel'

interface BulkActionBarProps {
  selected: Set<number>
  items: EventListItem[]
  filters: EventFilters
  onSelectionChange: Dispatch<SetStateAction<Set<number>>>
}

type BulkModal = 'approve' | 'reject' | null

interface BulkResultRow {
  eventId: number
  path: string | null
  succeeded: boolean
  reason?: string
}

interface BulkResultSummary {
  verb: 'aprobados' | 'rechazados'
  rows: BulkResultRow[]
}

export function BulkActionBar({ selected, items, onSelectionChange }: BulkActionBarProps) {
  const [modal, setModal] = useState<BulkModal>(null)
  const [rejectAction, setRejectAction] = useState<RejectAction>('restore')
  const [result, setResult] = useState<BulkResultSummary | null>(null)
  const [resultExpanded, setResultExpanded] = useState(false)
  const { bulkApproveMutation, bulkRejectMutation } = useEventActions()

  const selectedItems = items.filter((item) => selected.has(item.id))
  const previewPaths = selectedItems.slice(0, 10).map((item) => ({
    eventId: item.id,
    label: item.path ?? `Evento #${item.id} sin path`,
  }))
  const extraCount = selectedItems.length - previewPaths.length

  function recordResult(response: BulkResult, verb: BulkResultSummary['verb']) {
    const attempted = new Set(selectedItems.map((item) => item.id))
    const succeeded = new Set(response.succeeded.filter((id) => attempted.has(id)))
    const failed = new Map(response.failed.map((item) => [item.event_id, item.reason]))
    setResult({
      verb,
      rows: selectedItems.map((item) => ({
        eventId: item.id,
        path: item.path,
        succeeded: succeeded.has(item.id),
        reason: failed.get(item.id) ?? (
          succeeded.has(item.id) ? undefined : 'sin resultado devuelto por el servidor'
        ),
      })),
    })
    setResultExpanded(false)

    // Conciliar contra el estado ACTUAL evita pisar clicks ocurridos mientras
    // esperaba la red. Sólo se quitan éxitos de este lote; todo lo demás queda
    // exactamente como lo dejó el operador.
    onSelectionChange((current) => (
      new Set([...current].filter((id) => !succeeded.has(id)))
    ))
    setModal(null)
  }

  function handleBulkApprove() {
    bulkApproveMutation.mutate(selectedItems.map((item) => item.id), {
      onSuccess: (response) => recordResult(response, 'aprobados'),
    })
  }

  function handleBulkReject() {
    bulkRejectMutation.mutate({ eventIds: selectedItems.map((item) => item.id), action: rejectAction }, {
      onSuccess: (response) => recordResult(response, 'rechazados'),
    })
  }

  const isPending = bulkApproveMutation.isPending || bulkRejectMutation.isPending

  if (selected.size === 0 && result == null) return null

  const radioLabel = 'flex items-center gap-2 text-text'

  return (
    <>
      {/* Barra de acciones bulk */}
      {selected.size > 0 && (
        <div className="flex flex-wrap items-center gap-3 rounded-panel border border-accent bg-accent-soft px-4 py-2">
          <span className="font-semibold text-accent-soft-text">
            {selected.size} evento{selected.size !== 1 ? 's' : ''} seleccionado{selected.size !== 1 ? 's' : ''}
          </span>
          <div className="ml-auto flex flex-wrap gap-2">
            <Button variant="primary" size="sm" onClick={() => setModal('approve')} disabled={isPending}>
              Aprobar seleccionados
            </Button>
            <Button variant="danger" size="sm" onClick={() => setModal('reject')} disabled={isPending}>
              Rechazar seleccionados
            </Button>
            <Button size="sm" onClick={() => onSelectionChange(new Set())}>
              Limpiar selección
            </Button>
          </div>
        </div>
      )}

      {result && (
        <section className="rounded-panel border border-line bg-surface-raised px-4 py-3" aria-live="polite">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="text-text">
              Resultado: {result.rows.filter((row) => row.succeeded).length} {result.verb},{' '}
              {result.rows.filter((row) => !row.succeeded).length} fallidos
            </p>
            <Button
              size="sm"
              aria-expanded={resultExpanded}
              aria-controls="bulk-result-details"
              onClick={() => setResultExpanded((expanded) => !expanded)}
            >
              {resultExpanded ? 'Ocultar detalle del resultado' : 'Ver detalle del resultado'}
            </Button>
          </div>
          {resultExpanded && (
            <ul id="bulk-result-details" className="mt-3 space-y-2">
              {result.rows.map((row) => (
                <li key={row.eventId} className="flex flex-wrap items-start justify-between gap-x-4 gap-y-1 text-xs">
                  <PathLabel path={row.path ?? `Evento #${row.eventId} sin path`} />
                  <span className={row.succeeded ? 'text-success-fg' : 'text-danger-fg'}>
                    {row.succeeded ? 'Correcto' : `Falló: ${row.reason}`}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </section>
      )}

      {/* Modal de confirmación de bulk approve */}
      {modal === 'approve' && (
        <Modal title="Confirmar aprobación masiva" onClose={() => setModal(null)} busy={isPending}>
          <p className="mb-2 text-text">
            Se van a aprobar <span className="font-bold">{selected.size}</span> evento
            {selected.size !== 1 ? 's' : ''}:
          </p>
          <PreviewList items={previewPaths} extraCount={extraCount} />
          <div className="flex justify-end gap-2">
            <Button onClick={() => setModal(null)} disabled={isPending}>
              Cancelar
            </Button>
            <Button variant="primary" onClick={handleBulkApprove} loading={isPending}>
              {isPending ? 'Procesando...' : 'Aprobar'}
            </Button>
          </div>
        </Modal>
      )}

      {/* Modal de confirmación de bulk reject */}
      {modal === 'reject' && (
        <Modal title="Confirmar rechazo masivo" onClose={() => setModal(null)} busy={isPending}>
          <p className="mb-2 text-text">
            Se van a rechazar <span className="font-bold">{selected.size}</span> evento
            {selected.size !== 1 ? 's' : ''}:
          </p>
          <PreviewList items={previewPaths} extraCount={extraCount} />
          <fieldset className="mb-4">
            <legend className="mb-2 font-semibold text-text">Acción para todos:</legend>
            <label className={`${radioLabel} mb-1`}>
              <input
                type="radio"
                name="bulkRejectAction"
                value="restore"
                checked={rejectAction === 'restore'}
                onChange={() => setRejectAction('restore')}
                className="accent-accent"
              />
              Restaurar archivo
            </label>
            <label className={radioLabel}>
              <input
                type="radio"
                name="bulkRejectAction"
                value="quarantine"
                checked={rejectAction === 'quarantine'}
                onChange={() => setRejectAction('quarantine')}
                className="accent-accent"
              />
              Poner en cuarentena
            </label>
          </fieldset>
          <div className="flex justify-end gap-2">
            <Button onClick={() => setModal(null)} disabled={isPending}>
              Cancelar
            </Button>
            <Button variant="danger" onClick={handleBulkReject} loading={isPending}>
              {isPending ? 'Procesando...' : 'Rechazar'}
            </Button>
          </div>
        </Modal>
      )}
    </>
  )
}

function PreviewList({
  items,
  extraCount,
}: {
  items: { eventId: number; label: string }[]
  extraCount: number
}) {
  return (
    <>
      <ul className="mb-2 max-h-40 space-y-0.5 overflow-y-auto font-mono text-xs text-text-muted">
        {items.map((item) => (
          <li key={item.eventId} className="[overflow-wrap:anywhere]">
            • {item.label}
          </li>
        ))}
      </ul>
      {extraCount > 0 && <p className="mb-3 text-xs text-text-muted">... y {extraCount} más</p>}
    </>
  )
}
