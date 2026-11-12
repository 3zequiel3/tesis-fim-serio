import type { QuarantineState } from '@/api/events'

// Resultado FÍSICO de la cuarentena de un evento (D82/RN-176), derivado por el
// backend en cada lectura. NO es un estado del evento: un rechazo con
// cuarentena sigue mostrando `rejected` en el badge de status (RN-72), y este
// badge va aparte, con un estilo distinto del de `status` y del de ejecución.

export interface QuarantineStateMeta {
  /** El valor canónico (RN-71), que es lo que muestra el badge. */
  label: string
  /** El nombre legible, para los filtros y cualquier texto corrido. */
  name: string
  className: string
}

const QUARANTINE_STATE_META: Record<Exclude<QuarantineState, 'none'>, QuarantineStateMeta> = {
  quarantined: { label: 'quarantined', name: 'En cuarentena', className: 'bg-transparent text-status-quarantined-fg border border-status-quarantined border-dashed' },
  released: { label: 'released', name: 'Liberado', className: 'bg-transparent text-info-fg border border-info-line border-dashed' },
  discarded: { label: 'discarded', name: 'Descartado', className: 'bg-transparent text-neutral-fg border border-neutral-line border-dashed' },
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
