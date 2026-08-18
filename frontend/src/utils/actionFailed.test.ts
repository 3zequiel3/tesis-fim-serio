import { describe, it, expect } from 'vitest'
import { getActionFailedMeta } from './actionFailed'

describe('getActionFailedMeta', () => {
  it('retorna null cuando action_failed es false', () => {
    expect(getActionFailedMeta(false)).toBeNull()
  })

  it('retorna label y clase cuando action_failed es true', () => {
    const meta = getActionFailedMeta(true)
    expect(meta).not.toBeNull()
    expect(meta?.label).toMatch(/remediaci[oó]n fallida/i)
    expect(meta?.className).toContain('red')
  })
})
