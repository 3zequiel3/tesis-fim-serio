import { beforeEach, describe, expect, it, vi } from 'vitest'
import { act, screen, waitFor } from '@testing-library/react'
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

describe('ProtectedRoute — US-01 criterio 8 (scope password_change_only)', () => {
  beforeEach(() => {
    navigate.mockReset()
  })

  it('redirige a /change-password cuando el access token trae scope=password_change_only', async () => {
    // Payload: { scope: 'password_change_only', exp: 4102444800 } en base64url.
    const scopedToken =
      'header.eyJzY29wZSI6InBhc3N3b3JkX2NoYW5nZV9vbmx5IiwiZXhwIjo0MTAyNDQ0ODAwfQ==.signature'
    useAuthStore.setState({
      accessToken: scopedToken,
      user: { id: 1, username: 'admin', role: 'admin', must_change_password: true },
      isLoading: false,
    })

    renderWithProviders(<ProtectedRoute />, { route: '/events' })

    await waitFor(() =>
      expect(navigate).toHaveBeenCalledWith('/change-password', { replace: true }),
    )
  })

  it('NO redirige cuando el scope ya está en /change-password (evita loop)', async () => {
    const scopedToken =
      'header.eyJzY29wZSI6InBhc3N3b3JkX2NoYW5nZV9vbmx5IiwiZXhwIjo0MTAyNDQ0ODAwfQ==.signature'
    useAuthStore.setState({
      accessToken: scopedToken,
      user: { id: 1, username: 'admin', role: 'admin', must_change_password: true },
      isLoading: false,
    })

    renderWithProviders(<ProtectedRoute />, { route: '/change-password' })

    // Da tiempo a que el efecto corriera; no debe haber navegado.
    await waitFor(() => expect(screen.queryByText('Verificando sesión...')).not.toBeInTheDocument())
    expect(navigate).not.toHaveBeenCalled()
  })
})
