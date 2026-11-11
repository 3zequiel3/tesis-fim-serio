import { AxiosError, AxiosHeaders, type InternalAxiosRequestConfig } from 'axios'

/**
 * Builds an axios error with the REAL backend body shape `{"detail": ...}`
 * (D90/RN-184, design D-14), so a test cannot invent a flat `{code}` body.
 *
 *   mockApiError(422, {code: 'absent_confirmation_required', message: '...'})
 *   mockApiError(404, 'agent not found')
 *   mockApiError(429, {code: 'login_rate_limited', message: '...'}, {'retry-after': '30'})
 */
export function mockApiError(
  status: number,
  detail: unknown,
  headers: Record<string, string> = {},
): AxiosError {
  const config = { headers: new AxiosHeaders() } as InternalAxiosRequestConfig
  return new AxiosError(
    `Request failed with status code ${status}`,
    AxiosError.ERR_BAD_REQUEST,
    config,
    {},
    {
      status,
      statusText: '',
      data: { detail },
      headers: new AxiosHeaders(headers),
      config,
    },
  )
}

/** A request that never got a response (connection refused, DNS, timeout). */
export function mockNetworkError(): AxiosError {
  return new AxiosError('Network Error', AxiosError.ERR_NETWORK)
}
