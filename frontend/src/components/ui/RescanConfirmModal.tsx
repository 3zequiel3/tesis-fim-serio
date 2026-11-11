import { Modal } from '@/components/ui/Modal'
import { Button } from '@/components/ui/Button'

interface RescanConfirmModalProps {
  pendingCount: number
  onConfirm: () => void
  onCancel: () => void
  isLoading?: boolean
  // US-22: paths seleccionados para este rescan — el diálogo de confirmación
  // debe listarlos explícitamente, no solo la cantidad de eventos pending.
  paths?: string[]
}

export function RescanConfirmModal({
  pendingCount,
  onConfirm,
  onCancel,
  isLoading,
  paths,
}: RescanConfirmModalProps) {
  const scopedPaths = paths ?? []
  return (
    <Modal title="Confirmar rescan forzado" onClose={onCancel} busy={isLoading}>
      <p className="mb-2 text-text">
        Hay <span className="font-semibold text-warning-fg">{pendingCount}</span> evento
        {pendingCount !== 1 ? 's' : ''} pendiente{pendingCount !== 1 ? 's' : ''} que{' '}
        {pendingCount !== 1 ? 'serán marcados como' : 'será marcado como'}{' '}
        <span className="rounded-control bg-surface px-1 py-0.5 font-mono text-xs">superseded</span>{' '}
        si forzás el rescan{scopedPaths.length > 0 ? ' para los siguientes paths' : ''}.
      </p>
      {scopedPaths.length > 0 && (
        <ul className="mb-2 list-inside list-disc space-y-0.5 font-mono text-xs text-text-muted">
          {scopedPaths.map((p) => (
            <li key={p} className="[overflow-wrap:anywhere]">
              {p}
            </li>
          ))}
        </ul>
      )}
      <p className="text-text-muted">¿Querés continuar de todas formas?</p>

      <div className="mt-6 flex items-center justify-end gap-3">
        <Button onClick={onCancel} disabled={isLoading}>
          Cancelar
        </Button>
        <Button variant="primary" onClick={onConfirm} loading={isLoading}>
          {isLoading ? 'Forzando...' : 'Forzar rescan'}
        </Button>
      </div>
    </Modal>
  )
}
