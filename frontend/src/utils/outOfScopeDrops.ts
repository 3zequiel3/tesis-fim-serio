// D69/RN-163: contador de eventos que el agente descartó por caer fuera de
// los `watch_paths`. La marca de fanotify es de filesystem completo en modo
// FID (D46/RN-140), así que toda escritura ajena al alcance del agente
// produce un descarte: es el caso normal, no una anomalía. El contador es la
// evidencia de que el filtro de scope está funcionando, no una señal de
// pérdida.
//
// Deliberadamente **no** se reutiliza getDiscardedEventsMeta con un
// parámetro (D-7 del design): los dos mappers difieren justo en el eje que
// D69/RN-163 exige mantener distinguible — allá el positivo es una detección
// perdida (anomalía, paleta roja); acá el positivo es esperado (telemetría
// de rutina, paleta neutra gris). Compartir la función acoplaría dos
// presentaciones que deben poder evolucionar por separado: una edición
// futura de un mapper rompería al otro en silencio. La paleta acá es
// **siempre** neutra (gris), en los tres estados, incluido `positive` — una
// futura "unificación de estilos" no debería pintar este contador de rojo ni
// ámbar.

export type OutOfScopeDropsState = 'unknown' | 'zero' | 'positive'

export interface OutOfScopeDropsMeta {
  state: OutOfScopeDropsState
  label: string
  title: string
  className: string
}

const UNKNOWN_META: OutOfScopeDropsMeta = {
  state: 'unknown',
  label: '—',
  title: 'El agente no reportó descartes fuera de scope (versión anterior a esta funcionalidad, o sin heartbeat aún)',
  className: 'bg-gray-800 text-gray-500 border border-gray-700',
}

const ZERO_META: OutOfScopeDropsMeta = {
  state: 'zero',
  label: '0',
  title: 'Sin descartes fuera de scope',
  className: 'bg-gray-800 text-gray-400 border border-gray-600',
}

/**
 * Retorna la presentación del contador de descartes fuera de scope para los
 * tres estados posibles: desconocido (agente que nunca reportó), cero y
 * positivo. A diferencia de getDiscardedEventsMeta, el estado `positive` NO
 * usa la paleta de alarma: acá un positivo es esperado, no una anomalía.
 * Nunca lanza.
 */
export function getOutOfScopeDropsMeta(count: number | null | undefined): OutOfScopeDropsMeta {
  if (count === null || count === undefined || Number.isNaN(count)) {
    return UNKNOWN_META
  }
  if (count > 0) {
    return {
      state: 'positive',
      label: String(count),
      title: `${count} descarte(s) fuera de scope: esperado — la marca de fanotify cubre el filesystem completo, así que toda escritura ajena a los watch_paths se descarta. Es evidencia de que el filtro de scope está funcionando, no un problema.`,
      className: 'bg-gray-800 text-gray-400 border border-gray-600',
    }
  }
  return ZERO_META
}
