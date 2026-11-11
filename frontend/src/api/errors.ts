import axios from 'axios'

// Single reader of API errors (D90/RN-184, design D-4). Every error body of the
// backend is `{"detail": ...}`; `detail` has three shapes:
//   - string                       -> message
//   - {code, message?, ...extra}   -> code, message, extra fields in `data`
//   - list of Pydantic issues      -> message from the first `msg`
// Components, hooks and toasts must go through this module and never read
// `response.data` themselves (enforced by an ESLint rule).

export interface ApiError {
  /** HTTP status; 0 when the request got no response (network) or the error is not HTTP. */
  status: number
  /** Machine code from an object `detail`; null for string and list shapes. */
  code: string | null
  /** Human readable text; never `[object Object]`. Empty only if the backend sent none. */
  message: string
  /** Extra fields of an object `detail` (`count`, `index`, ...), without `code`/`message`. */
  data: Record<string, unknown>
  /** Seconds from a `Retry-After` header when present (429), else null. */
  retryAfter: number | null
}

const NETWORK_MESSAGE = 'No se pudo conectar con el servidor. Verificá tu conexión e intentá de nuevo.'
const UNEXPECTED_MESSAGE = 'Ocurrió un error inesperado.'

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function parseRetryAfter(headers: unknown): number | null {
  if (!headers) return null
  const raw =
    typeof (headers as { get?: unknown }).get === 'function'
      ? (headers as { get: (n: string) => unknown }).get('retry-after')
      : isRecord(headers)
        ? (headers['retry-after'] ?? headers['Retry-After'])
        : null
  const seconds = Number(raw)
  return raw != null && Number.isFinite(seconds) && seconds >= 0 ? Math.ceil(seconds) : null
}

function messageFromList(detail: unknown[]): string {
  for (const item of detail) {
    if (isRecord(item) && typeof item.msg === 'string' && item.msg) return item.msg
  }
  return 'Los datos enviados no son válidos.'
}

export function readApiError(err: unknown): ApiError {
  if (!axios.isAxiosError(err)) {
    return {
      status: 0,
      code: null,
      message: err instanceof Error && err.message ? err.message : UNEXPECTED_MESSAGE,
      data: {},
      retryAfter: null,
    }
  }
  const response = err.response
  if (!response) {
    return { status: 0, code: null, message: NETWORK_MESSAGE, data: {}, retryAfter: null }
  }

  const base = { status: response.status, retryAfter: parseRetryAfter(response.headers) }
  const body: unknown = response.data
  const detail = isRecord(body) ? body.detail : undefined

  if (typeof detail === 'string') {
    return { ...base, code: null, message: detail, data: {} }
  }
  if (Array.isArray(detail)) {
    return { ...base, code: null, message: messageFromList(detail), data: {} }
  }
  if (isRecord(detail)) {
    const { code, message, ...rest } = detail
    return {
      ...base,
      code: typeof code === 'string' ? code : null,
      message: typeof message === 'string' ? message : '',
      data: rest,
    }
  }
  return {
    ...base,
    code: null,
    message: `El servidor respondió con un error (${response.status}).`,
    data: {},
  }
}

/** Message to show the user: the backend text, or `fallback` when it sent none. */
export function apiErrorMessage(err: unknown, fallback: string): string {
  return readApiError(err).message || fallback
}
