import { useState } from 'react'
import { Modal } from '@/components/ui/Modal'
import { Button } from '@/components/ui/Button'
import { inputClassName } from '@/components/ui/Field'
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
export function ReleaseQuarantineModal(props: ReleaseQuarantineModalProps) {
  // The state lives in the body, so every opening starts clean (M8).
  if (!props.open) return null
  return <ReleaseQuarantineBody {...props} />
}

function ReleaseQuarantineBody({ path, onClose, onConfirm, isPending = false }: ReleaseQuarantineModalProps) {
  const [mode, setMode] = useState<ReleaseMode | null>(null)
  const [reason, setReason] = useState('')

  const trimmed = reason.trim()
  const canConfirm = mode !== null && trimmed.length > 0 && !isPending

  return (
    <Modal title="Liberar cuarentena" onClose={onClose} busy={isPending} widthClassName="max-w-lg">
      {path && <p className="mb-4 break-all font-mono text-xs text-text-muted">{path}</p>}

      <fieldset className="mb-4 space-y-2">
        <legend className="mb-2 font-semibold text-text">Qué hacer con el archivo:</legend>
        {OPTIONS.map((option) => (
          <label key={option.mode} className="flex cursor-pointer items-start gap-2 text-text">
            <input
              type="radio"
              name="releaseMode"
              value={option.mode}
              checked={mode === option.mode}
              onChange={() => setMode(option.mode)}
              className="mt-1 accent-accent"
            />
            <span>
              <span className="block">{option.label}</span>
              <span className="block text-xs text-text-muted">{option.consequence}</span>
            </span>
          </label>
        ))}
      </fieldset>

      {mode === 'restore_original' && (
        <p
          role="alert"
          className="mb-4 rounded-control border border-warning-line bg-warning-bg px-3 py-2 text-warning-fg"
        >
          Atención: restaurar el archivo original lo aprueba. El contenido cuarentenado pasará a ser
          el baseline y dejará de detectarse como cambio.
        </p>
      )}

      <label className="mb-4 block font-semibold text-text">
        Motivo (obligatorio)
        <textarea
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          maxLength={MAX_REASON_LENGTH}
          rows={3}
          className={`${inputClassName} mt-1 font-normal`}
        />
      </label>

      <div className="flex justify-end gap-2">
        <Button onClick={onClose} disabled={isPending}>
          Cancelar
        </Button>
        <Button
          variant="danger"
          onClick={() => {
            if (mode !== null) onConfirm(mode, trimmed)
          }}
          disabled={!canConfirm}
          loading={isPending}
        >
          {isPending ? 'Procesando...' : 'Confirmar liberación'}
        </Button>
      </div>
    </Modal>
  )
}
