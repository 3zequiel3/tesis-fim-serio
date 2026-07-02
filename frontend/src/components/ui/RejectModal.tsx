import { useState } from 'react'
import type { EventListItem } from '@/api/events'
import type { RejectAction } from '@/api/actions'

interface RejectModalProps {
  event: EventListItem
  open: boolean
  onClose: () => void
  onConfirm: (action: RejectAction) => void
  isPending?: boolean
}

/**
 * Modal de rechazo individual: el admin elige restore o quarantine.
 * El caso baseline_absent (D-EV-7, RN-77) lo resuelve el backend server-side
 * (reject con restore es no-op, 200) — hash_detected nunca llega null, por lo
 * que la rama de UI "archivo ausente" que dependía de ese null era código
 * muerto y se eliminó en C38.
 */
export function RejectModal({ event, open, onClose, onConfirm, isPending = false }: RejectModalProps) {
  const [action, setAction] = useState<RejectAction>('restore')

  if (!open) return null

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
      <div className="bg-gray-800 border border-gray-700 rounded-lg p-6 max-w-sm w-full mx-4">
        <h2 className="text-lg font-semibold text-white mb-2">Rechazar evento</h2>
        <p className="text-xs font-mono text-gray-400 mb-4 break-all">{event.path}</p>

        <fieldset className="mb-4">
          <legend className="text-sm text-gray-300 mb-2">Acción sobre el archivo:</legend>
          <label className="flex items-center gap-2 text-sm text-gray-300 mb-1 cursor-pointer">
            <input
              type="radio"
              name="rejectAction"
              value="restore"
              checked={action === 'restore'}
              onChange={() => setAction('restore')}
            />
            Restaurar archivo (volver al baseline)
          </label>
          <label className="flex items-center gap-2 text-sm text-gray-300 cursor-pointer">
            <input
              type="radio"
              name="rejectAction"
              value="quarantine"
              checked={action === 'quarantine'}
              onChange={() => setAction('quarantine')}
            />
            Poner en cuarentena
          </label>
        </fieldset>

        <div className="flex gap-2 justify-end">
          <button
            onClick={onClose}
            disabled={isPending}
            className="px-4 py-2 bg-gray-700 hover:bg-gray-600 text-gray-300 rounded text-sm"
          >
            Cancelar
          </button>
          <button
            onClick={() => onConfirm(action)}
            disabled={isPending}
            className="px-4 py-2 bg-danger hover:bg-danger-hover text-white rounded text-sm font-medium disabled:opacity-50"
          >
            {isPending ? 'Procesando...' : 'Confirmar rechazo'}
          </button>
        </div>
      </div>
    </div>
  )
}
