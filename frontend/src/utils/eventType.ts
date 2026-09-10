// D51/RN-145 (D-10 del design): discriminador para eventos que no hablan de
// ningun archivo concreto (path nulo) — la tabla y el detalle ramifican sobre
// `event_type`, no sobre `path === null`, porque el tipo es el dato con
// significado. Mismo contrato que getActionErrorMeta
// (frontend/src/utils/actionError.ts): vocabulario cerrado del lado del
// backend con fallback humanizado para un event_type futuro desconocido.

export interface EventTypeGapMeta {
  label: string
  cause: string
  className: string
}

// Vocabulario canonico que el agente ya emite (RN-71). Por ahora el unico
// event_type que se publica sin ruta es detection_gap (D50/RN-144); el mapa
// queda abierto a futuros tipos sin ruta sin tocar el llamador.
const EVENT_TYPE_GAP_META: Record<string, EventTypeGapMeta> = {
  detection_gap: {
    label: 'Brecha de detección',
    cause:
      'El kernel desbordó su cola de eventos fanotify y descartó cambios entre ' +
      'la última lectura y ésta — no se sabe qué archivos cambiaron durante esa ventana.',
    className: 'bg-amber-900 text-amber-300 border border-amber-800',
  },
}

/**
 * Retorna la etiqueta/causa/clase para un evento sin ruta, a partir de su
 * event_type. Un valor desconocido (agente más nuevo que el frontend) cae en
 * un fallback humanizado (snake_case -> Title Case) en vez de un guion o una
 * celda vacía — el punto de D51/RN-145 es que la ausencia de ruta se lea
 * como información, nunca como un dato faltante.
 */
export function getEventTypeGapMeta(eventType: string): EventTypeGapMeta {
  const known = EVENT_TYPE_GAP_META[eventType]
  if (known) return known
  const humanized = eventType
    .split('_')
    .filter(Boolean)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ')
  return {
    label: humanized || eventType,
    cause: `Evento sin ruta de tipo "${eventType}".`,
    className: 'bg-gray-800 text-gray-300 border border-gray-600',
  }
}
