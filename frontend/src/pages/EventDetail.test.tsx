import { describe, it, expect, beforeEach, vi } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import { Routes, Route } from 'react-router-dom'
import { renderWithProviders } from '@/test/renderWithProviders'
import { EventDetail } from './EventDetail'
import type { EventDetail as EventDetailData } from '@/api/events'

// D51/RN-145 (D-10 del design, task 11.6): el detalle de un evento sin ruta
// sustituye la fila de path por el tipo de evento y su causa, sin romper al
// renderizar. Mismo mock de @/api/client que Events.test.tsx.

const { apiGet } = vi.hoisted(() => ({ apiGet: vi.fn() }))

vi.mock('@/api/client', () => ({
  apiClient: { get: (...args: unknown[]) => apiGet(...args) },
  default: { get: (...args: unknown[]) => apiGet(...args) },
}))

function makeEvent(overrides: Partial<EventDetailData> = {}): EventDetailData {
  return {
    id: 42,
    event_type: 'file_modified',
    path: '/etc/passwd',
    hash_detected: 'deadbeef',
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
    is_symlink: false,
    symlink_target: null,
    action_failed: false,
    action_error: null,
    action_type: 'manual_review',
    ...overrides,
  }
}

/** Respuesta por defecto para GET /events/{id}/chain — cadena de un solo evento (US-10). */
function makeChainResponse(overrides: { path?: string | null; items?: unknown[] } = {}) {
  return { path: overrides.path ?? '/etc/passwd', items: overrides.items ?? [] }
}

/** Enruta apiGet según la URL: /chain va a la cadena, cualquier otra al detalle. */
function mockDetailAndChain(
  event: EventDetailData,
  chain: ReturnType<typeof makeChainResponse> = makeChainResponse()
) {
  apiGet.mockImplementation((url: string) => {
    if (url.includes('/chain')) return Promise.resolve({ data: chain })
    return Promise.resolve({ data: event })
  })
}

function renderDetail(id: number) {
  return renderWithProviders(
    <Routes>
      <Route path="/events/:id" element={<EventDetail />} />
    </Routes>,
    { route: `/events/${id}` }
  )
}

describe('EventDetail — evento sin ruta (D51/RN-145)', () => {
  beforeEach(() => {
    apiGet.mockReset()
  })

  it('el detalle de un evento sin ruta muestra el tipo de evento y su causa, no rompe al renderizar', async () => {
    apiGet.mockResolvedValue({
      data: makeEvent({ id: 7, path: null, event_type: 'detection_gap' }),
    })

    renderDetail(7)

    await waitFor(() => expect(apiGet).toHaveBeenCalled())
    expect(await screen.findByText('Brecha de detección')).toBeInTheDocument()
    expect(screen.getByText(/desbordó su cola de eventos fanotify/)).toBeInTheDocument()
  })

  it('el detalle de un evento sin ruta omite el bloque de contexto de proceso cuando los tres campos son nulos', async () => {
    apiGet.mockResolvedValue({
      data: makeEvent({
        id: 8,
        path: null,
        event_type: 'detection_gap',
        process_pid: null,
        process_uid: null,
        process_exe: null,
      }),
    })

    renderDetail(8)

    await screen.findByText('Brecha de detección')
    expect(screen.queryByText('Proceso que generó el evento')).not.toBeInTheDocument()
  })

  it('el detalle de un evento con ruta renderiza igual que antes (no regresión)', async () => {
    apiGet.mockResolvedValue({ data: makeEvent({ id: 9, path: '/etc/hosts' }) })

    renderDetail(9)

    expect(await screen.findByText('/etc/hosts')).toBeInTheDocument()
    expect(screen.queryByText('Brecha de detección')).not.toBeInTheDocument()
  })

  it('renderiza el diff textual real recibido por la API', async () => {
    apiGet.mockResolvedValue({
      data: makeEvent({
        id: 10,
        diff_text: '--- a/etc/hosts\n+++ b/etc/hosts\n@@ -1 +1 @@\n-old value\n+new value\n',
      }),
    })

    renderDetail(10)

    const viewer = await screen.findByTestId('content-diff')
    expect(viewer).toHaveTextContent('old value')
    expect(viewer).toHaveTextContent('new value')
  })

  it('declara la ausencia sin presentar hashes como diff', async () => {
    apiGet.mockResolvedValue({
      data: makeEvent({ id: 11, hash_expected: 'expected', diff_text: null }),
    })

    renderDetail(11)

    expect(await screen.findByText('Diff textual no disponible para este evento.')).toBeInTheDocument()
    expect(screen.queryByTestId('content-diff')).not.toBeInTheDocument()
  })

  it('muestra comparación de hashes y hex dump para un evento binario', async () => {
    apiGet.mockResolvedValue({
      data: makeEvent({
        id: 12,
        diff_text: null,
        is_binary: true,
        hash_expected: 'aaaa',
        hash_detected: 'bbbb',
        hex_dump_before: '00000000  89 50 4e 47',
        hex_dump_after: '00000000  ff ee dd cc',
      }),
    })

    renderDetail(12)

    const binaryView = await screen.findByTestId('binary-diff')
    expect(binaryView).toHaveTextContent('89 50 4e 47')
    expect(binaryView).toHaveTextContent('ff ee dd cc')
    expect(screen.queryByTestId('content-diff')).not.toBeInTheDocument()
  })
})

