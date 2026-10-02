import { useState } from 'react'
import { ModalDialog } from '@/components/ui/ModalDialog'
import type { ReleaseMode } from '@/api/actions'

interface ReleaseQuarantineModalProps {
  /** Ruta del archivo cuarentenado, sólo informativa. */
  path: string | null
  open: boolean
  onClose: () => void
  onConfirm: (mode: ReleaseMode, reason: string) => void
  isPending?: boolean
}

const MAX_REASON_LENGTH = 500

const OPTIONS: { mode: ReleaseMode; label: string; consequence: string }[] = [
  {
    mode: 'restore_original',
    label: 'Restaurar el archivo original',
    consequence:
      'Devuelve el archivo cuarentenado a su ruta y lo APRUEBA: su contenido pasa a ser el nuevo baseline.',
  },
  {
    mode: 'restore_baseline',
    label: 'Restaurar la versión aprobada',
    consequence:
      'Vuelve a poner en su ruta la versión aprobada del baseline y elimina el archivo cuarentenado.',
  },
  {
    mode: 'discard',
    label: 'Descartar el archivo cuarentenado',
    consequence:
      'Elimina el archivo cuarentenado. El archivo no se restaura y el baseline no cambia.',
  },
]

/**
 * Modal de liberación de cuarentena (D83/RN-177, presentacional). Obliga a
 * elegir un modo y a escribir un motivo antes de habilitar la confirmación;
 * `restore_original` advierte que aprueba el contenido cuarentenado. El motivo
 * sólo se audita en el backend: nunca viaja al agente.
 */
export function ReleaseQuarantineModal({
  path,
  open,
  onClose,
  onConfirm,
  isPending = false,
}: ReleaseQuarantineModalProps) {
  const [mode, setMode] = useState<ReleaseMode | null>(null)
  const [reason, setReason] = useState('')

  if (!open) return null

  const trimmed = reason.trim()
  const canConfirm = mode !== null && trimmed.length > 0 && !isPending

  return (
    <ModalDialog
      labelledBy="release-quarantine-modal-title"
      onClose={onClose}
      panelClassName="p-6 max-w-md w-full mx-4"
    >
      <h2 id="release-quarantine-modal-title" className="text-lg font-semibold text-white mb-2">
        Liberar cuarentena
      </h2>
      {path && <p className="text-xs font-mono text-gray-400 mb-4 break-all">{path}</p>}

      <fieldset className="mb-4 space-y-2">
        <legend className="text-sm text-gray-300 mb-2">Qué hacer con el archivo:</legend>
        {OPTIONS.map((option) => (
          <label key={option.mode} className="flex items-start gap-2 text-sm text-gray-300 cursor-pointer">
            <input
              type="radio"
              name="releaseMode"
              value={option.mode}
              checked={mode === option.mode}
              onChange={() => setMode(option.mode)}
              className="mt-1"
            />
            <span>
              <span className="block">{option.label}</span>
              <span className="block text-xs text-gray-500">{option.consequence}</span>
            </span>
          </label>
        ))}
      </fieldset>

      {mode === 'restore_original' && (
        <p
          role="alert"
          className="mb-4 text-sm text-yellow-300 bg-yellow-950 border border-yellow-800 rounded px-3 py-2"
        >
          Atención: restaurar el archivo original lo aprueba. El contenido cuarentenado pasará a ser
          el baseline y dejará de detectarse como cambio.
        </p>
      )}

      <label className="block mb-4 text-sm text-gray-300">
        Motivo (obligatorio)
        <textarea
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          maxLength={MAX_REASON_LENGTH}
          rows={3}
          className="mt-1 w-full rounded bg-gray-900 border border-gray-700 px-2 py-1 text-sm text-gray-200"
        />
      </label>

      <div className="flex gap-2 justify-end">
        <button
          onClick={onClose}
          disabled={isPending}
          className="px-4 py-2 bg-gray-700 hover:bg-gray-600 text-gray-300 rounded text-sm"
        >
          Cancelar
        </button>
        <button
          onClick={() => {
            if (mode !== null) onConfirm(mode, trimmed)
          }}
          disabled={!canConfirm}
          className="px-4 py-2 bg-danger hover:bg-danger-hover text-white rounded text-sm font-medium disabled:opacity-50"
        >
          {isPending ? 'Procesando...' : 'Confirmar liberación'}
        </button>
      </div>
    </ModalDialog>
  )
}
