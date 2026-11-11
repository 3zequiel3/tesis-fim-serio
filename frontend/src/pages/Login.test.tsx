import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithProviders } from '@/test/renderWithProviders'
import { mockApiError } from '@/test/mockApiError'
import { queryClient } from '@/api/queryClient'
import { QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { render, act } from '@testing-library/react'

// US-01 criterios 1 y 3: formulario usuario/contraseña + error genérico ante
// credenciales inválidas, sin revelar cuál de los dos campos falló. Se monta
// el store REAL (ya cubierto en auth.store.test.ts) y sólo se mockea la capa
// HTTP (@/api/auth), igual que en auth.store.test.ts, para no reimplementar
// la lógica de login en el test.

const { loginApi } = vi.hoisted(() => ({ loginApi: vi.fn() }))

vi.mock('@/api/auth', () => ({
  loginApi,
  refreshApi: vi.fn(),
  logoutApi: vi.fn(),
}))

import { Login } from './Login'
import { useAuthStore } from '@/stores/auth.store'

function axiosErrorWithStatus(status: number) {
  return Object.assign(new Error('request failed'), {
    isAxiosError: true,
    response: { status, data: {} },
  })
}

describe('Login — US-01 criterio 1 (formulario)', () => {
  beforeEach(() => {
    useAuthStore.setState({ accessToken: null, user: null, isLoading: false })
  })

  it('presenta campos de usuario y contraseña con sus labels', () => {
    renderWithProviders(<Login />, { route: '/login' })

    expect(screen.getByLabelText('Usuario')).toBeInTheDocument()
    const passwordField = screen.getByLabelText('Contraseña')
    expect(passwordField).toBeInTheDocument()
    expect(passwordField).toHaveAttribute('type', 'password')
  })

  it('el botón de ingresar está deshabilitado hasta completar ambos campos', async () => {
    const user = userEvent.setup()
    renderWithProviders(<Login />, { route: '/login' })

    const submit = screen.getByRole('button', { name: 'Ingresar' })
    expect(submit).toBeDisabled()

    await user.type(screen.getByLabelText('Usuario'), 'admin')
    expect(submit).toBeDisabled()

    await user.type(screen.getByLabelText('Contraseña'), 'whatever')
    expect(submit).not.toBeDisabled()
  })
})

describe('Login — US-01 criterio 3 (error genérico)', () => {
  beforeEach(() => {
    loginApi.mockReset()
    useAuthStore.setState({ accessToken: null, user: null, isLoading: false })
  })

  afterEach(() => {
    // login() exitoso agenda un refresh real (setTimeout); logout() lo cancela
    // para no dejar timers pendientes entre tests.
    useAuthStore.getState().logout()
  })

  it('credenciales inválidas (401) muestran un único mensaje genérico, sin señalar qué campo falló', async () => {
    loginApi.mockRejectedValue(axiosErrorWithStatus(401))
    const user = userEvent.setup()
    renderWithProviders(<Login />, { route: '/login' })

    await user.type(screen.getByLabelText('Usuario'), 'admin')
    await user.type(screen.getByLabelText('Contraseña'), 'wrong-password')
    await user.click(screen.getByRole('button', { name: 'Ingresar' }))

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Credenciales incorrectas. Revisá tu usuario y contraseña.')
    // El criterio pide no revelar CUÁL campo es incorrecto: el mensaje no debe
    // señalar exclusivamente uno de los dos.
    expect(alert.textContent).not.toMatch(/el usuario no existe|contraseña incorrecta$/i)
  })

  it('un 429 (rate limit) muestra un mensaje distinto al de credenciales inválidas', async () => {
    loginApi.mockRejectedValue(axiosErrorWithStatus(429))
    const user = userEvent.setup()
    renderWithProviders(<Login />, { route: '/login' })

    await user.type(screen.getByLabelText('Usuario'), 'admin')
    await user.type(screen.getByLabelText('Contraseña'), 'whatever')
    await user.click(screen.getByRole('button', { name: 'Ingresar' }))

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Demasiados intentos')
  })

  it('login exitoso no muestra ningún error y limpia el store', async () => {
    loginApi.mockResolvedValue({
      access_token: 'header.eyJpYXQiOjAsImV4cCI6OTk5OTk5OTk5OX0=.sig',
      token_type: 'bearer',
      user: { id: 1, username: 'admin', role: 'admin', must_change_password: false },
    })
    const user = userEvent.setup()
    renderWithProviders(<Login />, { route: '/login' })

    await user.type(screen.getByLabelText('Usuario'), 'admin')
    await user.type(screen.getByLabelText('Contraseña'), 'correct-password')
    await user.click(screen.getByRole('button', { name: 'Ingresar' }))

    await waitFor(() => expect(useAuthStore.getState().accessToken).not.toBeNull())
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })
})


// frontend-auth: destino original, aviso por navegación, mensajes del backend
// (D90/RN-184) y bloqueo con Retry-After (D92/RN-186).
const LOGGED_IN = {
  access_token: 'header.eyJpYXQiOjAsImV4cCI6OTk5OTk5OTk5OX0=.sig',
  token_type: 'bearer',
  user: { id: 1, username: 'admin', role: 'admin', must_change_password: false },
}

function Where() {
  const location = useLocation()
  return <div data-testid="where">{location.pathname + location.search}</div>
}

function renderLoginAt(state: unknown) {
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[{ pathname: '/login', state }]}>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="*" element={<Where />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

async function submitLogin(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByLabelText('Usuario'), 'admin')
  await user.type(screen.getByLabelText('Contraseña'), 'correct-password')
  await user.click(screen.getByRole('button', { name: /Ingresar/ }))
}

describe('Login — destino, aviso y mensajes del backend', () => {
  beforeEach(() => {
    loginApi.mockReset()
    useAuthStore.setState({ accessToken: null, user: null, isLoading: false })
  })
  afterEach(() => {
    useAuthStore.getState().logout()
  })

  it('vuelve al destino original guardado en state.from', async () => {
    loginApi.mockResolvedValue(LOGGED_IN)
    renderLoginAt({ from: { pathname: '/events/42', search: '?x=1', hash: '' } })
    await submitLogin(userEvent.setup())
    expect(await screen.findByTestId('where')).toHaveTextContent('/events/42?x=1')
  })

  it.each(['//evil.example', 'https://evil.example/x', '/\\evil.example'])(
    'ignora un destino externo (%s) y va al dashboard',
    async (from) => {
      loginApi.mockResolvedValue(LOGGED_IN)
      renderLoginAt({ from })
      await submitLogin(userEvent.setup())
      expect(await screen.findByTestId('where')).toHaveTextContent(/^\/$/)
    },
  )

  it('muestra el aviso recibido en state.notice sobre el formulario', () => {
    renderLoginAt({ notice: 'Contraseña actualizada. Ingresá con la contraseña nueva.' })
    expect(screen.getByRole('status')).toHaveTextContent(
      'Contraseña actualizada. Ingresá con la contraseña nueva.',
    )
  })

  it('401 invalid_credentials muestra el message anidado de detail', async () => {
    loginApi.mockRejectedValue(
      mockApiError(401, { code: 'invalid_credentials', message: 'Usuario o contraseña incorrectos.' }),
    )
    renderLoginAt(null)
    await submitLogin(userEvent.setup())
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Usuario o contraseña incorrectos.')
    expect(alert.textContent).not.toContain('[object Object]')
  })

  it('403 account_disabled muestra el message del backend', async () => {
    loginApi.mockRejectedValue(
      mockApiError(403, { code: 'account_disabled', message: 'La cuenta está deshabilitada.' }),
    )
    renderLoginAt(null)
    await submitLogin(userEvent.setup())
    expect(await screen.findByRole('alert')).toHaveTextContent('La cuenta está deshabilitada.')
  })

  it('429 con Retry-After menciona la espera y deshabilita el envío hasta que vence', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    try {
      loginApi.mockRejectedValue(
        mockApiError(
          429,
          { code: 'login_rate_limited', message: 'Demasiados intentos.' },
          { 'retry-after': '120' },
        ),
      )
      renderLoginAt(null)
      await submitLogin(userEvent.setup({ advanceTimers: vi.advanceTimersByTime }))

      const alert = await screen.findByRole('alert')
      expect(alert).toHaveTextContent(/intentos fallidos/i)
      expect(alert).toHaveTextContent('2 minutos')
      expect(screen.getByRole('button', { name: /Reintentar en/ })).toBeDisabled()

      await act(async () => {
        await vi.advanceTimersByTimeAsync(121_000)
      })
      expect(screen.getByRole('button', { name: 'Ingresar' })).not.toBeDisabled()
    } finally {
      vi.useRealTimers()
    }
  })
})
