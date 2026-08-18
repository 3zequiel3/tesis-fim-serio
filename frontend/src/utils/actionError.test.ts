import { describe, it, expect } from 'vitest'
import { getActionErrorMeta } from './actionError'

describe('getActionErrorMeta', () => {
  it('retorna null cuando no hay causa', () => {
    expect(getActionErrorMeta(null)).toBeNull()
    expect(getActionErrorMeta(undefined)).toBeNull()
    expect(getActionErrorMeta('')).toBeNull()
  })

  it('mapea read_only_mount como problema de despliegue', () => {
    const meta = getActionErrorMeta('read_only_mount')
    expect(meta).not.toBeNull()
    expect(meta?.label).toMatch(/solo lectura|escribible/i)
  })

  it('mapea permission_denied como problema de despliegue', () => {
    const meta = getActionErrorMeta('permission_denied')
    expect(meta).not.toBeNull()
    expect(meta?.label).toMatch(/permiso/i)
  })

  it('mapea no_baseline_metadata como problema de datos, distinto de los de despliegue', () => {
    const deployment = getActionErrorMeta('read_only_mount')
    const data = getActionErrorMeta('no_baseline_metadata')
    expect(data).not.toBeNull()
    expect(data?.label).toMatch(/metadata|baseline/i)
    expect(data?.className).not.toBe(deployment?.className)
  })

  it('un valor desconocido cae al literal crudo en vez de ocultarse', () => {
    const meta = getActionErrorMeta('some_future_cause_v2')
    expect(meta).not.toBeNull()
    expect(meta?.label).toContain('some_future_cause_v2')
  })
})
