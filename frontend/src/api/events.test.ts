import { describe, it, expect, vi, beforeEach } from 'vitest'

// D39/RN-133, D-4 del design: la conversión de hora local a UTC ocurre al
// construir la petición HTTP (api/events.ts), NO al escribir la URL
// (eventFilters.ts no se toca — ver eventFilters.test.ts). Este es el único
// punto de conversión y por lo tanto el único lugar donde va este test
// (frontend-events spec, 7.1/8.7).

const { apiGet } = vi.hoisted(() => ({ apiGet: vi.fn() }))

vi.mock('@/api/client', () => ({
  apiClient: { get: (...args: unknown[]) => apiGet(...args) },
  default: { get: (...args: unknown[]) => apiGet(...args) },
}))

import { getEvents } from './events'

describe('getEvents — conversión de filtros de fecha local a UTC (8.7)', () => {
  beforeEach(() => {
    apiGet.mockReset()
    apiGet.mockResolvedValue({ data: { total: 0, page: 1, page_size: 50, items: [] } })
  })

  it('un rango tipeado en hora local (America/Argentina/Buenos_Aires, UTC-3) produce instantes UTC en la petición', async () => {
    await getEvents({ date_from: '2026-08-20T16:55', date_to: '2026-08-20T20:55' })

    expect(apiGet).toHaveBeenCalledTimes(1)
    const config = apiGet.mock.calls[0][1] as {
      paramsSerializer: (p: Record<string, unknown>) => string
    }
    const qs = config.paramsSerializer({
      date_from: '2026-08-20T16:55',
      date_to: '2026-08-20T20:55',
    })
    const sp = new URLSearchParams(qs)

    // 16:55 y 20:55 hora de Argentina (UTC-3) son 19:55 y 23:55 UTC.
    expect(sp.get('date_from')).toBe('2026-08-20T19:55:00.000Z')
    expect(sp.get('date_to')).toBe('2026-08-20T23:55:00.000Z')
  })

  it('un filtro de fecha ausente no agrega date_from/date_to a la query string (7.4)', async () => {
    await getEvents({ path_prefix: '/etc' })

    const config = apiGet.mock.calls[0][1] as {
      paramsSerializer: (p: Record<string, unknown>) => string
    }
    const qs = config.paramsSerializer({ path_prefix: '/etc' })
    const sp = new URLSearchParams(qs)

    expect(sp.has('date_from')).toBe(false)
    expect(sp.has('date_to')).toBe(false)
  })
})
