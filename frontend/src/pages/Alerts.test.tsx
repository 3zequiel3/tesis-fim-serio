import { describe, it, expect, beforeEach, vi } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import { renderWithProviders } from '@/test/renderWithProviders'
import { Alerts } from './Alerts'
import type { Alert } from '@/api/alerts'

// US-19 (listado de alertas): cada alerta muestra path, severidad, tipo de
// acción, fecha y canal de entrega; y es navegable hacia el detalle del
// evento asociado. Mismo patrón de mock que Events.test.tsx / EventDetail.test.tsx.

const { apiGet } = vi.hoisted(() => ({ apiGet: vi.fn() }))

vi.mock('@/api/client', () => ({
  apiClient: { get: (...args: unknown[]) => apiGet(...args) },
  default: { get: (...args: unknown[]) => apiGet(...args) },
}))

function makeAlert(overrides: Partial<Alert> = {}): Alert {
  return {
    id: 1,
    event_id: 42,
    severity: 'critical',
    status: 'delivered',
    channel: 'n8n',
    path: '/etc/shadow',
    action_taken: 'quarantine',
    created_at: '2026-08-20T12:00:00Z',
    delivered_at: '2026-08-20T12:00:05Z',
    failed_at: null,
    ...overrides,
  }
}

describe('Alerts — US-19 listado de alertas', () => {
  beforeEach(() => {
    apiGet.mockReset()
  })

  it('muestra el path del archivo y el tipo de acción de cada alerta', async () => {
    apiGet.mockResolvedValue({
      data: { items: [makeAlert()], total: 1, page: 1, size: 50 },
    })

    renderWithProviders(<Alerts />, { route: '/alerts' })

    await waitFor(() => expect(apiGet).toHaveBeenCalled())
    expect(await screen.findByText('/etc/shadow')).toBeInTheDocument()
    expect(screen.getByText('quarantine')).toBeInTheDocument()
  })

  it('muestra un guion cuando la alerta todavía no tiene acción tomada', async () => {
    apiGet.mockResolvedValue({
      data: {
        items: [makeAlert({ action_taken: null, status: 'pending', channel: null })],
        total: 1,
        page: 1,
        size: 50,
      },
    })

    renderWithProviders(<Alerts />, { route: '/alerts' })

    await waitFor(() => expect(apiGet).toHaveBeenCalled())
    await screen.findByText('/etc/shadow')
    expect(screen.getByText('—')).toBeInTheDocument()
  })

  it('cada alerta es navegable hacia el detalle del evento asociado', async () => {
    apiGet.mockResolvedValue({
      data: { items: [makeAlert({ event_id: 99 })], total: 1, page: 1, size: 50 },
    })

    renderWithProviders(<Alerts />, { route: '/alerts' })

    await waitFor(() => expect(apiGet).toHaveBeenCalled())
    const link = await screen.findByRole('link', { name: /etc\/shadow/ })
    expect(link).toHaveAttribute('href', '/events/99')
  })
})
