import { describe, it, expect, beforeEach, vi } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithProviders } from '@/test/renderWithProviders'
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
    const conflictError = {
      isAxiosError: true,
      response: { status: 409, data: { code: 'pending_events_exist', count: 3 } },
    }
    apiPost.mockRejectedValueOnce(conflictError)
    apiPost.mockResolvedValueOnce({ data: undefined })

    renderWithProviders(<Agents />, { route: '/agents' })

    const rescanButton = await screen.findByRole('button', { name: 'Rescan' })
    await user.click(rescanButton)

    expect(await screen.findByText('Confirmar rescan forzado')).toBeInTheDocument()

    const confirmButton = screen.getByRole('button', { name: 'Forzar rescan' })
    await user.click(confirmButton)

    await waitFor(() => expect(toastSuccess).toHaveBeenCalledWith('Rescan forzado iniciado'))
  })
})
