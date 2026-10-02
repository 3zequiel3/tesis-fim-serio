import type { QuarantineState } from '@/api/events'

// Resultado FÍSICO de la cuarentena de un evento (D82/RN-176), derivado por el
// backend en cada lectura. NO es un estado del evento: un rechazo con
// cuarentena sigue mostrando `rejected` en el badge de status (RN-72), y este
// badge va aparte, con un estilo distinto del de `status` y del de ejecución.

export interface QuarantineStateMeta {
  label: string
  className: string
}

const QUARANTINE_STATE_META: Record<Exclude<QuarantineState, 'none'>, QuarantineStateMeta> = {
  quarantined: { label: 'quarantined', className: 'bg-transparent text-violet-300 border border-violet-500 border-dashed' },
  released: { label: 'released', className: 'bg-transparent text-sky-300 border border-sky-500 border-dashed' },
  discarded: { label: 'discarded', className: 'bg-transparent text-gray-400 border border-gray-500 border-dashed' },
}

/**
 * Retorna el label (valor en minúsculas, RN-71) y la clase del badge de
 * cuarentena, o null cuando no corresponde mostrar nada (`none`, ausente o un
 * valor desconocido de un backend más nuevo).
 */
export function getQuarantineStateMeta(
  state: QuarantineState | null | undefined,
): QuarantineStateMeta | null {
  if (!state || state === 'none') return null
  return QUARANTINE_STATE_META[state] ?? null
}
