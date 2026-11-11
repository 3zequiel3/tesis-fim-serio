import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithProviders } from '@/test/renderWithProviders'
import { mockApiError } from '@/test/mockApiError'
import { signInAs, signOut } from '@/test/signIn'
import { Agents } from './Agents'
import type { Agent } from '@/api/agents'

// US-22: criterio "Se muestra confirmación de que la solicitud fue enviada al
// agente" sin aserción hasta ahora. Mismo mock de @/api/client que
// Events.test.tsx (D-7 del design) y mock de sonner (la librería que importa
// Agents.tsx), igual que EventDetail.test.tsx.

const { apiGet, apiPost, toastSuccess, toastError } = vi.hoisted(() => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  toastSuccess: vi.fn(),
  toastError: vi.fn(),
}))

vi.mock('@/api/client', () => ({
  apiClient: {
    get: (...args: unknown[]) => apiGet(...args),
    post: (...args: unknown[]) => apiPost(...args),
  },
  default: {
    get: (...args: unknown[]) => apiGet(...args),
    post: (...args: unknown[]) => apiPost(...args),
  },
}))

vi.mock('sonner', () => ({
  toast: { success: toastSuccess, error: toastError },
}))

function makeAgent(overrides: Partial<Agent> = {}): Agent {
  return {
    agent_id: 'agent-01',
    status: 'online',
    watch_paths: ['/etc'],
    queue_pressure: 0.1,
    last_heartbeat: new Date().toISOString(),
    ruleset_version_applied: 1,
    ...overrides,
  }
}

// D93/RN-187: Editar and Rescan are shown only to `admin`.
beforeEach(() => signInAs('admin'))
afterEach(() => signOut())

describe('Agents — confirmación visual del rescan (US-22)', () => {
  beforeEach(() => {
    apiGet.mockReset()
    apiPost.mockReset()
    toastSuccess.mockReset()
    toastError.mockReset()
    apiGet.mockResolvedValue({ data: { items: [makeAgent()], total: 1 } })
  })

  it('rescan sin conflicto muestra confirmación de que la solicitud fue enviada al agente', async () => {
    const user = userEvent.setup()
    apiPost.mockResolvedValueOnce({ data: undefined })

    renderWithProviders(<Agents />, { route: '/agents' })

    const rescanButton = await screen.findByRole('button', { name: 'Rescan' })
    await user.click(rescanButton)

    await waitFor(() => expect(toastSuccess).toHaveBeenCalledWith('Rescan iniciado'))
  })

  it('rescan con 409 abre el modal de confirmación y, al confirmar, muestra el rescan forzado', async () => {
    const user = userEvent.setup()
    // Corrected by frontend-ux-redesign (D90/RN-184): the backend sends
    // {"detail": {"code", "count"}}. The flat {code, count} mock hid B3 (the
    // dialog always said 0 pending events).
    const conflictError = mockApiError(409, { code: 'pending_events_exist', count: 3 })
    apiPost.mockRejectedValueOnce(conflictError)
    apiPost.mockResolvedValueOnce({ data: undefined })

    renderWithProviders(<Agents />, { route: '/agents' })

    const rescanButton = await screen.findByRole('button', { name: 'Rescan' })
    await user.click(rescanButton)

    const dialog = await screen.findByRole('dialog', { name: 'Confirmar rescan forzado' })
    expect(within(dialog).getByText('3')).toBeInTheDocument()

    const confirmButton = screen.getByRole('button', { name: 'Forzar rescan' })
    await user.click(confirmButton)

    await waitFor(() => expect(toastSuccess).toHaveBeenCalledWith('Rescan forzado iniciado'))
  })
})

describe('Agents — errores del backend con la forma real (A7, D91/RN-185)', () => {
  beforeEach(() => {
    apiGet.mockReset()
    apiPost.mockReset()
    toastSuccess.mockReset()
    toastError.mockReset()
  })

  it('un 422 con detail objeto muestra su message y, si trae index, queda junto a esa entrada', async () => {
    apiGet.mockResolvedValue({ data: { items: [makeAgent({ watch_paths: ['/etc', '/var'] })], total: 1 } })
    apiPost.mockRejectedValue(
      mockApiError(422, { code: 'watch_path_duplicate', message: 'La ruta está repetida.', index: 1 }),
    )
    const user = userEvent.setup()
    renderWithProviders(<Agents />, { route: '/agents' })

    await user.click(await screen.findByRole('button', { name: /editar/i }))
    await user.click(screen.getByRole('button', { name: /guardar paths/i }))

    await waitFor(() =>
      expect(toastError).toHaveBeenCalledWith('Error al guardar configuración: La ruta está repetida.'),
    )
    const second = screen.getAllByText('/var')[0].closest('li')!
    expect(within(second).getByRole('alert')).toHaveTextContent('La ruta está repetida.')
    // The editor stays open with the admin's work.
    expect(screen.getByRole('button', { name: /guardar paths/i })).toBeInTheDocument()
  })

  it('un 404 con detail string y un detail con lista nunca producen [object Object]', async () => {
    apiGet.mockResolvedValue({ data: { items: [makeAgent()], total: 1 } })
    apiPost.mockRejectedValueOnce(mockApiError(404, 'agent not found'))
    const user = userEvent.setup()
    renderWithProviders(<Agents />, { route: '/agents' })

    await user.click(await screen.findByRole('button', { name: 'Rescan' }))
    await waitFor(() => expect(toastError).toHaveBeenCalledWith('Error al iniciar rescan: agent not found'))

    apiPost.mockRejectedValueOnce(mockApiError(422, [{ loc: ['body'], msg: 'Field required', type: 'missing' }]))
    await user.click(screen.getByRole('button', { name: 'Rescan' }))
    await waitFor(() => expect(toastError).toHaveBeenLastCalledWith('Error al iniciar rescan: Field required'))
  })

  it('GET /agents con 500 muestra el error con «Reintentar»', async () => {
    apiGet.mockRejectedValue(mockApiError(500, 'boom'))
    renderWithProviders(<Agents />, { route: '/agents' })
    expect(await screen.findByRole('button', { name: 'Reintentar' }, { timeout: 3000 })).toBeInTheDocument()
  })
})
