import { beforeEach, describe, expect, it, vi } from 'vitest'
import { act, waitFor } from '@testing-library/react'
import { renderWithProviders } from '@/test/renderWithProviders'

const { navigate } = vi.hoisted(() => ({ navigate: vi.fn() }))

vi.mock('react-router-dom', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router-dom')>()
  return { ...actual, useNavigate: () => navigate }
})

import { ProtectedRoute } from './ProtectedRoute'
import { useAuthStore } from '@/stores/auth.store'

describe('ProtectedRoute — US-03 expiración de sesión', () => {
  beforeEach(() => {
    navigate.mockReset()
    useAuthStore.setState({
      accessToken: 'header.eyJleHAiOjQxMDI0NDQ4MDB9.signature',
      user: { id: 1, username: 'admin', role: 'admin', must_change_password: false },
      isLoading: false,
    })
  })

  it('navega una sola vez a login cuando una sesión ya verificada queda sin token', async () => {
    renderWithProviders(<ProtectedRoute />, { route: '/events' })

    act(() => {
      useAuthStore.setState({ accessToken: null, user: null, isLoading: false })
    })

    await waitFor(() => expect(navigate).toHaveBeenCalledWith('/login', {
      state: expect.objectContaining({ from: expect.objectContaining({ pathname: '/events' }) }),
      replace: true,
    }))
    expect(navigate).toHaveBeenCalledTimes(1)
  })
})
