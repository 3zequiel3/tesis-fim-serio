import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ReleaseQuarantineModal } from './ReleaseQuarantineModal'

// D83/RN-177: el modal obliga a elegir modo y escribir motivo, explica la
// consecuencia de cada modo y advierte que restore_original APRUEBA.

function renderModal(onConfirm = vi.fn(), props: { isPending?: boolean } = {}) {
  render(
    <ReleaseQuarantineModal
      path="/etc/passwd"
      open
      onClose={vi.fn()}
      onConfirm={onConfirm}
      {...props}
    />,
  )
  return onConfirm
}

const confirmButton = () => screen.getByRole('button', { name: 'Confirmar liberación' })

describe('ReleaseQuarantineModal', () => {
  it('no renderiza nada con open=false', () => {
    render(<ReleaseQuarantineModal path="/x" open={false} onClose={vi.fn()} onConfirm={vi.fn()} />)
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('ofrece los tres modos, cada uno con su consecuencia', () => {
    renderModal()
    expect(screen.getByLabelText(/Restaurar el archivo original/)).toBeInTheDocument()
    expect(screen.getByLabelText(/Restaurar la versión aprobada/)).toBeInTheDocument()
    expect(screen.getByLabelText(/Descartar el archivo cuarentenado/)).toBeInTheDocument()
    expect(screen.getByText(/lo APRUEBA/)).toBeInTheDocument()
    expect(screen.getByText(/el baseline no cambia/)).toBeInTheDocument()
  })

  it('la confirmación está deshabilitada sin modo y sin motivo', async () => {
    const user = userEvent.setup()
    renderModal()
    expect(confirmButton()).toBeDisabled()

    await user.click(screen.getByLabelText(/Descartar/))
    expect(confirmButton()).toBeDisabled() // modo sin motivo

    await user.type(screen.getByLabelText(/Motivo/), '   ')
    expect(confirmButton()).toBeDisabled() // motivo sólo de espacios

    await user.type(screen.getByLabelText(/Motivo/), 'falso positivo')
    expect(confirmButton()).toBeEnabled()
  })

  it('un motivo sin modo tampoco habilita la confirmación', async () => {
    const user = userEvent.setup()
    renderModal()
    await user.type(screen.getByLabelText(/Motivo/), 'falso positivo')
    expect(confirmButton()).toBeDisabled()
  })

  it.each([
    ['Restaurar el archivo original', 'restore_original'],
    ['Restaurar la versión aprobada', 'restore_baseline'],
    ['Descartar el archivo cuarentenado', 'discard'],
  ])('confirmar %s envía modo %s y el motivo recortado', async (label, mode) => {
    const user = userEvent.setup()
    const onConfirm = renderModal()
    await user.click(screen.getByLabelText(new RegExp(label)))
    await user.type(screen.getByLabelText(/Motivo/), '  falso positivo  ')
    await user.click(confirmButton())
    expect(onConfirm).toHaveBeenCalledWith(mode, 'falso positivo')
  })

  it('advierte que restore_original aprueba, y sólo con ese modo', async () => {
    const user = userEvent.setup()
    renderModal()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()

    await user.click(screen.getByLabelText(/Restaurar el archivo original/))
    expect(screen.getByRole('alert')).toHaveTextContent(/lo aprueba/)

    await user.click(screen.getByLabelText(/Descartar/))
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('con isPending deshabilita la confirmación', async () => {
    const user = userEvent.setup()
    renderModal(vi.fn(), { isPending: true })
    await user.click(screen.getByLabelText(/Descartar/))
    await user.type(screen.getByLabelText(/Motivo/), 'x')
    expect(screen.getByRole('button', { name: 'Procesando...' })).toBeDisabled()
  })
})
