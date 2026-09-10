import { useState } from 'react'
import type { Dispatch, SetStateAction } from 'react'
import { ModalDialog } from '@/components/ui/ModalDialog'
import type { EventListItem, EventFilters } from '@/api/events'
import type { BulkResult, RejectAction } from '@/api/actions'
import { useEventActions } from '@/hooks/useEventActions'

interface BulkActionBarProps {
  selected: Set<number>
  items: EventListItem[]
  filters: EventFilters
  onSelectionChange: Dispatch<SetStateAction<Set<number>>>
}

type BulkModal = 'approve' | 'reject' | null

interface BulkResultRow {
  eventId: number
  path: string
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
  const previewPaths = selectedItems.slice(0, 10).map((item) => item.path)
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
    const bulkItems = selectedItems.map((item) => ({
      event_id: item.id,
      version: item.version,
      confirm_absent: false,
    }))
    bulkApproveMutation.mutate(bulkItems, {
      onSuccess: (response) => recordResult(response, 'aprobados'),
    })
  }

  function handleBulkReject() {
    // La elección única del modal es la UX que pide US-25; mapearla sobre
    // cada ítem es lo que exige el wire (BulkRejectItem.action, obligatoria
    // por ítem en el backend). Las dos cosas valen a la vez.
    const bulkItems = selectedItems.map((item) => ({
      event_id: item.id,
      version: item.version,
      action: rejectAction,
    }))
    bulkRejectMutation.mutate(bulkItems, {
      onSuccess: (response) => recordResult(response, 'rechazados'),
    })
  }

  const isPending = bulkApproveMutation.isPending || bulkRejectMutation.isPending

  if (selected.size === 0 && result == null) return null

  return (
    <>
      {/* Barra de acciones bulk */}
      {selected.size > 0 && (
        <div className="flex items-center gap-3 px-4 py-2 bg-blue-950 border border-blue-800 rounded text-sm">
          <span className="text-blue-300 font-medium">
            {selected.size} evento{selected.size !== 1 ? 's' : ''} seleccionado{selected.size !== 1 ? 's' : ''}
          </span>
          <div className="flex gap-2 ml-auto">
            <button
              onClick={() => setModal('approve')}
              disabled={isPending}
              className="px-3 py-1.5 bg-green-700 hover:bg-green-600 text-white rounded text-xs font-medium disabled:opacity-50"
            >
              Aprobar seleccionados
            </button>
            <button
              onClick={() => setModal('reject')}
              disabled={isPending}
              className="px-3 py-1.5 bg-danger hover:bg-danger-hover text-white rounded text-xs font-medium disabled:opacity-50"
            >
              Rechazar seleccionados
            </button>
            <button
              onClick={() => onSelectionChange(new Set())}
              className="px-3 py-1.5 bg-gray-700 hover:bg-gray-600 text-gray-300 rounded text-xs"
            >
              Limpiar selección
            </button>
          </div>
        </div>
      )}

      {result && (
        <section className="px-4 py-3 bg-gray-800 border border-gray-700 rounded text-sm" aria-live="polite">
          <div className="flex items-center justify-between gap-3">
            <p className="text-gray-200">
              Resultado: {result.rows.filter((row) => row.succeeded).length} {result.verb},{' '}
              {result.rows.filter((row) => !row.succeeded).length} fallidos
            </p>
            <button
              type="button"
              aria-expanded={resultExpanded}
              aria-controls="bulk-result-details"
              onClick={() => setResultExpanded((expanded) => !expanded)}
              className="px-3 py-1.5 bg-gray-700 hover:bg-gray-600 text-gray-200 rounded text-xs"
            >
              {resultExpanded ? 'Ocultar detalle del resultado' : 'Ver detalle del resultado'}
            </button>
          </div>
          {resultExpanded && (
            <ul id="bulk-result-details" className="mt-3 space-y-2">
              {result.rows.map((row) => (
                <li key={row.eventId} className="flex items-start justify-between gap-4 text-xs">
                  <span className="font-mono text-gray-300 break-all">{row.path}</span>
                  <span className={row.succeeded ? 'text-green-400' : 'text-red-400'}>
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
        <ModalDialog labelledBy="bulk-approve-title" onClose={() => setModal(null)} panelClassName="p-6 max-w-md w-full mx-4">
          <h2 id="bulk-approve-title" className="text-lg font-semibold text-white mb-3">
            Confirmar aprobación masiva
          </h2>
          <p className="text-gray-300 text-sm mb-2">
            Se van a aprobar{' '}
            <span className="font-bold text-white">{selected.size}</span> evento{selected.size !== 1 ? 's' : ''}:
          </p>
          <ul className="text-xs font-mono text-gray-400 mb-2 space-y-0.5 max-h-40 overflow-y-auto">
            {previewPaths.map((p) => (
              <li key={p} className="truncate">• {p}</li>
            ))}
          </ul>
          {extraCount > 0 && (
            <p className="text-xs text-gray-500 mb-3">... y {extraCount} más</p>
          )}
          <div className="flex gap-2 justify-end">
            <button
              onClick={() => setModal(null)}
              disabled={isPending}
              className="px-4 py-2 bg-gray-700 hover:bg-gray-600 text-gray-300 rounded text-sm"
            >
              Cancelar
            </button>
            <button
              onClick={handleBulkApprove}
              disabled={isPending}
              className="px-4 py-2 bg-green-700 hover:bg-green-600 text-white rounded text-sm font-medium disabled:opacity-50"
            >
              {isPending ? 'Procesando...' : 'Aprobar'}
            </button>
          </div>
        </ModalDialog>
      )}

      {/* Modal de confirmación de bulk reject */}
      {modal === 'reject' && (
        <ModalDialog labelledBy="bulk-reject-title" onClose={() => setModal(null)} panelClassName="p-6 max-w-md w-full mx-4">
          <h2 id="bulk-reject-title" className="text-lg font-semibold text-white mb-3">
            Confirmar rechazo masivo
          </h2>
          <p className="text-gray-300 text-sm mb-2">
            Se van a rechazar{' '}
            <span className="font-bold text-white">{selected.size}</span> evento{selected.size !== 1 ? 's' : ''}:
          </p>
          <ul className="text-xs font-mono text-gray-400 mb-3 space-y-0.5 max-h-40 overflow-y-auto">
            {previewPaths.map((p) => (
              <li key={p} className="truncate">• {p}</li>
            ))}
          </ul>
          {extraCount > 0 && (
            <p className="text-xs text-gray-500 mb-3">... y {extraCount} más</p>
          )}
          <fieldset className="mb-4">
            <legend className="text-sm text-gray-300 mb-2">Acción para todos:</legend>
            <label className="flex items-center gap-2 text-sm text-gray-300 mb-1">
              <input
                type="radio"
                name="bulkRejectAction"
                value="restore"
                checked={rejectAction === 'restore'}
                onChange={() => setRejectAction('restore')}
              />
              Restaurar archivo
            </label>
            <label className="flex items-center gap-2 text-sm text-gray-300">
              <input
                type="radio"
                name="bulkRejectAction"
                value="quarantine"
                checked={rejectAction === 'quarantine'}
                onChange={() => setRejectAction('quarantine')}
              />
              Poner en cuarentena
            </label>
          </fieldset>
          <div className="flex gap-2 justify-end">
            <button
              onClick={() => setModal(null)}
              disabled={isPending}
              className="px-4 py-2 bg-gray-700 hover:bg-gray-600 text-gray-300 rounded text-sm"
            >
              Cancelar
            </button>
            <button
              onClick={handleBulkReject}
              disabled={isPending}
              className="px-4 py-2 bg-danger hover:bg-danger-hover text-white rounded text-sm font-medium disabled:opacity-50"
            >
              {isPending ? 'Procesando...' : 'Rechazar'}
            </button>
          </div>
        </ModalDialog>
      )}
    </>
  )
}
