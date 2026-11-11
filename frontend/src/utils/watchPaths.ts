// Client-side mirror of the backend watch_paths validation (D91/RN-185,
// backend/app/core/path_validation.py). Pure so the same rules can be tested
// without rendering. The backend stays the authority; this only avoids a
// round trip for what it would reject anyway.

export const MAX_PATH_LENGTH = 1024
export const MAX_WATCH_PATHS = 64

export const EMPTY_LIST_MESSAGE = 'El agente necesita al menos una ruta vigilada.'

export interface WatchPathProblem {
  code: string
  message: string
  /** Position of the offending entry, when the problem is about one entry. */
  index?: number
}

const MESSAGES: Record<string, string> = {
  empty: 'La ruta no puede estar vacía.',
  not_absolute: 'La ruta debe ser absoluta (empezar con /).',
  parent_segment: 'La ruta no puede contener un segmento «..».',
  control_char: 'La ruta no puede contener saltos de línea ni otros caracteres de control.',
  too_long: `La ruta no puede superar los ${MAX_PATH_LENGTH} caracteres.`,
}

function hasControlChar(value: string): boolean {
  for (const ch of value) {
    const code = ch.codePointAt(0) ?? 0
    if (code < 0x20 || code === 0x7f) return true
  }
  return false
}

/** Reason suffix of the first failed check for one path, or null if it is fine. */
export function checkWatchPath(path: string): keyof typeof MESSAGES | null {
  if (!path || !path.trim()) return 'empty'
  if (!path.startsWith('/')) return 'not_absolute'
  if (path.split('/').includes('..')) return 'parent_segment'
  if (hasControlChar(path)) return 'control_char'
  if ([...path].length > MAX_PATH_LENGTH) return 'too_long'
  return null
}

/** "/etc" and "/etc/" are the same fanotify mark: duplicates ignore a trailing slash. */
export function canonicalWatchPath(path: string): string {
  return path.replace(/\/+$/, '') || '/'
}

/** Problem of one candidate path, as a message, or null. */
export function describeWatchPath(path: string): string | null {
  const reason = checkWatchPath(path)
  return reason ? MESSAGES[reason] : null
}

/** First problem of the whole list the backend would reject, or null. */
export function validateWatchPaths(paths: string[]): WatchPathProblem | null {
  if (paths.length === 0) return { code: 'watch_paths_empty', message: EMPTY_LIST_MESSAGE }
  if (paths.length > MAX_WATCH_PATHS) {
    return {
      code: 'watch_paths_too_many',
      message: `No se pueden vigilar más de ${MAX_WATCH_PATHS} rutas por agente.`,
    }
  }
  const seen = new Set<string>()
  for (const [index, path] of paths.entries()) {
    const reason = checkWatchPath(path)
    if (reason) return { code: `watch_path_${reason}`, message: MESSAGES[reason], index }
    const canonical = canonicalWatchPath(path)
    if (seen.has(canonical)) {
      return {
        code: 'watch_path_duplicate',
        message: 'La ruta está repetida (con o sin la barra final).',
        index,
      }
    }
    seen.add(canonical)
  }
  return null
}
