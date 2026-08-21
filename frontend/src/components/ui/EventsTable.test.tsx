import { describe, it, expect, vi } from 'vitest'
import { screen } from '@testing-library/react'
import { renderWithProviders } from '@/test/renderWithProviders'
import { EventsTable } from './EventsTable'
import type { EventListItem } from '@/api/events'

// D-1/D-7 del design de frontend-severity-triage: aserciones sobre lo que
// el operador VE (texto, presencia/ausencia de clase, contenido de la
// sublínea), nunca sobre clases de Tailwind como fin en sí mismo — un test
// que afirma `border-l-red-500` se rompe con un retoque de paleta y no dice
// nada sobre si el operador puede distinguir un `critical`.

function makeItem(overrides: Partial<EventListItem> = {}): EventListItem {
  return {
    id: 1,
    path: '/etc/passwd',
    hash_detected: 'deadbeef',
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

const noop = vi.fn()

describe('EventsTable — severidad (8.1, 8.2)', () => {
  it('la fila de un critical muestra el texto "critical" y la de un low muestra "low"', () => {
    const items = [makeItem({ id: 1, severity: 'critical' }), makeItem({ id: 2, severity: 'low' })]
    renderWithProviders(<EventsTable items={items} selected={new Set()} onSelectionChange={noop} />)

    expect(screen.getByText('critical')).toBeInTheDocument()
    expect(screen.getByText('low')).toBeInTheDocument()
  })

  it('la fila de un critical y la de un low no comparten la clase de banda de borde', () => {
    const items = [
      makeItem({ id: 1, path: '/etc/passwd', severity: 'critical' }),
      makeItem({ id: 2, path: '/etc/hosts', severity: 'low' }),
    ]
    renderWithProviders(<EventsTable items={items} selected={new Set()} onSelectionChange={noop} />)

    const criticalRow = screen.getByText('/etc/passwd').closest('tr')!
    const lowRow = screen.getByText('/etc/hosts').closest('tr')!

    expect(criticalRow.className).not.toBe(lowRow.className)
  })
})

describe('EventsTable — contenido de fila (US-06)', () => {
  it('una fila muestra path, estado, severidad y fecha juntos', () => {
    const items = [makeItem({ path: '/var/log/auth.log', status: 'pending', severity: 'high' })]
    renderWithProviders(<EventsTable items={items} selected={new Set()} onSelectionChange={noop} />)

    const row = screen.getByText('/var/log/auth.log').closest('tr')!
    expect(row).toHaveTextContent('pending')
    expect(row).toHaveTextContent('high')
    // formatAbsolute siempre incluye el año — suficiente para confirmar que
    // la celda de fecha está presente sin acoplar el test al formato exacto.
    expect(row).toHaveTextContent('2026')
  })
})

describe('EventsTable — proceso causante (8.3)', () => {
  it('una fila con contexto de proceso muestra el ejecutable, el pid y el uid', () => {
    const items = [
      makeItem({ process_exe: '/usr/bin/vim', process_pid: 4242, process_uid: 0 }),
    ]
    renderWithProviders(<EventsTable items={items} selected={new Set()} onSelectionChange={noop} />)

    expect(screen.getByText(/\/usr\/bin\/vim/)).toBeInTheDocument()
    expect(screen.getByText(/4242/)).toBeInTheDocument()
    expect(screen.getByText(/uid 0/)).toBeInTheDocument()
  })

  it('un evento sin contexto de proceso no renderiza la sublínea ni el texto "null"', () => {
    const items = [
      makeItem({ process_exe: null, process_pid: null, process_uid: null }),
    ]
    const { container } = renderWithProviders(
      <EventsTable items={items} selected={new Set()} onSelectionChange={noop} />
    )

    expect(container.textContent).not.toMatch(/null/i)
    // Sólo debe existir la fila de path, sin una segunda línea de proceso.
    expect(screen.queryByText(/pid/)).not.toBeInTheDocument()
  })
})
