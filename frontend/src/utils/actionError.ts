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
}

// Vocabulario cerrado del lado del agente (design D-7). Los dos primeros son
// barrera de despliegue; el resto, problema de datos.
const ACTION_ERROR_META: Record<string, ActionErrorMeta> = {
  read_only_mount: {
    label: 'Causa: el path no es escribible (mount de solo lectura del despliegue)',
    className: 'bg-orange-950 text-orange-300 border border-orange-800',
  },
  permission_denied: {
    label: 'Causa: permiso denegado al escribir (faltan capabilities en el despliegue)',
    className: 'bg-orange-950 text-orange-300 border border-orange-800',
  },
  no_baseline_content: {
    label: 'Causa: no hay contenido de baseline para restaurar',
    className: 'bg-red-950 text-red-300 border border-red-800',
  },
  no_restorable_content: {
    label: 'Causa: el baseline no tiene contenido restaurable',
    className: 'bg-red-950 text-red-300 border border-red-800',
  },
  no_baseline_metadata: {
    label: 'Causa: falta metadata de baseline (modo/dueño/grupo)',
    className: 'bg-red-950 text-red-300 border border-red-800',
  },
  file_not_found: {
    label: 'Causa: el archivo no se encontró',
    className: 'bg-red-950 text-red-300 border border-red-800',
  },
  hash_mismatch_after_restore: {
    label: 'Causa: el hash no coincide después de restaurar',
    className: 'bg-red-950 text-red-300 border border-red-800',
  },
  write_failed: {
    label: 'Causa: falló la escritura del archivo',
    className: 'bg-red-950 text-red-300 border border-red-800',
  },
  move_failed: {
    label: 'Causa: falló el movimiento a cuarentena',
    className: 'bg-red-950 text-red-300 border border-red-800',
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
      className: 'bg-gray-800 text-gray-300 border border-gray-600',
    }
  )
}
