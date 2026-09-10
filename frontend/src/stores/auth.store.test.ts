import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const { refreshApi, logoutApi } = vi.hoisted(() => ({
  refreshApi: vi.fn(),
  logoutApi: vi.fn(),
}))

vi.mock('@/api/auth', () => ({
  loginApi: vi.fn(),
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

function tokenExpiringAt(epochSeconds: number): string {
  const payload = btoa(JSON.stringify({ exp: epochSeconds }))
    .replaceAll('+', '-')
    .replaceAll('/', '_')
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
    refreshApi.mockResolvedValue({
      access_token: tokenExpiringAt(expiresAt + 15 * 60),
      token_type: 'bearer',
      user,
    })

    useAuthStore.getState().setToken(tokenExpiringAt(expiresAt), user)

    await vi.advanceTimersByTimeAsync(4 * 60 * 1000 - 1)
    expect(refreshApi).not.toHaveBeenCalled()

    await vi.advanceTimersByTimeAsync(1)

    expect(refreshApi).toHaveBeenCalledTimes(1)
    expect(useAuthStore.getState().accessToken).toBe(tokenExpiringAt(expiresAt + 15 * 60))
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

  it('un token ilegible no dispara refresh basado en claims no verificadas', async () => {
    useAuthStore.getState().setToken('not-a-jwt', user)

    await vi.runAllTimersAsync()

    expect(refreshApi).not.toHaveBeenCalled()
  })
})
