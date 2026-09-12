import { describe, it, expect, beforeEach, vi } from 'vitest'
import { screen, within } from '@testing-library/react'
import { Routes, Route } from 'react-router-dom'
import { renderWithProviders } from '@/test/renderWithProviders'
import { EventChain } from './EventChain'
import type { EventListItem } from '@/api/events'

// US-10: cadena de eventos del mismo path — vista dedicada accesible desde
// el detalle de un evento (US-08). Mismo patrón de mock de @/api/client que
// EventDetail.test.tsx y Events.test.tsx.

const { apiGet } = vi.hoisted(() => ({ apiGet: vi.fn() }))

vi.mock('@/api/client', () => ({
  apiClient: { get: (...args: unknown[]) => apiGet(...args) },
  default: { get: (...args: unknown[]) => apiGet(...args) },
}))

function makeItem(overrides: Partial<EventListItem> = {}): EventListItem {
  return {
    id: 1,
    event_type: 'file_modified',
    path: '/etc/passwd',
    hash_detected: 'deadbeef',
    status: 'superseded',
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

function renderChain(id: number) {
  return renderWithProviders(
    <Routes>
      <Route path="/events/:id/chain" element={<EventChain />} />
    </Routes>,
    { route: `/events/${id}/chain` }
  )
}

describe('EventChain (US-10)', () => {
  beforeEach(() => {
    apiGet.mockReset()
  })

  it('muestra todos los eventos de la cadena ordenados cronológicamente', async () => {
    apiGet.mockResolvedValue({
      data: {
        path: '/etc/passwd',
        items: [
          makeItem({ id: 1, status: 'superseded', created_at: '2026-08-20T10:00:00Z' }),
          makeItem({ id: 2, status: 'superseded', parent_event_id: 1, created_at: '2026-08-20T11:00:00Z' }),
          makeItem({ id: 3, status: 'pending', parent_event_id: 2, created_at: '2026-08-20T12:00:00Z' }),
        ],
      },
    })

    renderChain(3)

    const rows = await screen.findAllByTestId('chain-item')
    expect(rows).toHaveLength(3)
    expect(rows[0]).toHaveTextContent('#1')
    expect(rows[1]).toHaveTextContent('#2')
    expect(rows[2]).toHaveTextContent('#3')
  })

  it('cada evento de la cadena es navegable hacia su detalle', async () => {
    apiGet.mockResolvedValue({
      data: { path: '/etc/passwd', items: [makeItem({ id: 5 })] },
    })

    renderChain(5)

    const link = await screen.findByRole('link', { name: 'Ver #5' })
    expect(link).toHaveAttribute('href', '/events/5')
  })

  it('marca los eventos superseded con ícono de cadena rota y referencia a su parent_event_id', async () => {
    apiGet.mockResolvedValue({
      data: {
        path: '/etc/passwd',
        items: [
          makeItem({ id: 1, status: 'superseded', parent_event_id: null }),
          makeItem({ id: 2, status: 'pending', parent_event_id: 1 }),
        ],
      },
    })

    renderChain(2)

    const supersededRow = (await screen.findAllByTestId('chain-item'))[0]
    expect(supersededRow).toHaveTextContent('superseded')
    expect(within(supersededRow).getByTestId('broken-chain-icon')).toBeInTheDocument()

    const activeRow = (await screen.findAllByTestId('chain-item'))[1]
    expect(activeRow.querySelector('[data-testid="broken-chain-icon"]')).toBeNull()
    expect(activeRow).toHaveTextContent('padre: #1')
  })
})
