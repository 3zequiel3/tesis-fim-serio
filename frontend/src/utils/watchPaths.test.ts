import { describe, expect, it } from 'vitest'
import { checkWatchPath, describeWatchPath, validateWatchPaths } from './watchPaths'

// Mirrors backend/tests/test_path_validation.py (D91/RN-185).
describe('checkWatchPath', () => {
  it.each([
    ['', 'empty'],
    ['   ', 'empty'],
    ['var/www', 'not_absolute'],
    ['/etc/../shadow', 'parent_segment'],
    ['/etc/a\nb', 'control_char'],
    ['/etc/a\u007fb', 'control_char'],
    ['/' + 'a'.repeat(1024), 'too_long'],
  ])('rejects %j as %s', (path, reason) => {
    expect(checkWatchPath(path)).toBe(reason)
  })

  it.each(['/', '/etc', '/etc/', '/var/www/site..bak', '/' + 'a'.repeat(1023)])('accepts %j', (path) => {
    expect(checkWatchPath(path)).toBeNull()
  })

  it('explains a rejection in Spanish', () => {
    expect(describeWatchPath('var/www')).toMatch(/absoluta/)
  })
})

describe('validateWatchPaths', () => {
  it('rejects an empty list', () => {
    expect(validateWatchPaths([])?.code).toBe('watch_paths_empty')
  })

  it('rejects more than 64 paths', () => {
    const many = Array.from({ length: 65 }, (_, i) => `/p${i}`)
    expect(validateWatchPaths(many)?.code).toBe('watch_paths_too_many')
    expect(validateWatchPaths(many.slice(0, 64))).toBeNull()
  })

  it('points at the offending entry', () => {
    expect(validateWatchPaths(['/etc', 'relative'])).toMatchObject({ code: 'watch_path_not_absolute', index: 1 })
  })

  it('treats a trailing slash as a duplicate', () => {
    expect(validateWatchPaths(['/etc', '/etc/'])).toMatchObject({ code: 'watch_path_duplicate', index: 1 })
    expect(validateWatchPaths(['/', '/etc'])).toBeNull()
  })

  it('accepts a valid list', () => {
    expect(validateWatchPaths(['/etc', '/var/www'])).toBeNull()
  })
})
