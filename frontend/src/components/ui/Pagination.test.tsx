import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Pagination } from './Pagination'

// US-26: navegación numerada (primera/anterior/números/siguiente/última) +
// input "ir a página" con validación (1..totalPages).

describe('Pagination — US-26 navegación numerada', () => {
  it('muestra primera, anterior, siguiente y última', () => {
    render(<Pagination currentPage={3} totalPages={10} onPageChange={vi.fn()} />)

    expect(screen.getByRole('button', { name: /primera/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /anterior/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /siguiente/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /última/i })).toBeInTheDocument()
  })

  it('muestra botones numerados y marca la página actual', () => {
    render(<Pagination currentPage={3} totalPages={5} onPageChange={vi.fn()} />)

    for (const n of [1, 2, 3, 4, 5]) {
      expect(screen.getByRole('button', { name: String(n) })).toBeInTheDocument()
    }
    expect(screen.getByRole('button', { name: '3' })).toHaveAttribute('aria-current', 'page')
    expect(screen.getByRole('button', { name: '2' })).not.toHaveAttribute('aria-current')
  })

  it('deshabilita primera/anterior en la página 1', () => {
    render(<Pagination currentPage={1} totalPages={5} onPageChange={vi.fn()} />)

    expect(screen.getByRole('button', { name: /primera/i })).toBeDisabled()
    expect(screen.getByRole('button', { name: /anterior/i })).toBeDisabled()
    expect(screen.getByRole('button', { name: /siguiente/i })).not.toBeDisabled()
    expect(screen.getByRole('button', { name: /última/i })).not.toBeDisabled()
  })

  it('deshabilita siguiente/última en la última página', () => {
    render(<Pagination currentPage={5} totalPages={5} onPageChange={vi.fn()} />)

    expect(screen.getByRole('button', { name: /siguiente/i })).toBeDisabled()
    expect(screen.getByRole('button', { name: /última/i })).toBeDisabled()
    expect(screen.getByRole('button', { name: /primera/i })).not.toBeDisabled()
    expect(screen.getByRole('button', { name: /anterior/i })).not.toBeDisabled()
  })

  it('clickear un número de página dispara onPageChange con ese número', async () => {
    const onPageChange = vi.fn()
    const user = userEvent.setup()
    render(<Pagination currentPage={1} totalPages={5} onPageChange={onPageChange} />)

    await user.click(screen.getByRole('button', { name: '4' }))

    expect(onPageChange).toHaveBeenCalledWith(4)
  })

  it('clickear "última" dispara onPageChange con totalPages', async () => {
    const onPageChange = vi.fn()
    const user = userEvent.setup()
    render(<Pagination currentPage={1} totalPages={12} onPageChange={onPageChange} />)

    await user.click(screen.getByRole('button', { name: /última/i }))

    expect(onPageChange).toHaveBeenCalledWith(12)
  })

  it('el input "ir a página" navega a una página válida', async () => {
    const onPageChange = vi.fn()
    const user = userEvent.setup()
    render(<Pagination currentPage={1} totalPages={20} onPageChange={onPageChange} />)

    const input = screen.getByLabelText(/ir a página/i)
    await user.type(input, '15')
    await user.click(screen.getByRole('button', { name: /^ir$/i }))

    expect(onPageChange).toHaveBeenCalledWith(15)
  })

  it('el input "ir a página" rechaza un número fuera de rango sin navegar', async () => {
    const onPageChange = vi.fn()
    const user = userEvent.setup()
    render(<Pagination currentPage={1} totalPages={20} onPageChange={onPageChange} />)

    const input = screen.getByLabelText(/ir a página/i)
    await user.type(input, '999')
    await user.click(screen.getByRole('button', { name: /^ir$/i }))

    expect(onPageChange).not.toHaveBeenCalled()
    expect(screen.getByRole('alert')).toHaveTextContent(/entre 1 y 20/i)
  })

  it('el input "ir a página" rechaza un valor no numérico sin navegar', async () => {
    const onPageChange = vi.fn()
    const user = userEvent.setup()
    render(<Pagination currentPage={1} totalPages={20} onPageChange={onPageChange} />)

    const input = screen.getByLabelText(/ir a página/i)
    await user.type(input, '0')
    await user.click(screen.getByRole('button', { name: /^ir$/i }))

    expect(onPageChange).not.toHaveBeenCalled()
    expect(screen.getByRole('alert')).toBeInTheDocument()
  })
})
