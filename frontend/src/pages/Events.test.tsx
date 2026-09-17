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

// US-07 (RN-71, W1, D-2 del design): selector de estado con los 7 estados
// canónicos SIEMPRE visibles, sin depender del toggle "Mostrar superseded".
// Marcar/desmarcar superseded y encender/apagar el toggle mantienen la
// coherencia con include_superseded, porque el backend excluye superseded
// antes de aplicar el filtro de estado (events/router.py:129-133).
const ALL_STATUS_CHECKBOXES = [
  'pending',
  'approved',
  'rejected',
  'auto_restored',
  'quarantined',
  'alert_only',
  'superseded',
]

describe('Events — filtro por estado (US-07)', () => {
  beforeEach(() => {
    apiGet.mockReset()
    apiGet.mockResolvedValue({ data: { total: 0, page: 1, page_size: 50, items: [] } })
  })

  it('C1: los siete checkboxes existen sin activar el toggle y en el orden canónico', async () => {
    renderWithProviders(<Events />, { route: '/events' })
    await waitFor(() => expect(apiGet).toHaveBeenCalled())

    const statusCheckboxes = ALL_STATUS_CHECKBOXES.map((s) =>
      screen.getByRole('checkbox', { name: s }),
    )
    statusCheckboxes.forEach((cb) => expect(cb).not.toBeChecked())

    const allCheckboxes = screen.getAllByRole('checkbox')
    const positions = statusCheckboxes.map((cb) => allCheckboxes.indexOf(cb))
    expect(positions).toEqual([...positions].sort((a, b) => a - b))
  })

  it('C2: marcar pending y approved emite ambos status en la petición', async () => {
    const user = userEvent.setup()
    renderWithProviders(<Events />, { route: '/events' })
    await waitFor(() => expect(apiGet).toHaveBeenCalled())

    await user.click(screen.getByRole('checkbox', { name: 'pending' }))
    await waitFor(() => expect(lastEventsRequestParams()?.status).toEqual(['pending']))

    await user.click(screen.getByRole('checkbox', { name: 'approved' }))
    await waitFor(() =>
      expect(lastEventsRequestParams()?.status).toEqual(['pending', 'approved']),
    )
    expect(screen.getByRole('checkbox', { name: 'pending' })).toBeChecked()
    expect(screen.getByRole('checkbox', { name: 'approved' })).toBeChecked()
  })

  it('C3: sin parámetros ningún estado está marcado y la petición no lleva include_superseded', async () => {
    renderWithProviders(<Events />, { route: '/events' })
    await waitFor(() => expect(apiGet).toHaveBeenCalled())

    for (const status of ALL_STATUS_CHECKBOXES) {
      expect(screen.getByRole('checkbox', { name: status })).not.toBeChecked()
    }
    expect(lastEventsRequestParams()?.status).toBeUndefined()
    expect(lastEventsRequestParams()?.include_superseded).toBeUndefined()
  })

  it('C4: encender el toggle emite include_superseded=true y apagarlo con superseded marcado lo desmarca y lo quita de la petición', async () => {
    const user = userEvent.setup()
    renderWithProviders(<Events />, { route: '/events' })
    await waitFor(() => expect(apiGet).toHaveBeenCalled())

    const toggle = screen.getByRole('checkbox', { name: 'Mostrar eventos superseded' })
    await user.click(toggle)
    await waitFor(() => expect(lastEventsRequestParams()?.include_superseded).toBe(true))

    await user.click(screen.getByRole('checkbox', { name: 'superseded' }))
    await waitFor(() =>
      expect(lastEventsRequestParams()?.status).toEqual(['superseded']),
    )

    await user.click(toggle)
    await waitFor(() => expect(toggle).not.toBeChecked())
    expect(screen.getByRole('checkbox', { name: 'superseded' })).not.toBeChecked()
    expect(lastEventsRequestParams()?.include_superseded).toBeUndefined()
    expect(lastEventsRequestParams()?.status).toBeUndefined()
  })

  it('C5: desmarcar el último estado emite una petición nueva sin status', async () => {
    const user = userEvent.setup()
    renderWithProviders(<Events />, { route: '/events' })
    await waitFor(() => expect(apiGet).toHaveBeenCalled())

    await user.click(screen.getByRole('checkbox', { name: 'approved' }))
    await waitFor(() => expect(lastEventsRequestParams()?.status).toEqual(['approved']))

    const callsBefore = apiGet.mock.calls.filter(([url]: [string]) => url === '/events').length
    await user.click(screen.getByRole('checkbox', { name: 'approved' }))

    await waitFor(() => {
      const callsAfter = apiGet.mock.calls.filter(([url]: [string]) => url === '/events').length
      expect(callsAfter).toBeGreaterThan(callsBefore)
    })
    expect(lastEventsRequestParams()?.status).toBeUndefined()
  })

  // Escenarios del requisito ADDED de frontend-events.

  it('marcar superseded en el selector activa include_superseded=true', async () => {
    const user = userEvent.setup()
    renderWithProviders(<Events />, { route: '/events' })
    await waitFor(() => expect(apiGet).toHaveBeenCalled())

    await user.click(screen.getByRole('checkbox', { name: 'superseded' }))

    await waitFor(() => expect(lastEventsRequestParams()?.status).toEqual(['superseded']))
    expect(lastEventsRequestParams()?.include_superseded).toBe(true)
    expect(screen.getByRole('checkbox', { name: 'Mostrar eventos superseded' })).toBeChecked()
  })

  it('desmarcar superseded conserva el toggle activo', async () => {
    const user = userEvent.setup()
    renderWithProviders(<Events />, { route: '/events?status=pending&status=superseded&include_superseded=true' })
    await waitFor(() => expect(apiGet).toHaveBeenCalled())

    await user.click(screen.getByRole('checkbox', { name: 'superseded' }))

    await waitFor(() => expect(lastEventsRequestParams()?.status).toEqual(['pending']))
    expect(lastEventsRequestParams()?.include_superseded).toBe(true)
    expect(screen.getByRole('checkbox', { name: 'Mostrar eventos superseded' })).toBeChecked()
  })

  it('un deep-link con status=superseded arranca con el checkbox y el toggle activos', async () => {
    renderWithProviders(<Events />, { route: '/events?status=superseded' })
    await waitFor(() => expect(apiGet).toHaveBeenCalled())

    expect(screen.getByRole('checkbox', { name: 'superseded' })).toBeChecked()
    expect(screen.getByRole('checkbox', { name: 'Mostrar eventos superseded' })).toBeChecked()
    await waitFor(() => expect(lastEventsRequestParams()?.include_superseded).toBe(true))
  })
})

