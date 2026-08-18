// D35/RN-129 (C40): indicador de remediación fallida. Un pending con
// action_failed=true significa que el archivo sigue adulterado en disco Y
// la remediación automática ya falló — tiene prioridad operativa sobre un
// pending ordinario. Mapper puro, mismo contrato que getAckStatusMeta
// (frontend/src/utils/ackStatus.ts), para no sumar una cuarta copia del
// mapa de clases de estado.

export interface ActionFailedMeta {
  label: string
  className: string
}

const ACTION_FAILED_META: ActionFailedMeta = {
  label: 'Remediación fallida',
  className: 'bg-red-950 text-red-300 border border-red-800',
}

/**
 * Retorna el label/clase del indicador de remediación fallida, o null si
 * action_failed es false (no corresponde mostrar ningún indicador).
 */
export function getActionFailedMeta(actionFailed: boolean): ActionFailedMeta | null {
  if (!actionFailed) return null
  return ACTION_FAILED_META
}
