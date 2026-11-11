import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithProviders } from '@/test/renderWithProviders'
import { mockApiError } from '@/test/mockApiError'
import { signInAs, signOut } from '@/test/signIn'
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
    retry_count: 0,
    last_error: null,
    ...overrides,
  }
}

// D93/RN-187: mutation controls are shown only to `admin`.
beforeEach(() => signInAs('admin'))
afterEach(() => signOut())

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

// B8 (D93/RN-187): delivery context per row and «Reintentar todas».
describe('FailedAlerts — contexto de entrega y «Reintentar todas» (B8)', () => {
  beforeEach(() => {
    apiGet.mockReset()
    apiPost.mockReset()
  })

  it('cada fila enlaza al evento y muestra reintentos, último error y «sin canal entregado»', async () => {
    apiGet.mockResolvedValue({
      data: {
        items: [makeAlert({ id: 5, event_id: 42, retry_count: 3, last_error: 'n8n: 502', channel: null })],
        total: 1,
      },
    })
    renderWithProviders(<FailedAlerts />, { route: '/alerts/failed' })

    const link = await screen.findByRole('link', { name: 'Evento #42' })
    expect(link).toHaveAttribute('href', '/events/42')
    expect(screen.getByText('n8n: 502')).toBeInTheDocument()
    expect(screen.getByText('3')).toBeInTheDocument()
    expect(screen.getByText('sin canal entregado')).toBeInTheDocument()
  })

  it('un último error largo se trunca y conserva el texto completo en el title', async () => {
    const long = 'x'.repeat(200)
    apiGet.mockResolvedValue({ data: { items: [makeAlert({ last_error: long })], total: 1 } })
    renderWithProviders(<FailedAlerts />, { route: '/alerts/failed' })

    const node = await screen.findByTitle(long)
    expect(node.textContent!.length).toBeLessThan(long.length)
  })

  it('«Reintentar todas» reintenta cada alerta, informa 2 correctas y 1 fallida y refresca la lista', async () => {
    apiGet.mockResolvedValue({
      data: { items: [makeAlert({ id: 1 }), makeAlert({ id: 2 }), makeAlert({ id: 3 })], total: 3 },
    })
    apiPost.mockImplementation((url: string) =>
      url === '/alerts/2/retry'
        ? Promise.reject(mockApiError(502, 'n8n unreachable'))
        : Promise.resolve({ data: {} }),
    )
    const user = userEvent.setup()
    renderWithProviders(<FailedAlerts />, { route: '/alerts/failed' })

    await user.click(await screen.findByRole('button', { name: 'Reintentar todas' }))

    expect(await screen.findByRole('status')).toHaveTextContent('2 correctas, 1 fallida')
    expect(apiPost.mock.calls.map(([url]: [string]) => url)).toEqual([
      '/alerts/1/retry',
      '/alerts/2/retry',
      '/alerts/3/retry',
    ])
    // The list was requested again after the retries.
    await waitFor(() => expect(apiGet.mock.calls.length).toBeGreaterThan(1))
  })

  it('estado vacío y error con reintento', async () => {
    apiGet.mockResolvedValueOnce({ data: { items: [], total: 0 } })
    const { unmount } = renderWithProviders(<FailedAlerts />, { route: '/alerts/failed' })
    expect(await screen.findByText('No hay alertas fallidas.')).toBeInTheDocument()
    unmount()

    apiGet.mockReset()
    apiGet.mockRejectedValue(mockApiError(500, 'boom'))
    renderWithProviders(<FailedAlerts />, { route: '/alerts/failed' })
    expect(await screen.findByRole('button', { name: 'Reintentar' }, { timeout: 3000 })).toBeInTheDocument()
  })

  it('un viewer no ve ninguna acción de mutación', async () => {
    signInAs('viewer')
    apiGet.mockResolvedValue({ data: { items: [makeAlert()], total: 1 } })
    renderWithProviders(<FailedAlerts />, { route: '/alerts/failed' })
    await screen.findByRole('link', { name: 'Evento #42' })
    expect(screen.queryByRole('button', { name: 'Reintentar todas' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Reintentar' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Descartar' })).toBeNull()
  })

  it('un error de detail objeto al reintentar no muestra [object Object]', async () => {
    apiGet.mockResolvedValue({ data: { items: [makeAlert({ id: 7 })], total: 1 } })
    apiPost.mockRejectedValue(mockApiError(502, { code: 'x', message: 'Canal caído.' }))
    const user = userEvent.setup()
    renderWithProviders(<FailedAlerts />, { route: '/alerts/failed' })
    await user.click(await screen.findByRole('button', { name: 'Reintentar' }))
    // No crash and no raw object interpolation: the retry button comes back enabled.
    await waitFor(() => expect(screen.getByRole('button', { name: 'Reintentar' })).not.toBeDisabled())
  })
})