// US-26: navegación numerada + "ir a página", respetando filtros activos.
describe('Events — US-26 paginación', () => {
  beforeEach(() => {
    apiGet.mockReset()
    apiGet.mockResolvedValue({
      data: { total: 250, page: 1, page_size: 50, items: [] },
    })
  })

  it('muestra navegación numerada ademas de anterior/siguiente cuando hay varias páginas', async () => {
    renderWithProviders(<Events />, { route: '/events' })

    await waitFor(() => expect(apiGet).toHaveBeenCalled())

    // 250 eventos / 50 por página = 5 páginas.
    expect(await screen.findByRole('button', { name: '1' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '5' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /primera/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /última/i })).toBeInTheDocument()
  })

  it('clickear un número de página respeta el filtro de estado activo', async () => {
    const user = userEvent.setup()
    renderWithProviders(<Events />, { route: '/events?status=pending' })

    await waitFor(() => expect(apiGet).toHaveBeenCalled())

    await user.click(await screen.findByRole('button', { name: '3' }))

    await waitFor(() => expect(lastEventsRequestParams()?.page).toBe(3))
    expect(lastEventsRequestParams()?.status).toEqual(['pending'])
  })

  it('el input "ir a página" navega y conserva los filtros activos', async () => {
    const user = userEvent.setup()
    renderWithProviders(<Events />, { route: '/events?status=approved' })

    await waitFor(() => expect(apiGet).toHaveBeenCalled())

    const input = await screen.findByLabelText(/ir a página/i)
    await user.type(input, '4')
    await user.click(screen.getByRole('button', { name: /^ir$/i }))

    await waitFor(() => expect(lastEventsRequestParams()?.page).toBe(4))
    expect(lastEventsRequestParams()?.status).toEqual(['approved'])
  })
})
