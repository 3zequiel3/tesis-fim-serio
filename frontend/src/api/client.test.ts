import { beforeEach, describe, expect, it, vi } from 'vitest'

const { apiRequest, responseUse, refreshApi } = vi.hoisted(() => ({
  apiRequest: vi.fn(),
  responseUse: vi.fn(),
  refreshApi: vi.fn(),
}))

vi.mock('axios', () => ({
  default: {
    create: () => Object.assign(apiRequest, {
      interceptors: {
        request: { use: vi.fn() },
        response: { use: responseUse },
      },
    }),
    isAxiosError: () => true,
  },
}))

vi.mock('@/api/auth', () => ({
  loginApi: vi.fn(),
  logoutApi: vi.fn(),
  refreshApi,
}))

import { useAuthStore } from '@/stores/auth.store'
import './client'

const user = {
  id: 1,
  username: 'admin',
  role: 'admin',
  must_change_password: false,
}

describe('apiClient — US-03 renovación transparente', () => {
  beforeEach(() => {
    apiRequest.mockReset()
    refreshApi.mockReset()
    useAuthStore.setState({ accessToken: 'expired-token', user, isLoading: false })
  })

  it('reintenta la petición original con el token rotado después de un 401', async () => {
    const rotated = 'rotated-access-token'
    refreshApi.mockResolvedValue({ access_token: rotated, token_type: 'bearer', user })
    apiRequest.mockResolvedValue({ data: { ok: true } })
    const rejectInterceptor = responseUse.mock.calls[0][1]
    const originalRequest = { url: '/events', headers: { Authorization: 'Bearer expired-token' } }

    await expect(rejectInterceptor({
      response: { status: 401 },
      config: originalRequest,
    })).resolves.toEqual({ data: { ok: true } })

    expect(apiRequest).toHaveBeenCalledTimes(1)
    expect(apiRequest).toHaveBeenCalledWith(originalRequest)
    expect(originalRequest.headers.Authorization).toBe(`Bearer ${rotated}`)
  })
})
