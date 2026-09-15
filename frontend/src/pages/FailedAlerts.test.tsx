import { describe, it, expect, beforeEach, vi } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithProviders } from '@/test/renderWithProviders'
import { FailedAlerts } from './FailedAlerts'
import type { Alert } from '@/api/alerts'

// US-29: acciones de la DLQ — reintentar por fila, reintento masivo (N
// llamadas individuales) y descartar. Mismo patrón de mock que Alerts.test.tsx:
// se mockea la capa HTTP (@/api/client) y se deja correr la lógica real de
// useAlerts (React Query).

const { apiGet, apiPost, apiDelete } = vi.hoisted(() => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  apiDelete: vi.fn(),
}))

vi.mock('@/api/client', () => ({
  apiClient: {
    get: (...args: unknown[]) => apiGet(...args),
    post: (...args: unknown[]) => apiPost(...args),
    delete: (...args: unknown[]) => apiDelete(...args),
  },
  default: {
    get: (...args: unknown[]) => apiGet(...args),
    post: (...args: unknown[]) => apiPost(...args),
    delete: (...args: unknown[]) => apiDelete(...args),
  },
}))

function makeAlert(overrides: Partial<Alert> = {}): Alert {
  return {
    id: 1,
    event_id: 42,
    severity: 'critical',
    status: 'failed',
    channel: 'n8n',
    path: '/etc/shadow',
    action_taken: null,
    created_at: '2026-08-20T12:00:00Z',
    delivered_at: null,
    failed_at: '2026-08-20T12:05:00Z',
    ...overrides,
  }
}

describe('FailedAlerts — US-29 acciones de la DLQ', () => {
  beforeEach(() => {
    apiGet.mockReset()
    apiPost.mockReset()
    apiDelete.mockReset()
  })

  it('"Reintentar" por fila llama POST /alerts/{id}/retry', async () => {
    apiGet.mockResolvedValue({ data: { items: [makeAlert({ id: 7 })], total: 1 } })
    apiPost.mockResolvedValue({ data: {} })
    const user = userEvent.setup()

    renderWithProviders(<FailedAlerts />, { route: '/alerts/failed' })

    await screen.findByText('7')
    await user.click(screen.getByRole('button', { name: 'Reintentar' }))

    await waitFor(() => expect(apiPost).toHaveBeenCalledWith('/alerts/7/retry'))
  })

  it('seleccionar tres filas y usar el bulk llama POST /alerts/{id}/retry una vez por id', async () => {
    apiGet.mockResolvedValue({
      data: {
        items: [makeAlert({ id: 1 }), makeAlert({ id: 2 }), makeAlert({ id: 3 })],
        total: 3,
      },
    })
    apiPost.mockResolvedValue({ data: {} })
    const user = userEvent.setup()

    renderWithProviders(<FailedAlerts />, { route: '/alerts/failed' })

    await screen.findByText('3 alertas')
    const checkboxes = screen.getAllByRole('checkbox').slice(1) // primera es "seleccionar todas"
    for (const cb of checkboxes) {
      await user.click(cb)
    }

    await user.click(screen.getByRole('button', { name: 'Reintentar seleccionadas' }))

    await waitFor(() => {
      expect(apiPost).toHaveBeenCalledWith('/alerts/1/retry')
      expect(apiPost).toHaveBeenCalledWith('/alerts/2/retry')
      expect(apiPost).toHaveBeenCalledWith('/alerts/3/retry')
    })
    expect(apiPost).toHaveBeenCalledTimes(3)
  })

  it('"Descartar" confirmado llama DELETE /alerts/{id}', async () => {
    apiGet.mockResolvedValue({ data: { items: [makeAlert({ id: 9 })], total: 1 } })
    apiDelete.mockResolvedValue({ data: {} })
    const user = userEvent.setup()

    renderWithProviders(<FailedAlerts />, { route: '/alerts/failed' })

    await screen.findByText('9')
    await user.click(screen.getByRole('button', { name: 'Descartar' }))
    await user.click(screen.getByRole('button', { name: 'Confirmar' }))

    await waitFor(() => expect(apiDelete).toHaveBeenCalledWith('/alerts/9'))
  })
})
