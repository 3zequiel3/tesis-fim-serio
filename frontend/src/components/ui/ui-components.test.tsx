import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { mockApiError } from '@/test/mockApiError'
import { Button } from './Button'
import { DataState } from './DataState'
import { HashChip, formatHash } from './HashChip'
import { Modal } from './Modal'
import { PathLabel, splitPath } from './PathLabel'
import { ResponsiveTable } from './ResponsiveTable'
import { KNOWN_STATUSES, StatusBadge } from './StatusBadge'

describe('StatusBadge', () => {
  it.each(KNOWN_STATUSES)('shows the canonical text and an icon for %s', (status) => {
    const { container } = render(<StatusBadge status={status} />)
    const badge = screen.getByText(status)
    expect(badge).toBeInTheDocument()
    // Never color alone: the badge carries an svg icon too.
    expect(container.querySelector('svg')).not.toBeNull()
  })

  it('covers exactly the seven RN-71 states', () => {
    expect(KNOWN_STATUSES.sort()).toEqual(
      ['alert_only', 'approved', 'auto_restored', 'pending', 'quarantined', 'rejected', 'superseded'].sort(),
    )
  })

  it('shows an unknown value literally with the neutral style', () => {
    const { container } = render(<StatusBadge status="mystery_state" />)
    expect(screen.getByText('mystery_state').className).toContain('text-neutral-fg')
    expect(container.querySelector('svg')).not.toBeNull()
  })
})

describe('PathLabel and HashChip', () => {
  it('splits the directory from the file name', () => {
    expect(splitPath('/etc/ssh/sshd_config')).toEqual({ dir: '/etc/ssh/', name: 'sshd_config' })
    expect(splitPath('/etc/ssh/')).toEqual({ dir: '/etc/', name: 'ssh/' })
    expect(splitPath('file')).toEqual({ dir: '', name: 'file' })
  })

  it('exposes the full path once as text while styling the split', () => {
    render(<PathLabel path="/etc/ssh/sshd_config" />)
    expect(screen.getByText('/etc/ssh/sshd_config')).toBeInTheDocument()
  })

  it('renders a dash for a null path instead of crashing', () => {
    render(<PathLabel path={null} />)
    expect(screen.getByText('—')).toBeInTheDocument()
  })

  it('groups the first 8 hex in two blocks of 4 and keeps the full hash in the title', () => {
    expect(formatHash('a3f91c02deadbeef')).toBe('a3f9 1c02')
    expect(formatHash('sha256:a3f91c02deadbeef')).toBe('a3f9 1c02')
    render(<HashChip hash="a3f91c02deadbeef" />)
    expect(screen.getByRole('button')).toHaveAttribute('title', 'a3f91c02deadbeef')
  })

  it('copies the full hash on click', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })
    render(<HashChip hash="a3f91c02deadbeef" />)
    await userEvent.click(screen.getByRole('button'))
    expect(writeText).toHaveBeenCalledWith('a3f91c02deadbeef')
  })
})

