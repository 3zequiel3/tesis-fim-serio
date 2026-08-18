// D37/RN-131 (C42): contador de eventos que el agente descartó localmente
// porque el transporte se rindió — techo de reintentos agotado sin ninguna
// respuesta, o event_nack terminal (invalid_schema, clock_skew). Un evento
// descartado es una detección de integridad perdida: se presenta como
// anomalía, no como telemetría de rutina. Mismo contrato que
// getWatchPathStatusMeta / getActionErrorMeta (frontend/src/utils/), pero a
// diferencia de esos mappers este NUNCA retorna null — "nunca reportó" es un
// estado que el operador tiene que poder distinguir de "cero", no una
// ausencia de indicador.

export type DiscardedEventsState = 'unknown' | 'zero' | 'positive'

export interface DiscardedEventsMeta {
  state: DiscardedEventsState
  label: string
  title: string
  className: string
}

const UNKNOWN_META: DiscardedEventsMeta = {
  state: 'unknown',
  label: '—',
  title: 'El agente no reportó descartes locales (versión anterior a esta funcionalidad, o sin heartbeat aún)',
  className: 'bg-gray-800 text-gray-500 border border-gray-700',
}

const ZERO_META: DiscardedEventsMeta = {
  state: 'zero',
  label: '0',
  title: 'Sin eventos descartados localmente',
  className: 'bg-gray-800 text-gray-400 border border-gray-600',
}

/**
 * Retorna la presentación del contador de descartes locales para los tres
 * estados posibles: desconocido (agente que nunca reportó), cero (sano) y
 * positivo (anomalía — el transporte perdió una detección). Nunca lanza.
 */
export function getDiscardedEventsMeta(count: number | null | undefined): DiscardedEventsMeta {
  if (count === null || count === undefined || Number.isNaN(count)) {
    return UNKNOWN_META
  }
  if (count > 0) {
    return {
      state: 'positive',
      label: String(count),
      title: `${count} evento(s) descartado(s) localmente: el transporte agotó los reintentos o recibió un rechazo terminal del backend sin poder entregarlos`,
      className: 'bg-red-950 text-red-300 border border-red-800',
    }
  }
  return ZERO_META
}
