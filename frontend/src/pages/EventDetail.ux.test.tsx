import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, Routes } from 'react-router-dom'
import { renderWithProviders } from '@/test/renderWithProviders'
import { mockApiError } from '@/test/mockApiError'
import { signInAs, signOut } from '@/test/signIn'
import { EventDetail } from './EventDetail'
import { EventChain } from './EventChain'
import type { EventDetail as EventDetailData } from '@/api/events'

// frontend-events (frontend-ux-redesign): error states, role gating, command
// polling and process display. Error mocks use the REAL {"detail": ...} shape.

const { apiGet, apiPost, toastError, toastSuccess } = vi.hoisted(() => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  toastError: vi.fn(),
  toastSuccess: vi.fn(),
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
  toast: { error: toastError, success: toastSuccess, info: vi.fn(), warning: vi.fn() },
}))

function makeEvent(overrides: Partial<EventDetailData> = {}): EventDetailData {
  return {
    id: 7,
    event_type: 'file_modified',
    path: '/etc/passwd',
    hash_detected: 'deadbeefcafebabe',
    hash_expected: null,
    diff_text: null,
    is_binary: false,
    hex_dump_before: null,
    hex_dump_after: null,
    status: 'pending',
    severity: 'low',
    parent_event_id: null,
    version: 0,
    process_pid: null,
    process_uid: null,
    process_exe: null,
    detected_at: '2026-08-20T12:00:00Z',
    received_at: '2026-08-20T12:00:00Z',
    created_at: '2026-08-20T12:00:00Z',
    resolved_at: null,
    resolved_by: null,
    ack_status: null,
    ack_error: null,
    is_symlink: false,
    symlink_target: null,
    action_failed: false,
    action_error: null,
    action_type: 'manual_review',
    ...overrides,
  }
}

function eventRequests() {
  return apiGet.mock.calls.filter(([url]: [string]) => /^\/events\/\d+$/.test(url))
}

function route(id: string) {
  return renderWithProviders(
    <Routes>
      <Route path="/events/:id" element={<EventDetail />} />
      <Route path="/events/:id/chain" element={<EventChain />} />
    </Routes>,
    { route: `/events/${id}` },
  )
}

beforeEach(() => {
  apiGet.mockReset()
  apiPost.mockReset()
  toastError.mockReset()
  toastSuccess.mockReset()
  signInAs('admin')
})
afterEach(() => {
  signOut()
  vi.useRealTimers()
})

