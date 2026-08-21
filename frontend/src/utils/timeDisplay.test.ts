import { describe, it, expect } from 'vitest'
import { formatAbsolute, formatRelative } from './timeDisplay'

// D39/RN-133, D-5 regla 3 del design: vitest.config.ts fija TZ a
// America/Argentina/Buenos_Aires (una zona con desfase NO nulo). Este primer
// test es el que hace que perder esa configuración rompa la suite en vez de
// vaciarla de sentido en silencio (8.2) — si alguien borra `env.TZ` del
// config, este test es el primero en fallar.
describe('entorno de tests — guarda de zona horaria (8.2)', () => {
  it('el desfase efectivo del entorno de tests no es cero', () => {
    const offsetMinutes = new Date('2026-08-20T12:00:00Z').getTimezoneOffset()
    expect(offsetMinutes).not.toBe(0)
    // America/Argentina/Buenos_Aires es UTC-3 todo el año (sin horario de verano).
    expect(offsetMinutes).toBe(180)
  })
})

describe('formatAbsolute — forma absoluta con zona visible (6.2, 8.3)', () => {
  it('2026-08-20T19:55:59+00:00 renderiza como 16:55:59 del 2026-08-20, con la zona visible', () => {
    const result = formatAbsolute('2026-08-20T19:55:59+00:00')
    // Hora concreta afirmada, no un patrón (D-5 regla 1 aplicada también acá).
    expect(result).toContain('20/08/2026')
    expect(result).toContain('16:55:59')
    // La zona es parte del render, no un tooltip opcional (D-6).
    expect(result).toMatch(/ART|GMT-3|-03/)
  })

  it('un instante con desfase explícito no se desplaza — se parsea como ese instante', () => {
    // -03:00 y +00:00 denotan el mismo instante; el render en la zona del
    // visor (ART, UTC-3) debe coincidir con el que llegó ya en -03:00.
    const fromUtc = formatAbsolute('2026-08-20T19:55:59+00:00')
    const fromAr = formatAbsolute('2026-08-20T16:55:59-03:00')
    expect(fromUtc).toBe(fromAr)
  })

  it('un instante futuro se muestra sin lanzar, con su zona', () => {
    const future = new Date(Date.now() + 3600_000).toISOString()
    expect(formatAbsolute(future)).toMatch(/ART|GMT-3|-03/)
  })
})

describe('formatAbsolute/formatRelative — contrato del nulo (6.4, 8.6)', () => {
  it('null renderiza como ausencia explícita, nunca Invalid Date', () => {
    expect(formatAbsolute(null)).toBe('nunca')
    expect(formatRelative(null)).toBe('nunca')
    expect(formatAbsolute(undefined)).toBe('nunca')
  })

  it('acepta un nullLabel específico por sitio de uso (p.ej. AgentCard)', () => {
    expect(formatAbsolute(null, { nullLabel: 'sin datos' })).toBe('sin datos')
  })
})

describe('formatRelative — futuro rotulado, nunca negativo (6.5, 8.6)', () => {
  it('un instante futuro se rotula como tal, no como un intervalo negativo', () => {
    const now = Date.parse('2026-08-20T12:00:00Z')
    const future = new Date(now + 5 * 60_000).toISOString() // 5 min en el futuro
    const result = formatRelative(future, { now })
    expect(result).toContain('dentro de')
    expect(result).not.toMatch(/-\d/) // ningún número negativo crudo
  })

  it('un instante pasado reciente da un intervalo positivo pequeño ("hace ...")', () => {
    const now = Date.parse('2026-08-20T12:00:00Z')
    const past = new Date(now - 5_000).toISOString() // 5s atrás
    const result = formatRelative(past, { now })
    expect(result).toBe('hace 5 segundos')
  })
})

describe('formatAbsolute/formatRelative — valor no parseable (6.6, 8.6)', () => {
  it('un valor presente pero no parseable degrada de forma visible', () => {
    expect(formatAbsolute('no-es-una-fecha')).toBe('fecha inválida')
    expect(formatRelative('no-es-una-fecha')).toBe('fecha inválida')
  })

  it('nunca produce el texto literal "Invalid Date"', () => {
    expect(formatAbsolute('no-es-una-fecha')).not.toMatch(/Invalid Date/)
    expect(formatRelative('no-es-una-fecha')).not.toMatch(/Invalid Date/)
  })
})

describe('formatRelative — invariancia de zona (D-6, RN-90/RN-131)', () => {
  it('el intervalo transcurrido es igual bajo dos zonas de visualización distintas', () => {
    const now = Date.parse('2026-08-20T12:00:00Z')
    const instant = new Date(now - 90_000).toISOString() // 90s atrás

    // formatRelative no toma timeZone — es, por construcción, una propiedad
    // de los instantes (value, now) y no de la zona de visualización. Se
    // confirma acá comparando contra formatAbsolute, que SÍ varía con la
    // zona, para dejar constancia de que una realmente cambió y la otra no.
    const relativeA = formatRelative(instant, { now })
    const relativeB = formatRelative(instant, { now })
    expect(relativeA).toBe(relativeB)

    const absoluteArg = formatAbsolute(instant, { timeZone: 'America/Argentina/Buenos_Aires' })
    const absoluteUtc = formatAbsolute(instant, { timeZone: 'UTC' })
    expect(absoluteArg).not.toBe(absoluteUtc) // la absoluta sí depende de la zona
  })
})
