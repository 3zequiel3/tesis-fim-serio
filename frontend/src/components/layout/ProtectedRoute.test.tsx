import { useState } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, fireEvent, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { QueryClientProvider } from '@tanstack/react-query'
import { render } from '@testing-library/react'
import { renderWithProviders } from '@/test/renderWithProviders'

const { navigate, refreshApi } = vi.hoisted(() => ({ navigate: vi.fn(), refreshApi: vi.fn() }))

vi.mock('@/api/auth', () => ({ loginApi: vi.fn(), refreshApi, logoutApi: vi.fn() }))

vi.mock('react-router-dom', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router-dom')>()
  return { ...actual, useNavigate: () => navigate }
})

import { ProtectedRoute } from './ProtectedRoute'
import { useAuthStore } from '@/stores/auth.store'
import { queryClient } from '@/api/queryClient'

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


// Payload { scope: 'password_change_only', exp: 4102444800 } en base64url.
const SCOPED_TOKEN =
  'header.eyJzY29wZSI6InBhc3N3b3JkX2NoYW5nZV9vbmx5IiwiZXhwIjo0MTAyNDQ0ODAwfQ==.signature'

function LocationProbe() {
  const location = useLocation()
  return <div data-testid="location">{location.pathname}</div>
}

describe('ProtectedRoute — US-01 criterio 8 (scope password_change_only, D16)', () => {
  beforeEach(() => {
    navigate.mockReset()
    useAuthStore.setState({
      accessToken: SCOPED_TOKEN,
      user: { id: 1, username: 'admin', role: 'admin', must_change_password: true },
      isLoading: false,
    })
  })

  function renderAt(route: string, onPageMount: () => void) {
    function Page() {
      // Stands for any page: it would fire its queries on mount.
      onPageMount()
      return <div>página protegida</div>
    }
    return render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={[route]}>
          <Routes>
            <Route element={<ProtectedRoute />}>
              <Route path="/events" element={<Page />} />
              <Route path="/change-password" element={<Page />} />
            </Route>
          </Routes>
          <LocationProbe />
        </MemoryRouter>
      </QueryClientProvider>,
    )
  }

  it('no monta la página protegida ni una vez durante la redirección', () => {
    const mounted = vi.fn()
    function EventsPage() {
      mounted()
      return null
    }
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={['/events']}>
          <Routes>
            <Route element={<ProtectedRoute />}>
              <Route path="/events" element={<EventsPage />} />
            </Route>
            <Route path="/change-password" element={<div>cambio de contraseña</div>} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    )
    expect(screen.getByText('cambio de contraseña')).toBeInTheDocument()
    expect(mounted).not.toHaveBeenCalled()
  })

  it('NO redirige cuando el scope ya está en /change-password (evita loop)', () => {
    const mounted = vi.fn()
    renderAt('/change-password', mounted)
    expect(screen.getByText('página protegida')).toBeInTheDocument()
    expect(screen.getByTestId('location')).toHaveTextContent('/change-password')
  })
})

function tokenWithLifetime(seconds: number): string {
  const iat = Math.floor(Date.now() / 1000)
  const payload = btoa(JSON.stringify({ iat, exp: iat + seconds }))
    .replace(/\+/g, '-')
    .replace(/\//g, '_')
    .replace(/=+$/, '')
  return `header.${payload}.signature`
}

describe('ProtectedRoute — B4 renovación proactiva en segundo plano', () => {
  const adminUser = { id: 1, username: 'admin', role: 'admin', must_change_password: false }

  beforeEach(() => {
    vi.useFakeTimers()
    refreshApi.mockReset()
    navigate.mockReset()
  })

  afterEach(() => {
    useAuthStore.getState().endSession('logout')
    vi.useRealTimers()
  })

  function Page() {
    const [open, setOpen] = useState(false)
    return (
      <div>
        <button onClick={() => setOpen(true)}>Abrir modal</button>
        {open && <div role="dialog">Rechazar evento</div>}
      </div>
    )
  }

  it('la renovación proactiva no desmonta la página: el modal abierto sigue abierto y nunca aparece la pantalla de carga', async () => {
    let resolveRefresh!: (v: unknown) => void
    refreshApi.mockReturnValue(new Promise((r) => (resolveRefresh = r)))
    useAuthStore.getState().setToken(tokenWithLifetime(5 * 60), adminUser)

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={['/events/7']}>
          <Routes>
            <Route element={<ProtectedRoute />}>
              <Route path="/events/:id" element={<Page />} />
            </Route>
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    )
    fireEvent.click(screen.getByRole('button', { name: 'Abrir modal' }))
    expect(screen.getByRole('dialog')).toBeInTheDocument()

    // Fires the scheduled renewal (5 min lifetime, 60 s early).
    await act(async () => {
      await vi.advanceTimersByTimeAsync(4 * 60 * 1000)
    })
    expect(refreshApi).toHaveBeenCalledTimes(1)
    // The renewal is in flight right now.
    expect(screen.queryByText('Verificando sesión...')).toBeNull()
    expect(screen.getByRole('dialog')).toBeInTheDocument()

    await act(async () => {
      resolveRefresh({ access_token: tokenWithLifetime(15 * 60), token_type: 'bearer', user: adminUser })
      await Promise.resolve()
    })
    expect(screen.queryByText('Verificando sesión...')).toBeNull()
    expect(screen.getByRole('dialog')).toBeInTheDocument()
  })

  it('una renovación en segundo plano rechazada vacía store y caché y lleva a /login con el aviso de sesión vencida', async () => {
    refreshApi.mockRejectedValue(new Error('refresh revoked'))
    useAuthStore.getState().setToken(tokenWithLifetime(2 * 60), adminUser)
    queryClient.setQueryData(['events'], { items: [1] })

    renderWithProviders(<ProtectedRoute />, { route: '/events/7' })
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60 * 1000)
    })

    expect(useAuthStore.getState().accessToken).toBeNull()
    expect(queryClient.getQueryCache().getAll()).toHaveLength(0)
    expect(navigate).toHaveBeenCalledWith('/login', {
      state: expect.objectContaining({
        from: expect.objectContaining({ pathname: '/events/7' }),
        notice: 'Tu sesión venció. Ingresá de nuevo.',
      }),
      replace: true,
    })
  })
})