describe('EventDetail — id inválido y errores (B5)', () => {
  it('/events/abc muestra «Evento no encontrado» y no envía ninguna request de evento', async () => {
    route('abc')
    expect(await screen.findByText('Evento no encontrado')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Volver a eventos' })).toBeInTheDocument()
    expect(apiGet).not.toHaveBeenCalled()
  })

  it('un 404 muestra el mismo estado', async () => {
    apiGet.mockRejectedValue(mockApiError(404, 'Event not found'))
    route('7')
    expect(await screen.findByText('Evento no encontrado')).toBeInTheDocument()
  })

  it('un 500 muestra el error con «Reintentar» y al activarlo repite GET /events/7', async () => {
    apiGet.mockRejectedValue(mockApiError(500, 'Internal Server Error'))
    const user = userEvent.setup()
    route('7')

    const alert = await screen.findByRole('alert', undefined, { timeout: 3000 })
    expect(alert).toHaveTextContent('No se pudieron cargar el evento')
    expect(screen.queryByText('Cargando evento...')).toBeNull()
    const before = eventRequests().length

    await user.click(screen.getByRole('button', { name: 'Reintentar' }))

    await waitFor(() => expect(eventRequests().length).toBeGreaterThan(before))
  })

  it('un 403 muestra el aviso de permiso sin botón de reintento', async () => {
    apiGet.mockRejectedValue(mockApiError(403, 'Forbidden'))
    route('7')
    expect(await screen.findByText('No tenés permiso para ver esta sección.')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Reintentar' })).toBeNull()
  })

  it('EventChain: un 503 en la cadena muestra el error con «Reintentar», no «Cargando…»', async () => {
    apiGet.mockRejectedValue(mockApiError(503, 'Service Unavailable'))
    route('7/chain')
    expect(await screen.findByRole('alert', undefined, { timeout: 3000 })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Reintentar' })).toBeInTheDocument()
    expect(screen.queryByText(/Cargando cadena/)).toBeNull()
  })

  it('EventChain con id no numérico muestra «Evento no encontrado» sin pedir nada', async () => {
    route('abc/chain')
    expect(await screen.findByText('Evento no encontrado')).toBeInTheDocument()
    expect(apiGet).not.toHaveBeenCalled()
  })
})

describe('EventDetail — acciones solo para pending y admin (B6, D15)', () => {
  function serve(event: EventDetailData) {
    apiGet.mockImplementation((url: string) =>
      Promise.resolve({ data: url.includes('/chain') ? { path: event.path, items: [] } : event }),
    )
  }

  it('un evento alert_only no ofrece Aprobar ni Rechazar', async () => {
    serve(makeEvent({ status: 'alert_only' }))
    route('7')
    await screen.findByText('/etc/passwd')
    expect(screen.queryByRole('button', { name: 'Aprobar' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Rechazar' })).toBeNull()
  })

  it('un usuario con role viewer no ve Aprobar ni Rechazar en un evento pending', async () => {
    signInAs('viewer')
    serve(makeEvent({ status: 'pending' }))
    route('7')
    await screen.findByText('/etc/passwd')
    expect(screen.queryByRole('button', { name: 'Aprobar' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Rechazar' })).toBeNull()
  })

  it('un viewer tampoco ve «Liberar cuarentena»', async () => {
    signInAs('viewer')
    serve(makeEvent({ status: 'rejected', quarantine_state: 'quarantined' }))
    route('7')
    await screen.findByText('/etc/passwd')
    expect(screen.queryByRole('button', { name: 'Liberar cuarentena' })).toBeNull()
  })

  it('un error con detail objeto muestra su message, nunca [object Object]', async () => {
    serve(makeEvent({ status: 'pending' }))
    apiPost.mockRejectedValue(mockApiError(422, { code: 'otro_codigo', message: 'Mensaje del servidor.' }))
    const user = userEvent.setup()
    route('7')

    await user.click(await screen.findByRole('button', { name: 'Aprobar' }))

    await waitFor(() => expect(toastError).toHaveBeenCalledWith('Mensaje del servidor.'))
  })
})

describe('EventDetail — reconsulta del comando y motivo del fallo (D3/M3/D11)', () => {
  it('pending pasa a acked a los 4 s y se refleja sin interacción', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    let detail = makeEvent({
      status: 'rejected',
      ack_status: 'pending',
      quarantine_state: 'quarantined',
    })
    apiGet.mockImplementation((url: string) =>
      Promise.resolve({ data: url.includes('/chain') ? { path: '/etc/passwd', items: [] } : detail }),
    )
    route('7')
    expect(await screen.findByText('Ejecución: pendiente')).toBeInTheDocument()

    detail = makeEvent({ status: 'rejected', ack_status: 'acked', quarantine_state: 'released' })
    await act(async () => {
      await vi.advanceTimersByTimeAsync(4_000)
    })

    expect(await screen.findByText('Ejecución: confirmada')).toBeInTheDocument()
    expect(screen.getByText('released')).toBeInTheDocument()
  })

  it('a los 60 s sigue pendiente: deja de reconsultar y ofrece «Actualizar»', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    apiGet.mockImplementation((url: string) =>
      Promise.resolve({
        data: url.includes('/chain')
          ? { path: '/etc/passwd', items: [] }
          : makeEvent({ status: 'rejected', ack_status: 'pending' }),
      }),
    )
    route('7')
    await screen.findByText('Ejecución: pendiente')

    await act(async () => {
      await vi.advanceTimersByTimeAsync(61_000)
    })
    expect(await screen.findByRole('button', { name: 'Actualizar' })).toBeInTheDocument()
    expect(screen.getByText(/vencido a los 5 minutos/)).toBeInTheDocument()

    const after = eventRequests().length
    await act(async () => {
      await vi.advanceTimersByTimeAsync(30_000)
    })
    expect(eventRequests().length).toBe(after)
  })

  it('failed + no_restorable_content muestra el motivo en español', async () => {
    apiGet.mockImplementation((url: string) =>
      Promise.resolve({
        data: url.includes('/chain')
          ? { path: '/etc/passwd', items: [] }
          : makeEvent({ status: 'rejected', ack_status: 'failed', ack_error: 'no_restorable_content' }),
      }),
    )
    route('7')
    expect(await screen.findByText('Ejecución: falló')).toBeInTheDocument()
    expect(screen.getByText(/el baseline no tiene contenido restaurable/)).toBeInTheDocument()
  })

  it('un motivo desconocido se muestra literal con el prefijo «Motivo:»', async () => {
    apiGet.mockImplementation((url: string) =>
      Promise.resolve({
        data: url.includes('/chain')
          ? { path: '/etc/passwd', items: [] }
          : makeEvent({ status: 'rejected', ack_status: 'failed', ack_error: 'future_code_v9' }),
      }),
    )
    route('7')
    expect(await screen.findByText('Motivo: future_code_v9')).toBeInTheDocument()
  })
})

describe('EventDetail — proceso desconocido (D11)', () => {
  it('pid 0 y exe null se muestran como «desconocido»; uid 0 sigue siendo 0', async () => {
    apiGet.mockImplementation((url: string) =>
      Promise.resolve({
        data: url.includes('/chain')
          ? { path: '/etc/passwd', items: [] }
          : makeEvent({ process_pid: 0, process_uid: 0, process_exe: null }),
      }),
    )
    route('7')
    await screen.findByText('Proceso que generó el evento')
    expect(screen.getAllByText('desconocido')).toHaveLength(2)
    expect(screen.getByText('UID').nextSibling).toHaveTextContent('0')
    expect(screen.queryByText('?')).toBeNull()
  })
})
