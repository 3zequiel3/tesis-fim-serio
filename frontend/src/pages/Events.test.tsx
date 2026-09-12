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

// US-07: selector de estado con 7 estados posibles, selección múltiple,
// `superseded` excluido por defecto y sólo disponible como 7º checkbox
// cuando el toggle "Mostrar superseded" está activo, y actualización dinámica
// del listado al aplicar/quitar filtros.
const BASE_STATUS_CHECKBOXES = [
  'pending',
  'approved',
  'rejected',
  'auto_restored',
  'quarantined',
  'alert_only',
]

describe('Events — filtro por estado (US-07)', () => {
  beforeEach(() => {
    apiGet.mockReset()
    apiGet.mockResolvedValue({ data: { total: 0, page: 1, page_size: 50, items: [] } })
  })

  it('sin el toggle activo muestra los 6 checkboxes de estado base y NINGUNO de superseded', async () => {
    renderWithProviders(<Events />, { route: '/events' })
    await waitFor(() => expect(apiGet).toHaveBeenCalled())

    for (const status of BASE_STATUS_CHECKBOXES) {
      expect(screen.getByRole('checkbox', { name: status })).toBeInTheDocument()
    }
    expect(screen.queryByRole('checkbox', { name: 'superseded' })).not.toBeInTheDocument()
    // Falla si el checkbox default incluyera un 7mo estado: hay exactamente 6
    // checkboxes de estado + el toggle "Mostrar eventos superseded".
    const statusCheckboxes = BASE_STATUS_CHECKBOXES.map((s) =>
      screen.getByRole('checkbox', { name: s }),
    )
    expect(statusCheckboxes).toHaveLength(6)
  })

  it('con el toggle "Mostrar eventos superseded" activo aparecen los 7 checkboxes de estado', async () => {
    const user = userEvent.setup()
    renderWithProviders(<Events />, { route: '/events' })
    await waitFor(() => expect(apiGet).toHaveBeenCalled())

    await user.click(screen.getByRole('checkbox', { name: 'Mostrar eventos superseded' }))

    for (const status of [...BASE_STATUS_CHECKBOXES, 'superseded']) {
      expect(screen.getByRole('checkbox', { name: status })).toBeInTheDocument()
    }
  })

  it('seleccionar dos estados refleja ambos en la petición (selección múltiple)', async () => {
    const user = userEvent.setup()
    renderWithProviders(<Events />, { route: '/events' })
    await waitFor(() => expect(apiGet).toHaveBeenCalled())

    await user.click(screen.getByRole('checkbox', { name: 'pending' }))
    await waitFor(() => expect(lastEventsRequestParams()?.status).toEqual(['pending']))

    await user.click(screen.getByRole('checkbox', { name: 'quarantined' }))
    await waitFor(() =>
      expect(lastEventsRequestParams()?.status).toEqual(['pending', 'quarantined']),
    )
    expect(screen.getByRole('checkbox', { name: 'pending' })).toBeChecked()
    expect(screen.getByRole('checkbox', { name: 'quarantined' })).toBeChecked()
  })

  it('por defecto ningún filtro de estado incluye superseded (excluido por defecto, W1)', async () => {
    const user = userEvent.setup()
    renderWithProviders(<Events />, { route: '/events' })
    await waitFor(() => expect(apiGet).toHaveBeenCalled())

    expect(lastEventsRequestParams()?.status).toBeUndefined()

    await user.click(screen.getByRole('checkbox', { name: 'rejected' }))
    await waitFor(() => expect(lastEventsRequestParams()?.status).toEqual(['rejected']))
    expect(lastEventsRequestParams()?.status).not.toContain('superseded')
  })

  it('cambiar un filtro de estado dispara una nueva petición con los parámetros actualizados', async () => {
    const user = userEvent.setup()
    renderWithProviders(<Events />, { route: '/events' })
    await waitFor(() => expect(apiGet).toHaveBeenCalled())

    const callsBefore = apiGet.mock.calls.filter(([url]: [string]) => url === '/events').length

    await user.click(screen.getByRole('checkbox', { name: 'approved' }))

    await waitFor(() => {
      const callsAfter = apiGet.mock.calls.filter(([url]: [string]) => url === '/events').length
      expect(callsAfter).toBeGreaterThan(callsBefore)
    })
    expect(lastEventsRequestParams()?.status).toEqual(['approved'])

    // Quitar el filtro dispara otra petición más, sin 'approved'.
    await user.click(screen.getByRole('checkbox', { name: 'approved' }))
    await waitFor(() => expect(lastEventsRequestParams()?.status).toBeUndefined())
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
