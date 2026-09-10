import { beforeEach, describe, expect, it, vi } from 'vitest'

const { authPost } = vi.hoisted(() => ({ authPost: vi.fn() }))

vi.mock('axios', () => ({
  default: {
    create: () => ({ post: authPost }),
  },
}))

import { refreshApi } from './auth'

const refreshResponse = {
  access_token: 'rotated-access-token',
  token_type: 'bearer',
  user: { id: 1, username: 'admin', role: 'admin', must_change_password: false },
}

describe('refreshApi — US-03 renovación single-flight del cliente', () => {
  beforeEach(() => {
    authPost.mockReset()
  })

  it('comparte una única petición de refresh entre llamadores concurrentes', async () => {
    let resolveRequest!: (value: { data: typeof refreshResponse }) => void
    authPost.mockReturnValue(new Promise((resolve) => { resolveRequest = resolve }))

    const first = refreshApi()
    const second = refreshApi()
    const third = refreshApi()

    expect(authPost).toHaveBeenCalledTimes(1)
    expect(authPost).toHaveBeenCalledWith('/auth/refresh')

    resolveRequest({ data: refreshResponse })
    await expect(Promise.all([first, second, third])).resolves.toEqual([
      refreshResponse,
      refreshResponse,
      refreshResponse,
    ])
  })

  it('libera el single-flight al terminar para permitir la próxima rotación', async () => {
    authPost.mockResolvedValue({ data: refreshResponse })

    await refreshApi()
    await refreshApi()

    expect(authPost).toHaveBeenCalledTimes(2)
  })
})
