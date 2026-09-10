import { beforeEach, describe, expect, it, vi } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithProviders } from '@/test/renderWithProviders'
import type { Rule } from '@/api/rules'

const { apiGet, apiPut, apiDelete } = vi.hoisted(() => ({
  apiGet: vi.fn(),
  apiPut: vi.fn(),
  apiDelete: vi.fn(),
}))

vi.mock('@/api/client', () => ({
  apiClient: {
    get: (...args: unknown[]) => apiGet(...args),
    put: (...args: unknown[]) => apiPut(...args),
    delete: (...args: unknown[]) => apiDelete(...args),
  },
  default: {},
}))

import { Rules } from './Rules'

const rule: Rule = {
  id: 7,
  pattern: '/etc/ssh/**',
  severity: 'critical',
  action: 'auto_restore',
  ruleset_version: 4,
  created_at: '2026-09-01T12:00:00Z',
  updated_at: '2026-09-01T12:00:00Z',
}

describe('Rules — US-16 edición y US-17 eliminación', () => {
  beforeEach(() => {
    apiGet.mockReset()
    apiPut.mockReset()
    apiDelete.mockReset()
    apiGet.mockResolvedValue({ data: [rule] })
    apiPut.mockResolvedValue({ data: rule })
    apiDelete.mockResolvedValue({ data: undefined })
  })

  it('abre el formulario de edición precargado con patrón, severidad y acción de la regla elegida', async () => {
    const user = userEvent.setup()
    renderWithProviders(<Rules />)

    const row = await screen.findByText(rule.pattern).then((cell) => cell.closest('tr')!)
    await user.click(within(row).getByRole('button', { name: 'Editar' }))

    expect(screen.getByRole('heading', { name: 'Editar regla' })).toBeInTheDocument()
    expect(screen.getByRole('textbox')).toHaveValue(rule.pattern)
    const selects = screen.getAllByRole('combobox')
    expect(selects[0]).toHaveValue('critical')
    expect(selects[1]).toHaveValue('auto_restore')
  })

  it('no elimina al mostrar la confirmación y llama al endpoint sólo después de confirmar', async () => {
    const user = userEvent.setup()
    renderWithProviders(<Rules />)

    const row = await screen.findByText(rule.pattern).then((cell) => cell.closest('tr')!)
    await user.click(within(row).getByRole('button', { name: 'Eliminar' }))

    expect(within(row).getByText('¿Eliminar?')).toBeInTheDocument()
    expect(apiDelete).not.toHaveBeenCalled()

    await user.click(within(row).getByRole('button', { name: 'Confirmar' }))
    await waitFor(() => expect(apiDelete).toHaveBeenCalledWith('/rules/7'))
  })
})
