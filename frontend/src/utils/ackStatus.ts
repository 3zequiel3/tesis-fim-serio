import type { CommandAckStatus } from '@/api/events'

// Indicador secundario de estado de EJECUCIÓN del comando asociado a un
// evento (D30/RN-124, C36). Visualmente distinto del badge de `status` del
// evento; se omite por completo cuando no hay comando confirmable asociado.

export interface AckStatusMeta {
  label: string
  className: string
}

const ACK_STATUS_META: Record<CommandAckStatus, AckStatusMeta> = {
  pending: { label: 'Ejecución: pendiente', className: 'bg-yellow-950 text-yellow-400 border border-yellow-800' },
  acked: { label: 'Ejecución: confirmada', className: 'bg-emerald-950 text-emerald-400 border border-emerald-800' },
  failed: { label: 'Ejecución: falló', className: 'bg-red-950 text-red-400 border border-red-800' },
  timeout: { label: 'Ejecución: vencida', className: 'bg-gray-800 text-gray-400 border border-gray-600' },
}

/**
 * Retorna el label/clase del badge secundario de ejecución, o null si no
 * corresponde mostrar ningún indicador (sin comando confirmable asociado).
 */
export function getAckStatusMeta(ackStatus: CommandAckStatus | null | undefined): AckStatusMeta | null {
  if (!ackStatus) return null
  return ACK_STATUS_META[ackStatus] ?? null
}
