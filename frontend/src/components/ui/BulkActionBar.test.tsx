import { useState } from 'react'
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
    event_type: 'file_modified',
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
      <BulkActionBar selected={selected} items={items} filters={{}} onSelectionChange={vi.fn()} />
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

  it('el modal resume la cantidad, muestra sólo los primeros 10 paths y anuncia el excedente', async () => {
    const user = userEvent.setup()
    const items = Array.from({ length: 12 }, (_, index) => makeItem(index + 1))
    const selected = new Set(items.map((item) => item.id))

    renderWithProviders(
      <BulkActionBar selected={selected} items={items} filters={{}} onSelectionChange={vi.fn()} />
    )

    expect(screen.getByText('12 eventos seleccionados')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Aprobar seleccionados' }))

    expect(screen.getByRole('heading', { name: 'Confirmar aprobación masiva' })).toBeInTheDocument()
    for (let id = 1; id <= 10; id += 1) {
      expect(screen.getByText(`• /etc/file-${id}`)).toBeInTheDocument()
    }
    expect(screen.queryByText('• /etc/file-11')).not.toBeInTheDocument()
    expect(screen.queryByText('• /etc/file-12')).not.toBeInTheDocument()
    expect(screen.getByText('... y 2 más')).toBeInTheDocument()
  })

  it('muestra un resumen expandible por evento y conserva seleccionados sólo los fallidos', async () => {
    const user = userEvent.setup()
    const items = [makeItem(1), makeItem(2)]
    const onSelectionChange = vi.fn()
    apiPost.mockResolvedValue({
      data: {
        succeeded: [1],
        failed: [{ event_id: 2, reason: 'conflict' }],
      },
    })

    const { queryClient } = renderWithProviders(
      <BulkActionBar
        selected={new Set([1, 2])}
        items={items}
        filters={{}}
        onSelectionChange={onSelectionChange}
      />
    )
    const invalidate = vi.spyOn(queryClient, 'invalidateQueries')

    await user.click(screen.getByRole('button', { name: 'Aprobar seleccionados' }))
    await user.click(screen.getByRole('button', { name: 'Aprobar' }))

    const detailsButton = await screen.findByRole('button', { name: 'Ver detalle del resultado' })
    expect(detailsButton).toHaveAttribute('aria-expanded', 'false')
    expect(onSelectionChange).toHaveBeenCalledTimes(1)
    const updateSelection = onSelectionChange.mock.calls[0][0]
    expect(updateSelection(new Set([1, 2]))).toEqual(new Set([2]))
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['events'] })

    await user.click(detailsButton)

    expect(detailsButton).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByText('/etc/file-1')).toBeInTheDocument()
    expect(screen.getByText('Correcto')).toBeInTheDocument()
    expect(screen.getByText('/etc/file-2')).toBeInTheDocument()
    expect(screen.getByText('Falló: conflict')).toBeInTheDocument()
  })

  it('aplica el resultado sobre la selección actual sin perder cambios hechos durante la petición', async () => {
    const user = userEvent.setup()
    const items = [makeItem(1), makeItem(2), makeItem(3)]
    let resolveRequest!: (value: {
      data: { succeeded: number[]; failed: Array<{ event_id: number; reason: string }> }
    }) => void
    apiPost.mockReturnValue(new Promise((resolve) => { resolveRequest = resolve }))

    function Harness() {
      const [selected, setSelected] = useState(new Set([1, 2]))
      return (
        <>
          <BulkActionBar
            selected={selected}
            items={items}
            filters={{}}
            onSelectionChange={setSelected}
          />
          <button onClick={() => setSelected(new Set([3]))}>
            Cambiar selección durante la petición
          </button>
          <output aria-label="selección actual">{[...selected].sort().join(',')}</output>
        </>
      )
    }

    renderWithProviders(<Harness />)
    await user.click(screen.getByRole('button', { name: 'Aprobar seleccionados' }))
    await user.click(screen.getByRole('button', { name: 'Aprobar' }))
    await user.click(screen.getByRole('button', { name: 'Cambiar selección durante la petición' }))

    resolveRequest({
      data: { succeeded: [1], failed: [{ event_id: 2, reason: 'conflict' }] },
    })

    await screen.findByRole('button', { name: 'Ver detalle del resultado' })
    expect(screen.getByLabelText('selección actual')).toHaveTextContent('3')
  })
})
