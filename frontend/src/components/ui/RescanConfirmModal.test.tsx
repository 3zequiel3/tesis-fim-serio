import { describe, it, expect, vi } from 'vitest'
import { screen } from '@testing-library/react'
import { renderWithProviders } from '@/test/renderWithProviders'
import { RescanConfirmModal } from './RescanConfirmModal'

// US-22: el diálogo de confirmación de rescan forzado debe listar los paths
// seleccionados, no solo la cantidad de eventos pending que serán marcados
// como superseded (historias_de_usuario.md, US-22 criterio 2).

const noop = () => undefined

describe('RescanConfirmModal — paths seleccionados (US-22)', () => {
  it('lista los paths seleccionados cuando el rescan está acotado', () => {
    renderWithProviders(
      <RescanConfirmModal
        pendingCount={2}
        paths={['/etc', '/opt/app']}
        onConfirm={noop}
        onCancel={noop}
      />
    )
    expect(screen.getByText('/etc')).toBeInTheDocument()
    expect(screen.getByText('/opt/app')).toBeInTheDocument()
  })

  it('sin paths (rescan de todos los watch_paths) no muestra ninguna lista', () => {
    renderWithProviders(
      <RescanConfirmModal pendingCount={3} onConfirm={noop} onCancel={noop} />
    )
    expect(screen.queryByRole('list')).not.toBeInTheDocument()
  })

  it('confirmar dispara onConfirm', async () => {
    const onConfirm = vi.fn()
    const { default: userEvent } = await import('@testing-library/user-event')
    const user = userEvent.setup()
    renderWithProviders(
      <RescanConfirmModal pendingCount={1} paths={['/etc']} onConfirm={onConfirm} onCancel={noop} />
    )
    await user.click(screen.getByRole('button', { name: /forzar rescan/i }))
    expect(onConfirm).toHaveBeenCalled()
  })
})
