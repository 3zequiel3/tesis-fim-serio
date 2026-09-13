import { describe, expect, it, vi } from 'vitest'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithProviders } from '@/test/renderWithProviders'
import { RuleForm } from './RuleForm'

describe('RuleForm accessibility labels', () => {
  it('associates every control with a visible label', () => {
    renderWithProviders(<RuleForm onSubmit={vi.fn()} onCancel={vi.fn()} />)
    expect(screen.getByLabelText(/^Pattern/)).toHaveAttribute('id', 'rule-pattern')
    expect(screen.getByLabelText('Severidad')).toHaveAttribute('id', 'rule-severity')
    expect(screen.getByLabelText('Acción')).toHaveAttribute('id', 'rule-action')
  })

  it('connects the required error to the pattern input', async () => {
    const user = userEvent.setup()
    renderWithProviders(<RuleForm onSubmit={vi.fn()} onCancel={vi.fn()} />)
    const pattern = screen.getByLabelText(/^Pattern/)
    expect(pattern).toHaveAttribute('aria-invalid', 'false')
    await user.click(screen.getByRole('button', { name: 'Crear regla' }))
    expect(pattern).toHaveAttribute('aria-invalid', 'true')
    expect(pattern).toHaveAccessibleDescription('El pattern no puede estar vacío')
    expect(screen.getByText('*')).toHaveAttribute('aria-hidden', 'true')
  })
})
