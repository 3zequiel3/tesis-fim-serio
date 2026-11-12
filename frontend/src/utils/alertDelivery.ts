/**
 * Cómo se presenta el estado de entrega de una alerta: nombre y tono.
 *
 * `pages/Alerts.tsx` tenía el tono en un Record local y mostraba el valor
 * crudo como texto. Mismo contrato que `getSeverityMeta`.
 */
export interface AlertDeliveryMeta {
  /** El nombre que lleva en pantalla. `undefined` para un estado desconocido. */
  label: string | undefined
  /** Clase de texto — verbatim del STATUS_TONE que vivía en Alerts.tsx. */
  toneClass: string
}

const NEUTRAL_META: AlertDeliveryMeta = { label: undefined, toneClass: 'text-text' }

const ALERT_DELIVERY_META: Record<string, AlertDeliveryMeta> = {
  pending: { label: 'En camino', toneClass: 'text-warning-fg' },
  delivered: { label: 'Entregada', toneClass: 'text-success-fg' },
  failed: { label: 'Fallida', toneClass: 'text-danger-fg' },
}

export function getAlertDeliveryMeta(status: string | null | undefined): AlertDeliveryMeta {
  if (!status) return NEUTRAL_META
  return ALERT_DELIVERY_META[status] ?? NEUTRAL_META
}
