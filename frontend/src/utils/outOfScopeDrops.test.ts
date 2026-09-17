import { describe, it, expect } from 'vitest'
import { getOutOfScopeDropsMeta } from './outOfScopeDrops'
import { getDiscardedEventsMeta } from './discardedEvents'

describe('getOutOfScopeDropsMeta', () => {
  it('trata null como desconocido, no como cero', () => {
    const meta = getOutOfScopeDropsMeta(null)
    expect(meta.state).toBe('unknown')
    expect(meta.label).not.toBe('0')
  })

  it('trata undefined como desconocido, no como cero', () => {
    const meta = getOutOfScopeDropsMeta(undefined)
    expect(meta.state).toBe('unknown')
    expect(meta.label).not.toBe('0')
  })

  it('cero se muestra como estado propio, distinto de desconocido', () => {
    const meta = getOutOfScopeDropsMeta(0)
    expect(meta.state).toBe('zero')
    expect(meta.label).toBe('0')
  })

  it('un conteo positivo se presenta como informativo, no como anomalía', () => {
    const meta = getOutOfScopeDropsMeta(2748492)
    expect(meta.state).toBe('positive')
    expect(meta.label).toBe('2748492')
  })

  it('cubre los tres estados con resultados distintos', () => {
    const unknown = getOutOfScopeDropsMeta(undefined)
    const zero = getOutOfScopeDropsMeta(0)
    const positive = getOutOfScopeDropsMeta(1)
    const states = new Set([unknown.state, zero.state, positive.state])
    expect(states.size).toBe(3)
  })

  it('nunca lanza ante valores inesperados', () => {
    expect(() => getOutOfScopeDropsMeta(Number.NaN)).not.toThrow()
    expect(() => getOutOfScopeDropsMeta(-1)).not.toThrow()
  })

  // D-8 del design: el positivo NUNCA usa la paleta de alarma (roja/ámbar),
  // a diferencia de getDiscardedEventsMeta. Este test es el que impide que
  // un futuro cambio de estilo convierta el contador en un indicador rojo
  // en silencio.
  it('ningún estado usa la paleta de alarma (rojo/ámbar), ni siquiera el positivo', () => {
    const zero = getOutOfScopeDropsMeta(0)
    const positive = getOutOfScopeDropsMeta(2748492)
    const unknown = getOutOfScopeDropsMeta(null)
    for (const meta of [zero, positive, unknown]) {
      expect(meta.className).not.toContain('red')
      expect(meta.className).not.toContain('amber')
      expect(meta.className).not.toContain('yellow')
    }
  })

  it('el título del estado positivo explica que el descarte es esperado y evidencia del filtro', () => {
    const meta = getOutOfScopeDropsMeta(100)
    expect(meta.title).toMatch(/esperado/i)
    expect(meta.title).toMatch(/filtro de scope/i)
  })

  it('el título del estado desconocido distingue "nunca reportó" de cero', () => {
    const meta = getOutOfScopeDropsMeta(undefined)
    expect(meta.title).toMatch(/no reportó/i)
  })

  it('es independiente del mapper de descartes locales: mismo valor positivo, tratamiento distinto', () => {
    const outOfScope = getOutOfScopeDropsMeta(5)
    const discarded = getDiscardedEventsMeta(5)
    expect(outOfScope.className).not.toBe(discarded.className)
    expect(discarded.className).toContain('red')
    expect(outOfScope.className).not.toContain('red')
  })
})
