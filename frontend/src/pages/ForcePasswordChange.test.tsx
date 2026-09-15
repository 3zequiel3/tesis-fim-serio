import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithProviders } from '@/test/renderWithProviders'

// US-27 (D-2): contraseña actual + política de complejidad en el cambio
// forzado. Se mockea la capa HTTP (@/api/auth) y se monta el store real con
// un accessToken para no reimplementar la lógica de refresh.

const { changePasswordApi, refreshApi } = vi.hoisted(() => ({
  changePasswordApi: vi.fn(),
  refreshApi: vi.fn(),
}))

vi.mock('@/api/auth', () => ({
  changePasswordApi,
  refreshApi,
  loginApi: vi.fn(),
  logoutApi: vi.fn(),
}))

import { ForcePasswordChange } from './ForcePasswordChange'
import { useAuthStore } from '@/stores/auth.store'

function axiosErrorWithStatus(status: number, detail: string) {
  return Object.assign(new Error('request failed'), {
    isAxiosError: true,
    response: { status, data: { detail } },
  })
}

const FIXED_TOKEN = 'header.eyJpYXQiOjAsImV4cCI6OTk5OTk5OTk5OX0=.sig'

async function fillAndSubmit(
  user: ReturnType<typeof userEvent.setup>,
  { current = 'seed-password-1', next = 'GoodPass123x', confirm }: {
    current?: string
    next?: string
    confirm?: string
  } = {},
) {
  const currentField = screen.getByLabelText('Contraseña actual')
  const newField = screen.getByLabelText('Nueva contraseña')
  const confirmField = screen.getByLabelText('Confirmar contraseña')

  if (current) await user.type(currentField, current)
  if (next) await user.type(newField, next)
  await user.type(confirmField, confirm ?? next)

  await user.click(screen.getByRole('button', { name: /Cambiar contraseña/ }))
}

describe('ForcePasswordChange — US-27 (D-2, complejidad y contraseña actual)', () => {
  beforeEach(() => {
    changePasswordApi.mockReset()
    refreshApi.mockReset()
    useAuthStore.setState({ accessToken: FIXED_TOKEN, user: null, isLoading: false })
  })

  afterEach(() => {
    useAuthStore.getState().logout()
  })

  it('lista los requisitos del password en el formulario', () => {
    renderWithProviders(<ForcePasswordChange />, { route: '/change-password' })

    expect(screen.getByText('Mínimo 12 caracteres')).toBeInTheDocument()
    expect(screen.getByText('Al menos 1 mayúscula')).toBeInTheDocument()
    expect(screen.getByText('Al menos 1 minúscula')).toBeInTheDocument()
    expect(screen.getByText('Al menos 1 número')).toBeInTheDocument()
  })

  it('contraseña actual vacía muestra error y no llama a changePasswordApi', async () => {
    const user = userEvent.setup()
    renderWithProviders(<ForcePasswordChange />, { route: '/change-password' })

    await fillAndSubmit(user, { current: '' })

    expect(await screen.findByRole('alert')).toHaveTextContent('Ingresá tu contraseña actual.')
    expect(changePasswordApi).not.toHaveBeenCalled()
  })

  it('password nuevo sin mayúscula muestra error y no llama a changePasswordApi', async () => {
    const user = userEvent.setup()
    renderWithProviders(<ForcePasswordChange />, { route: '/change-password' })

    await fillAndSubmit(user, { next: 'lowercase123' })

    expect(await screen.findByRole('alert')).toHaveTextContent('mayúscula')
    expect(changePasswordApi).not.toHaveBeenCalled()
  })

  it('password nuevo sin minúscula muestra error y no llama a changePasswordApi', async () => {
    const user = userEvent.setup()
    renderWithProviders(<ForcePasswordChange />, { route: '/change-password' })

    await fillAndSubmit(user, { next: 'UPPERCASE123' })

    expect(await screen.findByRole('alert')).toHaveTextContent('minúscula')
    expect(changePasswordApi).not.toHaveBeenCalled()
  })

  it('password nuevo sin número muestra error y no llama a changePasswordApi', async () => {
    const user = userEvent.setup()
    renderWithProviders(<ForcePasswordChange />, { route: '/change-password' })

    await fillAndSubmit(user, { next: 'NoDigitsHereAtAll' })

    expect(await screen.findByRole('alert')).toHaveTextContent('número')
    expect(changePasswordApi).not.toHaveBeenCalled()
  })

  it('password corto muestra error y no llama a changePasswordApi', async () => {
    const user = userEvent.setup()
    renderWithProviders(<ForcePasswordChange />, { route: '/change-password' })

    await fillAndSubmit(user, { next: 'Short1x' })

    expect(await screen.findByRole('alert')).toHaveTextContent('12 caracteres')
    expect(changePasswordApi).not.toHaveBeenCalled()
  })

  it('password válido con Ñ como única mayúscula llama a changePasswordApi con current_password', async () => {
    changePasswordApi.mockResolvedValue(undefined)
    refreshApi.mockResolvedValue({
      access_token: FIXED_TOKEN,
      token_type: 'bearer',
      user: { id: 1, username: 'admin', role: 'admin', must_change_password: false },
    })
    const user = userEvent.setup()
    renderWithProviders(<ForcePasswordChange />, { route: '/change-password' })

    await fillAndSubmit(user, { next: 'Ñuevopass123' })

    await waitFor(() =>
      expect(changePasswordApi).toHaveBeenCalledWith(
        { current_password: 'seed-password-1', new_password: 'Ñuevopass123' },
        FIXED_TOKEN,
      ),
    )
  })

  it('un 401 del backend (contraseña actual incorrecta) muestra el detail recibido', async () => {
    changePasswordApi.mockRejectedValue(axiosErrorWithStatus(401, 'Incorrect current password'))
    const user = userEvent.setup()
    renderWithProviders(<ForcePasswordChange />, { route: '/change-password' })

    await fillAndSubmit(user, { current: 'wrong-current' })

    expect(await screen.findByRole('alert')).toHaveTextContent('Incorrect current password')
    expect(refreshApi).not.toHaveBeenCalled()
  })
})
