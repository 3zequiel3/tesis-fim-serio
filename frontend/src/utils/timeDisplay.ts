// D39/RN-133 (change timestamps-timezone-aware, capacidad frontend-time-display):
// único punto de render de un instante en toda la consola. Antes de esta
// change la misma decisión se tomaba nueve veces sueltas con
// `toLocaleString('es-AR')`, sin contrato compartido — lo que permitió que
// un desplazamiento de tres horas fuera uniforme en toda la pantalla y no
// fuera responsabilidad de nadie. Ningún componente debe formatear un
// instante por su cuenta: todo pasa por acá.
//
// Contrato (D-6 del design):
//   - La forma absoluta SIEMPRE muestra la zona junto a la hora — no es un
//     tooltip opcional. Un operador que correlaciona contra journalctl o un
//     .pcap necesita saber contra qué reloj está leyendo.
//   - La forma relativa acompaña a la absoluta, nunca la reemplaza.
//   - null es un estado real (nunca latió, evento no resuelto) y se
//     renderiza como ausencia explícita — nunca `Invalid Date`, nunca una
//     fecha inventada.
//   - Un instante futuro se rotula como tal (Intl.RelativeTimeFormat ya
//     produce "dentro de X" en vez de un intervalo negativo) — nunca se
//     redondea a cero ni se esconde: un reloj desincronizado en el host del
//     agente es justamente lo que RN-90/RN-131 vigilan.
//   - Un valor presente pero no parseable degrada de forma visible.
//
// Usa Intl.DateTimeFormat / Intl.RelativeTimeFormat — sin dependencia de
// fechas nueva.

export type InstantInput = string | number | Date | null | undefined

export interface FormatOptions {
  /** Locale de Intl. Default 'es-AR' — el operador es de un único laboratorio. */
  locale?: string
  /** Zona IANA explícita. Sin especificar, Intl usa la del entorno del visor. */
  timeZone?: string
  /** Texto para instante ausente (null/undefined). Default 'nunca'. */
  nullLabel?: string
  /** Texto para un valor presente que no se puede parsear. */
  invalidLabel?: string
}

export const DEFAULT_LOCALE = 'es-AR'
export const NULL_LABEL = 'nunca'
export const INVALID_LABEL = 'fecha inválida'

function toDate(value: InstantInput): Date | null {
  if (value === null || value === undefined) return null
  const d = value instanceof Date ? value : new Date(value)
  return Number.isNaN(d.getTime()) ? null : d
}

/**
 * Forma absoluta: hora en la zona del visor, con la zona SIEMPRE visible
 * (`timeZoneName: 'short'` — p.ej. "20/08/2026, 16:55:59 ART").
 */
export function formatAbsolute(value: InstantInput, options: FormatOptions = {}): string {
  const {
    locale = DEFAULT_LOCALE,
    timeZone,
    nullLabel = NULL_LABEL,
    invalidLabel = INVALID_LABEL,
  } = options

  if (value === null || value === undefined) return nullLabel

  const d = toDate(value)
  if (d === null) return invalidLabel

  return new Intl.DateTimeFormat(locale, {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
    timeZoneName: 'short',
    ...(timeZone ? { timeZone } : {}),
  }).format(d)
}

const _RELATIVE_UNITS: Array<[Intl.RelativeTimeFormatUnit, number]> = [
  ['day', 86400],
  ['hour', 3600],
  ['minute', 60],
  ['second', 1],
]

export interface RelativeOptions extends FormatOptions {
  /** Instante de referencia ("ahora"), en epoch ms. Default Date.now(). */
  now?: number
}

/**
 * Forma relativa ("hace 4 min" / "dentro de 4 min"). El intervalo es una
 * propiedad de los DOS instantes (`value`, `now`) — nunca de la zona de
 * visualización, que no interviene acá en absoluto (D-6, RN-90/RN-131:
 * invariancia de zona).
 *
 * Un instante futuro produce "dentro de X", NUNCA un número negativo — es
 * información operativa (reloj del agente desincronizado), no se esconde.
 */
export function formatRelative(value: InstantInput, options: RelativeOptions = {}): string {
  const {
    locale = DEFAULT_LOCALE,
    nullLabel = NULL_LABEL,
    invalidLabel = INVALID_LABEL,
    now = Date.now(),
  } = options

  if (value === null || value === undefined) return nullLabel

  const d = toDate(value)
  if (d === null) return invalidLabel

  const diffSeconds = (d.getTime() - now) / 1000
  const absSeconds = Math.abs(diffSeconds)

  const [unit, divisor] =
    _RELATIVE_UNITS.find(([, secs]) => absSeconds >= secs) ?? _RELATIVE_UNITS[_RELATIVE_UNITS.length - 1]
  const unitValue = Math.round(diffSeconds / divisor)

  if (unitValue === 0) return 'justo ahora'

  const rtf = new Intl.RelativeTimeFormat(locale, { numeric: 'always' })
  return rtf.format(unitValue, unit)
}
