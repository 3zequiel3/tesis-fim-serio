import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithProviders } from '@/test/renderWithProviders'
import { signInAs, signOut } from '@/test/signIn'
import { Events } from './Events'
import type { EventListItem } from '@/api/events'

// frontend-events (frontend-ux-redesign): URL sanitizing, debounce race, selection.

const { apiGet } = vi.hoisted(() => ({ apiGet: vi.fn() }))

vi.mock('@/api/client', () => ({
  apiClient: { get: (...args: unknown[]) => apiGet(...args) },
  default: { get: (...args: unknown[]) => apiGet(...args) },
}))

function makeItem(id: number, path = `/etc/file-${id}`): EventListItem {
  return {
    id,
    event_type: 'file_modified',
    path,
    hash_detected: 'abc123',
    status: 'pending',
    severity: 'low',
    parent_event_id: null,
    version: 0,
    process_pid: 0,
    process_uid: 0,
    process_exe: null,
    detected_at: '2026-08-20T12:00:00Z',
    received_at: '2026-08-20T12:00:00Z',
    created_at: '2026-08-20T12:00:00Z',
    resolved_at: null,
    resolved_by: null,
    is_symlink: false,
    symlink_target: null,
    action_failed: false,
  }
}

function page(items: EventListItem[]) {
  return { data: { total: items.length, page: 1, page_size: 50, items } }
}

function requests() {
  return apiGet.mock.calls
    .filter(([url]: [string]) => url === '/events')
    .map(([, config]: [string, { params: Record<string, unknown> }]) => config.params)
}

beforeEach(() => {
  apiGet.mockReset()
  signInAs('admin')
})
afterEach(() => {
  signOut()
  vi.useRealTimers()
})

describe('Events — parámetros de página saneados (M7)', () => {
  it('/events?page=abc pide la página 1 y nunca envía NaN', async () => {
    apiGet.mockResolvedValue(page([]))
    renderWithProviders(<Events />, { route: '/events?page=abc' })
    await waitFor(() => expect(apiGet).toHaveBeenCalled())
    expect(requests()[0].page).toBe(1)
    expect(JSON.stringify(requests()[0])).not.toContain('NaN')
  })

  it('/events?page=-3 también vuelve a la página 1', async () => {
    apiGet.mockResolvedValue(page([]))
    renderWithProviders(<Events />, { route: '/events?page=-3' })
    await waitFor(() => expect(apiGet).toHaveBeenCalled())
    expect(requests()[0].page).toBe(1)
  })
})

describe('Events — filtro de ruta con debounce (M9)', () => {
  it('una respuesta tardía de un valor anterior no reemplaza la de uno más nuevo', async () => {
    const resolvers: Record<string, (v: unknown) => void> = {}
    apiGet.mockImplementation((_url: string, config: { params: { path_prefix?: string } }) => {
      const key = config.params.path_prefix ?? ''
      return new Promise((resolve) => {
        resolvers[key] = resolve
      })
    })
    const user = userEvent.setup()
    renderWithProviders(<Events />, { route: '/events' })
    await waitFor(() => expect(resolvers['']).toBeDefined())
    await act(async () => resolvers['']?.(page([])))

    const input = screen.getByLabelText('Prefijo de path')
    await user.type(input, '/et')
    await waitFor(() => expect(resolvers['/et']).toBeDefined())
    await user.type(input, 'c/ssh')
    await waitFor(() => expect(resolvers['/etc/ssh']).toBeDefined())

    // The newer value answers first, the older one arrives late.
    await act(async () => resolvers['/etc/ssh'](page([makeItem(2, '/etc/ssh/sshd_config')])))
    await act(async () => resolvers['/et'](page([makeItem(1, '/etc/hosts')])))

    expect(await screen.findByText('/etc/ssh/sshd_config')).toBeInTheDocument()
    expect(screen.queryByText('/etc/hosts')).toBeNull()
  })

  it('el valor escrito no pisa un filtro de estado marcado mientras corría el debounce', async () => {
    apiGet.mockResolvedValue(page([]))
    const user = userEvent.setup()
    renderWithProviders(<Events />, { route: '/events' })
    await waitFor(() => expect(apiGet).toHaveBeenCalled())

    await user.type(screen.getByLabelText('Prefijo de path'), '/etc')
    // Within the 300 ms window, the operator also ticks a status.
    await user.click(screen.getByRole('checkbox', { name: 'pending' }))

    await waitFor(() => {
      const last = requests()[requests().length - 1]
      expect(last.path_prefix).toBe('/etc')
      expect(last.status).toEqual(['pending'])
    }, { timeout: 4000 })
  })
})

describe('Events — selección (M9)', () => {
  it('«Seleccionar todos» + refresco: la selección sólo conserva los ids presentes', async () => {
    apiGet.mockResolvedValue(page([makeItem(1), makeItem(2), makeItem(3), makeItem(4)]))
    const user = userEvent.setup()
    const { queryClient } = renderWithProviders(<Events />, { route: '/events' })

    await user.click(await screen.findByRole('checkbox', { name: 'Seleccionar todos en la página' }))
    expect(await screen.findByText('4 eventos seleccionados')).toBeInTheDocument()

    // Two events stopped being pending and left the list.
    apiGet.mockResolvedValue(page([makeItem(1), makeItem(2)]))
    await act(async () => {
      await queryClient.invalidateQueries({ queryKey: ['events'] })
    })

    expect(await screen.findByText('2 eventos seleccionados')).toBeInTheDocument()
    expect(screen.queryByRole('checkbox', { name: 'Seleccionar evento #3' })).toBeNull()
  })

  it('un usuario que no es admin no ve casillas ni acciones masivas', async () => {
    signInAs('viewer')
    apiGet.mockResolvedValue(page([makeItem(1)]))
    renderWithProviders(<Events />, { route: '/events' })
    await screen.findByText('/etc/file-1')
    expect(screen.queryByRole('checkbox', { name: /Seleccionar/ })).toBeNull()
  })
})

describe('Events — proceso desconocido en la tabla (D11)', () => {
  it('pid 0 y exe null se muestran como desconocido', async () => {
    apiGet.mockResolvedValue(page([makeItem(1)]))
    renderWithProviders(<Events />, { route: '/events' })
    expect(await screen.findByText(/desconocido \(pid desconocido, uid 0\)/)).toBeInTheDocument()
  })
})
