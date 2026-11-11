import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithProviders } from '@/test/renderWithProviders'
import { mockApiError } from '@/test/mockApiError'
import { signInAs, signOut } from '@/test/signIn'
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

// D93/RN-187: mutation controls are shown only to `admin`.
beforeEach(() => signInAs('admin'))
afterEach(() => signOut())

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
    await user.type(screen.getByLabelText(/^Patrón/), '!/etc/motd')
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

// D91/RN-185 + D90/RN-184: the backend rejects a bad pattern with a nested detail.
describe('Rules — rechazos del backend con la forma real', () => {
  beforeEach(() => {
    apiGet.mockReset()
    apiPost.mockReset()
    apiGet.mockImplementation((url: string) =>
      url === '/rules/version'
        ? Promise.resolve({ data: { version: RULESET_VERSION } })
        : Promise.resolve({ data: [rule] }),
    )
  })

  it('un 422 pattern_not_absolute se muestra junto al campo y el formulario sigue abierto', async () => {
    apiPost.mockRejectedValue(
      mockApiError(422, {
        code: 'pattern_not_absolute',
        message: 'El patrón debe ser una ruta absoluta (empezar con /).',
      }),
    )
    const user = userEvent.setup()
    renderWithProviders(<Rules />, { route: '/rules' })

    await user.click(await screen.findByRole('button', { name: 'Nueva regla' }))
    await user.type(screen.getByLabelText(/^Patrón/), 'etc/**')
    await user.click(screen.getByRole('button', { name: 'Crear regla' }))

    const message = await screen.findByText('El patrón debe ser una ruta absoluta (empezar con /).')
    expect(message).toHaveAttribute('id', 'rule-pattern-error')
    expect(screen.getByLabelText(/^Patrón/)).toHaveAttribute('aria-invalid', 'true')
    expect(screen.getByRole('heading', { name: 'Nueva regla' })).toBeInTheDocument()
    expect(screen.queryByText(/\[object Object\]/)).toBeNull()
  })

  it('un viewer no ve «Nueva regla», «Editar» ni «Eliminar»', async () => {
    signInAs('viewer')
    renderWithProviders(<Rules />, { route: '/rules' })
    await screen.findByText(rule.pattern)
    expect(screen.queryByRole('button', { name: 'Nueva regla' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Editar' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Eliminar' })).toBeNull()
  })

  it('GET /rules con 500 muestra el error con «Reintentar»', async () => {
    apiGet.mockImplementation((url: string) =>
      url === '/rules/version'
        ? Promise.resolve({ data: { version: RULESET_VERSION } })
        : Promise.reject(mockApiError(500, 'boom')),
    )
    renderWithProviders(<Rules />, { route: '/rules' })
    expect(await screen.findByRole('button', { name: 'Reintentar' })).toBeInTheDocument()
  })
})
