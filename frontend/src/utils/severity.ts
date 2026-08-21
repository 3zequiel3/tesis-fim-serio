// D34/RN-128 (C38, capacidad frontend-severity-display): único contrato de
// presentación de severidad en toda la consola. Antes de esta change
// `SEVERITY_COLORS` estaba copiado literal en Alerts.tsx, Rules.tsx y
// FailedAlerts.tsx, y ausente de EventsTable.tsx — el lugar donde más
// importaba. Mismo contrato que getAckStatusMeta/getActionFailedMeta
// (frontend/src/utils/ackStatus.ts, actionFailed.ts): un Record privado por
// nivel y una función de acceso que tolera lo desconocido, para que el
// fallback no sea opcional en el sitio de uso.
//
// Los cuatro niveles se definen siempre, aunque el ruleset del laboratorio
// hoy no produzca ningún evento `medium` (D-2 del design). Un nivel que
// aparece por primera vez cuando alguien crea la primera regla `medium` es
// un nivel que se descubre como defecto.

export interface SeverityMeta {
  /** Clase de texto — idéntica a la que las tres pantallas migradas ya usaban. */
  textClass: string
  /** Clase de banda de borde izquierdo (`border-l-4` + esta clase) — D-1 del design. */
  bandClass: string
  /** Rango numérico de precedencia: critical > high > medium > low. */
  rank: number
}

const NEUTRAL_META: SeverityMeta = {
  textClass: 'text-gray-400',
  bandClass: 'border-l-gray-600',
  rank: 0,
}

// Clases de texto verbatim de Alerts.tsx:29-32 (D-2: la migración es un
// no-op observable). Clases de banda elegidas para que ningún par de
// niveles comparta una, y para que critical se distinga de high también en
// luminancia y no sólo en tono (red-600 es notablemente más oscuro que
// orange-400) — rojo contra naranja es el par exacto que un deuteranope no
// separa por tono solo (WCAG 1.4.1).
const SEVERITY_META: Record<string, SeverityMeta> = {
  critical: { textClass: 'text-red-400', bandClass: 'border-l-red-600', rank: 4 },
  high: { textClass: 'text-orange-400', bandClass: 'border-l-orange-400', rank: 3 },
  medium: { textClass: 'text-yellow-400', bandClass: 'border-l-yellow-400', rank: 2 },
  low: { textClass: 'text-blue-400', bandClass: 'border-l-blue-400', rank: 1 },
}

/**
 * Retorna el contrato de presentación (texto, banda, precedencia) para un
 * nivel de severidad. Un valor fuera de los cuatro niveles conocidos —o
 * ausente— devuelve un tratamiento neutro y nunca lanza, mismo patrón que
 * `EventsTable.tsx` ya usa para `status` desconocidos.
 */
export function getSeverityMeta(severity: string | null | undefined): SeverityMeta {
  if (!severity) return NEUTRAL_META
  return SEVERITY_META[severity] ?? NEUTRAL_META
}
