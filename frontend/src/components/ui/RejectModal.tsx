import { useState } from 'react'
import { ModalDialog } from '@/components/ui/ModalDialog'
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
 * Modal de rechazo individual: el admin elige restore o quarantine, salvo
 * cuando el baseline del path está `absent` (US-12, C10, D-8) — en ese caso
 * no hay archivo al que volver y el modal oculta el fieldset de acción
 * correctiva, mostrando en su lugar el texto literal del criterio. El
 * `onConfirm` sigue enviando `action: 'restore'` (no-op server-side sobre
 * baseline absent, RN-74/actions/service.py:309-339) para no introducir una
 * tercera forma de payload.
 */
export function RejectModal({ event, open, onClose, onConfirm, isPending = false }: RejectModalProps) {
  const [action, setAction] = useState<RejectAction>('restore')
  const baselineAbsent = event.baseline_status === 'absent'

  if (!open) return null

  return (
    <ModalDialog labelledBy="reject-modal-title" onClose={onClose} panelClassName="p-6 max-w-sm w-full mx-4">
      <h2 id="reject-modal-title" className="text-lg font-semibold text-white mb-2">Rechazar evento</h2>
      <p className="text-xs font-mono text-gray-400 mb-4 break-all">{event.path}</p>

      {baselineAbsent ? (
        <p className="mb-4 text-sm text-yellow-300 bg-yellow-950 border border-yellow-800 rounded px-3 py-2">
          No hay archivo a restaurar (baseline ausente). Confirmar rechazará el evento sin acción
          en filesystem.
        </p>
      ) : (
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
          onClick={() => onConfirm(action)}
          disabled={isPending}
          className="px-4 py-2 bg-danger hover:bg-danger-hover text-white rounded text-sm font-medium disabled:opacity-50"
        >
          {isPending ? 'Procesando...' : 'Confirmar rechazo'}
        </button>
      </div>
    </ModalDialog>
  )
}
