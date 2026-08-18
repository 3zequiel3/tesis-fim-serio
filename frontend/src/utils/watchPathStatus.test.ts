import { describe, it, expect } from 'vitest'
import { getWatchPathStatusMeta } from './watchPathStatus'

describe('getWatchPathStatusMeta', () => {
  it('retorna null cuando no hay dato reportado (agente viejo o sin heartbeat)', () => {
    expect(getWatchPathStatusMeta(undefined)).toBeNull()
  })

  it('retorna null para writable — sin indicador alarmante', () => {
    expect(getWatchPathStatusMeta('writable')).toBeNull()
  })

  it('marca read_only_mount como solo-detección', () => {
    const meta = getWatchPathStatusMeta('read_only_mount')
    expect(meta).not.toBeNull()
    expect(meta?.title).toMatch(/solo lectura/i)
  })

  it('marca permission_denied como solo-detección', () => {
    const meta = getWatchPathStatusMeta('permission_denied')
    expect(meta).not.toBeNull()
    expect(meta?.title).toMatch(/permiso/i)
  })

  it('distingue missing de un problema de permisos', () => {
    const missing = getWatchPathStatusMeta('missing')
    const denied = getWatchPathStatusMeta('permission_denied')
    expect(missing).not.toBeNull()
    expect(missing?.label).not.toBe(denied?.label)
  })

  it('un valor desconocido cae al literal crudo en vez de ocultarse', () => {
    const meta = getWatchPathStatusMeta('some_future_state')
    expect(meta).not.toBeNull()
    expect(meta?.label).toBe('some_future_state')
  })
})
