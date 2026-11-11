import type { CommandAckStatus } from '@/api/events'

// Indicador secundario de estado de EJECUCIÓN del comando asociado a un
// evento (D30/RN-124, C36). Visualmente distinto del badge de `status` del
// evento; se omite por completo cuando no hay comando confirmable asociado.

export interface AckStatusMeta {
  label: string
  className: string
}

const ACK_STATUS_META: Record<CommandAckStatus, AckStatusMeta> = {
  pending: { label: 'Ejecución: pendiente', className: 'bg-warning-bg text-warning-fg border border-warning-line' },
  acked: { label: 'Ejecución: confirmada', className: 'bg-success-bg text-success-fg border border-success-line' },
  failed: { label: 'Ejecución: falló', className: 'bg-danger-bg text-danger-fg border border-danger-line' },
  timeout: { label: 'Ejecución: vencida', className: 'bg-neutral-bg text-neutral-fg border border-neutral-line' },
}

/**
 * Retorna el label/clase del badge secundario de ejecución, o null si no
 * corresponde mostrar ningún indicador (sin comando confirmable asociado).
 */
export function getAckStatusMeta(ackStatus: CommandAckStatus | null | undefined): AckStatusMeta | null {
  if (!ackStatus) return null
  return ACK_STATUS_META[ackStatus] ?? null
}
