import { beforeEach, describe, expect, it, vi } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithProviders } from '@/test/renderWithProviders'
import type { Rule } from '@/api/rules'

const { apiGet, apiPost, apiPut, apiDelete } = vi.hoisted(() => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  apiPut: vi.fn(),
  apiDelete: vi.fn(),
}))

vi.mock('@/api/client', () => ({
  apiClient: {
    get: (...args: unknown[]) => apiGet(...args),
    post: (...args: unknown[]) => apiPost(...args),
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

const RULESET_VERSION = 12

describe('Rules — US-16 edición y US-17 eliminación', () => {
  beforeEach(() => {
    apiGet.mockReset()
    apiPost.mockReset()
    apiPut.mockReset()
    apiDelete.mockReset()
    apiGet.mockImplementation((url: string) => {
      if (url === '/rules/version') return Promise.resolve({ data: { version: RULESET_VERSION } })
      return Promise.resolve({ data: [rule] })
    })
    apiPost.mockResolvedValue({ data: rule })
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

describe('Rules — US-14 listado', () => {
  beforeEach(() => {
    apiGet.mockReset()
    apiPost.mockReset()
    apiPut.mockReset()
    apiDelete.mockReset()
    apiGet.mockImplementation((url: string) => {
      if (url === '/rules/version') return Promise.resolve({ data: { version: RULESET_VERSION } })
      return Promise.resolve({ data: [rule] })
    })
    apiPost.mockResolvedValue({ data: rule })
  })

  it('criterio 2: cada fila muestra patrón, severidad y acción', async () => {
    renderWithProviders(<Rules />)

    const row = await screen.findByText(rule.pattern).then((cell) => cell.closest('tr')!)
    expect(within(row).getByText(rule.pattern)).toBeInTheDocument()
    expect(within(row).getByText(rule.severity)).toBeInTheDocument()
    expect(within(row).getByText('Auto-restaurar')).toBeInTheDocument()
  })

  it('criterio 3: indica que la acción por defecto sin regla que matchee es alert_only', async () => {
    renderWithProviders(<Rules />)

    await screen.findByText(rule.pattern)
    expect(screen.getByText(/Solo alerta \(alert_only\)/)).toBeInTheDocument()
  })

  it('criterio 4: muestra el ruleset_version actual del sistema', async () => {
    renderWithProviders(<Rules />)

    await screen.findByText(rule.pattern)
    expect(await screen.findByText(String(RULESET_VERSION))).toBeInTheDocument()
  })
})

describe('Rules — US-15 creación', () => {
  beforeEach(() => {
    apiGet.mockReset()
    apiPost.mockReset()
    apiPut.mockReset()
    apiDelete.mockReset()
    apiGet.mockImplementation((url: string) => {
      if (url === '/rules/version') return Promise.resolve({ data: { version: RULESET_VERSION } })
      return Promise.resolve({ data: [] })
    })
    apiPost.mockResolvedValue({ data: rule })
  })

  it('criterio 1: existe un formulario para crear una regla con pattern (glob+negación), severidad y acción', async () => {
    const user = userEvent.setup()
    renderWithProviders(<Rules />)

    await screen.findByText('No hay reglas configuradas.')
    await user.click(screen.getByRole('button', { name: 'Nueva regla' }))

    expect(screen.getByRole('heading', { name: 'Nueva regla' })).toBeInTheDocument()
    await user.type(screen.getByLabelText(/^Pattern/), '!/etc/motd')
    await user.selectOptions(screen.getByLabelText('Severidad'), 'critical')
    await user.selectOptions(screen.getByLabelText('Acción'), 'auto_restore')
    await user.click(screen.getByRole('button', { name: 'Crear regla' }))

    await waitFor(() =>
      expect(apiPost).toHaveBeenCalledWith('/rules', {
        pattern: '!/etc/motd',
        severity: 'critical',
        action: 'auto_restore',
      })
    )
  })
})
