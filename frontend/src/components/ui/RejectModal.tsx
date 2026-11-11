import { useState } from 'react'
import { Modal } from '@/components/ui/Modal'
import { Button } from '@/components/ui/Button'
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
 *
 * M8 (D93/RN-187): the state lives in `RejectModalBody`, which only exists
 * while the modal is open, so every opening starts from the initial state.
 */
export function RejectModal(props: RejectModalProps) {
  if (!props.open) return null
  return <RejectModalBody {...props} />
}

function RejectModalBody({ event, onClose, onConfirm, isPending = false }: RejectModalProps) {
  const [action, setAction] = useState<RejectAction>('restore')
  const baselineAbsent = event.baseline_status === 'absent'

  return (
    <Modal title="Rechazar evento" onClose={onClose} busy={isPending} widthClassName="max-w-md">
      {/* D50/RN-144: a detection gap has no path. */}
      <p className="mb-4 break-all font-mono text-xs text-text-muted">{event.path ?? 'ruta desconocida'}</p>

      {baselineAbsent ? (
        <p className="mb-4 rounded-control border border-warning-line bg-warning-bg px-3 py-2 text-warning-fg">
          No hay archivo a restaurar (baseline ausente). Confirmar rechazará el evento sin acción
          en filesystem.
        </p>
      ) : (
        <fieldset className="mb-4">
          <legend className="mb-2 font-semibold text-text">Acción sobre el archivo:</legend>
          <label className="mb-1 flex cursor-pointer items-center gap-2 text-text">
            <input
              type="radio"
              name="rejectAction"
              value="restore"
              checked={action === 'restore'}
              onChange={() => setAction('restore')}
              className="accent-accent"
            />
            Restaurar archivo (volver al baseline)
          </label>
          <label className="flex cursor-pointer items-center gap-2 text-text">
            <input
              type="radio"
              name="rejectAction"
              value="quarantine"
              checked={action === 'quarantine'}
              onChange={() => setAction('quarantine')}
              className="accent-accent"
            />
            Poner en cuarentena
          </label>
        </fieldset>
      )}

      <div className="flex justify-end gap-2">
        <Button onClick={onClose} disabled={isPending}>
          Cancelar
        </Button>
        <Button variant="danger" onClick={() => onConfirm(action)} loading={isPending}>
          {isPending ? 'Procesando...' : 'Confirmar rechazo'}
        </Button>
      </div>
    </Modal>
  )
}
