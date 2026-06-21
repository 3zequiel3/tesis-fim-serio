import { describe, it, expect } from 'vitest'
import { parseEventFilters, serializeEventFilters } from './eventFilters'

describe('parseEventFilters', () => {
  it('retorna defaults cuando el URLSearchParams está vacío', () => {
    const sp = new URLSearchParams()
    const result = parseEventFilters(sp)
    expect(result.status).toBeUndefined()
    expect(result.path_prefix).toBeUndefined()
    expect(result.date_from).toBeUndefined()
    expect(result.date_to).toBeUndefined()
    expect(result.include_superseded).toBeUndefined()
    expect(result.page).toBe(1)
    expect(result.page_size).toBe(50)
  })

  it('parsea multi-select status', () => {
    const sp = new URLSearchParams('status=pending&status=approved')
    const result = parseEventFilters(sp)
    expect(result.status).toEqual(['pending', 'approved'])
  })

  it('parsea include_superseded=true', () => {
    const sp = new URLSearchParams('include_superseded=true')
    const result = parseEventFilters(sp)
    expect(result.include_superseded).toBe(true)
  })

  it('include_superseded=false queda como undefined', () => {
    const sp = new URLSearchParams('include_superseded=false')
    const result = parseEventFilters(sp)
    expect(result.include_superseded).toBeUndefined()
  })

  it('parsea page, path_prefix, date_from, date_to', () => {
    const sp = new URLSearchParams(
      'page=3&path_prefix=/etc&date_from=2026-01-01T00:00:00&date_to=2026-06-01T00:00:00'
    )
    const result = parseEventFilters(sp)
    expect(result.page).toBe(3)
    expect(result.path_prefix).toBe('/etc')
    expect(result.date_from).toBe('2026-01-01T00:00:00')
    expect(result.date_to).toBe('2026-06-01T00:00:00')
  })
})

describe('serializeEventFilters', () => {
  it('genera URLSearchParams vacío con filtros default', () => {
    const sp = serializeEventFilters({ page: 1, page_size: 50 })
    expect(sp.toString()).toBe('')
  })

  it('serializa multi-select status como repeated params', () => {
    const sp = serializeEventFilters({ status: ['pending', 'rejected'] })
    expect(sp.getAll('status')).toEqual(['pending', 'rejected'])
  })

  it('serializa include_superseded=true', () => {
    const sp = serializeEventFilters({ include_superseded: true })
    expect(sp.get('include_superseded')).toBe('true')
  })

  it('omite include_superseded cuando es false/undefined', () => {
    const sp1 = serializeEventFilters({ include_superseded: false })
    expect(sp1.get('include_superseded')).toBeNull()
    const sp2 = serializeEventFilters({})
    expect(sp2.get('include_superseded')).toBeNull()
  })

  it('omite page cuando es 1 (default)', () => {
    const sp = serializeEventFilters({ page: 1 })
    expect(sp.get('page')).toBeNull()
  })

  it('incluye page cuando es mayor a 1', () => {
    const sp = serializeEventFilters({ page: 3 })
    expect(sp.get('page')).toBe('3')
  })
})

describe('round-trip parse/serialize', () => {
  it('preserva filtros complejos en ida y vuelta', () => {
    const original: URLSearchParams = new URLSearchParams(
      'status=pending&status=rejected&path_prefix=/var/log&include_superseded=true&page=2'
    )
    const parsed = parseEventFilters(original)
    const serialized = serializeEventFilters(parsed)
    const reparsed = parseEventFilters(serialized)

    expect(reparsed.status).toEqual(parsed.status)
    expect(reparsed.path_prefix).toBe(parsed.path_prefix)
    expect(reparsed.include_superseded).toBe(parsed.include_superseded)
    expect(reparsed.page).toBe(parsed.page)
  })

  it('filtros vacíos round-trip produce URLSearchParams vacío', () => {
    const sp = new URLSearchParams()
    const parsed = parseEventFilters(sp)
    const serialized = serializeEventFilters(parsed)
    expect(serialized.toString()).toBe('')
  })
})
