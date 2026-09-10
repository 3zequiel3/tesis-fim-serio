import { describe, it, expect, beforeEach, vi } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithProviders } from '@/test/renderWithProviders'
import { Events } from './Events'

// D34/RN-128: activar un checkbox de severidad deja el parámetro en la URL
// (verificado indirectamente vía round-trip: el checkbox refleja el filtro
// parseado DESDE la URL, así que si sigue marcado después del re-render es
// porque la URL lo tiene) y dispara una petición con esa severidad; quitar
// el último lo saca de las dos (8.6).

const { apiGet } = vi.hoisted(() => ({ apiGet: vi.fn() }))

vi.mock('@/api/client', () => ({
  apiClient: { get: (...args: unknown[]) => apiGet(...args) },
  default: { get: (...args: unknown[]) => apiGet(...args) },
}))

function lastEventsRequestParams(): Record<string, unknown> | undefined {
  const calls = apiGet.mock.calls.filter(([url]: [string]) => url === '/events')
  const last = calls[calls.length - 1]
  return last?.[1]?.params
}

describe('Events — filtro por severidad (8.6)', () => {
  beforeEach(() => {
    apiGet.mockReset()
    apiGet.mockResolvedValue({ data: { total: 0, page: 1, page_size: 50, items: [] } })
  })

  it('activar un checkbox de severidad lo deja marcado y dispara una petición con esa severidad', async () => {
    const user = userEvent.setup()
    renderWithProviders(<Events />, { route: '/events' })

    await waitFor(() => expect(apiGet).toHaveBeenCalled())

    const criticalCheckbox = screen.getByRole('checkbox', { name: 'critical' })
    expect(criticalCheckbox).not.toBeChecked()

    await user.click(criticalCheckbox)

    await waitFor(() => expect(criticalCheckbox).toBeChecked())
    await waitFor(() => expect(lastEventsRequestParams()?.severity).toEqual(['critical']))
  })

  it('desactivar el último nivel seleccionado lo saca del checkbox y de la petición', async () => {
    const user = userEvent.setup()
    renderWithProviders(<Events />, { route: '/events?severity=critical' })

    await waitFor(() => expect(apiGet).toHaveBeenCalled())

    const criticalCheckbox = screen.getByRole('checkbox', { name: 'critical' })
    expect(criticalCheckbox).toBeChecked()
    expect(lastEventsRequestParams()?.severity).toEqual(['critical'])

    await user.click(criticalCheckbox)

    await waitFor(() => expect(criticalCheckbox).not.toBeChecked())
    await waitFor(() => expect(lastEventsRequestParams()?.severity).toBeUndefined())
  })
})

describe('Events — US-31 toggle superseded', () => {
  beforeEach(() => {
    apiGet.mockReset()
    apiGet.mockResolvedValue({ data: { total: 0, page: 1, page_size: 50, items: [] } })
  })

  it('está desmarcado por defecto y al activarlo persiste en la URL lógica y llega a la petición', async () => {
    const user = userEvent.setup()
    renderWithProviders(<Events />, { route: '/events' })

    await waitFor(() => expect(apiGet).toHaveBeenCalled())
    const toggle = screen.getByRole('checkbox', { name: 'Mostrar eventos superseded' })
    expect(toggle).not.toBeChecked()

    await user.click(toggle)

    await waitFor(() => expect(toggle).toBeChecked())
    await waitFor(() => expect(lastEventsRequestParams()?.include_superseded).toBe(true))
    expect(screen.getByRole('checkbox', { name: 'superseded' })).toBeInTheDocument()
  })

  it('restaura el toggle desde include_superseded=true de la URL', async () => {
    renderWithProviders(<Events />, { route: '/events?include_superseded=true' })

    await waitFor(() => expect(apiGet).toHaveBeenCalled())
    expect(screen.getByRole('checkbox', { name: 'Mostrar eventos superseded' })).toBeChecked()
    expect(lastEventsRequestParams()?.include_superseded).toBe(true)
  })
})
