import { describe, expect, it } from 'vitest'
import { formatExe, formatPid, formatUid, processContextLabel } from './process'

describe('process context (D93/RN-187)', () => {
  it('shows pid 0 and null as «desconocido»', () => {
    expect(formatPid(0)).toBe('desconocido')
    expect(formatPid(null)).toBe('desconocido')
    expect(formatPid(4242)).toBe('4242')
  })

  it('shows a null, empty or "?" executable as «desconocido»', () => {
    expect(formatExe(null)).toBe('desconocido')
    expect(formatExe('?')).toBe('desconocido')
    expect(formatExe('')).toBe('desconocido')
    expect(formatExe('/usr/bin/vim')).toBe('/usr/bin/vim')
  })

  it('keeps uid 0 as a real value (root)', () => {
    expect(formatUid(0)).toBe('0')
    expect(formatUid(null)).toBeNull()
  })

  it('labels pid 0 with a null exe as unknown in the table', () => {
    const label = processContextLabel({ process_pid: 0, process_uid: 0, process_exe: null })
    expect(label).toBe('desconocido (pid desconocido, uid 0)')
    expect(label).not.toContain('?')
  })

  it('omits the label entirely when the three fields are null', () => {
    expect(processContextLabel({ process_pid: null, process_uid: null, process_exe: null })).toBeNull()
  })
})
