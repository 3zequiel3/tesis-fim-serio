import { describe, it, expect } from 'vitest'
import { getSeverityMeta } from './severity'

describe('getSeverityMeta', () => {
  it('cada uno de los cuatro niveles conocidos resuelve un tratamiento distinto', () => {
    const levels = ['critical', 'high', 'medium', 'low'] as const
    const metas = levels.map((l) => getSeverityMeta(l))

    const textClasses = new Set(metas.map((m) => m.textClass))
    const bandClasses = new Set(metas.map((m) => m.bandClass))

    expect(textClasses.size).toBe(4)
    expect(bandClasses.size).toBe(4)
  })

  it('las clases de texto son idénticas a las que las tres pantallas migradas producían antes (Alerts.tsx:29-32)', () => {
    expect(getSeverityMeta('critical').textClass).toBe('text-red-400')
    expect(getSeverityMeta('high').textClass).toBe('text-orange-400')
    expect(getSeverityMeta('medium').textClass).toBe('text-yellow-400')
    expect(getSeverityMeta('low').textClass).toBe('text-blue-400')
  })

  it('un valor fuera de los cuatro niveles degrada a un tratamiento neutro en vez de lanzar', () => {
    expect(() => getSeverityMeta('not-a-severity')).not.toThrow()
    const meta = getSeverityMeta('not-a-severity')
    expect(meta.textClass).not.toBe('')
    expect(meta.bandClass).not.toBe('')
  })

  it('null/undefined también degradan al tratamiento neutro', () => {
    expect(getSeverityMeta(null)).toEqual(getSeverityMeta('not-a-severity'))
    expect(getSeverityMeta(undefined)).toEqual(getSeverityMeta('not-a-severity'))
  })

  it('la precedencia ordena los niveles como el dominio lo hace: critical > high > medium > low', () => {
    const levels = ['low', 'critical', 'medium', 'high']
    const sorted = [...levels].sort((a, b) => getSeverityMeta(b).rank - getSeverityMeta(a).rank)
    expect(sorted).toEqual(['critical', 'high', 'medium', 'low'])
  })
})