describe('EventDetail — US-08 (tipo de acción, severidad, fecha de creación, cadena)', () => {
  beforeEach(() => {
    apiGet.mockReset()
  })

  it('muestra el tipo de acción, la severidad y la fecha de creación', async () => {
    mockDetailAndChain(
      makeEvent({ id: 12, action_type: 'auto_restore', severity: 'critical', created_at: '2026-08-20T10:00:00Z' })
    )

    renderDetail(12)

    expect(await screen.findByText('auto_restore')).toBeInTheDocument()
    expect(screen.getByText('critical')).toBeInTheDocument()
    expect(screen.getByText('Fecha de creación')).toBeInTheDocument()
  })

  it('si el evento tiene parent_event_id, muestra un enlace al evento padre', async () => {
    mockDetailAndChain(makeEvent({ id: 13, parent_event_id: 5 }))

    renderDetail(13)

    const parentLink = await screen.findByRole('link', { name: /evento padre/i })
    expect(parentLink).toHaveAttribute('href', '/events/5')
  })

  it('sin parent_event_id no muestra enlace al evento padre', async () => {
    mockDetailAndChain(makeEvent({ id: 14, parent_event_id: null }))

    renderDetail(14)

    await screen.findByText('/etc/passwd')
    expect(screen.queryByRole('link', { name: /evento padre/i })).not.toBeInTheDocument()
  })

  it('si el evento pertenece a una cadena de más de un elemento, indica su posición y permite navegar a la cadena (US-10)', async () => {
    mockDetailAndChain(
      makeEvent({ id: 20, path: '/etc/passwd' }),
      makeChainResponse({
        path: '/etc/passwd',
        items: [{ id: 18 }, { id: 20 }, { id: 21 }],
      })
    )

    renderDetail(20)

    expect(await screen.findByText(/posici[oó]n 2 de 3/i)).toBeInTheDocument()
    const chainLink = screen.getByRole('link', { name: /ver cadena/i })
    expect(chainLink).toHaveAttribute('href', '/events/20/chain')
  })

  it('si la cadena tiene un solo evento, no muestra el indicador de posición', async () => {
    mockDetailAndChain(
      makeEvent({ id: 30, path: '/etc/passwd' }),
      makeChainResponse({ path: '/etc/passwd', items: [{ id: 30 }] })
    )

    renderDetail(30)

    await screen.findByText('/etc/passwd')
    expect(screen.queryByText(/posici[oó]n/i)).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /ver cadena/i })).not.toBeInTheDocument()
  })

  it('un evento sin path (detection_gap) no dispara la consulta de cadena', async () => {
    apiGet.mockImplementation((url: string) => {
      if (url.includes('/chain')) {
        throw new Error('no debería consultarse la cadena para un evento sin path')
      }
      return Promise.resolve({ data: makeEvent({ id: 40, path: null, event_type: 'detection_gap' }) })
    })

    renderDetail(40)

    expect(await screen.findByText('Brecha de detección')).toBeInTheDocument()
    expect(screen.queryByText(/posici[oó]n/i)).not.toBeInTheDocument()
  })
})
