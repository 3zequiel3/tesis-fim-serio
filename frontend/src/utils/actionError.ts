// D36/RN-130 (C41): causa del fallo de una acción automática
// (auto_restore/quarantine), califica al indicador de action_failed que
// introdujo C40 (D35/RN-129). El punto de esta decisión es que el operador
// pueda distinguir un problema de despliegue (read_only_mount,
// permission_denied) de un problema de datos (no_baseline_content,
// no_baseline_metadata, ...) sin salir de la interfaz. Mapper puro, mismo
// contrato que getAckStatusMeta (frontend/src/utils/ackStatus.ts).

export interface ActionErrorMeta {
  label: string
  className: string
  /** The cause without the «Causa:» prefix, for the command failure line (D93/RN-187). */
  reason: string
}

// Vocabulario cerrado del lado del agente (design D-7). Los dos primeros son
// barrera de despliegue; el resto, problema de datos.
const ACTION_ERROR_META: Record<string, ActionErrorMeta> = {
  read_only_mount: {
    label: 'Causa: el path no es escribible (mount de solo lectura del despliegue)',
    reason: 'el path no es escribible (mount de solo lectura del despliegue)',
    className: 'bg-warning-bg text-warning-fg border border-warning-line',
  },
  permission_denied: {
    label: 'Causa: permiso denegado al escribir (faltan capabilities en el despliegue)',
    reason: 'permiso denegado al escribir (faltan capabilities en el despliegue)',
    className: 'bg-warning-bg text-warning-fg border border-warning-line',
  },
  no_baseline_content: {
    label: 'Causa: no hay contenido de baseline para restaurar',
    reason: 'no hay contenido de baseline para restaurar',
    className: 'bg-danger-bg text-danger-fg border border-danger-line',
  },
  no_restorable_content: {
    label: 'Causa: el baseline no tiene contenido restaurable',
    reason: 'el baseline no tiene contenido restaurable',
    className: 'bg-danger-bg text-danger-fg border border-danger-line',
  },
  no_baseline_metadata: {
    label: 'Causa: falta metadata de baseline (modo/dueño/grupo)',
    reason: 'falta metadata de baseline (modo/dueño/grupo)',
    className: 'bg-danger-bg text-danger-fg border border-danger-line',
  },
  file_not_found: {
    label: 'Causa: el archivo no se encontró',
    reason: 'el archivo no se encontró',
    className: 'bg-danger-bg text-danger-fg border border-danger-line',
  },
  hash_mismatch_after_restore: {
    label: 'Causa: el hash no coincide después de restaurar',
    reason: 'el hash no coincide después de restaurar',
    className: 'bg-danger-bg text-danger-fg border border-danger-line',
  },
  write_failed: {
    label: 'Causa: falló la escritura del archivo',
    reason: 'falló la escritura del archivo',
    className: 'bg-danger-bg text-danger-fg border border-danger-line',
  },
  artifact_not_found: {
    label: 'Causa: el artefacto en cuarentena ya no existe',
    reason: 'el artefacto en cuarentena ya no existe',
    className: 'bg-danger-bg text-danger-fg border border-danger-line',
  },
  path_occupied: {
    label: 'Causa: la ruta de destino ya está ocupada por otro archivo',
    reason: 'la ruta de destino ya está ocupada por otro archivo',
    className: 'bg-danger-bg text-danger-fg border border-danger-line',
  },
  path_outside_watch_paths: {
    label: 'Causa: la ruta quedó fuera de los watch_paths del agente',
    reason: 'la ruta quedó fuera de los watch_paths del agente',
    className: 'bg-warning-bg text-warning-fg border border-warning-line',
  },
  no_watch_paths_configured: {
    label: 'Causa: el agente no tiene watch_paths configurados',
    reason: 'el agente no tiene watch_paths configurados',
    className: 'bg-warning-bg text-warning-fg border border-warning-line',
  },
  quarantine_identity_missing: {
    label: 'Causa: falta la identidad del archivo en cuarentena',
    reason: 'falta la identidad del archivo en cuarentena',
    className: 'bg-danger-bg text-danger-fg border border-danger-line',
  },
  quarantine_failed: {
    label: 'Causa: falló la cuarentena del archivo',
    reason: 'falló la cuarentena del archivo',
    className: 'bg-danger-bg text-danger-fg border border-danger-line',
  },
  baseline_mark_failed: {
    label: 'Causa: no se pudo actualizar el baseline',
    reason: 'no se pudo actualizar el baseline',
    className: 'bg-danger-bg text-danger-fg border border-danger-line',
  },
  move_failed: {
    label: 'Causa: falló el movimiento a cuarentena',
    reason: 'falló el movimiento a cuarentena',
    className: 'bg-danger-bg text-danger-fg border border-danger-line',
  },
}

/**
 * Retorna el label/clase de la causa del fallo de acción, o null si no hay
 * causa. Un valor desconocido (agente más nuevo que el frontend) cae al
 * literal crudo en vez de ocultarse — degrada a "menos legible", nunca a
 * "información perdida".
 */
export function getActionErrorMeta(cause: string | null | undefined): ActionErrorMeta | null {
  if (!cause) return null
  return (
    ACTION_ERROR_META[cause] ?? {
      label: `Causa: ${cause}`,
      reason: `Motivo: ${cause}`,
      className: 'bg-neutral-bg text-neutral-fg border border-neutral-line',
    }
  )
}

/**
 * Motivo legible del fallo de un comando (`ack_error`, D93/RN-187): el mismo
 * mapa de causas que `action_error`; un código desconocido se muestra literal
 * con el prefijo «Motivo:». Devuelve null cuando no hay motivo.
 */
export function getAckErrorReason(error: string | null | undefined): string | null {
  const meta = getActionErrorMeta(error)
  if (!meta) return null
  return meta.reason
}
