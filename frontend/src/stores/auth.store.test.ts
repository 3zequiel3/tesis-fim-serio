import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const { refreshApi, logoutApi, loginApi } = vi.hoisted(() => ({
  refreshApi: vi.fn(),
  logoutApi: vi.fn(),
  loginApi: vi.fn(),
}))

vi.mock('@/api/auth', () => ({
  loginApi,
  refreshApi,
  logoutApi,
}))

import { useAuthStore } from './auth.store'

const user = {
  id: 1,
  username: 'admin',
  role: 'admin',
  must_change_password: false,
}

function tokenExpiringAt(epochSeconds: number, issuedAt = Math.floor(Date.now() / 1000)): string {
  const payload = btoa(JSON.stringify({ iat: issuedAt, exp: epochSeconds }))
    .replace(/\+/g, '-')
    .replace(/\//g, '_')
    .replace(/=+$/, '')
  return `header.${payload}.signature`
}

describe('auth store — US-03 refresh anticipado', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-09-10T12:00:00Z'))
    refreshApi.mockReset()
    logoutApi.mockReset()
    logoutApi.mockResolvedValue(undefined)
    useAuthStore.getState().logout()
    logoutApi.mockClear()
  })

  afterEach(() => {
    useAuthStore.getState().logout()
    vi.useRealTimers()
  })

  it('renueva una vez sesenta segundos antes de expirar y reemplaza el token en memoria', async () => {
    const expiresAt = Math.floor(Date.now() / 1000) + 5 * 60
    const nextToken = tokenExpiringAt(expiresAt + 15 * 60)
    refreshApi.mockResolvedValue({
      access_token: nextToken,
      token_type: 'bearer',
      user,
    })

    useAuthStore.getState().setToken(tokenExpiringAt(expiresAt), user)

    await vi.advanceTimersByTimeAsync(4 * 60 * 1000 - 1)
    expect(refreshApi).not.toHaveBeenCalled()

    await vi.advanceTimersByTimeAsync(1)

    expect(refreshApi).toHaveBeenCalledTimes(1)
    expect(useAuthStore.getState().accessToken).toBe(nextToken)
  })

  it('si el refresh anticipado falla limpia la sesión local', async () => {
    const expiresAt = Math.floor(Date.now() / 1000) + 2 * 60
    refreshApi.mockRejectedValue(new Error('refresh revoked'))

    useAuthStore.getState().setToken(tokenExpiringAt(expiresAt), user)
    await vi.advanceTimersByTimeAsync(60 * 1000)

    expect(refreshApi).toHaveBeenCalledTimes(1)
    expect(useAuthStore.getState().accessToken).toBeNull()
    expect(useAuthStore.getState().user).toBeNull()
  })

  it('agenda desde la duración exp-iat y no entra en loop cuando el reloj cliente está adelantado', async () => {
    const issuerNow = Math.floor(Date.parse('2026-09-10T12:00:00Z') / 1000)
    vi.setSystemTime(new Date('2026-09-10T20:00:00Z'))
    refreshApi.mockResolvedValue({
      access_token: tokenExpiringAt(issuerNow + 16 * 60, issuerNow + 60),
      token_type: 'bearer',
      user,
    })

    useAuthStore.getState().setToken(tokenExpiringAt(issuerNow + 15 * 60, issuerNow), user)

    await vi.advanceTimersByTimeAsync(1)
    expect(refreshApi).not.toHaveBeenCalled()
    await vi.advanceTimersByTimeAsync(14 * 60 * 1000 - 1)
    expect(refreshApi).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(1_000)
    expect(refreshApi).toHaveBeenCalledTimes(1)
  })

  it('un token ilegible no dispara refresh basado en claims no verificadas', async () => {
    useAuthStore.getState().setToken('not-a-jwt', user)

    await vi.runAllTimersAsync()

    expect(refreshApi).not.toHaveBeenCalled()
  })
})

describe('auth store — US-01 access token nunca en storage persistente (W9)', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-09-10T12:00:00Z'))
    loginApi.mockReset()
    useAuthStore.getState().logout()
  })

  afterEach(() => {
    useAuthStore.getState().logout()
    vi.useRealTimers()
  })

  it('login() nunca escribe en localStorage ni sessionStorage (spy en Storage.prototype.setItem)', async () => {
    // Storage.prototype es compartido por localStorage y sessionStorage en
    // jsdom: un único spy cubre ambos storages sin instanciar cada uno.
    const setItemSpy = vi.spyOn(Storage.prototype, 'setItem')
    const expiresAt = Math.floor(Date.now() / 1000) + 15 * 60
    loginApi.mockResolvedValue({
      access_token: tokenExpiringAt(expiresAt),
      token_type: 'bearer',
      user,
    })

    await useAuthStore.getState().login({ username: 'admin', password: 'AdminPassword123!' })

    expect(useAuthStore.getState().accessToken).not.toBeNull()
    expect(setItemSpy).not.toHaveBeenCalled()
    setItemSpy.mockRestore()
  })
})
