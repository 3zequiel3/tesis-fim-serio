// D36/RN-130 (C41): clasificación de escritura por watch_path, reportada por
// el preflight del agente en cada heartbeat. Un path degradado sigue
// MONITOREADO — solo la remediación automática no puede correr ahí. Por eso
// el tratamiento visual es deliberadamente distinto del de un agente
// offline/dead: leer "solo-detección" como "el agente está roto" es
// exactamente la confusión que este mapper existe para prevenir. Mismo
// contrato que getAckStatusMeta (frontend/src/utils/ackStatus.ts).

export interface WatchPathStatusMeta {
  label: string
  title: string
  className: string
}

// Vocabulario cerrado del preflight (design D-3): writable | read_only_mount
// | permission_denied | missing. Solo los tres últimos tienen indicador —
// writable no muestra nada (ver getWatchPathStatusMeta). `label` es el chip
// corto para la tarjeta; `title` es la prosa completa (tooltip).
const WATCH_PATH_STATUS_META: Record<string, WatchPathStatusMeta> = {
  read_only_mount: {
    label: 'Solo detección',
    title: 'Monitoreado, no remediable: el path está en un mount de solo lectura del despliegue',
    className: 'bg-amber-950 text-amber-300 border border-amber-800',
  },
  permission_denied: {
    label: 'Solo detección',
    title: 'Monitoreado, no remediable: permiso denegado al escribir en este path',
    className: 'bg-amber-950 text-amber-300 border border-amber-800',
  },
  missing: {
    label: 'No existe',
    title: 'El path no existe en el host del agente',
    className: 'bg-gray-700 text-gray-300 border border-gray-600',
  },
}

/**
 * Retorna el label/clase del indicador de un watch_path, o null cuando el
 * path es escribible (sin indicador — RN-92) o cuando la clasificación no
 * viene informada. Un valor desconocido (agente más nuevo que el frontend)
 * cae al literal crudo en vez de ocultarse.
 */
export function getWatchPathStatusMeta(status: string | undefined): WatchPathStatusMeta | null {
  if (!status || status === 'writable') return null
  return (
    WATCH_PATH_STATUS_META[status] ?? {
      label: status,
      title: status,
      className: 'bg-gray-700 text-gray-300 border border-gray-600',
    }
  )
}
