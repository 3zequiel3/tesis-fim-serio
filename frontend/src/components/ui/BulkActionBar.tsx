import { useState } from 'react'
import { ModalDialog } from '@/components/ui/ModalDialog'
import type { EventListItem, EventFilters } from '@/api/events'
import type { RejectAction } from '@/api/actions'
import { useEventActions } from '@/hooks/useEventActions'

interface BulkActionBarProps {
  selected: Set<number>
  items: EventListItem[]
  filters: EventFilters
  onClearSelection: () => void
}

type BulkModal = 'approve' | 'reject' | null

export function BulkActionBar({ selected, items, onClearSelection }: BulkActionBarProps) {
  const [modal, setModal] = useState<BulkModal>(null)
  const [rejectAction, setRejectAction] = useState<RejectAction>('restore')
  const { bulkApproveMutation, bulkRejectMutation } = useEventActions()

  if (selected.size === 0) return null

  const selectedItems = items.filter((item) => selected.has(item.id))
  const previewPaths = selectedItems.slice(0, 10).map((item) => item.path)
  const extraCount = selectedItems.length - previewPaths.length

  function handleBulkApprove() {
    const bulkItems = selectedItems.map((item) => ({
      event_id: item.id,
      version: item.version,
      confirm_absent: false,
    }))
    bulkApproveMutation.mutate(bulkItems, {
      onSuccess: () => {
        onClearSelection()
        setModal(null)
      },
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
      onSuccess: () => {
        onClearSelection()
        setModal(null)
      },
    })
  }

  const isPending = bulkApproveMutation.isPending || bulkRejectMutation.isPending

  return (
    <>
      {/* Barra de acciones bulk */}
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
            onClick={onClearSelection}
            className="px-3 py-1.5 bg-gray-700 hover:bg-gray-600 text-gray-300 rounded text-xs"
          >
            Limpiar selección
          </button>
        </div>
      </div>

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
