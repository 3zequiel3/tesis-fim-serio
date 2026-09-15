import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { RejectModal } from './RejectModal'
import type { EventListItem } from '@/api/events'

// US-12, C10 (D-8): con baseline_status='absent' el modal oculta las opciones
// de acción correctiva y muestra el texto literal del criterio; con 'present'
// o null (ausencia del dato) se comporta como hoy.

function makeEvent(overrides: Partial<EventListItem> = {}): EventListItem {
  return {
    id: 1,
    event_type: 'file_modified',
    path: '/etc/passwd',
    hash_detected: 'abc123',
    status: 'pending',
    severity: 'high',
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
    is_symlink: false,
    symlink_target: null,
    action_failed: false,
    baseline_status: null,
    ...overrides,
  }
}

describe('RejectModal — US-12 C10 (baseline_status)', () => {
  it('con baseline_status=absent no renderiza los radios y muestra el texto literal de C10', () => {
    render(
      <RejectModal
        event={makeEvent({ baseline_status: 'absent' })}
        open
        onClose={vi.fn()}
        onConfirm={vi.fn()}
      />
    )

    expect(screen.queryByLabelText(/Restaurar archivo/)).not.toBeInTheDocument()
    expect(screen.queryByLabelText(/Poner en cuarentena/)).not.toBeInTheDocument()
    expect(
      screen.getByText(
        'No hay archivo a restaurar (baseline ausente). Confirmar rechazará el evento sin acción en filesystem.'
      )
    ).toBeInTheDocument()
    // Confirmar / Cancelar se conservan.
    expect(screen.getByRole('button', { name: 'Cancelar' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Confirmar rechazo' })).toBeInTheDocument()
  })

  it('con baseline_status=present renderiza los radios de acción correctiva', () => {
    render(
      <RejectModal
        event={makeEvent({ baseline_status: 'present' })}
        open
        onClose={vi.fn()}
        onConfirm={vi.fn()}
      />
    )

    expect(screen.getByLabelText(/Restaurar archivo/)).toBeInTheDocument()
    expect(screen.getByLabelText(/Poner en cuarentena/)).toBeInTheDocument()
    expect(
      screen.queryByText(/No hay archivo a restaurar/)
    ).not.toBeInTheDocument()
  })

  it('con baseline_status=null (evento sin path baselineado) renderiza los radios como hoy', () => {
    render(
      <RejectModal
        event={makeEvent({ baseline_status: null })}
        open
        onClose={vi.fn()}
        onConfirm={vi.fn()}
      />
    )

    expect(screen.getByLabelText(/Restaurar archivo/)).toBeInTheDocument()
    expect(screen.getByLabelText(/Poner en cuarentena/)).toBeInTheDocument()
  })
})
