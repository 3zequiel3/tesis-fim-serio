import { describe, it, expect } from 'vitest'
import { getDiscardedEventsMeta } from './discardedEvents'

describe('getDiscardedEventsMeta', () => {
  it('trata null como desconocido, no como cero', () => {
    const meta = getDiscardedEventsMeta(null)
    expect(meta.state).toBe('unknown')
    expect(meta.label).not.toBe('0')
  })

  it('trata undefined como desconocido, no como cero', () => {
    const meta = getDiscardedEventsMeta(undefined)
    expect(meta.state).toBe('unknown')
    expect(meta.label).not.toBe('0')
  })

  it('cero se muestra como estado sano, distinto de desconocido', () => {
    const meta = getDiscardedEventsMeta(0)
    expect(meta.state).toBe('zero')
    expect(meta.label).toBe('0')
  })

  it('un conteo positivo se presenta como anomalía', () => {
    const meta = getDiscardedEventsMeta(4)
    expect(meta.state).toBe('positive')
    expect(meta.label).toBe('4')
    expect(meta.className).toContain('red')
  })

  it('el estado positivo usa una clase visualmente distinta del estado sano', () => {
    const zero = getDiscardedEventsMeta(0)
    const positive = getDiscardedEventsMeta(3)
    expect(positive.className).not.toBe(zero.className)
  })

  it('nunca lanza ante valores inesperados', () => {
    expect(() => getDiscardedEventsMeta(Number.NaN)).not.toThrow()
    expect(() => getDiscardedEventsMeta(-1)).not.toThrow()
  })

  it('cubre los tres estados con resultados distintos', () => {
    const unknown = getDiscardedEventsMeta(undefined)
    const zero = getDiscardedEventsMeta(0)
    const positive = getDiscardedEventsMeta(1)
    const states = new Set([unknown.state, zero.state, positive.state])
    expect(states.size).toBe(3)
  })
})
