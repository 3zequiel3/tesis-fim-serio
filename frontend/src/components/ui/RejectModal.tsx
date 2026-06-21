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
 * Modal de rechazo individual.
 * Branch baseline_absent (D-EV-7, RN-77): si hash_detected === null,
 * el archivo no está en el baseline → no hay nada que restaurar ni quarantine.
 * El confirm igual llama reject con action:"restore" (backend no-op, 200).
 */
export function RejectModal({ event, open, onClose, onConfirm, isPending = false }: RejectModalProps) {
  const [action, setAction] = useState<RejectAction>('restore')
  const isAbsent = event.hash_detected === null

  if (!open) return null

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
      <div className="bg-gray-800 border border-gray-700 rounded-lg p-6 max-w-sm w-full mx-4">
        <h2 className="text-lg font-semibold text-white mb-2">Rechazar evento</h2>
        <p className="text-xs font-mono text-gray-400 mb-4 break-all">{event.path}</p>

        {isAbsent ? (
          /* Branch baseline_absent */
          <div className="mb-4 p-3 bg-yellow-950 border border-yellow-800 rounded text-sm text-yellow-300">
            El archivo no existe en el baseline — no hay nada que restaurar ni poner en cuarentena.
            Al confirmar, el evento quedará marcado como rechazado.
          </div>
        ) : (
          /* Branch normal: pedir acción restore/quarantine */
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
        )}

        <div className="flex gap-2 justify-end">
          <button
            onClick={onClose}
            disabled={isPending}
            className="px-4 py-2 bg-gray-700 hover:bg-gray-600 text-gray-300 rounded text-sm"
          >
            Cancelar
          </button>
          <button
            onClick={() => onConfirm(isAbsent ? 'restore' : action)}
            disabled={isPending}
            className="px-4 py-2 bg-red-700 hover:bg-red-600 text-white rounded text-sm font-medium disabled:opacity-50"
          >
            {isPending ? 'Procesando...' : 'Confirmar rechazo'}
          </button>
        </div>
      </div>
    </div>
  )
}
