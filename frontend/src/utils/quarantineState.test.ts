import { describe, it, expect } from 'vitest'
import { getQuarantineStateMeta } from './quarantineState'
import { getAckStatusMeta } from './ackStatus'

describe('getQuarantineStateMeta', () => {
  it('retorna null para none, ausente y valores desconocidos', () => {
    expect(getQuarantineStateMeta('none')).toBeNull()
    expect(getQuarantineStateMeta(undefined)).toBeNull()
    expect(getQuarantineStateMeta(null)).toBeNull()
    // Un backend más nuevo puede enviar un valor que este cliente no conoce.
    expect(getQuarantineStateMeta('archived' as never)).toBeNull()
  })

  it('usa el valor en minúsculas como etiqueta (RN-71)', () => {
    expect(getQuarantineStateMeta('quarantined')?.label).toBe('quarantined')
    expect(getQuarantineStateMeta('released')?.label).toBe('released')
    expect(getQuarantineStateMeta('discarded')?.label).toBe('discarded')
  })

  it('tiene un estilo distinto del badge de ejecución (no es un estado del evento)', () => {
    const quarantined = getQuarantineStateMeta('quarantined')
    for (const ack of ['pending', 'acked', 'failed', 'timeout'] as const) {
      expect(quarantined?.className).not.toBe(getAckStatusMeta(ack)?.className)
    }
    expect(getQuarantineStateMeta('quarantined')?.className).not.toBe(
      getQuarantineStateMeta('released')?.className,
    )
  })
})
