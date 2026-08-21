import { describe, it, expect, beforeEach, vi } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithProviders } from '@/test/renderWithProviders'
import { BulkActionBar } from './BulkActionBar'
import type { EventListItem } from '@/api/events'

// Este es el test que habría atrapado el defecto original (8.7): tiene que
// fallar si alguien revierte 6.2 y vuelve a mandar `action` al nivel
// superior del cuerpo en vez de por ítem.

const { apiPost } = vi.hoisted(() => ({ apiPost: vi.fn() }))

vi.mock('@/api/client', () => ({
  apiClient: { post: (...args: unknown[]) => apiPost(...args) },
  default: { post: (...args: unknown[]) => apiPost(...args) },
}))

function makeItem(id: number): EventListItem {
  return {
    id,
    path: `/etc/file-${id}`,
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
  }
}

describe('BulkActionBar — bulk reject con acción por ítem (8.7)', () => {
  beforeEach(() => {
    apiPost.mockReset()
    apiPost.mockResolvedValue({ data: { succeeded: [1, 2, 3], failed: [], baseline_absent: {} } })
  })

  it('rechazar 3 eventos con "quarantine" produce 3 ítems con action:"quarantine" cada uno, sin action al nivel superior', async () => {
    const user = userEvent.setup()
    const items = [makeItem(1), makeItem(2), makeItem(3)]
    const selected = new Set([1, 2, 3])

    renderWithProviders(
      <BulkActionBar selected={selected} items={items} filters={{}} onClearSelection={vi.fn()} />
    )

    await user.click(screen.getByRole('button', { name: /rechazar seleccionados/i }))
    await user.click(screen.getByLabelText(/poner en cuarentena/i))
    await user.click(screen.getByRole('button', { name: /^rechazar$/i }))

    await waitFor(() => expect(apiPost).toHaveBeenCalledWith('/actions/bulk-reject', expect.anything()))

    const [, body] = apiPost.mock.calls[0]
    expect(body.action).toBeUndefined()
    expect(body.items).toHaveLength(3)
    for (const item of body.items) {
      expect(item.action).toBe('quarantine')
    }
    expect(body.items.map((i: { event_id: number }) => i.event_id).sort()).toEqual([1, 2, 3])
  })
})
