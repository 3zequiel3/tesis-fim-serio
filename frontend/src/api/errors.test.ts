import { describe, expect, it } from 'vitest'
import { mockApiError, mockNetworkError } from '@/test/mockApiError'
import { apiErrorMessage, readApiError } from './errors'

describe('readApiError', () => {
  it('reads a code nested in detail', () => {
    const e = readApiError(
      mockApiError(422, { code: 'absent_confirmation_required', message: 'Confirmá el archivo ausente' }),
    )
    expect(e).toMatchObject({
      status: 422,
      code: 'absent_confirmation_required',
      message: 'Confirmá el archivo ausente',
    })
  })

  it('does not look for the code at the root of the body', () => {
    // The flat shape the old mocks invented; the backend never emits it.
    const flat = mockApiError(422, undefined)
    flat.response!.data = { code: 'absent_confirmation_required' }
    expect(readApiError(flat).code).toBeNull()
  })

  it('keeps extra fields of the detail in data', () => {
    const e = readApiError(mockApiError(409, { code: 'pending_events_exist', count: 3 }))
    expect(e.code).toBe('pending_events_exist')
    expect(e.data).toEqual({ count: 3 })
  })

  it('keeps the index of a watch path error', () => {
    const e = readApiError(mockApiError(422, { code: 'watch_path_not_absolute', message: 'm', index: 2 }))
    expect(e.data.index).toBe(2)
  })

  it('reads a plain string detail', () => {
    const e = readApiError(mockApiError(404, 'agent not found'))
    expect(e).toMatchObject({ status: 404, code: null, message: 'agent not found' })
  })

  it('turns a Pydantic list into a string message', () => {
    const e = readApiError(
      mockApiError(422, [{ loc: ['body', 'pattern'], msg: 'Field required', type: 'missing' }]),
    )
    expect(e.message).toBe('Field required')
    expect(e.message).not.toContain('[object Object]')
  })

  it('exposes Retry-After seconds', () => {
    const e = readApiError(
      mockApiError(429, { code: 'login_rate_limited', message: 'Demasiados intentos' }, { 'retry-after': '37' }),
    )
    expect(e.retryAfter).toBe(37)
  })

  it('reports a network error with status 0 and a Spanish message', () => {
    const e = readApiError(mockNetworkError())
    expect(e.status).toBe(0)
    expect(e.message).toMatch(/conect/i)
  })

  it('degrades on a body without detail', () => {
    const err = mockApiError(502, undefined)
    err.response!.data = '<html>Bad gateway</html>'
    expect(readApiError(err).message).toContain('502')
  })

  it('handles an error that is not HTTP at all', () => {
    expect(readApiError(new Error('boom')).message).toBe('boom')
    expect(readApiError('weird').message).not.toBe('')
  })
})

describe('apiErrorMessage', () => {
  it('prefers the backend message and falls back otherwise', () => {
    expect(apiErrorMessage(mockApiError(422, { code: 'x', message: 'Desde el backend' }), 'Fallback')).toBe(
      'Desde el backend',
    )
    expect(apiErrorMessage(mockApiError(422, { code: 'x' }), 'Fallback')).toBe('Fallback')
  })
})
