import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithProviders } from '@/test/renderWithProviders'
import { mockApiError } from '@/test/mockApiError'
import { queryClient } from '@/api/queryClient'
import { QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { render } from '@testing-library/react'

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


// D89/RN-183 + D90/RN-184: el backend ya revocó la sesión al cambiar la
// contraseña. Los mocks usan la forma REAL {"detail": {code, message}}.
function LoginProbe() {
  const location = useLocation()
  const notice = (location.state as { notice?: string } | null)?.notice
  return <div>pantalla de login: {notice}</div>
}

function renderFlow() {
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={['/change-password']}>
        <Routes>
          <Route path="/change-password" element={<ForcePasswordChange />} />
          <Route path="/login" element={<LoginProbe />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('ForcePasswordChange — B1 el cambio exitoso termina la sesión (D89/RN-183)', () => {
  beforeEach(() => {
    changePasswordApi.mockReset()
    refreshApi.mockReset()
    queryClient.clear()
    useAuthStore.setState({
      accessToken: FIXED_TOKEN,
      user: { id: 1, username: 'admin', role: 'admin', must_change_password: true },
      isLoading: false,
    })
  })

  it('no envía POST /auth/refresh: vacía el store y la caché y llega a /login con el aviso', async () => {
    changePasswordApi.mockResolvedValue(undefined)
    queryClient.setQueryData(['events'], { items: [] })
    const user = userEvent.setup()
    renderFlow()

    await fillAndSubmit(user)

    expect(
      await screen.findByText(/Contraseña actualizada\. Ingresá con la contraseña nueva\./),
    ).toBeInTheDocument()
    expect(refreshApi).not.toHaveBeenCalled()
    expect(useAuthStore.getState().accessToken).toBeNull()
    expect(useAuthStore.getState().user).toBeNull()
    expect(queryClient.getQueryCache().getAll()).toHaveLength(0)
  })

  it('rechaza sin enviar una contraseña nueva igual a la actual', async () => {
    const user = userEvent.setup()
    renderFlow()

    await fillAndSubmit(user, { current: 'SamePass123xx', next: 'SamePass123xx' })

    expect(await screen.findByRole('alert')).toHaveTextContent('distinta de la actual')
    expect(changePasswordApi).not.toHaveBeenCalled()
  })

  it('401 current_password_invalid muestra el message del backend sin navegar', async () => {
    changePasswordApi.mockRejectedValue(
      mockApiError(401, { code: 'current_password_invalid', message: 'La contraseña actual es incorrecta.' }),
    )
    const user = userEvent.setup()
    renderFlow()

    await fillAndSubmit(user, { current: 'wrong-current' })

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('La contraseña actual es incorrecta.')
    expect(alert.textContent).not.toContain('[object Object]')
    expect(screen.queryByText(/pantalla de login/)).toBeNull()
    expect(useAuthStore.getState().accessToken).toBe(FIXED_TOKEN)
  })

  it('422 password_reuse muestra el message del backend sin navegar', async () => {
    changePasswordApi.mockRejectedValue(
      mockApiError(422, { code: 'password_reuse', message: 'No podés reutilizar una contraseña anterior.' }),
    )
    const user = userEvent.setup()
    renderFlow()

    await fillAndSubmit(user)

    expect(await screen.findByRole('alert')).toHaveTextContent('No podés reutilizar una contraseña anterior.')
    expect(screen.queryByText(/pantalla de login/)).toBeNull()
  })

  it('deshabilita el envío mientras la request está en curso', async () => {
    let resolve!: () => void
    changePasswordApi.mockReturnValue(new Promise<void>((r) => (resolve = r)))
    const user = userEvent.setup()
    renderFlow()

    await fillAndSubmit(user)

    expect(screen.getByRole('button', { name: /Guardando/ })).toBeDisabled()
    resolve()
    await screen.findByText(/pantalla de login/)
  })
})
