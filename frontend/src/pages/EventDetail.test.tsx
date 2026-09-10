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
    ...overrides,
  }
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
})
