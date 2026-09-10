import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithProviders } from '@/test/renderWithProviders'

const { logoutApi, navigate } = vi.hoisted(() => ({
  logoutApi: vi.fn(),
  navigate: vi.fn(),
}))

vi.mock('react-router-dom', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router-dom')>()
  return { ...actual, useNavigate: () => navigate }
})

vi.mock('@/api/auth', () => ({
  loginApi: vi.fn(),
  refreshApi: vi.fn(),
  logoutApi,
}))

import { Navbar } from './Navbar'
import { useAuthStore } from '@/stores/auth.store'

describe('Navbar — US-02 logout del cliente', () => {
  beforeEach(() => {
    logoutApi.mockReset()
    logoutApi.mockResolvedValue(undefined)
    navigate.mockReset()
    useAuthStore.setState({
      accessToken: 'access-token-in-memory',
      user: { id: 7, username: 'admin', role: 'admin', must_change_password: false },
      isLoading: false,
    })
  })

  afterEach(() => {
    useAuthStore.setState({ accessToken: null, user: null, isLoading: false })
  })

  it('muestra el botón y al usarlo limpia el token y el usuario, solicita logout y navega a /login con replace', async () => {
    const user = userEvent.setup()
    renderWithProviders(<Navbar />, { route: '/events' })

    await user.click(screen.getByRole('button', { name: 'Cerrar sesión' }))

    expect(useAuthStore.getState().accessToken).toBeNull()
    expect(useAuthStore.getState().user).toBeNull()
    expect(navigate).toHaveBeenCalledTimes(1)
    expect(navigate).toHaveBeenCalledWith('/login', { replace: true })
    await waitFor(() => expect(logoutApi).toHaveBeenCalledTimes(1))
  })
})
