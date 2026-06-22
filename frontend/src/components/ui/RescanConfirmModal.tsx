interface RescanConfirmModalProps {
  pendingCount: number
  onConfirm: () => void
  onCancel: () => void
  isLoading?: boolean
}

export function RescanConfirmModal({
  pendingCount,
  onConfirm,
  onCancel,
  isLoading,
}: RescanConfirmModalProps) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/60"
        onClick={onCancel}
      />

      {/* Dialog */}
      <div className="relative bg-gray-800 border border-gray-700 rounded-lg p-6 w-full max-w-md mx-4 shadow-xl">
        <h2 className="text-base font-semibold text-white mb-3">
          Confirmar rescan forzado
        </h2>

        <p className="text-sm text-gray-300 mb-2">
          Hay{' '}
          <span className="font-semibold text-yellow-300">{pendingCount}</span>{' '}
          evento{pendingCount !== 1 ? 's' : ''} pendiente
          {pendingCount !== 1 ? 's' : ''} que{' '}
          {pendingCount !== 1 ? 'serán marcados como' : 'será marcado como'}{' '}
          <span className="font-mono text-xs bg-gray-700 px-1 py-0.5 rounded">superseded</span>{' '}
          si forzás el rescan.
        </p>
        <p className="text-sm text-gray-400">
          ¿Querés continuar de todas formas?
        </p>

        <div className="flex items-center justify-end gap-3 mt-6">
          <button
            type="button"
            onClick={onCancel}
            disabled={isLoading}
            className="px-4 py-1.5 text-sm text-gray-300 hover:text-white disabled:opacity-40"
          >
            Cancelar
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={isLoading}
            className="px-4 py-1.5 bg-yellow-600 hover:bg-yellow-500 text-white text-sm rounded disabled:opacity-40"
          >
            {isLoading ? 'Forzando...' : 'Forzar rescan'}
          </button>
        </div>
      </div>
    </div>
  )
}
