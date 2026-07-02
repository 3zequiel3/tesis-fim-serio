import { describe, it, expect } from 'vitest'
import { getAckStatusMeta } from './ackStatus'

describe('getAckStatusMeta', () => {
  it('retorna null cuando no hay ack_status (sin comando confirmable)', () => {
    expect(getAckStatusMeta(null)).toBeNull()
    expect(getAckStatusMeta(undefined)).toBeNull()
  })

  it('retorna label y clase para pending', () => {
    const meta = getAckStatusMeta('pending')
    expect(meta).not.toBeNull()
    expect(meta?.label).toMatch(/pendiente/i)
  })

  it('retorna label y clase distintos para acked, failed y timeout', () => {
    const acked = getAckStatusMeta('acked')
    const failed = getAckStatusMeta('failed')
    const timeout = getAckStatusMeta('timeout')

    expect(acked?.className).not.toBe(failed?.className)
    expect(failed?.className).not.toBe(timeout?.className)
    expect(acked?.label).toMatch(/confirmada/i)
    expect(failed?.label).toMatch(/falló/i)
    expect(timeout?.label).toMatch(/vencida/i)
  })
})