describe('Button', () => {
  it('is disabled and busy while loading', () => {
    render(<Button loading>Guardar</Button>)
    expect(screen.getByRole('button', { name: 'Guardar' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Guardar' })).toHaveAttribute('aria-busy', 'true')
  })
})

describe('DataState', () => {
  it('shows a loading status', () => {
    render(<DataState isLoading>contenido</DataState>)
    expect(screen.getByRole('status')).toHaveTextContent('Cargando')
    expect(screen.queryByText('contenido')).toBeNull()
  })

  it('shows the empty state', () => {
    render(
      <DataState isLoading={false} isEmpty emptyTitle="Sin reglas" emptyHint="Creá la primera.">
        contenido
      </DataState>,
    )
    expect(screen.getByText('Sin reglas')).toBeInTheDocument()
    expect(screen.getByText('Creá la primera.')).toBeInTheDocument()
  })

  it('shows the error with Reintentar and calls onRetry', async () => {
    const onRetry = vi.fn()
    render(
      <DataState isLoading={false} error={mockApiError(500, 'boom')} onRetry={onRetry} resource="las reglas">
        contenido
      </DataState>,
    )
    expect(screen.getByRole('alert')).toHaveTextContent('No se pudieron cargar las reglas.')
    await userEvent.click(screen.getByRole('button', { name: 'Reintentar' }))
    expect(onRetry).toHaveBeenCalledTimes(1)
  })

  it('shows the permission message for a 403 and offers no retry', () => {
    render(
      <DataState isLoading={false} error={mockApiError(403, 'Forbidden')} onRetry={() => undefined}>
        contenido
      </DataState>,
    )
    expect(screen.getByRole('alert')).toHaveTextContent('No tenés permiso para ver esta sección.')
    expect(screen.queryByRole('button', { name: 'Reintentar' })).toBeNull()
  })

  it('does not stay loading when an error arrives', () => {
    render(
      <DataState isLoading error={mockApiError(500, 'boom')}>
        contenido
      </DataState>,
    )
    expect(screen.queryByRole('status')).toBeNull()
    expect(screen.getByRole('alert')).toBeInTheDocument()
  })
})

function ModalHarness({ busy = false, onClose = () => undefined }: { busy?: boolean; onClose?: () => void }) {
  const [open, setOpen] = useState(false)
  return (
    <div>
      <button onClick={() => setOpen(true)}>Abrir</button>
      {open && (
        <Modal
          title="Rechazar evento"
          busy={busy}
          onClose={() => {
            onClose()
            setOpen(false)
          }}
        >
          <input aria-label="Motivo" />
          <button>Confirmar</button>
        </Modal>
      )}
    </div>
  )
}

describe('Modal', () => {
  it('is a labelled modal dialog with the first control focused', async () => {
    render(<ModalHarness />)
    await userEvent.click(screen.getByRole('button', { name: 'Abrir' }))
    const dialog = screen.getByRole('dialog', { name: 'Rechazar evento' })
    expect(dialog).toHaveAttribute('aria-modal', 'true')
    expect(within(dialog).getByLabelText('Motivo')).toHaveFocus()
  })

  it('traps focus: Tab from the last control returns to the first', async () => {
    render(<ModalHarness />)
    await userEvent.click(screen.getByRole('button', { name: 'Abrir' }))
    const dialog = screen.getByRole('dialog')
    within(dialog).getByRole('button', { name: 'Cerrar' }).focus()
    await userEvent.tab()
    expect(within(dialog).getByLabelText('Motivo')).toHaveFocus()
  })

  it('returns focus to the opener when it closes', async () => {
    render(<ModalHarness />)
    const opener = screen.getByRole('button', { name: 'Abrir' })
    await userEvent.click(opener)
    await userEvent.keyboard('{Escape}')
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(opener).toHaveFocus()
  })

  it('ignores Escape, the close button and outside clicks while a mutation is running', async () => {
    const onClose = vi.fn()
    render(<ModalHarness busy onClose={onClose} />)
    await userEvent.click(screen.getByRole('button', { name: 'Abrir' }))
    await userEvent.keyboard('{Escape}')
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Cerrar' })).toBeDisabled()
    expect(onClose).not.toHaveBeenCalled()
  })
})

describe('ResponsiveTable', () => {
  const columns = [
    { key: 'name', header: 'Nombre', primary: true, cell: (r: { name: string; n: number }) => r.name },
    { key: 'n', header: 'Cantidad', cell: (r: { name: string; n: number }) => String(r.n) },
  ]
  const rows = [{ name: 'uno', n: 1 }]

  function mockWidth(wide: boolean) {
    window.matchMedia = ((q: string) => ({
      matches: wide,
      media: q,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
    })) as unknown as typeof window.matchMedia
  }

  it('renders a table from 640 px', () => {
    mockWidth(true)
    render(<ResponsiveTable caption="Cosas" columns={columns} rows={rows} getRowKey={(r) => r.name} />)
    expect(screen.getByRole('table', { name: 'Cosas' })).toBeInTheDocument()
  })

  it('renders cards below 640 px with the same columns', () => {
    mockWidth(false)
    render(<ResponsiveTable caption="Cosas" columns={columns} rows={rows} getRowKey={(r) => r.name} />)
    expect(screen.queryByRole('table')).toBeNull()
    expect(screen.getByRole('list', { name: 'Cosas' })).toBeInTheDocument()
    expect(screen.getByText('Cantidad')).toBeInTheDocument()
    expect(screen.getByText('uno')).toBeInTheDocument()
  })
})
